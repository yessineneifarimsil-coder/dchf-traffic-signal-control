"""Read-only diagnosis of an evaluation that failed to clear, against the successful evaluations of
the same checkpoint (no simulation; inputs are never modified).

    python diagnosis/diagnose_clearance_failure.py --runs-root <comparison/runs> \
        --model qmix_seed101_t350000 --failed 9305 --ok 9301 9302 9303 9304 --out diagnosis/out

Facts are taken from the run files only:
  * clearance_failures.jsonl  - ids still active / pending at the end;
  * tripinfo.xml (unfinished written) - depart, lanes, waiting time, route length of those vehicles;
  * lane_states.csv           - per-second queue / vehicle count / speed per lane;
  * signal_actions.csv        - decisions, observation vectors, Q(EXTEND), Q(SWITCH), epsilon;
  * signal_phases.csv         - the EXECUTOR's commanded state per second (it is NOT a read-back of
                                SUMO; these runs did not log a SUMO read-back);
  * episode_summary.csv / evaluation_metrics.json.
Observation order (frozen config): q_H, q_V (halting / 150 and / 100), phase_H, elapsed/(elapsed+60),
lambda_H, lambda_V (30 s arrival window), occ_H_out, occ_V_out.
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

V_IN = {"J1": ["E4_0", "E4_1", "E5_0", "E5_1"], "J2": ["E7_0", "E7_1", "E6_0", "E6_1"]}
H_IN = {"J1": ["-E1_0", "-E1_1", "E0_0", "E0_1"], "J2": ["E2_0", "E2_1", "E1_0", "E1_1"]}


def tripinfo(run, ids):
    txt = (run / "tripinfo.xml").read_text(encoding="utf-8")
    out = {}
    for vid in ids:
        m = re.search(r'<tripinfo id="%s"([^>]*)/>' % re.escape(vid), txt)
        out[vid] = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1))) if m else None
    return out


def spells(series_t, series_phase, movement):
    """Contiguous commanded spells without `movement` green (red incl. yellow), as (start, end, length)."""
    out, start = [], None
    for t, p in zip(series_t, series_phase):
        if p != movement and start is None:
            start = t
        elif p == movement and start is not None:
            out.append((start, t, t - start))
            start = None
    if start is not None:
        out.append((start, series_t[-1], series_t[-1] - start + 1))
    return out


def run_profile(run):
    ep = pd.read_csv(run / "episode_summary.csv").iloc[0].to_dict()
    sa = pd.read_csv(run / "signal_actions.csv")
    sp = pd.read_csv(run / "signal_phases.csv")
    prof = {"status": ep["status"], "end_time": ep["end_time"], "completed": int(ep["completed"]),
            "inserted": int(ep["inserted"]), "pending_due": int(ep["pending_due"]),
            "active_sumo": int(ep["active_sumo"]), "timeout_truncated": bool(ep["timeout_truncated"])}
    for j in ("J1", "J2"):
        a = sa[sa.intersection == j]
        p = sp[sp.intersection == j]
        dem = a[a.decision_time < 3600]
        post = a[a.decision_time >= 3600]
        v_sp = spells(p.time.tolist(), p.actual_phase.tolist(), "V")
        h_sp = spells(p.time.tolist(), p.actual_phase.tolist(), "H")
        prof[j] = {
            "decisions": int(len(a)), "switches_total": int((a.action == "SWITCH").sum()),
            "switches_during_demand": int((dem.action == "SWITCH").sum()),
            "switches_after_3600": int((post.action == "SWITCH").sum()),
            "explore_any": bool(a.explore.any()),
            "max_V_red_commanded_s": int(p.V_red_elapsed_s.max()), "max_H_red_commanded_s": int(p.H_red_elapsed_s.max()),
            "longest_V_denial_spell_s": max((s[2] for s in v_sp), default=0),
            "longest_V_denial_spell_during_demand_s": max((min(s[1], 3600) - s[0] for s in v_sp if s[0] < 3600), default=0),
            "longest_H_denial_spell_s": max((s[2] for s in h_sp), default=0),
            "share_q_switch_gt_q_extend": float((a.q_switch > a.q_extend).mean()),
        }
    return prof


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-root", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--failed", type=int, required=True)
    ap.add_argument("--ok", type=int, nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.runs_root)
    fail = root / f"C_{a.model}__traffic{a.failed}"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res = {"model": a.model, "failed_traffic": a.failed, "ok_traffic": a.ok,
           "phase_log_semantics": "signal_phases.actual_phase is the executor's commanded state; no SUMO read-back was logged in these runs"}
    cf = json.loads((fail / "clearance_failures.jsonl").read_text().splitlines()[-1])
    res["end_record"] = {k: cf[k] for k in ("time", "active_ids", "pending_due_ids", "scheduled_future_ids",
                                            "teleport_started_ids") if k in cf}
    rem = cf["active_ids"] + cf.get("pending_due_ids", [])
    res["remaining_tripinfo"] = tripinfo(fail, rem)
    # lane timeline of the remaining vehicle's approach
    ls = pd.read_csv(fail / "lane_states.csv")
    lanes = sorted({ti["departLane"].rsplit("_", 1)[0] for ti in res["remaining_tripinfo"].values() if ti})
    lane_rows = ls[ls.lane.str.rsplit("_", n=1).str[0].isin(lanes)]
    occ = lane_rows[lane_rows.vehicle_count > 0]
    halt = lane_rows[lane_rows.queue > 0]
    last_motion = occ[occ.mean_speed > 0.1].time.max()
    res["approach_lanes"] = lanes
    res["approach_timeline"] = {
        "first_time_vehicle_present_after_3500": float(occ[occ.time >= 3500].time.min()),
        "last_time_moving_vehicle_present": float(last_motion),
        "halting_from": float(halt[halt.time >= 3500].time.min()) if len(halt[halt.time >= 3500]) else None,
        "halting_lane_at_end": halt[halt.time == halt.time.max()].lane.tolist(),
        "max_vehicles_on_approach_after_3600": int(lane_rows[lane_rows.time > 3600].groupby("time").vehicle_count.sum().max()),
    }
    # whole-network occupancy after the remaining vehicle stopped (physical blocking?)
    after = ls[ls.time > (last_motion or 3600)]
    res["network_after_stop"] = {"max_total_vehicles": int(after.groupby("time").vehicle_count.sum().max()),
                                 "lanes_with_any_vehicle": sorted(after[after.vehicle_count > 0].lane.unique().tolist())}
    # decisions and Q at the intersection controlling the approach
    sa = pd.read_csv(fail / "signal_actions.csv")
    sp = pd.read_csv(fail / "signal_phases.csv")
    j = next((k for k in ("J1", "J2") if any(f"{l}_0" in V_IN[k] + H_IN[k] for l in lanes)), None)
    a_j = sa[sa.intersection == j].copy()
    a_j["obs"] = a_j.observation_json.apply(json.loads)
    stop_t = res["approach_timeline"]["halting_from"] or 3600
    after_stop = a_j[a_j.decision_time >= stop_t]
    obs_after = np.array(after_stop.obs.tolist())
    res["controlling_intersection"] = j
    res["after_vehicle_stopped"] = {
        "decisions": int(len(after_stop)), "actions": after_stop.action.value_counts().to_dict(),
        "q_extend_range": [float(after_stop.q_extend.min()), float(after_stop.q_extend.max())],
        "q_switch_range": [float(after_stop.q_switch.min()), float(after_stop.q_switch.max())],
        "q_gap_extend_minus_switch_range": [float((after_stop.q_extend - after_stop.q_switch).min()),
                                            float((after_stop.q_extend - after_stop.q_switch).max())],
        "observation_min": obs_after.min(0).round(5).tolist(), "observation_max": obs_after.max(0).round(5).tolist(),
        "distinct_observations": int(len({tuple(np.round(o, 6)) for o in obs_after})),
        "explore_any": bool(after_stop.explore.any()),
    }
    p_j = sp[sp.intersection == j]
    res["commanded_phase_after_vehicle_stopped"] = p_j[p_j.time >= stop_t].actual_phase.value_counts().to_dict()
    res["last_decisions"] = a_j.tail(6)[["decision_time", "observation_json", "action", "q_extend", "q_switch"]].to_dict("records")
    res["decisions_around_stop"] = a_j[(a_j.decision_time >= stop_t - 40) & (a_j.decision_time <= stop_t + 40)][
        ["decision_time", "observation_json", "action", "q_extend", "q_switch"]].to_dict("records")
    other = "J1" if j == "J2" else "J2"
    a_o = sa[(sa.intersection == other) & (sa.decision_time >= stop_t)]
    res["other_intersection_after_stop"] = {"intersection": other, "actions": a_o.action.value_counts().to_dict()}
    # profiles: failed vs successes
    res["profiles"] = {str(a.failed): run_profile(fail)}
    for t in a.ok:
        res["profiles"][str(t)] = run_profile(root / f"C_{a.model}__traffic{t}")
    # how the last vehicle of the same secondary stream was served in the successes
    stream = rem[0].split("_")[2] if rem else None
    last_service = {}
    for t in a.ok:
        r = root / f"C_{a.model}__traffic{t}"
        txt = (r / "tripinfo.xml").read_text(encoding="utf-8")
        trips = [dict(re.findall(r'(\w+)="([^"]*)"', m)) for m in re.findall(r"<tripinfo ([^>]*)/>", txt)]
        s = [x for x in trips if f"_{stream}_" in x["id"]]
        lastv = max(s, key=lambda x: float(x["depart"]))
        last_service[str(t)] = {k: lastv[k] for k in ("id", "depart", "arrival", "waitingTime", "timeLoss")}
    res["last_vehicle_same_stream_in_successes"] = last_service
    (out / "diagnosis.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("end_record", "remaining_tripinfo", "approach_timeline", "network_after_stop",
                                          "controlling_intersection", "after_vehicle_stopped",
                                          "commanded_phase_after_vehicle_stopped", "other_intersection_after_stop",
                                          "last_vehicle_same_stream_in_successes")}, indent=1, default=str)[:6000])
    print(json.dumps(res["profiles"], indent=1)[:5000])


if __name__ == "__main__":
    main()
