"""
REVIEW ITEM #7: Initialization ablation for the Scenario B transfer effect.

The transfer result (policy from Scenario A beats direct Scenario B training by ~31%)
has three candidate mechanisms: curriculum, initialization, or optimization landscape.
The reviewer asks for a 3-way comparison on Scenario B:
   (i)   WARM-START : initialize from Scenario A weights, then train on B (no further
                      A training; fresh exploration). [THIS SCRIPT runs it]
   (ii)  RANDOM-INIT: random weights, train on B, identical budget.
                      [ALREADY HAVE: direct 300-ep = 258.964 s/veh]
   (iii) TRANSFER   : the Scenario A policy evaluated on B.
                      [ALREADY HAVE: 178.455 s/veh]

INTERPRETATION:
   - WARM-START approx TRANSFER  -> the benefit is essentially INITIALIZATION
     (a good Q-function start), not sequential curriculum.
   - WARM-START approx RANDOM-INIT (i.e. stays bad) -> initialization alone is not
     enough; the CURRICULUM (actually training through Scenario A) is the active
     ingredient.
   - WARM-START between the two -> partial initialization benefit plus a remaining
     curriculum/landscape component.

DESIGN (safe, no guesswork): copies the proven Scenario B training script
(train_qmix_corridor_v2_turning.py) and patches exactly two things:
   (a) MODEL_PATH -> a distinct warm-start output path
   (b) inserts `qmix.load("results/raw/qmix_corridor_model_v2.pth")` immediately
       after the agent is constructed, so training begins from Scenario A weights
       with a fresh exploration schedule (epsilon_start=1.0 from the constructor).
Then it evaluates the warm-start model on 5 seeds by reusing the proven evaluator
(same as the 600-ep multiseed eval).

SANITY: warm-start eval should be a plausible corridor delay. Compare to the two
references above. A crash or >2000 s/veh = problem; STOP.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_init_ablation_warmstart.py
"""
import os, sys, re, importlib.util
import numpy as np

