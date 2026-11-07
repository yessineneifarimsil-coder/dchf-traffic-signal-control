"""Generalisation of the IDQN 107 / traffic 8203 diagnosis to every degraded IDQN pair and every QMIX run in
which the guarantee acts (no simulation; reads the robustness outputs, writes only --out).

    python tools/article_analyses/guarantee_diagnostic.py --root D:\\QMIX_Results\\robustness_validation ^
        --analysis analysis\\robustness --out analysis\\guarantee_diagnostic

Selections (from the robustness analysis tables, definitions fixed here):
  IDQN degraded pairs, contrast guarantee - none on the same model and traffic (also reported for both - none):
    D2  dD_bar_demand_window_s > 0                                                        (primary: the
        definition of the 35 pairs, decided on 2026-11-07)
    D1  dJ_whole_episode_s > 0 (both runs clear), or the arm fails while `none` clears   (reported)
    D3  D1 or D2                                                                         (reported)
  QMIX runs where the guarantee acts: learned guarantee or both, at least one guarantee intervention
  (demand window or after). Counts are printed for every definition, so that they can be compared with the
  counts reported elsewhere (35 IDQN pairs, 17 QMIX evaluations: reported, not recomputed here).

Per guarantee intervention (protection_decisions.csv, intervention == "guarantee"), on its intersection (column
`intersection` when present, else the intersection whose yellow starts at that second, else both): the green
the guarantee served (first green starting at or after the decision), then the NEXT green of the opposite phase:
its duration, flagged when > 60 s; and the time until the served phase is green again.
Per run and stream (manifest column `stream`): vehicles, mean and max waitingTime, counts >= 60 s and >= 300 s,
and the difference with the paired `none` run.
"""
from __future__ import absolute_import, division, print_function

import argparse
import csv
import json
import math
import os
import statistics
import sys
import xml.etree.ElementTree as ET

LONG_OPPOSITE_GREEN_S = 60


def finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def select(analysis):
    pairs = rows(os.path.join(analysis, "pairs.csv"))
    cells = rows(os.path.join(analysis, "cells.csv"))
    out = {"idqn": {}, "qmix_acting": []}
    for arm in ("guarantee", "both"):
        ps = [p for p in pairs if p["method"] == "idqn" and p["arm"] == arm]
        d1 = [p for p in ps if (finite(p["dJ_whole_episode_s"]) and float(p["dJ_whole_episode_s"]) > 0)
              or (p["status_none"] == "CLEARED" and p["status_arm"] != "CLEARED")]
        d2 = [p for p in ps if finite(p["dD_bar_demand_window_s"]) and float(p["dD_bar_demand_window_s"]) > 0]
        keys = lambda xs: set((p["scenario"], p["seed"], p["model"]) for p in xs)  # noqa: E731
        d3 = [p for p in ps if (p["scenario"], p["seed"], p["model"]) in keys(d1) | keys(d2)]
        out["idqn"][arm] = {"pairs": len(ps), "D1": d1, "D2": d2, "D3": d3}
    for c in cells:
        if c.get("method") == "qmix" and c.get("arm") in ("guarantee", "both"):
            total = sum(int(float(c.get(k) or 0)) for k in ("interventions_guarantee_demand",
                                                             "interventions_guarantee_after"))
            if total > 0:
                out["qmix_acting"].append(c)
    return out


def cell_dir(root, scenario, seed, model, arm):
    return os.path.join(root, "cells", scenario, str(seed), model, arm)


def segments(path):
    seq = {}
    for r in rows(path):
        seq.setdefault(r["intersection"], []).append((int(float(r["time"])), r["actual_phase"]))
    out = {}
    for tl, s in seq.items():
        s.sort()
        segs = []
        for t, p in s:
            if segs and segs[-1][0] == p and t == segs[-1][2] + 1:
                segs[-1][2] = t
            else:
                segs.append([p, t, t])
        out[tl] = [(p, a, b - a + 1) for p, a, b in segs]
    return out


def intervention_rows(directory):
    path = os.path.join(directory, "protection_decisions.csv")
    return [r for r in rows(path) if r.get("intervention") == "guarantee"] if os.path.isfile(path) else []


def locate(row, segs):
    for key in ("intersection", "tl", "tl_id", "agent"):
        if row.get(key) in segs:
            return [row[key]], "column"
    t = float(row["decision_time"])
    starting = [tl for tl, s in segs.items() if any(p == "Y" and t <= a <= t + 1 for p, a, _d in s)]
    if len(starting) == 1:
        return starting, "yellow_start"
    return sorted(segs), "both (not identifiable)"


def after_intervention(segs, t):
    greens = [(p, a, d) for p, a, d in segs if p != "Y"]
    served = next((g for g in greens if g[1] >= t), None)
    if served is None:
        return None
    phase, start, duration = served
    opposite = next((g for g in greens if g[1] > start and g[0] != phase), None)
    again = next((g for g in greens if g[1] > start + duration and g[0] == phase), None)
    return {"served_phase": phase, "served_green_start_s": start, "served_green_s": duration,
            "opposite_green_s": opposite[2] if opposite else None,
            "opposite_green_gt_60s": bool(opposite and opposite[2] > LONG_OPPOSITE_GREEN_S),
            "served_phase_red_after_s": (again[1] - (start + duration)) if again else None}


