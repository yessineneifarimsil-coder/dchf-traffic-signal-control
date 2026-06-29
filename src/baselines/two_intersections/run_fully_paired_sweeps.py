"""
REVIEW ITEM #1 (most serious flaw): Fully-paired multi-seed demand + spatial sweeps.

The demand and spatial sweep tables currently compare 5-seed Max Pressure against
SINGLE-seed optimized-offset and QMIX reference values. The reviewer requires all
THREE controllers evaluated on the SAME seeds so the controller-family transition
and the demand horizon rest on fully paired statistics, not mixed-seed diagnostics.

This script runs offset, QMIX, and Max Pressure on the SAME 5 SUMO seeds at every
cell of:
  * the SPATIAL sweep (d in {100,200,300,500,750,1000} m, medium demand)
  * the DEMAND sweep (d=300 m, demand in {low,medium,high,saturation,oversaturation})
and reports, per cell:
  * mean +/- std waiting time for each controller
  * QMIX gap and MP gap vs the (now multi-seed) optimized-offset benchmark, each
    with a 95% bootstrap CI
  * paired Wilcoxon p-values for offset-vs-QMIX and offset-vs-MP
  * the best controller and DCHF regime from the multi-seed means

It REUSES the three proven evaluation routines:
  * run_distance_offset            (offset benchmark, holds full green)
  * evaluate_qmix_for_distance     (QMIX, holds full green; np-injection safeguard)
  * the proven per-traffic-light Max Pressure functions from max_pressure_corridor
All three therefore use the identical 3600 s horizon and identical seeds.

SANITY: d=300 m / medium must reproduce the canonical ~2-3% QMIX gap (matches the
paper's 2.931% single-seed and 2.678% W1 5-seed). MP at d<=300 m should be best
(negative gap). A QMIX gap >150% anywhere = broken run; STOP.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_fully_paired_sweeps.py
"""
import os, sys
import numpy as np
from scipy.stats import wilcoxon

REPO_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "qmix"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "baselines", "two_intersections"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "env", "two_intersections"))

import traci
import evaluate_qmix_distance_sensitivity as qdist
import run_distance_offset_sweep as offsweep
import max_pressure_corridor as mpc

if not hasattr(qdist, "np"):
    qdist.np = np  # distance module uses np.nan but only imports pandas

SEEDS = [0, 1, 2, 3, 4]

# Spatial sweep: distance -> (config, best offset at medium demand)
SPATIAL = [
    (100,  "sumo_scenarios/two_intersections/distance_100m/corridor_turning.sumocfg",  25),
    (200,  "sumo_scenarios/two_intersections/distance_200m/corridor_turning.sumocfg",  45),
    (300,  "sumo_scenarios/two_intersections/distance_300m/corridor_turning.sumocfg",  45),
    (500,  "sumo_scenarios/two_intersections/distance_500m/corridor_turning.sumocfg",  70),
    (750,  "sumo_scenarios/two_intersections/distance_750m/corridor_turning.sumocfg",   0),
    (1000, "sumo_scenarios/two_intersections/distance_1000m/corridor_turning.sumocfg", 85),
]

# Demand sweep at d=300 m: demand -> (config, best offset)
DEMAND = [
    ("low",            "sumo_scenarios/two_intersections/demand_sensitivity/demand_low/corridor_turning.sumocfg",            45),
    ("medium",         "sumo_scenarios/two_intersections/demand_sensitivity/demand_medium/corridor_turning.sumocfg",         45),
    ("high",           "sumo_scenarios/two_intersections/demand_sensitivity/demand_high/corridor_turning.sumocfg",           55),
    ("saturation",     "sumo_scenarios/two_intersections/demand_sensitivity/demand_saturation/corridor_turning.sumocfg",     45),
    ("oversaturation", "sumo_scenarios/two_intersections/demand_sensitivity/demand_oversaturation/corridor_turning.sumocfg", 50),
]

OUT_RAW = "results/tables/fully_paired_sweeps_raw.csv"
OUT_SUMMARY = "results/tables/fully_paired_sweeps_summary.csv"


def run_offset(config, offset, seed, distance):
    _, s = offsweep.run_distance_offset(distance=distance, offset=offset, sumo_seed=seed,
                                        sumo_config_override=config, scenario_label="paired")
    return float(s["mean_total_waiting_time"])


def run_qmix(config, seed, distance):
    _, s = qdist.evaluate_qmix_for_distance(distance=distance, sumo_seed=seed,
                                            sumo_config_override=config, scenario_label="paired")
    return float(s["mean_total_waiting_time"])


