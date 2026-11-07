"""J(cycle) from the EXISTING optimized-fixed-timing searches (no simulation; read only).

    python tools/article_analyses/j_cycle_curve.py ^
        --roots D:\\QMIX_Results\\qualification_300m_medium_official ^
                D:\\QMIX_Results\\qualification_300m_medium_boundary_audit_20260920 ^
                D:\\QMIX_Results\\qualification_300m_medium_timing_amendment002r ^
                D:\\QMIX_Results\\fixed_timing_min7_2026-10-27 ^
        --ablation-cells analysis/ablation/cells.csv ^
        --fixed-plan-runs figures/data/fig1_same_traffic_performance.csv ^
        --out analysis/j_cycle

Reads every evaluation_metrics.json under the roots whose controller is optimized_fixed_timing, keeps the
benchmark_design runs (seeds 2001-2005) and identifies each run by its realized plan (C, g_H, g_V, offset mod C)
from phase_parameters. Runs of one plan and seed found in several roots must agree on J to 1e-9 (else listed
as conflicts). A plan is valid only if its 5 design runs are CLEARED with a valid finite J (frozen rule). Per
cycle C: plans, valid plans, best mean J and median mean J over valid plans, separately for every plan
(g >= 5) and for plans with both greens >= 7 s. Also: the best plan overall and within the original grid
40-140 s.

Position of QMIX: QMIX has no run on the design seeds. Its J is therefore shown as a reference band from the
development traffics 9301-9305 (10 selected models, no protection, from the ablation cells), together with the
old fixed plan C19 and the min-7 plan C25 on the SAME development traffics, so that the gap between families
(design 2001-2005 versus development 9301-9305) can be read off the two fixed plans. It is a different traffic
family: the band is a reference, not a point on the curve.
"""
from __future__ import absolute_import, division, print_function

import argparse
import csv
import json
import math
import os
import statistics
import sys

DESIGN_FAMILY = "benchmark_design"
VALIDATION_FAMILY = "benchmark_validation"
DESIGN_SEEDS = (2001, 2002, 2003, 2004, 2005)
CONTROLLER = "optimized_fixed_timing"
J = "J_primary_mean_scheduled_waiting_burden_s"


def finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def realized(plan):
    c = int(plan["cycle_s"])
    return (c, int(plan["green_H_s"]), int(plan["green_V_s"]), int(plan["offset_s"]) % c)


def collect(roots, family=DESIGN_FAMILY):
    runs, conflicts, files = {}, [], 0
    for root in roots:
        for d, _dirs, names in os.walk(root):
            if "evaluation_metrics.json" not in names:
                continue
            try:
                with open(os.path.join(d, "evaluation_metrics.json")) as f:
                    m = json.load(f)
            except (ValueError, OSError):
                continue
            if m.get("controller") != CONTROLLER or m.get("traffic_family") != family or not m.get("phase_parameters"):
                continue
            files += 1
            key = (realized(m["phase_parameters"]), int(m["traffic_seed"]))
            valid = (m.get("clearance_status") == "CLEARED" and bool(m.get("J_primary_valid")) and finite(m.get(J)))
            value = (valid, float(m[J]) if valid else None, d)
            if key in runs:
                old = runs[key]
                if old[0] != value[0] or (valid and abs(old[1] - value[1]) > 1e-9):
                    conflicts.append({"plan": list(key[0]), "seed": key[1], "dirs": [old[2], d]})
                continue
            runs[key] = value
    return runs, conflicts, files


def plan_scores(runs, seeds=DESIGN_SEEDS):
    by_plan = {}
    for (plan, seed), value in runs.items():
        by_plan.setdefault(plan, {})[seed] = value
    scores = {}
    for plan, per_seed in by_plan.items():
        complete = set(per_seed) == set(seeds)
        valid = complete and all(v[0] for v in per_seed.values())
        scores[plan] = {"complete": complete, "valid": valid,
                        "mean_J": statistics.mean(per_seed[s][1] for s in seeds) if valid else None}
    return scores


def curve(scores, min_green):
    out = []
    for c in sorted(set(p[0] for p in scores)):
        plans = [(p, s) for p, s in scores.items() if p[0] == c and min(p[1], p[2]) >= min_green]
        if not plans:
            continue
        valid = sorted((s["mean_J"], p) for p, s in plans if s["valid"])
        out.append({"cycle_s": c, "min_green_s": min_green, "plans": len(plans),
                    "complete": sum(1 for _p, s in plans if s["complete"]), "valid": len(valid),
                    "best_J": valid[0][0] if valid else None, "best_plan": list(valid[0][1]) if valid else None,
                    "median_J": statistics.median(v for v, _p in valid) if valid else None})
    return out


def best(scores, low=None, high=None, min_green=5):
    valid = sorted((s["mean_J"], p) for p, s in scores.items() if s["valid"] and min(p[1], p[2]) >= min_green
                   and (low is None or p[0] >= low) and (high is None or p[0] <= high))
    return {"plan": list(valid[0][1]), "mean_J": valid[0][0]} if valid else None


