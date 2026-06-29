"""
REVIEW ITEM 2.4: Scenario B 600-episode training-budget ablation.

The headline transfer result: a QMIX V2 policy TRANSFERRED from Scenario A and
evaluated on Scenario B beats a QMIX V2 policy trained DIRECTLY on Scenario B by
~31%. A reviewer notes the direct model (300 episodes) might simply be undertrained.
This ablation trains the direct model for 600 episodes and re-evaluates it, to test
whether the transfer advantage is a training-BUDGET effect or a genuine
curriculum/initialization effect.

DESIGN (zero guesswork -- reuses the repo's OWN proven scripts):
  1. Copy train_qmix_corridor_v2_turning.py, patch ONLY:
        NUM_EPISODES 300 -> 600
        MODEL_PATH   -> ..._turning_600ep.pth
     Run it -> trains + saves the 600-episode direct model.
  2. Copy evaluate_qmix_corridor_v2_turning_trained_per_second.py, patch ONLY:
        MODEL_PATH  -> ..._turning_600ep.pth
        OUTPUT_CSV  -> ..._600ep.csv
     Run it -> writes a per-second eval log with a total_waiting_time column.
  3. Read the eval CSV, compute mean total_waiting_time, compute gap vs the
     published optimized-offset benchmark (172.097 s/veh, 10-seed).

Reference values (already in the paper):
  Optimized offset (Scenario B):        172.097 s/veh
  QMIX transferred from A:              178.455 s/veh  (gap 3.694%, Effective)
  QMIX direct, 300 episodes:           258.964 s/veh  (gap 50.476%, Outside)

INTERPRETATION:
  - 600-ep direct ~178-185 s/veh (gap < ~7%): advantage was a TRAINING-BUDGET effect.
  - 600-ep direct still ~250+ s/veh (gap ~50%): advantage is NOT budget -> genuine
    curriculum/initialization/landscape effect (claim stands, strengthened).

SANITY: training should show decreasing waiting time; eval mean should be a plausible
corridor delay. A crash or >2000 s/veh means a problem; STOP and report.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_scenario_b_600ep_ablation.py
"""
import os, sys, re, csv, importlib.util

REPO_ROOT = os.getcwd()
QMIX_DIR = os.path.join(REPO_ROOT, "src", "qmix")
ENV_DIR = os.path.join(REPO_ROOT, "src", "env", "two_intersections")

# The patched train/eval scripts do `from qmix_agent import QMIXAgent` and
# `from two_intersection_env import TwoIntersectionEnv`. When run directly those
# resolve because Python puts the script's own folder on sys.path; when imported
# via importlib they do not, so we add both folders explicitly here.
for _p in (QMIX_DIR, ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ORIG_TRAIN = os.path.join(QMIX_DIR, "train_qmix_corridor_v2_turning.py")
ORIG_EVAL = os.path.join(QMIX_DIR,
                         "evaluate_qmix_corridor_v2_turning_trained_per_second.py")
TMP_TRAIN = os.path.join(QMIX_DIR, "_tmp_train_v2_turning_600ep.py")
TMP_EVAL = os.path.join(QMIX_DIR, "_tmp_eval_v2_turning_600ep.py")

NEW_MODEL = "results/raw/qmix_corridor_model_v2_turning_600ep.pth"
NEW_EVAL_CSV = "results/raw/qmix_corridor_v2_turning_trained_600ep_per_second.csv"
OFFSET_WT_10SEED = 172.097


def run_module(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "main"):
        mod.main()


def patch_file(orig, dst, subs):
    with open(orig, "r") as f:
        src = f.read()
    for pat, repl in subs:
        src = re.sub(pat, repl, src)
    with open(dst, "w") as f:
        f.write(src)
    print(f"[OK] wrote patched {dst}")


def main():
    for p in (ORIG_TRAIN, ORIG_EVAL):
        if not os.path.exists(p):
            print(f"[ERROR] missing {p}")
            return
    try:
        # 1) patched training (600 episodes, new model path)
        patch_file(ORIG_TRAIN, TMP_TRAIN, [
            (r'NUM_EPISODES\s*=\s*300', 'NUM_EPISODES = 600'),
            (r'MODEL_PATH\s*=\s*"[^"]*"', f'MODEL_PATH = "{NEW_MODEL}"'),
        ])
        print("\n=== [1/3] Training QMIX V2 directly on Scenario B for 600 episodes ===")
        run_module(TMP_TRAIN, "_train600")

        # 2) patched evaluation (load 600-ep model, write new csv)
        patch_file(ORIG_EVAL, TMP_EVAL, [
            (r'MODEL_PATH\s*=\s*"[^"]*"', f'MODEL_PATH = "{NEW_MODEL}"'),
            (r'OUTPUT_CSV\s*=\s*"[^"]*"', f'OUTPUT_CSV = "{NEW_EVAL_CSV}"'),
        ])
        print("\n=== [2/3] Evaluating the 600-episode direct model on Scenario B ===")
        run_module(TMP_EVAL, "_eval600")

        # 3) compute mean waiting time from the eval csv
        print("\n=== [3/3] Computing mean waiting time and gap ===")
        if not os.path.exists(NEW_EVAL_CSV):
            print(f"[ERROR] eval CSV not found: {NEW_EVAL_CSV}")
            return
        waits = []
        with open(NEW_EVAL_CSV) as f:
            for row in csv.DictReader(f):
                if "total_waiting_time" in row and row["total_waiting_time"] != "":
                    waits.append(float(row["total_waiting_time"]))
        mean_wt = sum(waits) / len(waits) if waits else float("nan")
        gap = (mean_wt - OFFSET_WT_10SEED) / OFFSET_WT_10SEED * 100.0

        print("\n========== SCENARIO B 600-EPISODE ABLATION RESULT ==========")
        print(f"  600-episode direct model mean waiting time: {mean_wt:.3f} s/veh")
        print(f"  Optimized-offset benchmark:                 {OFFSET_WT_10SEED:.3f} s/veh")
        print(f"  Gap vs offset:                              {gap:+.3f}%")
        print("\n  Reference (published):")
        print("    transferred-from-A:      178.455 s/veh  (gap 3.694%, Effective)")
        print("    direct 300-episode:      258.964 s/veh  (gap 50.476%, Outside)")
        print("\n  INTERPRETATION:")
        if mean_wt < 200:
            print("    -> approaches the transferred model: advantage was a TRAINING-BUDGET effect.")
        elif mean_wt > 240:
            print("    -> still far worse: transfer advantage is NOT just budget")
            print("       (genuine curriculum / initialization / landscape effect).")
        else:
            print("    -> intermediate; send me the number and I will interpret.")
        print("\nSend me this result and I will integrate it into the Scenario B section.")
    finally:
        for tmp in (TMP_TRAIN, TMP_EVAL):
            if os.path.exists(tmp):
                os.remove(tmp)
                print(f"[OK] removed {tmp}")


if __name__ == "__main__":
    main()
