"""Analysis of the protection ablation (written and committed before the runs; applied once after all
600 cells exist). Descriptive, development traffics already inspected: no hypothesis test, no selection.

    python tools/ablation_analysis.py --root <ablation root> --out analysis/ablation

Per cell (tools/ablation_metrics.py definitions): status, end time, J_primary (cleared runs only),
mean completed time loss, D_demand and D_bar, P_post (censored flag), service counters (logged for new
cells, reconstructed from logs for the reused QMIX/none cells; the reconstruction is checked against the
logged counters of every new arm-"none" cell), access to first green, open waits, interventions by type
during / after the demand, realised green spells, per-vehicle maxima of SUMO waitingTime and timeLoss
(arrival), main-axis stop-line crossings, SUMO signal mismatches (new cells only).
Paired comparisons: within each (model, traffic) block, every arm minus "none", and the 2x2 interaction
(both - min_green) - (guarantee - none); J differences only over pairs where both runs clear (count reported).
Outputs: cells.csv, pairs.csv, summary.json, reconstruction_check.json, failures.json.
"""
import argparse
import csv
import json
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ablation_metrics as am  # noqa: E402

ARMS = ("none", "guarantee", "min_green", "both")
METHODS = ("qmix", "vdn", "idqn")


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def rj(path):
    with open(path) as f:
        return json.load(f)


def trip_stats(path):
    txt = open(path, encoding="utf-8").read()
    T = [dict(re.findall(r'(\w+)="([^"]*)"', m)) for m in re.findall(r"<tripinfo ([^>]*)/>", txt)]
    unfinished = [t for t in T if float(t["arrival"]) < 0]
    wmax = max(T, key=lambda t: float(t["waitingTime"]))
    return {"tripinfo_rows": len(T), "unfinished_ids": [t["id"] for t in unfinished],
            "max_vehicle_waiting_s": float(wmax["waitingTime"]), "max_waiting_vehicle": wmax["id"],
            "vehicles_waiting_ge_60s": sum(float(t["waitingTime"]) >= 60 for t in T),
            "vehicles_waiting_ge_120s": sum(float(t["waitingTime"]) >= 120 for t in T),
            "max_vehicle_time_loss_s": max(float(t["timeLoss"]) for t in T)}


def stopline_stats(path):
    r = [x for x in rows(path) if x["event"] == "STOP_LINE_EXIT"]
    return {"main_axis_stop_line_exits": len(r)}


def cell_metrics(cell, d, reused):
    m = rj(os.path.join(d, "evaluation_metrics.json"))
    ep = rows(os.path.join(d, "episode_summary.csv"))[0]
    end = float(ep["end_time"])
    D, P = am.demand_and_post_cost(rows(os.path.join(d, "reward_seconds.csv")), end)
    phase_rows = rows(os.path.join(d, "signal_phases.csv"))
    sp = am.spell_stats(am.green_spells(phase_rows), demand_only=True)
    out = {"model": cell["model"], "method": cell["method"], "traffic_seed": cell["traffic_seed"], "arm": cell["arm"],
           "reused": reused, "status": m["clearance_status"], "end_time_s": end,
           "J_primary_s": m["J_primary_mean_scheduled_waiting_burden_s"] if m.get("J_primary_valid") else None,
           "mean_completed_time_loss_s": m["mean_completed_time_loss_s"], "completed": m["completed_count"],
           "scheduled": m["scheduled_count"], "D_demand_veh_s": D, "D_bar_s": D / float(m["scheduled_count"]),
           "P_post_veh_s": P, "P_post_censored": m["clearance_status"] != "CLEARED"}
    out.update(sp)
    out.update(trip_stats(os.path.join(d, "tripinfo.xml")))
    out.update(stopline_stats(os.path.join(d, "vehicle_crossings.csv")))
    lane_rows = rows(os.path.join(d, "lane_states.csv"))
    series, summ = am.counters_from_logs(lane_rows, phase_rows)
    check = None
    if reused:
        out.update({"interventions_guarantee": 0, "interventions_guarantee_demand": 0, "interventions_min_green": 0,
                    "interventions_min_green_demand": 0, "sumo_mismatch_s": None, "counters_source": "reconstructed"})
    else:
        rec = rj(os.path.join(d, "protection_record.json"))
        dec = rows(os.path.join(d, "protection_decisions.csv"))
        for kind in ("guarantee", "min_green"):
            out["interventions_" + kind] = sum(r["intervention"] == kind for r in dec)
            out["interventions_{}_demand".format(kind)] = sum(r["intervention"] == kind and float(r["decision_time"]) < am.GENERATION_END_S for r in dec)
        out["sumo_mismatch_s"] = rec["sumo_index_mismatch_s"] + rec["sumo_state_mismatch_s"]
        out["counters_source"] = "logged"
        logged = rows(os.path.join(d, "service_counters.csv"))
        lc = {(int(round(float(r["time"]))), r["intersection"]): (int(r["c_H"]), int(r["c_V"])) for r in logged}
        diff = sum(1 for (t, tl), v in lc.items() if (series[t][tl]["c_H"], series[t][tl]["c_V"]) != v)
        check = {"cell": cell["directory"], "rows": len(lc), "rows_differing": diff}
        out["max_counter_logged_s"] = max(max(v) for v in lc.values())
        out["max_wait_to_first_green_record_s"] = rec.get("max_wait_to_first_green_s")
    out["max_counter_s"] = max(summ[tl][x]["max_counter"] for tl in summ for x in ("H", "V"))
    out["max_wait_to_first_green_s"] = max(summ[tl][x]["max_wait_to_first_green"] for tl in summ for x in ("H", "V"))
    ow = [summ[tl][x]["open_wait_at_end"] for tl in summ for x in ("H", "V") if summ[tl][x]["open_wait_at_end"] is not None]
    out["open_wait_at_end_s"] = max(ow) if ow else None
    return out, check


