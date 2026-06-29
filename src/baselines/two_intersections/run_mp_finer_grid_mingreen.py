"""
REVIEW ITEM #6: Finer spatial grid (450 m) + Max Pressure min-green sensitivity.

Two parts:
  PART A -- Locate the Max Pressure transition distance more precisely by adding
            d=450 m (between 300 m, where MP is best, and 500 m, where MP and the
            offset are statistically tied). Runs all three controllers fully paired
            on the same 5 seeds at 450 m, medium demand.
  PART B -- Test whether the 10 s MP minimum-green interval drives the long-spacing
            failure: re-run Max Pressure at d=750 m and d=1000 m with min-green
            raised from 10 s to 20 s, and compare the gap.

PART A first GENERATES the 450 m corridor by reusing the repo's own scenario
generator (generate_distance_scenarios.generate_scenario), so the 450 m network is
built identically to the existing distance corridors (requires `netconvert` on PATH,
same as when the other corridors were built). It then reuses the three proven
evaluation routines, exactly like run_fully_paired_sweeps.py.

PART B reuses the proven Max Pressure per-TL functions with MIN_GREEN temporarily
raised to 20 s.

SANITY (Part A): the 450 m QMIX gap should sit between the 300 m (~2.7%) and 500 m
(~25%) values; the MP gap should sit between -13.8% (300 m) and +3.1% (500 m), i.e.
near the crossover. A gap >150% = broken; STOP.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_mp_finer_grid_mingreen.py
"""
import os, sys
import numpy as np

REPO_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "qmix"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "baselines", "two_intersections"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "env", "two_intersections"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "traci_tests"))

import traci
import evaluate_qmix_distance_sensitivity as qdist
import run_distance_offset_sweep as offsweep
import max_pressure_corridor as mpc
if not hasattr(qdist, "np"):
    qdist.np = np

SEEDS = [0, 1, 2, 3, 4]
OFFSET_GRID = list(range(0, 91, 5))   # 90 s cycle, same as the main spatial sweep
OUT_A = "results/tables/mp_finer_grid_450m_summary.csv"
OUT_A_RAW = "results/tables/mp_finer_grid_450m_raw.csv"
OUT_B = "results/tables/mp_mingreen_sensitivity_summary.csv"

CONFIG_450 = "sumo_scenarios/two_intersections/distance_450m/corridor_turning.sumocfg"


# ---------------- shared helpers ----------------
def run_offset(config, offset, seed, distance):
    _, s = offsweep.run_distance_offset(distance=distance, offset=offset, sumo_seed=seed,
                                        sumo_config_override=config, scenario_label="finer")
    return float(s["mean_total_waiting_time"])


def run_qmix(config, seed, distance):
    _, s = qdist.evaluate_qmix_for_distance(distance=distance, sumo_seed=seed,
                                            sumo_config_override=config, scenario_label="finer")
    return float(s["mean_total_waiting_time"])


def run_mp(config, seed, min_green=None):
    """2-intersection Max Pressure; min_green overrides mpc.MIN_GREEN if given."""
    saved = mpc.MIN_GREEN
    if min_green is not None:
        mpc.MIN_GREEN = min_green
    started = False
    try:
        traci.start([mpc.SUMO_BINARY, "-c", config, "--no-step-log", "true", "--seed", str(seed)])
        started = True
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
        return float(np.mean(waits))
    finally:
        if started:
            traci.close()
        mpc.MIN_GREEN = saved


def sweep_best_offset(config, distance, seed):
    best_wt, best_off = float("inf"), None
    for off in OFFSET_GRID:
        wt = run_offset(config, off, seed, distance)
        if wt < best_wt:
            best_wt, best_off = wt, off
    return best_off, best_wt


