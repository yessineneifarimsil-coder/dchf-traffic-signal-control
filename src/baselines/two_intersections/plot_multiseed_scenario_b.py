import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


INPUT_CSV = "results/tables/multiseed_scenario_b_summary.csv"
OUTPUT_FIG = "results/figures/multiseed_scenario_b_waiting_time.png"


def main():
    df = pd.read_csv(INPUT_CSV)

    desired_order = [
        "Best Offset Fixed-Time 45s",
        "QMIX V2 transferred",
        "QMIX V2 trained on Scenario B",
    ]

    df["order"] = df["controller"].apply(lambda x: desired_order.index(x))
    df = df.sort_values("order")

    controllers = df["controller"]
    means = df["mean_total_waiting_time_mean"]
    stds = df["mean_total_waiting_time_std"]

    x = np.arange(len(controllers))

    plt.figure(figsize=(11, 6))

    bars = plt.bar(
        x,
        means,
        yerr=stds,
        capsize=6,
    )

    plt.title("Scenario B Multi-Seed Robustness: Mean Total Waiting Time")
    plt.xlabel("Controller")
    plt.ylabel("Mean Total Waiting Time")
    plt.xticks(x, controllers, rotation=15, ha="right")
    plt.grid(axis="y", linestyle="--", alpha=0.5)

    for bar, mean_value, std_value in zip(bars, means, stds):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + std_value + 3,
            f"{mean_value:.3f} ± {std_value:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.tight_layout()

    os.makedirs(os.path.dirname(OUTPUT_FIG), exist_ok=True)
    plt.savefig(OUTPUT_FIG, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Figure saved to: {OUTPUT_FIG}")


if __name__ == "__main__":
    main()