import os
import pandas as pd
import matplotlib.pyplot as plt


INPUT_CSV = "results/tables/three_intersection_d23_best_offset_vs_qmix.csv"

OUT_WAITING = "results/figures/three_intersection_d23_best_offset_vs_qmix_waiting.png"
OUT_GAP = "results/figures/three_intersection_d23_qmix_gap.png"
OUT_QUEUE = "results/figures/three_intersection_d23_best_offset_vs_qmix_queue.png"


def main():
    os.makedirs("results/figures", exist_ok=True)

    df = pd.read_csv(INPUT_CSV)

    # ------------------------------------------------------------
    # 1. Waiting time comparison
    # ------------------------------------------------------------
    plt.figure(figsize=(10, 6))

    plt.plot(
        df["d23"],
        df["best_offset_waiting_time"],
        marker="o",
        label="Best offset pattern",
    )

    plt.plot(
        df["d23"],
        df["qmix_waiting_time"],
        marker="o",
        label="QMIX 3 agents",
    )

    plt.xlabel("Distance between J2 and J3, d23 (m)")
    plt.ylabel("Mean Total Waiting Time")
    plt.title("Three-Intersection Distance Sensitivity: Best Offset vs QMIX")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT_WAITING, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_WAITING}")

    # ------------------------------------------------------------
    # 2. QMIX gap versus best offset
    # ------------------------------------------------------------
    plt.figure(figsize=(10, 6))

    plt.plot(
        df["d23"],
        df["qmix_gap_vs_best_offset_percent"],
        marker="o",
    )

    plt.axhline(5, linestyle="--", label="Effective threshold = 5%")
    plt.axhline(10, linestyle="--", label="Marginal threshold = 10%")

    plt.xlabel("Distance between J2 and J3, d23 (m)")
    plt.ylabel("QMIX Gap vs Best Offset (%)")
    plt.title("Spatial Generalization Gap of QMIX 3-Agent Policy")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT_GAP, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_GAP}")

    # ------------------------------------------------------------
    # 3. Queue comparison
    # ------------------------------------------------------------
    plt.figure(figsize=(10, 6))

    plt.plot(
        df["d23"],
        df["best_offset_queue"],
        marker="o",
        label="Best offset pattern",
    )

    plt.plot(
        df["d23"],
        df["qmix_queue"],
        marker="o",
        label="QMIX 3 agents",
    )

    plt.xlabel("Distance between J2 and J3, d23 (m)")
    plt.ylabel("Mean Total Queue")
    plt.title("Three-Intersection Distance Sensitivity: Queue Comparison")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT_QUEUE, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_QUEUE}")


if __name__ == "__main__":
    main()