"""Read-only check of the canonical max pressure (A4): minimum green, switching frequency, pressure definition.

    python tools/comparators/mp_check.py static --protected-root C:\\Users\\LENOVO\\QMIX_PROTECTED
    python tools/comparators/mp_check.py logs --runs <dir> [<dir> ...] --out analysis\\mp_check.json
    python tools/comparators/mp_check.py robustness --root D:\\QMIX_Results\\robustness_validation_2026-11-04 --out ...

static: reads the frozen code and both frozen configurations (nothing is run): the settings the robustness
evaluator really uses (qualification config + executor defaults) against the official baseline configuration.
logs: per run directory with signal_phases.csv (+ evaluation_metrics.json), per intersection: greens, switches
per hour of demand, green durations (min, median, p90, max), share of greens ending at the minimum green,
share of yellow time, J. robustness: the same for every canonical_mp cell of a robustness root.
Nothing is written except --out.
"""
from __future__ import absolute_import, print_function

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys

DEMAND_END_S = 3600
FROZEN_FILES = ("src/adaptive_qmix/baselines/executors.py", "src/adaptive_qmix/baselines/pressure.py",
                "src/adaptive_qmix/baselines/runner.py", "config/adaptive_qmix/qualification_300m_medium.json",
                "config/adaptive_qmix/baselines_300m_medium.json")


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def static(protected_root):
    sys.path.insert(0, os.path.join(protected_root, "src"))
    from adaptive_qmix.baselines import pressure as PR
    read = lambda rel: open(os.path.join(protected_root, rel)).read()  # noqa: E731
    executors = read("src/adaptive_qmix/baselines/executors.py")
    default_min = re.search(r'settings\.get\("minimum_green_s", (\d+)\)', executors)
    default_yellow = re.search(r'settings\.get\("yellow_duration_s", (\d+)\)', executors)
    qual = json.loads(read("config/adaptive_qmix/qualification_300m_medium.json"))
    base = json.loads(read("config/adaptive_qmix/baselines_300m_medium.json"))
    official = base["baselines"]["canonical_operational_max_pressure"]
    used_section = qual.get("baselines", {}).get("canonical_operational_max_pressure", {})
    used = {"minimum_green_s": used_section.get("minimum_green_s", int(default_min.group(1))),
            "yellow_duration_s": used_section.get("yellow_duration_s", int(default_yellow.group(1)))}
    official_pairs = dict((tl, dict((m, [tuple(p) for p in pairs]) for m, pairs in v.items()))
                          for tl, v in official["movement_pairs"].items())
    frozen_pairs = dict((tl, dict((m, [tuple(p) for p in pairs]) for m, pairs in v.items()))
                        for tl, v in PR.FROZEN_MOVEMENT_PAIRS.items())
    lanes = qual["observation"]["expected_lane_lengths_m"]
    facts = {
        "robustness_evaluator_config": "qualification_300m_medium.json (no 'baselines' section: executor defaults)",
        "used_by_robustness": used, "official_baseline_config": {k: official[k] for k in (
            "minimum_green_s", "yellow_duration_s", "decision_clock", "pressure_input", "tie_rule")},
        "minimum_green_identical": used["minimum_green_s"] == official["minimum_green_s"],
        "yellow_identical": used["yellow_duration_s"] == official["yellow_duration_s"],
        "movement_pairs_identical": official_pairs == frozen_pairs,
        "same_network_executor_demand": all(qual[k] == base[k] for k in ("network", "executor", "demand")),
        "pressure_accessor": PR.LANE_COUNT_ACCESSOR, "forbidden_accessors": list(PR.FORBIDDEN_ACCESSORS),
        "pressure_definition": "P_i(p,t) = sum over the 4 straight-through lane pairs of phase p of "
                               "[vehicles on the whole incoming lane - vehicles on the whole outgoing lane]; "
                               "moving and halted vehicles count alike",
        "counted_lane_lengths_m": {"H_in": sorted(set(lanes[l] for l in qual["observation"]["lanes"]["J1"]["H_in"])),
                                   "V_in": sorted(set(lanes[l] for l in qual["observation"]["lanes"]["J1"]["V_in"]))},
        "decision_rule": "after the minimum green, every second: switch (3 s yellow) iff the other phase's pressure "
                         "is strictly greater; a tie retains; no maximum green; J1 and J2 independent",
        "frozen_file_sha256": dict((f, sha256(os.path.join(protected_root, f))) for f in FROZEN_FILES),
    }
    return facts


