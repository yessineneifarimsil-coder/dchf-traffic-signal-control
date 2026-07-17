"""
REVIEW ITEM 2.3: Max Pressure at N=3 and N=5 reference conditions.

The scalability experiments (N=3, N=5) were QMIX-only. This script adds the Max
Pressure controller-family reference at the homogeneous d=300 m, medium-demand
reference condition for N=3 and N=5, across 5 seeds, so the controller-family
comparison extends to the scalability dimension.

It REUSES the proven per-traffic-light Max Pressure logic from
src/baselines/two_intersections/max_pressure_corridor.py
(choose_max_pressure_phase, apply_transition, the metric helpers, and the phase
constants / MIN_GREEN / YELLOW_DURATION), and only generalizes the run loop from
the hardcoded J1/J2 to ALL traffic lights discovered dynamically via TraCI. This
keeps the acyclic re-evaluation, the 10 s min-green, and the pressure computation
identical to the validated 2-intersection implementation.

For comparison context, the published single-seed optimized-offset and QMIX values
at these conditions are:
  N=3, d=300 m medium:  offset 227.171,  QMIX 237.292  (QMIX gap 4.455%)
  N=5, d=300 m medium:  offset 360.505,  QMIX 356.659  (QMIX gap -1.067%)
These are printed alongside the MP results so the controller-family picture is clear.

SANITY: MP mean waiting time should be a plausible time-averaged network waiting measure (tens to a few
hundred seconds), with zero/near-zero buffered ratio at medium demand. A value
>2000 or a crash would indicate a config/outlane problem; STOP and report.

Run from repo root:
    conda activate traffic_rl
    python src/baselines/scalability/run_max_pressure_scalability.py
"""
import os, sys, csv
import numpy as np

REPO_ROOT = os.getcwd()
MP_DIR = os.path.join(REPO_ROOT, "src", "baselines", "two_intersections")
sys.path.insert(0, MP_DIR)

import traci
import max_pressure_corridor as mp   # proven 2-intersection MP implementation

# Reference conditions: (label, N, sumo config, published offset WT, published QMIX WT)
CONDITIONS = [
    {"label": "N=3, d=300m medium", "N": 3,
     "config": "sumo_scenarios/three_intersections/distance_sensitivity/d23_300m/corridor_3x2_through.sumocfg",
     "offset_wt": 227.171, "qmix_wt": 237.292},
    {"label": "N=5, d=300m medium", "N": 5,
     "config": "sumo_scenarios/scalability/corridor_5x2_d300m_medium/corridor.sumocfg",
     "offset_wt": 360.505, "qmix_wt": 356.659},
]

SEEDS = [0, 1, 2, 3, 4]
OUT_RAW = "results/tables/max_pressure_scalability_raw.csv"
OUT_SUMMARY = "results/tables/max_pressure_scalability_summary.csv"


def run_single_seed_n(config, seed):
    """Acyclic Max Pressure over ALL traffic lights in the corridor (generalized
    from the proven 2-light loop). Returns mean episode metrics."""
    traci.start([mp.SUMO_BINARY, "-c", config, "--no-step-log", "true",
                 "--seed", str(seed)])
    tl_ids = list(traci.trafficlight.getIDList())
    previous_phase = {tl: mp.MAIN_GREEN for tl in tl_ids}

    waits, speeds, queues, vehs = [], [], [], []
    step = 0
    while step < mp.SIMULATION_STEPS:
        # Decide each TL's next phase from its local pressure (proven function).
        chosen = {}
        any_yellow = False
        for tl in tl_ids:
            phase, group, sp, mpr = mp.choose_max_pressure_phase(tl)
            chosen[tl] = phase
            if mp.apply_transition(tl, previous_phase[tl], phase):
                any_yellow = True

        if any_yellow:
            for _ in range(mp.YELLOW_DURATION):
                if step >= mp.SIMULATION_STEPS:
                    break
                traci.simulationStep()
                waits.append(mp.get_total_waiting_time())
                speeds.append(mp.get_mean_speed())
                queues.append(mp.get_total_queue())
                vehs.append(mp.get_vehicle_count())
                step += 1

        # Apply chosen greens, hold MIN_GREEN, then re-decide (acyclic).
        for tl in tl_ids:
            traci.trafficlight.setPhase(tl, chosen[tl])
            traci.trafficlight.setPhaseDuration(tl, mp.MIN_GREEN)

        for _ in range(mp.MIN_GREEN):
            if step >= mp.SIMULATION_STEPS:
                break
            traci.simulationStep()
            waits.append(mp.get_total_waiting_time())
            speeds.append(mp.get_mean_speed())
            queues.append(mp.get_total_queue())
            vehs.append(mp.get_vehicle_count())
            if step % 600 == 0:
                print(f"    [seed {seed}] step {step} | wait {waits[-1]:.1f} | "
                      f"speed {speeds[-1]:.2f} | queue {queues[-1]}")
            step += 1

        for tl in tl_ids:
            previous_phase[tl] = chosen[tl]

    traci.close()
    n = len(waits)
    return {"mean_waiting": sum(waits) / n, "mean_speed": sum(speeds) / n,
            "mean_queue": sum(queues) / n, "mean_vehicles": sum(vehs) / n}


