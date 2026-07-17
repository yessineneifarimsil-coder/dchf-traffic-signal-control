"""
C4 FIX: Generate QMIX training convergence curves for the manuscript.

Reads the per-episode training logs written by the QMIX training scripts
(results/raw/qmix_corridor_training*.csv) and produces a two-panel convergence
figure: (left) episode reward vs. episode, (right) final total waiting time vs.
episode, for QMIX V1, V2, and V3. A light rolling mean is overlaid to show the
trend. No retraining is performed -- this only reads existing logs.

If a CSV is missing, the script reports which one and skips it, so you can run it
with whatever logs are present. If NONE are present, re-run the training scripts
(train_qmix_corridor.py / _v2.py / _v3.py) once to regenerate the logs, then
re-run this.

Output: figures/qmix_training_convergence.pdf

Run from repo root:
    conda activate traffic_rl
    python src/qmix/plot_qmix_training_convergence.py
"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# (label, csv path, colour)
SERIES = [
    ("QMIX V1", "results/raw/qmix_corridor_training.csv",    "#9467bd"),
    ("QMIX V2", "results/raw/qmix_corridor_training_v2.csv", "#1f77b4"),
    ("QMIX V3", "results/raw/qmix_corridor_training_v3.csv", "#2ca02c"),
]

OUT = "figures/qmix_training_convergence.pdf"
ROLL = 10  # rolling-mean window for the trend overlay


def rolling(series, w):
    return pd.Series(series).rolling(window=w, min_periods=1).mean().values


def main():
    os.makedirs("figures", exist_ok=True)
    loaded = []
    for label, path, colour in SERIES:
        if not os.path.exists(path):
            print(f"[WARN] missing training log, skipping: {path}")
            continue
        df = pd.read_csv(path)
        if "episode" not in df.columns:
            print(f"[WARN] no 'episode' column in {path}, skipping")
            continue
        loaded.append((label, df, colour))
        print(f"[OK] loaded {label}: {len(df)} episodes from {path}")

    if not loaded:
        print("\nNo training logs found. Re-run the training scripts once to "
              "regenerate results/raw/qmix_corridor_training*.csv, then re-run this.")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    # Panel 1: episode reward
    for label, df, colour in loaded:
        ep = df["episode"].values
        r = df["episode_reward"].values
        ax1.plot(ep, r, color=colour, alpha=0.25, linewidth=0.8)
        ax1.plot(ep, rolling(r, ROLL), color=colour, linewidth=1.8, label=label)
    ax1.set_xlabel("Training episode")
    ax1.set_ylabel("Logged waiting-only episode reward")
    ax1.set_title("(a) Common waiting-reward trace")
    ax1.legend(frameon=False, fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Panel 2: final total waiting time
    for label, df, colour in loaded:
        ep = df["episode"].values
        wt = df["final_total_waiting_time"].values
        ax2.plot(ep, wt, color=colour, alpha=0.25, linewidth=0.8)
        ax2.plot(ep, rolling(wt, ROLL), color=colour, linewidth=1.8, label=label)
    ax2.set_xlabel("Training episode")
    ax2.set_ylabel("Final total waiting time (s)")
    ax2.set_title("(b) Waiting-time convergence")
    ax2.legend(frameon=False, fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT, bbox_inches="tight")
    print(f"\nSaved convergence figure to: {OUT}")
    print("Upload this PDF to your Overleaf figures/ folder.")


if __name__ == "__main__":
    main()
