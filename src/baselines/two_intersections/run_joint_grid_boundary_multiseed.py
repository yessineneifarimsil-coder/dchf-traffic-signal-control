"""
JOINT-GRID BOUNDARY MULTI-SEED VALIDATION (closes the last Critical).

The 30-cell joint distance x demand grid is single-seed. The spatial and demand
horizon BOUNDARIES were already multi-seed validated (W1). This script validates
the remaining boundary-ADJACENT cells of the joint grid -- the off-cross cells
whose gap sits close enough to a 5% or 10% threshold that seed variation could
plausibly flip the DCHF regime. Deep-region cells (e.g. gap 104%, 132%) cannot
flip and are not run.

Reuses the SAME proven functions as the successful W1 script
(run_distance_offset + evaluate_qmix_for_distance), looping over 5 seeds, with the
correct per-cell best offset taken from the published grid summary. Computes the
mean gap, 95% bootstrap CI, and mean-regime stability per cell.

Boundary-adjacent cells (single-seed gap / regime for reference):
  d=100,  medium          gap  8.334%  Marginal
  d=500,  saturation      gap 12.453%  Outside        (capacity-limited)
  d=500,  oversaturation  gap  6.014%  Marginal       (oversaturated)
  d=750,  oversaturation  gap  9.930%  Marginal       (oversaturated)
  d=1000, saturation      gap  4.130%  Effective      (capacity-limited)
  d=1000, oversaturation  gap  0.583%  Effective      (oversaturated)

SANITY: these are off-cross cells, so unlike W1 there is no reference cell that must
reproduce exactly. But the means should land in the same ballpark as the
single-seed gaps above (regime may legitimately shift at a true boundary -- that is
the point of running them). A gap >150% anywhere would indicate a broken run; STOP.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_joint_grid_boundary_multiseed.py
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

# Safeguard: distance module references np.nan but only imports pandas.
if not hasattr(qdist, "np"):
    qdist.np = np

SEEDS = [0, 1, 2, 3, 4]
GRID_DIR = "sumo_scenarios/two_intersections/distance_demand_grid"

# best_offset values taken from distance_demand_grid_dchf_summary_updated.csv
# label -> distance (for the raw CSV), config dir, best offset, single-seed gap
CELLS = [
    {"label": "d=100, medium",          "distance": 100,  "dir": "d100_medium",          "best_offset": 25, "ss_gap": 8.334},
    {"label": "d=500, saturation",      "distance": 500,  "dir": "d500_saturation",      "best_offset": 10, "ss_gap": 12.453},
    {"label": "d=500, oversaturation",  "distance": 500,  "dir": "d500_oversaturation",  "best_offset": 0,  "ss_gap": 6.014},
    {"label": "d=750, oversaturation",  "distance": 750,  "dir": "d750_oversaturation",  "best_offset": 5,  "ss_gap": 9.930},
    {"label": "d=1000, saturation",     "distance": 1000, "dir": "d1000_saturation",     "best_offset": 45, "ss_gap": 4.130},
    {"label": "d=1000, oversaturation", "distance": 1000, "dir": "d1000_oversaturation", "best_offset": 0,  "ss_gap": 0.583},
]

OUT_RAW = "results/tables/joint_grid_boundary_multiseed_raw.csv"
OUT_SUMMARY = "results/tables/joint_grid_boundary_multiseed_summary.csv"


def cfg(cell):
    return os.path.join(GRID_DIR, cell["dir"], "corridor_turning.sumocfg")


def run_offset(config, best_offset, seed, distance):
    _, summary = offsweep.run_distance_offset(
        distance=distance, offset=best_offset, sumo_seed=seed,
        sumo_config_override=config, scenario_label="jointbnd")
    return float(summary["mean_total_waiting_time"])


def run_qmix(config, seed, distance):
    _, summary = qdist.evaluate_qmix_for_distance(
        distance=distance, sumo_seed=seed,
        sumo_config_override=config, scenario_label="jointbnd")
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


def main():
    os.makedirs("results/tables", exist_ok=True)
    raw_rows, summary_rows = [], []

    for cell in CELLS:
        config = cfg(cell)
        if not os.path.exists(config):
            print(f"[WARN] missing config, skipping: {config}")
            continue
        print(f"\n=== {cell['label']} | offset={cell['best_offset']}s "
              f"(single-seed gap {cell['ss_gap']}%) ===")
        gaps, regimes, offs, qmixs = [], [], [], []
        for seed in SEEDS:
            ow = run_offset(config, cell["best_offset"], seed, cell["distance"])
            qw = run_qmix(config, seed, cell["distance"])
            gap = (qw - ow) / ow * 100.0
            gaps.append(gap); regimes.append(classify(gap))
            offs.append(ow); qmixs.append(qw)
            raw_rows.append({"cell": cell["label"], "seed": seed,
                             "offset_wt": round(ow, 3), "qmix_wt": round(qw, 3),
                             "gap_pct": round(gap, 3), "regime": classify(gap)})
            print(f"  seed {seed}: offset={ow:.3f}  qmix={qw:.3f}  gap={gap:+.3f}%  [{classify(gap)}]")

        mean_gap = float(np.mean(gaps))
        lo, hi = bootstrap_ci(gaps)
        mean_regime = classify(mean_gap)
        stab = 100.0 * sum(r == mean_regime for r in regimes) / len(regimes)
        summary_rows.append({"cell": cell["label"],
                             "offset_wt_mean": round(float(np.mean(offs)), 3),
                             "qmix_wt_mean": round(float(np.mean(qmixs)), 3),
                             "single_seed_gap_pct": cell["ss_gap"],
                             "mean_gap_pct": round(mean_gap, 3),
                             "ci_low": round(lo, 3), "ci_high": round(hi, 3),
                             "mean_regime": mean_regime,
                             "regime_stability_pct": round(stab, 1)})
        print(f"  --> mean gap {mean_gap:+.3f}%  95% CI [{lo:.3f}, {hi:.3f}]  "
              f"{mean_regime}  stability {stab:.0f}%  (single-seed was {cell['ss_gap']}%)")

    pd.DataFrame(raw_rows).to_csv(OUT_RAW, index=False)
    summ = pd.DataFrame(summary_rows)
    summ.to_csv(OUT_SUMMARY, index=False)
    print("\n========== JOINT-GRID BOUNDARY MULTI-SEED SUMMARY ==========")
    print(summ.to_string(index=False))
    print(f"\nSaved raw to:     {OUT_RAW}")
    print(f"Saved summary to: {OUT_SUMMARY}")
    print("\nSend me the summary table and I will integrate it.")
    print("Note: a regime may legitimately shift at a true boundary -- report faithfully.")
    print("Only a gap >150% would indicate a broken run; otherwise results are valid.")


if __name__ == "__main__":
    main()
