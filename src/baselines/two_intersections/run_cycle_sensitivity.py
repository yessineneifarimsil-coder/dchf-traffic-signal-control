"""
GENERALIZABILITY (cycle sensitivity): does the spatial horizon shift with cycle
length, as classical progression theory predicts?

Classical coordination theory ties the useful progression range to cycle length and
free-flow travel time. The paper holds the cycle at 90 s throughout, so a reviewer
asks whether the spatial horizon H_S moves when the cycle changes. This script tests
three cycles -- 60 s, 90 s (the paper's setting), and 120 s -- at the spatial-horizon
boundary distances (200, 300, 500 m, medium demand) and reports whether the
effective -> outside boundary moves.

CYCLE CONTROL: both controllers use green = (cycle/2 - yellow):
    60 s cycle -> green 27 s ; 90 s -> green 42 s ; 120 s -> green 57 s
For the optimized offset benchmark this changes the fixed cycle and the offset range
(0..cycle in 5 s steps), so the best offset is RE-SWEPT for every (cycle, distance).
For QMIX the trained policy is re-run with the matching green-hold; QMIX is NOT
retrained per cycle, so its rows are an honest robustness probe of the 42 s-trained
policy under a different hold, not a per-cycle re-optimization. This asymmetry is
stated in the manuscript when integrating.

For each (cycle, distance): re-sweep offsets -> best offset + offset WT (per seed),
run QMIX (per seed), gap = (qmix - offset)/offset; report mean gap + 95% CI + regime.

SANITY: at 90 s cycle the d=300 m gap must reproduce ~2-3% (canonical). If it does,
the cycle machinery is correct. >150% anywhere = broken; STOP.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_cycle_sensitivity.py
"""
import os, sys
import numpy as np

REPO_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "qmix"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "baselines", "two_intersections"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "env", "two_intersections"))

import evaluate_qmix_distance_sensitivity as qdist
import run_distance_offset_sweep as offsweep
if not hasattr(qdist, "np"):
    qdist.np = np

YELLOW = 3
CYCLES = [60, 90, 120]                 # seconds
DISTANCES = [200, 300, 500]            # H_S boundary span, medium demand
SEEDS = [0, 1, 2]                      # sweep is expensive; 3 seeds
CONFIG = "sumo_scenarios/two_intersections/distance_{d}m/corridor_turning.sumocfg"

OUT_RAW = "results/tables/cycle_sensitivity_raw.csv"
OUT_SUMMARY = "results/tables/cycle_sensitivity_summary.csv"


def set_cycle(cycle):
    """Patch green/yellow/cycle globals in BOTH controller modules so they use
    `cycle`. YELLOW is held constant at 3 s; it is set explicitly anyway so no stale
    90 s-cycle assumption can leak through either module's call-time reads."""
    green = cycle // 2 - YELLOW
    # offset benchmark: phase_from_cycle_time reads all three at call time
    offsweep.GREEN_DURATION = green
    offsweep.YELLOW_DURATION = YELLOW
    offsweep.CYCLE_LENGTH = 2 * (green + YELLOW)   # == cycle
    # qmix evaluator: reads GREEN_DURATION and YELLOW_DURATION at call time
    # (it is acyclic and has no CYCLE_LENGTH, so none is set)
    qdist.GREEN_DURATION = green
    qdist.YELLOW_DURATION = YELLOW
    return green


def offset_grid(cycle):
    return list(range(0, cycle, 5))


def sweep_best_offset(config, distance, cycle, seed):
    """Re-sweep offsets at this cycle; return (best_offset, best_wt)."""
    best_wt, best_off = float("inf"), None
    for off in offset_grid(cycle):
        _, s = offsweep.run_distance_offset(distance=distance, offset=off, sumo_seed=seed,
                                            sumo_config_override=config, scenario_label="cycle")
        wt = float(s["mean_total_waiting_time"])
        if wt < best_wt:
            best_wt, best_off = wt, off
    return best_off, best_wt


def run_qmix(config, distance, seed):
    _, s = qdist.evaluate_qmix_for_distance(distance=distance, sumo_seed=seed,
                                            sumo_config_override=config, scenario_label="cycle")
    return float(s["mean_total_waiting_time"])


