"""
THRESHOLD-CURVE FIGURE.

Plots the offset-sweep performance curve (mean total waiting time vs. offset) for
the reference condition d=300 m, medium demand, read from the existing offset-sweep
summary. Shades the band of offsets whose waiting time is within 5% of the optimum,
visually grounding the 5% effectiveness threshold in the flat-minimum bandwidth of
the benchmark's own offset response.

No new simulation -- reads results/tables/distance_offset_sweep_summary.csv.

Output: results/figures/offset_sweep_threshold_curve.pdf

Run from repo root:
    conda activate traffic_rl
    python src/baselines/two_intersections/plot_offset_sweep_threshold_curve.py
"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = "results/tables/distance_offset_sweep_summary.csv"
REF_DISTANCE = 300
OUT = "results/figures/offset_sweep_threshold_curve.pdf"


def main():
    os.makedirs("results/figures", exist_ok=True)
    if not os.path.exists(CSV):
        print(f"[ERROR] missing {CSV}")
        return
    df = pd.read_csv(CSV)
    d = df[df["distance"] == REF_DISTANCE].sort_values("offset")
    if d.empty:
        print(f"[ERROR] no rows for distance={REF_DISTANCE} in {CSV}")
        return

    offsets = d["offset"].values
    wt = d["mean_total_waiting_time"].values
    best = wt.min()
    best_off = offsets[np.argmin(wt)]
    gap = (wt - best) / best * 100.0

    # offsets within 5% of optimum
    within5 = offsets[gap <= 5.0]
    lo5, hi5 = within5.min(), within5.max()

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    ax.plot(offsets, wt, "-o", color="#1f77b4", markersize=4, linewidth=1.5,
            label="Mean total waiting time")
    # 5% band as horizontal reference + shaded vertical region
    ax.axhline(best * 1.05, color="#d62728", linestyle="--", linewidth=1.0,
               label="+5% above optimum")
    ax.axvspan(lo5, hi5, color="#2ca02c", alpha=0.15,
               label=f"within 5% of optimum ({lo5:.0f}--{hi5:.0f} s)")
    ax.plot([best_off], [best], "*", color="#d62728", markersize=14,
            label=f"optimum ({best_off:.0f} s, {best:.1f} s)")

    ax.set_xlabel("Offset $\\Delta$ (s)")
    ax.set_ylabel("Mean total waiting time (s)")
    ax.set_title("Offset-sweep response at $d=300$ m, medium demand")
    ax.legend(frameon=False, fontsize=8, loc="upper center")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT, bbox_inches="tight")

    print(f"Saved threshold curve to: {OUT}")
    print(
    f"\nOptimum: offset {best_off:.0f} s, "
    f"network waiting measure {best:.3f} s"
)
    print(f"5% flat-minimum band: offsets {lo5:.0f}--{hi5:.0f} s "
          f"(width {hi5 - lo5:.0f} s, about +/-{(hi5 - lo5) / 2:.0f} s around optimum)")
    print("Upload the PDF to your Overleaf figures/ folder.")


if __name__ == "__main__":
    main()
