"""
W1 FIX (CORRECTED v3): Multi-seed validation of spatial and demand horizon boundaries.

Reuses the PROVEN repo evaluation functions (evaluate_qmix_distance_sensitivity.py
and run_distance_offset_sweep.py) -- the exact functions that produced the paper's
single-seed spatial/demand values -- and loops over 5 seeds. This avoids the v1 bug
(which flipped phases every sim step and made QMIX look catastrophically bad).

Per case, across 5 seeds: optimized fixed offset (correct per-case best offset) and
QMIX V2 (trained model, eval only), then approximation gap + 95% bootstrap CI +
mean-regime stability + offset/QMIX mean +/- std.

NOTE ON CONFIG: corridor_turning.sumocfg (70/15/15 split) is the SAME config that
generated the paper's published spatial/demand horizon values, so this is a true
multi-seed validation of those exact published numbers (not a different scenario).

NOTE ON BR: these proven functions return waiting/speed/queue, not buffered ratio,
so this script validates APPROXIMATION-GAP robustness only. Capacity (BR) claims are
already supported by the existing single-seed demand table; we do not re-derive BR here.

Spatial (medium demand): d = 200, 300, 500 m       offsets 45, 45, 70
Demand  (d = 300 m):     low, medium, high, saturation, oversaturation
                          offsets 45, 45, 55, 45, 50 (from demand_offset_best_summary.csv)

Run from repo root:
    conda activate traffic_rl
    python scripts/run_w1_multiseed_horizon.py
"""
import os, sys
import numpy as np
import pandas as pd

REPO_ROOT = os.getcwd()
SRC = os.path.join(REPO_ROOT, "src")
sys.path.insert(0, os.path.join(SRC, "qmix"))
sys.path.insert(0, os.path.join(SRC, "env", "two_intersections"))
sys.path.insert(0, os.path.join(SRC, "baselines", "two_intersections"))

import evaluate_qmix_distance_sensitivity as qdist
import run_distance_offset_sweep as offsweep

# Safeguard: the distance module references np.nan in its summary dict but only
# imports pandas. Inject numpy so calling its function does not raise NameError.
if not hasattr(qdist, "np"):
    qdist.np = np

SEEDS = [0, 1, 2, 3, 4]

# best offsets verified against results/tables/distance_offset_best_summary.csv
SPATIAL_CASES = [
    {"label": "d=200m", "distance": 200, "best_offset": 45, "config": "sumo_scenarios/two_intersections/distance_200m/corridor_turning.sumocfg"},
    {"label": "d=300m", "distance": 300, "best_offset": 45, "config": "sumo_scenarios/two_intersections/distance_300m/corridor_turning.sumocfg"},
    {"label": "d=500m", "distance": 500, "best_offset": 70, "config": "sumo_scenarios/two_intersections/distance_500m/corridor_turning.sumocfg"},
]
# best offsets verified against results/tables/demand_offset_best_summary.csv
# (low=45, medium=45, high=55, saturation=45, oversaturation=50 -- NOT all 45)
DEMAND_CASES = [
    {"label": "low",            "distance": 300, "best_offset": 45, "config": "sumo_scenarios/two_intersections/demand_sensitivity/demand_low/corridor_turning.sumocfg"},
    {"label": "medium",         "distance": 300, "best_offset": 45, "config": "sumo_scenarios/two_intersections/demand_sensitivity/demand_medium/corridor_turning.sumocfg"},
    {"label": "high",           "distance": 300, "best_offset": 55, "config": "sumo_scenarios/two_intersections/demand_sensitivity/demand_high/corridor_turning.sumocfg"},
    {"label": "saturation",     "distance": 300, "best_offset": 45, "config": "sumo_scenarios/two_intersections/demand_sensitivity/demand_saturation/corridor_turning.sumocfg"},
    {"label": "oversaturation", "distance": 300, "best_offset": 50, "config": "sumo_scenarios/two_intersections/demand_sensitivity/demand_oversaturation/corridor_turning.sumocfg"},
]

OUT_RAW = "results/tables/w1_multiseed_horizon_raw.csv"
OUT_SUMMARY = "results/tables/w1_multiseed_horizon_summary.csv"


