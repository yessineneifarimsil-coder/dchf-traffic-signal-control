"""
Regenerate figures/multiseed_robustness_waiting_time.png

Changes vs original plot_multiseed_robustness.py:
  - Adds Max Pressure bar (canonical 149.911 ± 2.640)
  - Uses canonical Scenario A values from the locked context package
  - Adds DCHF gap annotation (G_QMIX = 4.42%)
  - Marks best controller (Max Pressure)
  - Publication-quality formatting for TR-C journal submission

Run from repository root:
    conda activate traffic_rl
    python src/analysis/plot_multiseed_robustness.py
"""

import os
import csv
import statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# ============================================================
# DATA — canonical locked values (Context Package §3)
# ============================================================

# Read offset and QMIX from the existing summary CSV
OFFSET_QMIX_CSV = "results/tables/multiseed_offset_qmix_per_second_summary.csv"

# Read Max Pressure seed-level data from the Scenario A summary
MP_CSV = "results/tables/max_pressure_corridor_2x2_summary.csv"

# Output
OUTPUT_PNG = "results/figures/multiseed_robustness_waiting_time.png"
OUTPUT_PDF = "results/figures/multiseed_robustness_waiting_time.pdf"


def load_offset_qmix():
    """Load offset and QMIX from the existing summary CSV."""
    data = {}
    with open(OFFSET_QMIX_CSV, newline="") as f:
        for row in csv.DictReader(f):
            data[row["controller"]] = {
                "mean": float(row["mean_total_waiting_time_mean"]),
                "std":  float(row["mean_total_waiting_time_std"]),
            }
    return data


def load_max_pressure():
    """Compute mean ± std from the per-seed Max Pressure Scenario A CSV."""
    values = []
    with open(MP_CSV, newline="") as f:
        for row in csv.DictReader(f):
            # Skip the aggregate MEAN+-STD row
            try:
                values.append(float(row["mean_waiting"]))
            except ValueError:
                pass
    m = statistics.mean(values)
    s = statistics.stdev(values)
    return {"mean": m, "std": s}


def main():
    os.makedirs("results/figures", exist_ok=True)

    oq   = load_offset_qmix()
    mp   = load_max_pressure()

    # Controller order: best → worst (by mean waiting time)
    controllers = [
        "Max Pressure",
        "Optimized offset\n(45 s, 10 seeds)",
        "QMIX V2\n(10 seeds)",
    ]
    means = [
        mp["mean"],
        oq["Best Offset Fixed-Time 45s"]["mean"],
        oq["QMIX V2"]["mean"],
    ]
    stds = [
        mp["std"],
        oq["Best Offset Fixed-Time 45s"]["std"],
        oq["QMIX V2"]["std"],
    ]

    # Colour scheme: 3 distinct, accessible colours
    colors = ["#2196F3",   # blue  — Max Pressure
              "#4CAF50",   # green — Optimized offset (benchmark)
              "#FF9800"]   # orange — QMIX V2

    # --------------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 5.5))

    x = np.arange(len(controllers))
    bars = ax.bar(
        x, means,
        yerr=stds,
        capsize=7,
        color=colors,
        edgecolor="white",
        linewidth=0.8,
        error_kw=dict(elinewidth=1.4, ecolor="#333333"),
        width=0.55,
        zorder=3,
    )

    # ---- value labels above each bar -----------------------
    for bar, m, s in zip(bars, means, stds):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            m + s + 2.5,
            f"{m:.3f} ± {s:.3f}",
            ha="center", va="bottom",
            fontsize=9.5, color="#222222",
        )

    # ---- DCHF gap annotation: arrow offset → QMIX ----------
    off_x   = x[1]
    qmix_x  = x[2]
    gap_pct = (means[2] - means[1]) / means[1] * 100   # should be 4.42%

    y_arrow = max(means[1], means[2]) + max(stds[1], stds[2]) + 18
    ax.annotate(
        "",
        xy=(qmix_x, y_arrow), xytext=(off_x, y_arrow),
        arrowprops=dict(arrowstyle="<->", color="#555555", lw=1.4),
    )
    ax.text(
        (off_x + qmix_x) / 2, y_arrow + 2,
        f"$G_{{\\mathrm{{QMIX}}}}$ = {gap_pct:.2f}%\n(Effective ≤ 5%)",
        ha="center", va="bottom",
        fontsize=8.5, color="#333333",
        style="italic",
    )

    # ---- Best controller label on Max Pressure bar ----------
    ax.text(
        x[0], means[0] / 2,
        "Best\ncontroller",
        ha="center", va="center",
        fontsize=8, color="white",
        fontweight="bold",
    )

    # ---- p-value note --------------------------------------
    ax.text(
        0.98, 0.03,
        "All pairwise differences: $p = 0.001953$ (Wilcoxon, 10 seeds)",
        transform=ax.transAxes,
        ha="right", va="bottom",
        fontsize=8, color="#555555",
        style="italic",
    )

    # ---- formatting ----------------------------------------
    ax.set_xticks(x)
    ax.set_xticklabels(controllers, fontsize=10)
    ax.set_ylabel("Time-averaged network waiting measure (s)", fontsize=11)
    ax.set_xlabel("Controller", fontsize=11)
    ax.set_title(
        "Scenario A: Ten-Seed Controller Comparison\n"
        "(Two-intersection through-movement corridor, medium demand)",
        fontsize=11, pad=10,
    )
    ax.set_ylim(0, max(means) + max(stds) + 45)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=300, bbox_inches="tight")
    plt.savefig(OUTPUT_PDF, bbox_inches="tight")
    plt.close()

    print(f"Saved: {OUTPUT_PNG}")
    print(f"Saved: {OUTPUT_PDF}")
    print()
    print("Values used:")
    for c, m, s in zip(controllers, means, stds):
        print(f"  {c.replace(chr(10), ' '):40s} {m:.3f} ± {s:.3f}")
    print(f"  G_QMIX = {gap_pct:.2f}%")


if __name__ == "__main__":
    main()