def development_reference(ablation_cells, fixed_runs):
    out = {}
    if ablation_cells:
        with open(ablation_cells) as f:
            rows = [r for r in csv.DictReader(f) if r["method"] == "qmix" and r["arm"] == "none"]
        js = [float(r["J_primary_s"]) for r in rows if r["status"] == "CLEARED" and finite(r["J_primary_s"])]
        per_model = {}
        for r in rows:
            if r["status"] == "CLEARED" and finite(r["J_primary_s"]):
                per_model.setdefault(r["model"], []).append(float(r["J_primary_s"]))
        out["qmix_none_9301_9305"] = {"evaluations": len(rows), "cleared": len(js), "failures": len(rows) - len(js),
                                      "mean_J_over_cleared": statistics.mean(js) if js else None,
                                      "model_means_range": [min(statistics.mean(v) for v in per_model.values()),
                                                            max(statistics.mean(v) for v in per_model.values())]
                                      if per_model else None}
    if fixed_runs:
        with open(fixed_runs) as f:
            rows = list(csv.DictReader(f))
        for label in sorted(set(r["group"] for r in rows if r["group"].lower().startswith(("old fixed", "fixed plan")))):
            js = [float(r["J_primary_s"]) for r in rows if r["group"] == label and r["status"] == "CLEARED"]
            out[label] = {"runs": len(js), "mean_J": statistics.mean(js) if js else None,
                          "plan": sorted(set(r["model"] for r in rows if r["group"] == label))}
    return out


def plot(curves, reference, design_points, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for rows, style, label in ((curves[0], "-o", "best plan per cycle, greens >= 5 s"),
                               (curves[1], "--s", "best plan per cycle, greens >= 7 s")):
        xs = [r["cycle_s"] for r in rows if r["best_J"] is not None]
        ys = [r["best_J"] for r in rows if r["best_J"] is not None]
        ax.plot(xs, ys, style, ms=3, lw=1, label=label)
    for name, (c, j) in design_points.items():
        if j is not None:
            ax.annotate(name, (c, j), textcoords="offset points", xytext=(4, 6), fontsize=6.5)
    q = reference.get("qmix_none_9301_9305")
    if q and q["model_means_range"]:
        ax.axhspan(q["model_means_range"][0], q["model_means_range"][1], color="#d9d9d9", alpha=0.6,
                   label="QMIX, 10 models, development traffics 9301-9305 (other family)")
    ax.set_xlabel("cycle C (s)")
    ax.set_ylabel("J on design traffics 2001-2005 (s)")
    ax.legend(fontsize=6.5)
    fig.tight_layout()
    fig.savefig(path)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--ablation-cells")
    ap.add_argument("--fixed-plan-runs")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    runs, conflicts, files = collect(a.roots)
    scores = plan_scores(runs)
    curves = (curve(scores, 5), curve(scores, 7))
    result = {
        "roots": a.roots, "design_metric_files_read": files, "distinct_plan_seed_runs": len(runs),
        "plans": len(scores), "valid_plans": sum(1 for s in scores.values() if s["valid"]),
        "conflicts": conflicts, "curve_g5": curves[0], "curve_min7": curves[1],
        "best_overall_g5": best(scores), "best_grid_40_140_g5": best(scores, 40, 140),
        "best_overall_min7": best(scores, min_green=7),
        "design_J_of": dict((name, (scores.get(tuple(p)) or {}).get("mean_J")) for name, p in (
            ("old plan C19 8/5 D9", (19, 8, 5, 9)), ("min-7 plan C25 12/7 D0", (25, 12, 7, 0)),
            ("original 40-140 winner (40, 650, 23)", (40, 22, 12, 23)))),
        "development_reference": development_reference(a.ablation_cells, a.fixed_plan_runs)}
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    with open(os.path.join(a.out, "j_cycle.json"), "w") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(a.out, "j_cycle.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["min_green_s", "cycle_s", "plans", "complete", "valid", "best_J",
                                          "median_J", "best_plan"])
        w.writeheader()
        for row in curves[0] + curves[1]:
            w.writerow(dict(row, best_plan=json.dumps(row["best_plan"])))
    points = {"C19 (old)": (19, result["design_J_of"]["old plan C19 8/5 D9"]),
              "C25 (min-7)": (25, result["design_J_of"]["min-7 plan C25 12/7 D0"])}
    plotted = plot(curves, result["development_reference"], points, os.path.join(a.out, "j_cycle.pdf"))
    print(json.dumps({k: result[k] for k in ("design_metric_files_read", "plans", "valid_plans", "best_overall_g5",
                                             "best_grid_40_140_g5", "best_overall_min7", "design_J_of")}, indent=1))
    print("conflicts:", len(conflicts), "| figure:", plotted)
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