def segments(path):
    seq = {}
    with open(path) as f:
        for r in csv.DictReader(f):
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


def quantile(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def run_stats(directory, minimum_green_s=10):
    segs = segments(os.path.join(directory, "signal_phases.csv"))
    metrics_path = os.path.join(directory, "evaluation_metrics.json")
    m = json.load(open(metrics_path)) if os.path.isfile(metrics_path) else {}
    out = {"directory": directory, "scenario": m.get("scenario"), "traffic_seed": m.get("traffic_seed"),
           "controller": m.get("controller"), "status": m.get("clearance_status"),
           "J_s": m.get("J_primary_mean_scheduled_waiting_burden_s"), "intersections": {}}
    for tl, s in sorted(segs.items()):
        complete = s[1:-1]                                  # the first and last segments are truncated
        greens = [(p, a, d) for p, a, d in complete if p != "Y" and a <= DEMAND_END_S]
        durations = [d for _p, _a, d in greens]
        yellow = sum(d for p, a, d in s if p == "Y" and a <= DEMAND_END_S)
        switches = sum(1 for p, a, _d in s if p == "Y" and a <= DEMAND_END_S)
        out["intersections"][tl] = {
            "greens_in_demand": len(greens), "switches_per_hour_demand": switches * 3600.0 / DEMAND_END_S,
            "green_s_min": min(durations) if durations else None, "green_s_median": quantile(durations, 0.5),
            "green_s_p90": quantile(durations, 0.9), "green_s_max": max(durations) if durations else None,
            "share_greens_at_minimum": (sum(1 for d in durations if d == minimum_green_s) / float(len(durations))
                                        if durations else None),
            "greens_below_minimum": sum(1 for d in durations if d < minimum_green_s),
            "yellow_share_of_demand_time": yellow / float(DEMAND_END_S),
            "median_green_by_phase": dict((ph, quantile([d for p, _a, d in greens if p == ph], 0.5))
                                          for ph in ("H", "V"))}
    return out


def summarise(stats):
    rows = []
    for s in stats:
        for tl, v in s["intersections"].items():
            rows.append(dict(scenario=s["scenario"], seed=s["traffic_seed"], intersection=tl, J_s=s["J_s"],
                             status=s["status"], **v))
    by = {}
    for r in rows:
        by.setdefault(r["scenario"], []).append(r)
    summary = {}
    for sc, rs in sorted(by.items(), key=lambda kv: str(kv[0])):
        finite_j = [r["J_s"] for r in rs if r["J_s"] is not None and math.isfinite(float(r["J_s"]))
                    and r["status"] == "CLEARED"]
        summary[str(sc)] = {
            "runs": len(set(r["seed"] for r in rs)),
            "J_s_range_cleared": [min(finite_j), max(finite_j)] if finite_j else None,
            "clearance_failures": len(set(r["seed"] for r in rs if r["status"] != "CLEARED")),
            "J_note": "J is undefined for a clearance failure (NaN in its metrics) and is never imputed",
            "switches_per_hour_range": [min(r["switches_per_hour_demand"] for r in rs),
                                        max(r["switches_per_hour_demand"] for r in rs)],
            "green_median_range_s": [min(r["green_s_median"] for r in rs), max(r["green_s_median"] for r in rs)],
            "share_at_minimum_range": [min(r["share_greens_at_minimum"] for r in rs),
                                       max(r["share_greens_at_minimum"] for r in rs)],
            "greens_below_minimum": sum(r["greens_below_minimum"] for r in rs),
            "yellow_share_range": [min(r["yellow_share_of_demand_time"] for r in rs),
                                   max(r["yellow_share_of_demand_time"] for r in rs)]}
    return rows, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("static", "logs", "robustness"))
    ap.add_argument("--protected-root", default=os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"))
    ap.add_argument("--runs", nargs="*", default=[])
    ap.add_argument("--root")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.action == "static":
        payload = static(a.protected_root)
    else:
        dirs = list(a.runs)
        if a.action == "robustness":
            dirs = sorted(os.path.join(d) for d, _s, files in os.walk(os.path.join(a.root, "cells"))
                          if os.path.basename(d) == "canonical_mp" and "signal_phases.csv" in files)
        stats = [run_stats(d) for d in dirs]
        rows, summary = summarise(stats)
        payload = {"runs": len(stats), "summary_by_scenario": summary, "per_run_intersection": rows}
    text = json.dumps(payload, indent=1, sort_keys=True, default=str)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
    print(text if a.action == "static" else json.dumps(payload["summary_by_scenario"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