def bootstrap_ci(vals, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    a = np.array(vals, float)
    b = [np.mean(rng.choice(a, size=len(a), replace=True)) for _ in range(n)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def regime(g):
    return "Effective" if g <= 5 else ("Marginal" if g <= 10 else "Outside horizon")


# ---------------- Part A: 450 m ----------------
def ensure_450_config():
    if os.path.exists(CONFIG_450):
        print(f"[OK] 450 m config already exists: {CONFIG_450}")
        return True
    print("[INFO] generating 450 m corridor via the repo scenario generator...")
    try:
        import generate_distance_scenarios as gen
        gen.generate_scenario(450)
    except Exception as e:
        print(f"[ERROR] could not generate 450 m corridor: {e}")
        print("        (requires netconvert on PATH, same as the other corridors)")
        return False
    return os.path.exists(CONFIG_450)


def part_a():
    if not ensure_450_config():
        print("[SKIP] Part A skipped: no 450 m config.")
        return None
    print("\n=== PART A: fully paired sweep at d=450 m, medium demand ===")
    offs, qms, mps, best_offsets = [], [], [], []
    raw_rows = []
    for seed in SEEDS:
        bo, ow = sweep_best_offset(CONFIG_450, 450, seed)
        qw = run_qmix(CONFIG_450, seed, 450)
        mw = run_mp(CONFIG_450, seed)
        offs.append(ow); qms.append(qw); mps.append(mw); best_offsets.append(bo)
        gq_s = (qw - ow) / ow * 100
        gm_s = (mw - ow) / ow * 100
        raw_rows.append({"seed": seed, "best_offset": bo,
                         "offset_wt": round(ow, 3), "qmix_wt": round(qw, 3),
                         "mp_wt": round(mw, 3), "G_QMIX": round(gq_s, 3),
                         "G_MP": round(gm_s, 3)})
        print(f"  seed {seed}: best_off={bo}s offset={ow:.2f} qmix={qw:.2f} mp={mw:.2f}")
    g_q = [(q - o) / o * 100 for q, o in zip(qms, offs)]
    g_m = [(m - o) / o * 100 for m, o in zip(mps, offs)]
    gq, gm = float(np.mean(g_q)), float(np.mean(g_m))
    gqlo, gqhi = bootstrap_ci(g_q); gmlo, gmhi = bootstrap_ci(g_m)
    best = min({"Optimized offset": float(np.mean(offs)), "QMIX": float(np.mean(qms)),
                "Max Pressure": float(np.mean(mps))},
               key=lambda k: {"Optimized offset": float(np.mean(offs)), "QMIX": float(np.mean(qms)),
                              "Max Pressure": float(np.mean(mps))}[k])
    row = {"distance": 450, "best_offset_mode": max(set(best_offsets), key=best_offsets.count),
           "offset_wt_mean": round(float(np.mean(offs)), 3),
           "offset_wt_std": round(float(np.std(offs, ddof=1)), 3),
           "qmix_wt_mean": round(float(np.mean(qms)), 3),
           "qmix_wt_std": round(float(np.std(qms, ddof=1)), 3),
           "mp_wt_mean": round(float(np.mean(mps)), 3),
           "mp_wt_std": round(float(np.std(mps, ddof=1)), 3),
           "G_QMIX_mean": round(gq, 3), "G_QMIX_ci": f"[{gqlo:.2f}, {gqhi:.2f}]",
           "G_MP_mean": round(gm, 3), "G_MP_ci": f"[{gmlo:.2f}, {gmhi:.2f}]",
           "qmix_regime": regime(gq), "best_controller": best}
    import pandas as pd
    pd.DataFrame(raw_rows).to_csv(OUT_A_RAW, index=False)
    pd.DataFrame([row]).to_csv(OUT_A, index=False)
    print(f"\n  450 m: offset {row['offset_wt_mean']} | QMIX {row['qmix_wt_mean']} "
          f"(G {gq:+.2f}% {row['G_QMIX_ci']}) | MP {row['mp_wt_mean']} (G {gm:+.2f}% {row['G_MP_ci']})")
    print(f"  best controller: {best}")
    print(f"  Saved Part A raw to:     {OUT_A_RAW}")
    print(f"  Saved Part A summary to: {OUT_A}")
    return row


# ---------------- Part B: min-green sensitivity ----------------
def part_b():
    print("\n=== PART B: Max Pressure min-green sensitivity at long spacing ===")
    print("    (computing the optimized-offset benchmark too, so G_MP can be reported)")
    configs = {750: "sumo_scenarios/two_intersections/distance_750m/corridor_turning.sumocfg",
               1000: "sumo_scenarios/two_intersections/distance_1000m/corridor_turning.sumocfg"}
    rows = []
    for dist, config in configs.items():
        if not os.path.exists(config):
            print(f"[WARN] missing {dist} m config, skipping")
            continue
        # optimized offset benchmark at this distance (re-swept per seed), and
        # Max Pressure at min-green 10 s and 20 s, all on the same seeds.
        offs, mp10, mp20 = [], [], []
        for s in SEEDS:
            _, ow = sweep_best_offset(config, dist, s)
            offs.append(ow)
            mp10.append(run_mp(config, s, min_green=10))
            mp20.append(run_mp(config, s, min_green=20))
        o_mean = float(np.mean(offs))
        m10_mean, m20_mean = float(np.mean(mp10)), float(np.mean(mp20))
        g10 = [(m - o) / o * 100 for m, o in zip(mp10, offs)]
        g20 = [(m - o) / o * 100 for m, o in zip(mp20, offs)]
        g10_mean, g20_mean = float(np.mean(g10)), float(np.mean(g20))
        g10lo, g10hi = bootstrap_ci(g10); g20lo, g20hi = bootstrap_ci(g20)
        rows.append({"distance": dist,
                     "offset_wt_mean": round(o_mean, 3),
                     "mp_wt_10s_mean": round(m10_mean, 3),
                     "mp_wt_10s_std": round(float(np.std(mp10, ddof=1)), 3),
                     "mp_wt_20s_mean": round(m20_mean, 3),
                     "mp_wt_20s_std": round(float(np.std(mp20, ddof=1)), 3),
                     "G_MP_10s_mean": round(g10_mean, 3), "G_MP_10s_ci": f"[{g10lo:.2f}, {g10hi:.2f}]",
                     "G_MP_20s_mean": round(g20_mean, 3), "G_MP_20s_ci": f"[{g20lo:.2f}, {g20hi:.2f}]",
                     "gap_change_pts": round(g20_mean - g10_mean, 3)})
        print(f"  d={dist}m: offset {o_mean:.2f} | "
              f"MP@10s {m10_mean:.2f} (G {g10_mean:+.2f}%) | "
              f"MP@20s {m20_mean:.2f} (G {g20_mean:+.2f}%) | "
              f"gap change {g20_mean - g10_mean:+.2f} pts")
    import pandas as pd
    pd.DataFrame(rows).to_csv(OUT_B, index=False)
    print(f"  Saved Part B to: {OUT_B}")
    return rows


def main():
    os.makedirs("results/tables", exist_ok=True)
    a = part_a()
    b = part_b()
    print("\n========== #6 SUMMARY ==========")
    if a:
        print(f"PART A (450 m): QMIX gap {a['G_QMIX_mean']}% ({a['qmix_regime']}), "
              f"MP gap {a['G_MP_mean']}%, best = {a['best_controller']}")
        print("  -> locates the MP transition: compare to 300 m (MP best) and 500 m (tie).")
    if b:
        print("PART B (min-green): G_MP at 10 s vs 20 s min-green at 750/1000 m:")
        for r in b:
            print(f"    d={r['distance']}m: G_MP 10s={r['G_MP_10s_mean']}% "
                  f"-> 20s={r['G_MP_20s_mean']}% (change {r['gap_change_pts']:+} pts)")
        print("  -> if 20 s does NOT substantially reduce G_MP, the long-spacing failure is")
        print("     structural (acyclic misalignment), not a min-green artifact. Send both tables.")


if __name__ == "__main__":
    main()