def stream_waits(directory, manifest_csv):
    stream = dict((r["vehicle_id"], r["stream"]) for r in rows(manifest_csv))
    waits = {}
    for _event, el in ET.iterparse(os.path.join(directory, "tripinfo.xml")):
        if el.tag == "tripinfo":
            waits.setdefault(stream.get(el.get("id"), "?"), []).append(float(el.get("waitingTime")))
            el.clear()
    return dict((s, {"vehicles": len(w), "mean_wait_s": statistics.mean(w), "max_wait_s": max(w),
                     "n_ge_60s": sum(1 for x in w if x >= 60), "n_ge_300s": sum(1 for x in w if x >= 300)})
                for s, w in waits.items())


def diagnose(root, scenario, seed, model, arm, label):
    d = cell_dir(root, scenario, seed, model, arm)
    base = cell_dir(root, scenario, seed, model, "none")
    segs = segments(os.path.join(d, "signal_phases.csv"))
    events = []
    for r in intervention_rows(d):
        t = float(r["decision_time"])
        tls, how = locate(r, segs)
        for tl in tls:
            info = after_intervention(segs[tl], t)
            if info:
                events.append(dict(info, selection=label, scenario=scenario, seed=seed, model=model, arm=arm,
                                   intersection=tl, located_by=how, decision_time_s=t, in_demand=t < 3600))
    manifest = os.path.join(root, "manifests", "{}_{}.csv".format(scenario, seed))
    waits = stream_waits(d, manifest)
    waits_none = stream_waits(base, manifest) if os.path.isdir(base) else {}
    streams = []
    for s in sorted(waits):
        w, n = waits[s], waits_none.get(s)
        streams.append(dict(selection=label, scenario=scenario, seed=seed, model=model, arm=arm, stream=s,
                            **dict(w, d_mean_wait_s=(w["mean_wait_s"] - n["mean_wait_s"]) if n else None,
                                   d_max_wait_s=(w["max_wait_s"] - n["max_wait_s"]) if n else None)))
    return events, streams


def write_csv(path, records):
    keys = []
    for r in records:
        keys += [k for k in r if k not in keys]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(records)


def summary_of(events, label):
    ev = [e for e in events if e["selection"] == label]
    with_opp = [e for e in ev if e["opposite_green_s"] is not None]
    long = [e for e in with_opp if e["opposite_green_gt_60s"]]
    return {"interventions": len(ev), "in_demand": sum(1 for e in ev if e["in_demand"]),
            "runs": len(set((e["scenario"], e["seed"], e["model"], e["arm"]) for e in ev)),
            "with_opposite_green": len(with_opp), "opposite_green_gt_60s": len(long),
            "runs_with_opposite_green_gt_60s": len(set((e["scenario"], e["seed"], e["model"], e["arm"]) for e in long)),
            "opposite_green_median_s": statistics.median([e["opposite_green_s"] for e in with_opp]) if with_opp else None,
            "located_by": dict((k, sum(1 for e in ev if e["located_by"] == k)) for k in set(e["located_by"] for e in ev))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, help="robustness root (cells/, manifests/)")
    ap.add_argument("--analysis", required=True, help="robustness analysis output (pairs.csv, cells.csv)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sel = select(a.analysis)
    counts = {"idqn_pairs": dict((arm, dict((k, len(v)) if isinstance(v, list) else (k, v) for k, v in d.items()))
                                 for arm, d in sel["idqn"].items()),
              "qmix_runs_where_guarantee_acts": len(sel["qmix_acting"]),
              "qmix_runs_where_guarantee_acts_in_demand": sum(
                  1 for c in sel["qmix_acting"] if int(float(c.get("interventions_guarantee_demand") or 0)) > 0),
              "reported_elsewhere_not_recomputed": {"idqn_degraded_pairs": 35, "qmix_evaluations_guarantee_acts": 17}}
    events, streams, missing = [], [], []
    todo = [(p["scenario"], p["seed"], p["model"], "guarantee", "idqn_degraded_D2") for p in sel["idqn"]["guarantee"]["D2"]]
    todo += [(c["scenario"], c["seed"], c["model"], c["arm"], "qmix_guarantee_acts") for c in sel["qmix_acting"]]
    for scenario, seed, model, arm, label in todo:
        try:
            e, s = diagnose(a.root, scenario, seed, model, arm, label)
        except (IOError, OSError) as error:
            missing.append({"cell": [scenario, seed, model, arm], "selection": label, "error": str(error)})
            continue
        events += e
        streams += s
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    write_csv(os.path.join(a.out, "interventions.csv"), events)
    write_csv(os.path.join(a.out, "stream_waits.csv"), streams)
    result = {"selection_counts": counts, "primary_idqn_definition": "D2 (dD_bar_demand_window_s > 0)",
              "idqn_degraded_D2": summary_of(events, "idqn_degraded_D2"),
              "qmix_guarantee_acts": summary_of(events, "qmix_guarantee_acts"),
              "threshold_opposite_green_s": LONG_OPPOSITE_GREEN_S, "cells_not_readable": missing}
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(result, f, indent=1)
    print(json.dumps(result, indent=1))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