def bootstrap_ci(values, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    boot = [np.mean(rng.choice(arr, size=len(arr), replace=True)) for _ in range(n)]
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def main():
    os.makedirs("results/tables", exist_ok=True)
    raw_rows, summary_rows = [], []

    for cond in CONDITIONS:
        if not os.path.exists(cond["config"]):
            print(f"[WARN] missing config, skipping: {cond['config']}")
            continue
        print(f"\n=== {cond['label']} (Max Pressure, {len(SEEDS)} seeds) ===")
        mp_waits = []
        for seed in SEEDS:
            res = run_single_seed_n(cond["config"], seed)
            mp_waits.append(res["mean_waiting"])
            raw_rows.append({"condition": cond["label"], "seed": seed,
                             "mp_mean_waiting": round(res["mean_waiting"], 3),
                             "mp_mean_speed": round(res["mean_speed"], 3),
                             "mp_mean_queue": round(res["mean_queue"], 3)})
            print(f"  seed {seed}: MP mean waiting = {res['mean_waiting']:.3f}")

        mp_mean = float(np.mean(mp_waits))
        mp_std = float(np.std(mp_waits, ddof=1)) if len(mp_waits) > 1 else 0.0
        lo, hi = bootstrap_ci(mp_waits)
        # Gap of MP vs the published optimized-offset benchmark.
        g_mp = (mp_mean - cond["offset_wt"]) / cond["offset_wt"] * 100.0
        # Which controller wins (lower waiting time)?
        trio = {"Optimized offset": cond["offset_wt"], "QMIX": cond["qmix_wt"],
                "Max Pressure": mp_mean}
        best = min(trio, key=trio.get)
        summary_rows.append({
            "condition": cond["label"], "N": cond["N"],
            "offset_wt": cond["offset_wt"], "qmix_wt": cond["qmix_wt"],
            "mp_wt_mean": round(mp_mean, 3), "mp_wt_std": round(mp_std, 3),
            "mp_ci_low": round(lo, 3), "mp_ci_high": round(hi, 3),
            "G_MP_vs_offset_pct": round(g_mp, 3),
            "best_controller": best})
        print(f"  --> MP mean {mp_mean:.3f} +/- {mp_std:.3f}  95% CI [{lo:.3f}, {hi:.3f}]")
        print(f"      G_MP vs offset = {g_mp:+.3f}%  |  best of three: {best}")
        print(f"      (offset {cond['offset_wt']}, QMIX {cond['qmix_wt']})")

    import pandas as pd
    pd.DataFrame(raw_rows).to_csv(OUT_RAW, index=False)
    summ = pd.DataFrame(summary_rows)
    summ.to_csv(OUT_SUMMARY, index=False)
    print("\n========== MAX PRESSURE SCALABILITY SUMMARY ==========")
    print(summ.to_string(index=False))
    print(f"\nSaved raw to:     {OUT_RAW}")
    print(f"Saved summary to: {OUT_SUMMARY}")
    print("\nSend me the summary table and I will integrate it.")
    print("Note: MP values are 5-seed; offset/QMIX are published single-seed reference,")
    print("so this is a controller-family diagnostic (state it as such, like the other MP sweeps).")


if __name__ == "__main__":
    main()
