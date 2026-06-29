"""
REVIEW ITEM 2.4 (multi-seed eval): 5-seed evaluation of the ALREADY-TRAINED
600-episode direct Scenario B model.

The training-budget ablation trained one QMIX V2 model directly on Scenario B for
600 episodes (saved as qmix_corridor_model_v2_turning_600ep.pth). The single-seed
eval gave 269.7 s/veh. This script makes that result reviewer-proof by evaluating
the SAME saved model across 5 common SUMO seeds and reporting mean +/- std with a
95% bootstrap CI. NO retraining -- it only loads the saved model and evaluates.

It REUSES the repo's own proven evaluation helpers (normalize_global_state,
split_observations, action_to_phase, run_yellow_with_logging,
run_green_with_logging, get_total_waiting_time) by importing them directly from
evaluate_qmix_corridor_v2_turning_trained_per_second.py, so the evaluation logic is
byte-identical to the validated single-seed evaluator. Only the SUMO seed varies,
injected through TwoIntersectionEnv(sumo_seed=...), which the env already supports.

Reference values (already in the paper):
  Optimized offset (Scenario B, 10-seed):  172.097 s/veh
  QMIX transferred from A (10-seed):        178.455 s/veh  (gap 3.694%, Effective)
  QMIX direct 300-ep:                       258.964 s/veh  (gap 50.476%, Outside)
  QMIX direct 600-ep (single seed):         269.734 s/veh  (gap 56.734%, Outside)

EXPECTED: the 5-seed mean should land near the single-seed 269.7 (say ~255-275),
confirming the budget effect ruling holds across seeds. A value suddenly near ~180
would be surprising and worth a second look, but is not expected.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_scenario_b_600ep_eval_multiseed.py
"""
import os, sys
import numpy as np

REPO_ROOT = os.getcwd()
QMIX_DIR = os.path.join(REPO_ROOT, "src", "qmix")
ENV_DIR = os.path.join(REPO_ROOT, "src", "env", "two_intersections")
for _p in (QMIX_DIR, ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import traci
from two_intersection_env import TwoIntersectionEnv
from qmix_agent import QMIXAgent
# Reuse the PROVEN evaluation helpers from the repo's own evaluator.
import evaluate_qmix_corridor_v2_turning_trained_per_second as ev

MODEL_PATH = "results/raw/qmix_corridor_model_v2_turning_600ep.pth"
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2_turning.sumocfg"
SEEDS = [0, 1, 2, 3, 4]
OFFSET_WT_10SEED = 172.097
OUT_SUMMARY = "results/tables/scenario_b_600ep_multiseed_summary.csv"


def evaluate_one_seed(seed):
    """Run one greedy evaluation episode at a given SUMO seed, reusing the repo's
    proven per-second eval loop. Returns the episode mean total waiting time."""
    env = TwoIntersectionEnv(
        sumo_binary="sumo",
        sumo_config=SUMO_CONFIG,
        simulation_steps=ev.SIMULATION_STEPS,
        green_duration=ev.GREEN_DURATION,
        yellow_duration=ev.YELLOW_DURATION,
        sumo_seed=seed,
    )
    qmix = QMIXAgent(n_agents=2, obs_dim=3, state_dim=6, action_dim=2, batch_size=64)
    qmix.load(MODEL_PATH)
    qmix.epsilon = 0.0

    raw_state = env.reset()
    global_state = ev.normalize_global_state(raw_state)
    observations = ev.split_observations(global_state)

    rows = []
    decision = 0
    while env.step_count < ev.SIMULATION_STEPS:
        actions = qmix.select_actions(observations)
        selected_phases = {
            "J1": ev.action_to_phase(env, actions[0]),
            "J2": ev.action_to_phase(env, actions[1]),
        }
        decision += 1
        ev.run_yellow_with_logging(env=env, selected_phases=selected_phases,
                                   rows=rows, decision=decision, actions=actions)
        ev.run_green_with_logging(env=env, selected_phases=selected_phases,
                                  rows=rows, decision=decision, actions=actions)
        next_state = env.get_state()
        global_state = ev.normalize_global_state(next_state)
        observations = ev.split_observations(global_state)
    env.close()

    waits = [r["total_waiting_time"] for r in rows if "total_waiting_time" in r]
    return float(np.mean(waits)) if waits else float("nan")


def bootstrap_ci(values, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    boot = [np.mean(rng.choice(arr, size=len(arr), replace=True)) for _ in range(n)]
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def main():
    if not os.path.exists(MODEL_PATH):
        print(f"[ERROR] saved 600-episode model not found: {MODEL_PATH}")
        print("Run run_scenario_b_600ep_ablation.py first to train it.")
        return
    os.makedirs("results/tables", exist_ok=True)

    print(f"=== 5-seed evaluation of the 600-episode direct Scenario B model ===")
    waits = []
    for s in SEEDS:
        wt = evaluate_one_seed(s)
        waits.append(wt)
        print(f"  seed {s}: mean waiting time = {wt:.3f} s/veh")

    mean_wt = float(np.mean(waits))
    std_wt = float(np.std(waits, ddof=1)) if len(waits) > 1 else 0.0
    lo, hi = bootstrap_ci(waits)
    gap = (mean_wt - OFFSET_WT_10SEED) / OFFSET_WT_10SEED * 100.0

    import pandas as pd
    pd.DataFrame([{
        "model": "QMIX direct Scenario B, 600 episodes",
        "seeds": len(SEEDS),
        "mean_waiting": round(mean_wt, 3),
        "std_waiting": round(std_wt, 3),
        "ci_low": round(lo, 3), "ci_high": round(hi, 3),
        "gap_vs_offset_pct": round(gap, 3),
    }]).to_csv(OUT_SUMMARY, index=False)

    print("\n========== SCENARIO B 600-EPISODE 5-SEED EVAL ==========")
    print(f"  Mean waiting time: {mean_wt:.3f} +/- {std_wt:.3f} s/veh")
    print(f"  95% bootstrap CI:  [{lo:.3f}, {hi:.3f}]")
    print(f"  Gap vs optimized offset (172.097): {gap:+.3f}%")
    print("\n  Reference:")
    print("    transferred-from-A (10-seed):  178.455  (gap 3.694%, Effective)")
    print("    direct 300-ep (single seed):   258.964  (gap 50.476%, Outside)")
    print("    direct 600-ep (single seed):   269.734  (gap 56.734%, Outside)")
    print("\n  INTERPRETATION:")
    if mean_wt > 240:
        print("    -> 5-seed mean confirms: doubling the budget does NOT recover")
        print("       performance. The transfer advantage is robustly NOT a")
        print("       training-budget artifact.")
    elif mean_wt < 200:
        print("    -> unexpected: 5-seed mean approaches the transferred model;")
        print("       send me the numbers and I will re-interpret.")
    else:
        print("    -> intermediate; send me the numbers and I will interpret.")
    print(f"\n  Saved summary to: {OUT_SUMMARY}")
    print("  Send me this and I will finalize the Scenario B ablation reporting.")


if __name__ == "__main__":
    main()
