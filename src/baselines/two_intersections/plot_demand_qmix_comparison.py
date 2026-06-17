import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


INPUT_CSV = "results/tables/demand_best_offset_vs_qmix.csv"

OUT_WAITING = "results/figures/demand_best_offset_vs_qmix_waiting_time.png"
OUT_GAP = "results/figures/demand_qmix_gap_vs_best_offset.png"
OUT_BUFFER = "results/figures/demand_buffered_ratio_comparison.png"
OUT_QUEUE = "results/figures/demand_best_offset_vs_qmix_queue.png"


DEMAND_ORDER = ["low", "medium", "high", "saturation", "oversaturation"]


def prepare_df():
    df = pd.read_csv(INPUT_CSV)
    df["order"] = df["demand_scenario"].apply(lambda x: DEMAND_ORDER.index(x))
    return df.sort_values("order")


def save_waiting_comparison(df):
    x = np.arange(len(df))
    width = 0.35

    plt.figure(figsize=(11, 6))

    plt.bar(
        x - width / 2,
        df["best_offset_waiting_time"],
        width,
        label="Best offset fixed-time",
    )

    plt.bar(
        x + width / 2,
        df["qmix_waiting_time"],
        width,
        label="QMIX V2 transferred",
    )

    plt.xlabel("Demand Scenario")
    plt.ylabel("Mean Total Waiting Time")
    plt.title("Demand Sensitivity: Best Offset vs QMIX V2")
    plt.xticks(x, df["demand_scenario"])
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_WAITING), exist_ok=True)
    plt.savefig(OUT_WAITING, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_WAITING}")


def save_gap_plot(df):
    plt.figure(figsize=(10, 6))

    plt.plot(
        df["demand_scenario"],
        df["qmix_gap_vs_best_offset_percent"],
        marker="o",
    )

    plt.xlabel("Demand Scenario")
    plt.ylabel("QMIX Gap vs Best Offset (%)")
    plt.title("Demand Sensitivity of QMIX V2 Generalization Gap")
    plt.grid(True, linestyle="--", alpha=0.5)

    for x, y in zip(df["demand_scenario"], df["qmix_gap_vs_best_offset_percent"]):
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


def save_buffered_ratio_comparison(df):
    x = np.arange(len(df))
    width = 0.35

    plt.figure(figsize=(11, 6))

    plt.bar(
        x - width / 2,
        df["best_offset_buffered_ratio"] * 100,
        width,
        label="Best offset fixed-time",
    )

    plt.bar(
        x + width / 2,
        df["qmix_buffered_ratio"] * 100,
        width,
        label="QMIX V2 transferred",
    )

    plt.xlabel("Demand Scenario")
    plt.ylabel("Buffered Vehicles Ratio (%)")
    plt.title("Demand Sensitivity: Buffered Vehicles Ratio")
    plt.xticks(x, df["demand_scenario"])
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_BUFFER), exist_ok=True)
    plt.savefig(OUT_BUFFER, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_BUFFER}")


def save_queue_comparison(df):
    x = np.arange(len(df))
    width = 0.35

    plt.figure(figsize=(11, 6))

    plt.bar(
        x - width / 2,
        df["best_offset_queue"],
        width,
        label="Best offset fixed-time",
    )

    plt.bar(
        x + width / 2,
        df["qmix_queue"],
        width,
        label="QMIX V2 transferred",
    )

    plt.xlabel("Demand Scenario")
    plt.ylabel("Mean Total Queue")
    plt.title("Demand Sensitivity: Queue Comparison")
    plt.xticks(x, df["demand_scenario"])
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_QUEUE), exist_ok=True)
    plt.savefig(OUT_QUEUE, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_QUEUE}")


def main():
    df = prepare_df()

    save_waiting_comparison(df)
    save_gap_plot(df)
    save_buffered_ratio_comparison(df)
    save_queue_comparison(df)


if __name__ == "__main__":
    main()