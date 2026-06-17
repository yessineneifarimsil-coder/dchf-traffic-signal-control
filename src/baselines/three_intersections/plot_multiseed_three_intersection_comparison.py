import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


INPUT_CSV = "results/tables/multiseed_three_intersection_controllers_summary.csv"

OUT_WAITING = "results/figures/multiseed_three_intersection_waiting_time.png"
OUT_SPEED = "results/figures/multiseed_three_intersection_speed.png"
OUT_QUEUE = "results/figures/multiseed_three_intersection_queue.png"


CONTROLLER_ORDER = [
    "Simultaneous Fixed-Time",
    "Best Offset Pattern",
    "QMIX 3 Agents",
]


def prepare_df():
    df = pd.read_csv(INPUT_CSV)
    df["order"] = df["controller"].apply(lambda x: CONTROLLER_ORDER.index(x))
    return df.sort_values("order")


def save_bar_with_error(
    df,
    mean_col,
    std_col,
    ylabel,
    title,
    output_path,
):
    x = np.arange(len(df))

    plt.figure(figsize=(10, 6))

    bars = plt.bar(
        x,
        df[mean_col],
        yerr=df[std_col],
        capsize=6,
    )

    plt.xlabel("Controller")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.xticks(x, df["controller"], rotation=15, ha="right")
    plt.grid(axis="y", linestyle="--", alpha=0.5)

    for bar, value in zip(bars, df[mean_col]):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {output_path}")


def main():
    df = prepare_df()

    save_bar_with_error(
        df=df,
        mean_col="mean_total_waiting_time_mean",
        std_col="mean_total_waiting_time_std",
        ylabel="Mean Total Waiting Time",
        title="Multi-Seed Three-Intersection Controller Comparison: Waiting Time",
        output_path=OUT_WAITING,
    )

    save_bar_with_error(
        df=df,
        mean_col="mean_speed_mean",
        std_col="mean_speed_std",
        ylabel="Mean Speed",
        title="Multi-Seed Three-Intersection Controller Comparison: Mean Speed",
        output_path=OUT_SPEED,
    )

    save_bar_with_error(
        df=df,
        mean_col="mean_total_queue_mean",
        std_col="mean_total_queue_std",
        ylabel="Mean Total Queue",
        title="Multi-Seed Three-Intersection Controller Comparison: Queue",
        output_path=OUT_QUEUE,
    )


if __name__ == "__main__":
    main()