REPO_ROOT = os.getcwd()
QMIX_DIR = os.path.join(REPO_ROOT, "src", "qmix")
ENV_DIR = os.path.join(REPO_ROOT, "src", "env", "two_intersections")
for _p in (QMIX_DIR, ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ORIG_TRAIN = os.path.join(QMIX_DIR, "train_qmix_corridor_v2_turning.py")
TMP_TRAIN = os.path.join(QMIX_DIR, "_tmp_train_warmstart.py")

SCENARIO_A_MODEL = "results/raw/qmix_corridor_model_v2.pth"
WARMSTART_MODEL = "results/raw/qmix_corridor_model_v2_turning_warmstart.pth"
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2_turning.sumocfg"
SEEDS = [0, 1, 2, 3, 4]
OFFSET_WT_10SEED = 172.097
TRANSFER_WT = 178.455
DIRECT_300_WT = 258.964
OUT_SUMMARY = "results/tables/init_ablation_warmstart_summary.csv"


def patch_training():
    with open(ORIG_TRAIN) as f:
        src = f.read()
    # (a) redirect the saved model path
    src2 = re.sub(r'MODEL_PATH\s*=\s*"[^"]*"', f'MODEL_PATH = "{WARMSTART_MODEL}"', src)
    if f'MODEL_PATH = "{WARMSTART_MODEL}"' not in src2:
        raise RuntimeError("MODEL_PATH patch failed")
    # (b) inject qmix.load(...) right after the QMIXAgent(...) block.
    # The constructor call ends with a line containing 'target_update_freq=200,' then ')'.
    # We anchor on the first 'rows = []' that follows the agent construction.
    anchor = "    rows = []"
    if anchor not in src2:
        raise RuntimeError("Could not find injection anchor 'rows = []'")
    injection = (
        '    # [WARM-START ABLATION] initialize from Scenario A weights, fresh exploration.\n'
        f'    qmix.load("{SCENARIO_A_MODEL}")\n'
        '    qmix.epsilon = 1.0\n'
        '    print("[WARM-START] loaded Scenario A weights; epsilon reset to 1.0")\n\n'
        "    rows = []"
    )
    src3 = src2.replace(anchor, injection, 1)
    if "[WARM-START ABLATION]" not in src3:
        raise RuntimeError("warm-start injection failed")
    with open(TMP_TRAIN, "w") as f:
        f.write(src3)
    print(f"[OK] wrote patched warm-start training script -> {TMP_TRAIN}")


def run_module(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "main"):
        mod.main()


def evaluate_5seed():
    import evaluate_qmix_corridor_v2_turning_trained_per_second as ev
    from two_intersection_env import TwoIntersectionEnv
    from qmix_agent import QMIXAgent

    def one_seed(seed):
        env = TwoIntersectionEnv(
            sumo_binary="sumo", sumo_config=SUMO_CONFIG,
            simulation_steps=ev.SIMULATION_STEPS,
            green_duration=ev.GREEN_DURATION, yellow_duration=ev.YELLOW_DURATION,
            sumo_seed=seed)
        qmix = QMIXAgent(n_agents=2, obs_dim=3, state_dim=6, action_dim=2, batch_size=64)
        qmix.load(WARMSTART_MODEL)
        qmix.epsilon = 0.0
        raw = env.reset()
        g = ev.normalize_global_state(raw)
        obs = ev.split_observations(g)
        rows = []
        dec = 0
        while env.step_count < ev.SIMULATION_STEPS:
            actions = qmix.select_actions(obs)
            phases = {"J1": ev.action_to_phase(env, actions[0]),
                      "J2": ev.action_to_phase(env, actions[1])}
            dec += 1
            ev.run_yellow_with_logging(env=env, selected_phases=phases, rows=rows,
                                       decision=dec, actions=actions)
            ev.run_green_with_logging(env=env, selected_phases=phases, rows=rows,
                                      decision=dec, actions=actions)
            g = ev.normalize_global_state(env.get_state())
            obs = ev.split_observations(g)
        env.close()
        w = [r["total_waiting_time"] for r in rows if "total_waiting_time" in r]
        return float(np.mean(w)) if w else float("nan")

    waits = []
    for s in SEEDS:
        wt = one_seed(s)
        waits.append(wt)
        print(f"  warm-start seed {s}: {wt:.3f} s/veh")
    return waits


def bootstrap_ci(vals, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    a = np.array(vals, float)
    b = [np.mean(rng.choice(a, size=len(a), replace=True)) for _ in range(n)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def main():
    for p, desc in [(ORIG_TRAIN, "B training script"),
                    (SCENARIO_A_MODEL, "Scenario A model")]:
        if not os.path.exists(p):
            print(f"[ERROR] missing {desc}: {p}")
            return
    try:
        print("=== [1/2] Warm-start training: Scenario A init -> train on B ===")
        patch_training()
        run_module(TMP_TRAIN, "_warmstart")
        print("\n=== [2/2] Evaluating warm-start model on 5 seeds ===")
        waits = evaluate_5seed()
        mean_wt = float(np.mean(waits))
        std_wt = float(np.std(waits, ddof=1)) if len(waits) > 1 else 0.0
        lo, hi = bootstrap_ci(waits)
        gap = (mean_wt - OFFSET_WT_10SEED) / OFFSET_WT_10SEED * 100

        import pandas as pd
        pd.DataFrame([{
            "model": "Scenario B, warm-start from Scenario A (no curriculum)",
            "seeds": len(SEEDS),
            "mean_waiting": round(mean_wt, 3), "std_waiting": round(std_wt, 3),
            "ci_low": round(lo, 3), "ci_high": round(hi, 3),
            "gap_vs_offset_pct": round(gap, 3),
        }]).to_csv(OUT_SUMMARY, index=False)

        print("\n========== INITIALIZATION ABLATION (WARM-START) RESULT ==========")
        print(f"  Warm-start (A-init, train B): {mean_wt:.3f} +/- {std_wt:.3f} s/veh  "
              f"(gap {gap:+.3f}%)  CI [{lo:.3f}, {hi:.3f}]")
        print("\n  Comparison:")
        print(f"    Transfer (A policy on B):   {TRANSFER_WT:.3f}  (gap 3.694%)")
        print(f"    Direct random-init 300-ep:  {DIRECT_300_WT:.3f}  (gap 50.476%)")
        print("\n  INTERPRETATION:")
        if mean_wt < 200:
            print("    -> warm-start approaches transfer: benefit is mainly INITIALIZATION.")
        elif mean_wt > 240:
            print("    -> warm-start stays near direct: initialization alone is NOT enough;")
            print("       the CURRICULUM (training through Scenario A) is the active ingredient.")
        else:
            print("    -> intermediate: partial initialization benefit + remaining curriculum effect.")
        print(f"\n  Saved to: {OUT_SUMMARY}")
        print("  Send me this and I will integrate the mechanism finding.")
    finally:
        if os.path.exists(TMP_TRAIN):
            os.remove(TMP_TRAIN)
            print(f"[OK] removed {TMP_TRAIN}")


if __name__ == "__main__":
    main()