def describe(v):
    v = sorted(x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not v:
        return {"n": 0}

    def q(p):
        k = (len(v) - 1) * p
        lo = int(math.floor(k))
        hi = min(lo + 1, len(v) - 1)
        return v[lo] + (v[hi] - v[lo]) * (k - lo)
    return {"n": len(v), "mean": statistics.mean(v), "median": q(0.5), "q25": q(0.25), "q75": q(0.75),
            "min": v[0], "max": v[-1], "n_pos": sum(x > 0 for x in v), "n_neg": sum(x < 0 for x in v),
            "n_zero": sum(x == 0 for x in v)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    plan = rj(os.path.join(a.root, "plan.json"))
    os.makedirs(a.out, exist_ok=True)
    if os.path.exists(os.path.join(a.out, "summary.json")):
        raise SystemExit("analysis already written (applied once)")
    cells, checks, missing = [], [], []
    for c in plan["cells"]:
        reused = "reused_from" in c
        d = c["reused_from"] if reused else os.path.join(plan["root"], c["directory"])
        if not reused and not os.path.isfile(os.path.join(d, "protection_record.json")):
            missing.append(c["directory"])
            continue
        r, chk = cell_metrics(c, d, reused)
        cells.append(r)
        if chk is not None and c["arm"] == "none":
            checks.append(chk)
    if missing:
        raise SystemExit("incomplete: {} cells missing, e.g. {}".format(len(missing), missing[:3]))
    keys = list(cells[0].keys())
    for r in cells:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(os.path.join(a.out, "cells.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in cells:
            w.writerow(dict((k, json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()))
    idx = dict(((r["model"], r["traffic_seed"], r["arm"]), r) for r in cells)
    pairs = []
    for r in cells:
        if r["arm"] == "none":
            continue
        b = idx[(r["model"], r["traffic_seed"], "none")]
        pairs.append({"model": r["model"], "method": r["method"], "traffic_seed": r["traffic_seed"], "arm": r["arm"],
                      "status_none": b["status"], "status_arm": r["status"],
                      "dD_veh_s": r["D_demand_veh_s"] - b["D_demand_veh_s"],
                      "dJ_s": (r["J_primary_s"] - b["J_primary_s"]) if r["J_primary_s"] is not None and b["J_primary_s"] is not None else None,
                      "dTimeLoss_s": r["mean_completed_time_loss_s"] - b["mean_completed_time_loss_s"],
                      "dMaxVehicleWait_s": r["max_vehicle_waiting_s"] - b["max_vehicle_waiting_s"],
                      "interventions_guarantee_demand": r["interventions_guarantee_demand"],
                      "interventions_min_green_demand": r["interventions_min_green_demand"]})
    with open(os.path.join(a.out, "pairs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pairs[0].keys()))
        w.writeheader()
        w.writerows(pairs)
    summary = {"label": plan["label"], "plan_fingerprint": plan["fingerprint"], "cells": len(cells),
               "by_method_arm": {}, "interaction": {}, "sumo_mismatch_total_new_cells":
               sum(r["sumo_mismatch_s"] or 0 for r in cells if not r["reused"])}
    for m in METHODS:
        for arm in ARMS:
            mine = [r for r in cells if r["method"] == m and r["arm"] == arm]
            pm = [p for p in pairs if p["method"] == m and p["arm"] == arm]
            valid_j = [r["J_primary_s"] for r in mine if r["J_primary_s"] is not None]
            summary["by_method_arm"]["{}|{}".format(m, arm)] = {
                "evaluations": len(mine), "cleared": sum(r["status"] == "CLEARED" for r in mine),
                "failures": sum(r["status"] != "CLEARED" for r in mine),
                "failure_cells": ["{} {}".format(r["model"], r["traffic_seed"]) for r in mine if r["status"] != "CLEARED"],
                "J_mean_over_cleared": statistics.mean(valid_j) if valid_j else None, "J_n": len(valid_j),
                "D_bar_mean": statistics.mean(r["D_bar_s"] for r in mine),
                "time_loss_mean_completed": statistics.mean(r["mean_completed_time_loss_s"] for r in mine),
                "interventions_guarantee": sum(r["interventions_guarantee"] for r in mine),
                "interventions_guarantee_demand": sum(r["interventions_guarantee_demand"] for r in mine),
                "interventions_min_green": sum(r["interventions_min_green"] for r in mine),
                "interventions_min_green_demand": sum(r["interventions_min_green_demand"] for r in mine),
                "max_counter_s": max(r["max_counter_s"] for r in mine),
                "max_wait_to_first_green_s": max(r["max_wait_to_first_green_s"] for r in mine),
                "max_vehicle_waiting_s": max(r["max_vehicle_waiting_s"] for r in mine),
                "shortest_green_demand_s": min(r["shortest_green_s"] for r in mine if r["shortest_green_s"] is not None),
                "share_2s_greens_mean": statistics.mean(r["share_2s_greens"] for r in mine),
                "pairs_vs_none": None if arm == "none" else {
                    "dD_veh_s": describe([p["dD_veh_s"] for p in pm]),
                    "dJ_s": describe([p["dJ_s"] for p in pm]),
                    "J_comparable_pairs": sum(p["dJ_s"] is not None for p in pm), "pairs": len(pm),
                    "dTimeLoss_s": describe([p["dTimeLoss_s"] for p in pm]),
                    "dMaxVehicleWait_s": describe([p["dMaxVehicleWait_s"] for p in pm])}}
        inter_d, inter_j = [], []
        for mod in sorted({r["model"] for r in cells if r["method"] == m}):
            for s in sorted({r["traffic_seed"] for r in cells}):
                g = dict((arm, idx[(mod, s, arm)]) for arm in ARMS)
                inter_d.append((g["both"]["D_demand_veh_s"] - g["min_green"]["D_demand_veh_s"])
                               - (g["guarantee"]["D_demand_veh_s"] - g["none"]["D_demand_veh_s"]))
                if all(g[x]["J_primary_s"] is not None for x in ARMS):
                    inter_j.append((g["both"]["J_primary_s"] - g["min_green"]["J_primary_s"])
                                   - (g["guarantee"]["J_primary_s"] - g["none"]["J_primary_s"]))
        summary["interaction"][m] = {"D_veh_s": describe(inter_d), "J_s": describe(inter_j),
                                     "blocks_all_four_cleared": len(inter_j), "blocks": len(inter_d)}
    summary["reconstruction_check"] = {"new_none_cells": len(checks), "cells_with_differences":
                                       sum(c["rows_differing"] > 0 for c in checks)}
    with open(os.path.join(a.out, "reconstruction_check.json"), "w") as f:
        json.dump(checks, f, indent=1)
    with open(os.path.join(a.out, "failures.json"), "w") as f:
        json.dump([r for r in cells if r["status"] != "CLEARED"], f, indent=1, default=str)
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, default=str)
    for k, v in summary["by_method_arm"].items():
        print(k, "cleared {}/{}".format(v["cleared"], v["evaluations"]), "J n={} mean={}".format(v["J_n"], v["J_mean_over_cleared"]),
              "Dbar={:.3f}".format(v["D_bar_mean"]), "guar {}({}) ming {}({})".format(
                  v["interventions_guarantee"], v["interventions_guarantee_demand"], v["interventions_min_green"],
                  v["interventions_min_green_demand"]))
    print(json.dumps(summary["reconstruction_check"]), "sumo mismatch", summary["sumo_mismatch_total_new_cells"])


if __name__ == "__main__":
    main()
