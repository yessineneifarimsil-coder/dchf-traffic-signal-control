import os
import pandas as pd
import matplotlib.pyplot as plt


INPUT_CSV = "results/tables/distance_best_offset_vs_qmix.csv"

OUT_WAITING = "results/figures/distance_best_offset_vs_qmix_waiting_time.png"
OUT_GAP = "results/figures/distance_qmix_gap_vs_best_offset.png"
OUT_QUEUE = "results/figures/distance_best_offset_vs_qmix_queue.png"


def save_waiting_comparison(df):
    plt.figure(figsize=(10, 6))

    plt.plot(
        df["distance"],
        df["best_offset_waiting_time"],
        marker="o",
        label="Best offset fixed-time",
    )

    plt.plot(
        df["distance"],
        df["qmix_waiting_time"],
        marker="o",
        label="QMIX V2 transferred",
    )

    plt.xlabel("Inter-Intersection Distance (m)")
    plt.ylabel("Mean Total Waiting Time")
    plt.title("Best Offset vs QMIX V2 Across Inter-Intersection Distances")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_WAITING), exist_ok=True)
    plt.savefig(OUT_WAITING, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_WAITING}")


def save_gap_plot(df):
    plt.figure(figsize=(10, 6))

    plt.plot(
        df["distance"],
        df["qmix_gap_vs_best_offset_percent"],
        marker="o",
    )

    plt.xlabel("Inter-Intersection Distance (m)")
    plt.ylabel("QMIX Gap vs Best Offset (%)")
    plt.title("Spatial Generalization Gap of QMIX V2")
    plt.grid(True, linestyle="--", alpha=0.5)

    for x, y in zip(df["distance"], df["qmix_gap_vs_best_offset_percent"]):
        plt.text(
            x,
            y,
            f"{y:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_GAP), exist_ok=True)
    plt.savefig(OUT_GAP, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_GAP}")


def save_queue_comparison(df):
    plt.figure(figsize=(10, 6))

    plt.plot(
        df["distance"],
        df["best_offset_queue"],
        marker="o",
        label="Best offset fixed-time",
    )

    plt.plot(
        df["distance"],
        df["qmix_queue"],
        marker="o",
        label="QMIX V2 transferred",
    )

    plt.xlabel("Inter-Intersection Distance (m)")
    plt.ylabel("Mean Total Queue")
    plt.title("Best Offset vs QMIX V2 Queue Performance Across Distances")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_QUEUE), exist_ok=True)
    plt.savefig(OUT_QUEUE, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_QUEUE}")


def main():
    df = pd.read_csv(INPUT_CSV)
    df = df.sort_values("distance")

    save_waiting_comparison(df)
    save_gap_plot(df)
    save_queue_comparison(df)


if __name__ == "__main__":
    main()