def run_mp(config, seed):
    """2-intersection Max Pressure, reusing the proven per-TL functions."""
    traci.start([mpc.SUMO_BINARY, "-c", config, "--no-step-log", "true", "--seed", str(seed)])
    tls = list(traci.trafficlight.getIDList())
    prev = {tl: mpc.MAIN_GREEN for tl in tls}
    waits = []
    step = 0
    while step < mpc.SIMULATION_STEPS:
        chosen, any_yellow = {}, False
        for tl in tls:
            phase, *_ = mpc.choose_max_pressure_phase(tl)
            chosen[tl] = phase
            if mpc.apply_transition(tl, prev[tl], phase):
                any_yellow = True
        if any_yellow:
            for _ in range(mpc.YELLOW_DURATION):
                if step >= mpc.SIMULATION_STEPS:
                    break
                traci.simulationStep(); waits.append(mpc.get_total_waiting_time()); step += 1
        for tl in tls:
            traci.trafficlight.setPhase(tl, chosen[tl])
            traci.trafficlight.setPhaseDuration(tl, mpc.MIN_GREEN)
        for _ in range(mpc.MIN_GREEN):
            if step >= mpc.SIMULATION_STEPS:
                break
            traci.simulationStep(); waits.append(mpc.get_total_waiting_time()); step += 1
        for tl in tls:
            prev[tl] = chosen[tl]
    traci.close()
    return float(np.mean(waits))


def bootstrap_ci(vals, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    a = np.array(vals, float)
    b = [np.mean(rng.choice(a, size=len(a), replace=True)) for _ in range(n)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def regime(gap):
    return "Effective" if gap <= 5 else ("Marginal" if gap <= 10 else "Outside horizon")


def paired_p(a, b):
    """Paired Wilcoxon; returns NaN if all differences are zero."""
    d = np.array(a) - np.array(b)
    if np.allclose(d, 0):
        return float("nan")
    try:
        return float(wilcoxon(a, b).pvalue)
    except Exception:
        return float("nan")


def process(label_key, cells, is_spatial):
    raw, summ = [], []
    for cell in cells:
        if is_spatial:
            dist, config, offset = cell
            label = f"d={dist}m"
        else:
            name, config, offset = cell
            dist, label = 300, name
        if not os.path.exists(config):
            print(f"[WARN] missing config, skipping: {config}")
            continue
        print(f"\n=== {label_key}: {label} (offset {offset}s) ===")
        offs, qms, mps = [], [], []
        for seed in SEEDS:
            o = run_offset(config, offset, seed, dist)
            q = run_qmix(config, seed, dist)
            m = run_mp(config, seed)
            offs.append(o); qms.append(q); mps.append(m)
            raw.append({"sweep": label_key, "cell": label, "seed": seed,
                        "offset_wt": round(o, 3), "qmix_wt": round(q, 3), "mp_wt": round(m, 3)})
            print(f"  seed {seed}: offset={o:.2f} qmix={q:.2f} mp={m:.2f}")
        o_mean, q_mean, m_mean = map(lambda x: float(np.mean(x)), (offs, qms, mps))
        g_q = [(q - o) / o * 100 for q, o in zip(qms, offs)]
        g_m = [(m - o) / o * 100 for m, o in zip(mps, offs)]
        gq_lo, gq_hi = bootstrap_ci(g_q); gm_lo, gm_hi = bootstrap_ci(g_m)
        best = min({"Optimized offset": o_mean, "QMIX": q_mean, "Max Pressure": m_mean},
                   key=lambda k: {"Optimized offset": o_mean, "QMIX": q_mean, "Max Pressure": m_mean}[k])
        summ.append({"sweep": label_key, "cell": label, "offset": offset,
                     "offset_wt_mean": round(o_mean, 3), "offset_wt_std": round(float(np.std(offs, ddof=1)), 3),
                     "qmix_wt_mean": round(q_mean, 3), "qmix_wt_std": round(float(np.std(qms, ddof=1)), 3),
                     "mp_wt_mean": round(m_mean, 3), "mp_wt_std": round(float(np.std(mps, ddof=1)), 3),
                     "G_QMIX_mean": round(float(np.mean(g_q)), 3), "G_QMIX_ci": f"[{gq_lo:.2f}, {gq_hi:.2f}]",
                     "G_MP_mean": round(float(np.mean(g_m)), 3), "G_MP_ci": f"[{gm_lo:.2f}, {gm_hi:.2f}]",
                     "p_offset_qmix": round(paired_p(offs, qms), 5),
                     "p_offset_mp": round(paired_p(offs, mps), 5),
                     "qmix_regime": regime(float(np.mean(g_q))),
                     "best_controller": best})
        print(f"  --> offset {o_mean:.2f} | QMIX {q_mean:.2f} (G {np.mean(g_q):+.2f}%) | "
              f"MP {m_mean:.2f} (G {np.mean(g_m):+.2f}%) | best {best}")
    return raw, summ


def main():
    os.makedirs("results/tables", exist_ok=True)
    raw_all, summ_all = [], []
    for key, cells, spatial in [("spatial", SPATIAL, True), ("demand", DEMAND, False)]:
        r, s = process(key, cells, spatial)
        raw_all += r; summ_all += s
    import pandas as pd
    pd.DataFrame(raw_all).to_csv(OUT_RAW, index=False)
    summ = pd.DataFrame(summ_all)
    summ.to_csv(OUT_SUMMARY, index=False)
    print("\n========== FULLY-PAIRED SWEEPS SUMMARY ==========")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(summ.to_string(index=False))
    print(f"\nSaved raw to:     {OUT_RAW}")
    print(f"Saved summary to: {OUT_SUMMARY}")
    print("\nSANITY: d=300m/medium QMIX gap should be ~2-3% (canonical). Send me the summary.")
    print("Paired Wilcoxon at n=5: minimum attainable p is 0.0625, so report CIs alongside.")


if __name__ == "__main__":
    main()