def bootstrap_ci(vals, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    a = np.array(vals, float)
    b = [np.mean(rng.choice(a, size=len(a), replace=True)) for _ in range(n)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def regime(g):
    return "Effective" if g <= 5 else ("Marginal" if g <= 10 else "Outside horizon")


def main():
    os.makedirs("results/tables", exist_ok=True)
    raw, summ = [], []
    for cycle in CYCLES:
        green = set_cycle(cycle)
        print(f"\n########## CYCLE {cycle}s (green {green}s) ##########")
        for d in DISTANCES:
            config = CONFIG.format(d=d)
            if not os.path.exists(config):
                print(f"[WARN] missing config, skipping: {config}")
                continue
            print(f"\n=== cycle {cycle}s | d={d}m ===")
            gaps, offs_wt, qmix_wt, best_offsets = [], [], [], []
            for seed in SEEDS:
                bo, ow = sweep_best_offset(config, d, cycle, seed)
                qw = run_qmix(config, d, seed)
                gap = (qw - ow) / ow * 100
                gaps.append(gap); offs_wt.append(ow); qmix_wt.append(qw); best_offsets.append(bo)
                raw.append({"cycle": cycle, "distance": d, "seed": seed,
                            "best_offset": bo, "offset_wt": round(ow, 3),
                            "qmix_wt": round(qw, 3), "gap_pct": round(gap, 3)})
                print(f"  seed {seed}: best_off={bo}s offset={ow:.2f} qmix={qw:.2f} gap={gap:+.2f}%")
            mg = float(np.mean(gaps)); lo, hi = bootstrap_ci(gaps)
            gap_std = float(np.std(gaps, ddof=1)) if len(gaps) > 1 else 0.0
            mean_regime = regime(mg)
            seed_regimes = [regime(g) for g in gaps]
            stability = 100.0 * sum(r == mean_regime for r in seed_regimes) / len(seed_regimes)
            summ.append({"cycle": cycle, "distance": d,
                         "best_offset_mode": max(set(best_offsets), key=best_offsets.count),
                         "offset_wt_mean": round(float(np.mean(offs_wt)), 3),
                         "offset_wt_std": round(float(np.std(offs_wt, ddof=1)), 3) if len(offs_wt) > 1 else 0.0,
                         "qmix_wt_mean": round(float(np.mean(qmix_wt)), 3),
                         "qmix_wt_std": round(float(np.std(qmix_wt, ddof=1)), 3) if len(qmix_wt) > 1 else 0.0,
                         "mean_gap_pct": round(mg, 3),
                         "gap_std_pct": round(gap_std, 3),
                         "ci_low": round(lo, 3), "ci_high": round(hi, 3),
                         "regime": mean_regime,
                         "regime_stability_pct": round(stability, 1)})
            print(f"  --> mean gap {mg:+.2f}% +/-{gap_std:.2f} CI [{lo:.2f},{hi:.2f}] "
                  f"-> {mean_regime} (stability {stability:.0f}%)")

    import pandas as pd
    pd.DataFrame(raw).to_csv(OUT_RAW, index=False)
    s = pd.DataFrame(summ)
    s.to_csv(OUT_SUMMARY, index=False)
    print("\n========== CYCLE SENSITIVITY SUMMARY (exploratory, 3-seed probe) ==========")
    print(s.to_string(index=False))
    print(f"\nSaved raw to:     {OUT_RAW}")
    print(f"Saved summary to: {OUT_SUMMARY}")
    print("\nNOTE: this is an EXPLORATORY cycle-sensitivity robustness probe (3 seeds,")
    print("QMIX re-evaluated without per-cycle retraining; offset re-optimized per cycle).")
    print("It is NOT a full statistical validation. If a regime shift appears at a")
    print("boundary, rerun that cell with 5 seeds to confirm.")
    print("\nSANITY: cycle 90s / d=300m gap should be ~2-3% (canonical reference).")
    print("KEY QUESTION: does the effective->outside boundary (around 300-500m) shift")
    print("with cycle? Compare the regime column across the three cycles. Send me the table.")


if __name__ == "__main__":
    main()