def run_offset(config, best_offset, seed, distance):
    rows, summary = offsweep.run_distance_offset(
        distance=distance, offset=best_offset, sumo_seed=seed,
        sumo_config_override=config, scenario_label="w1")
    return float(summary["mean_total_waiting_time"])


def run_qmix(config, seed, distance):
    rows, summary = qdist.evaluate_qmix_for_distance(
        distance=distance, sumo_seed=seed,
        sumo_config_override=config, scenario_label="w1")
    return float(summary["mean_total_waiting_time"])


def bootstrap_ci(values, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    boot = [np.mean(rng.choice(arr, size=len(arr), replace=True)) for _ in range(n)]
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def classify(gap):
    if gap <= 5.0: return "Effective"
    if gap <= 10.0: return "Marginal"
    return "Outside horizon"


def run_block(cases, dim):
    raw_rows, summary_rows = [], []
    for case in cases:
        if not os.path.exists(case["config"]):
            print(f"[WARN] missing config, skipping: {case['config']}")
            continue
        print(f"\n=== {dim} | {case['label']} | offset={case['best_offset']}s ===")
        gaps, regimes, offset_vals, qmix_vals = [], [], [], []
        for seed in SEEDS:
            off_wt = run_offset(case["config"], case["best_offset"], seed, case["distance"])
            qmix_wt = run_qmix(case["config"], seed, case["distance"])
            gap = (qmix_wt - off_wt) / off_wt * 100.0
            regime = classify(gap)
            offset_vals.append(off_wt); qmix_vals.append(qmix_wt)
            gaps.append(gap); regimes.append(regime)
            raw_rows.append({"dim": dim, "case": case["label"], "seed": seed,
                             "offset_wt": round(off_wt, 3), "qmix_wt": round(qmix_wt, 3),
                             "gap_pct": round(gap, 3), "regime": regime})
            print(f"  seed {seed}: offset={off_wt:.3f}  qmix={qmix_wt:.3f}  gap={gap:+.3f}%  [{regime}]")

        mean_gap = float(np.mean(gaps))
        lo, hi = bootstrap_ci(gaps)
        # Stability around the SEED-AVERAGED (mean-gap) regime, not the most-frequent.
        mean_regime = classify(mean_gap)
        stab = 100.0 * sum(r == mean_regime for r in regimes) / len(regimes)

        summary_rows.append({
            "dim": dim, "case": case["label"],
            "offset_wt_mean": round(float(np.mean(offset_vals)), 3),
            "offset_wt_std": round(float(np.std(offset_vals, ddof=1)), 3),
            "qmix_wt_mean": round(float(np.mean(qmix_vals)), 3),
            "qmix_wt_std": round(float(np.std(qmix_vals, ddof=1)), 3),
            "mean_gap_pct": round(mean_gap, 3),
            "ci_low": round(lo, 3), "ci_high": round(hi, 3),
            "mean_regime": mean_regime,
            "regime_stability_pct": round(stab, 1)})
        print(f"  --> mean gap {mean_gap:+.3f}%  95% CI [{lo:.3f}, {hi:.3f}]  "
              f"{mean_regime}  stability {stab:.0f}%")
    return raw_rows, summary_rows


def main():
    os.makedirs("results/tables", exist_ok=True)
    all_raw, all_sum = [], []
    r, s = run_block(SPATIAL_CASES, "spatial"); all_raw += r; all_sum += s
    r, s = run_block(DEMAND_CASES, "demand");   all_raw += r; all_sum += s
    pd.DataFrame(all_raw).to_csv(OUT_RAW, index=False)
    summ = pd.DataFrame(all_sum); summ.to_csv(OUT_SUMMARY, index=False)
    print("\n========== W1 MULTI-SEED SUMMARY ==========")
    print(summ.to_string(index=False))
    print(f"\nSaved raw to:     {OUT_RAW}")
    print(f"Saved summary to: {OUT_SUMMARY}")
    print("\n*** SANITY CHECK ***")
    print("d=300m spatial and 'medium' demand should BOTH show ~2-3% gap (Effective),")
    print("matching the paper's single-seed values (300m gap = 2.931%).")
    print("If they do -> run is correct, send me the summary.")
    print("If they show >100% -> STOP and tell me, control logic still wrong.")


if __name__ == "__main__":
    main()
