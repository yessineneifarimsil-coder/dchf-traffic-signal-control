import os
import pandas as pd
import matplotlib.pyplot as plt


INPUT_CSV = "results/tables/scenario_b_controller_comparison.csv"
OUTPUT_FIG = "results/figures/scenario_b_controller_comparison_waiting_time.png"


def main():
    df = pd.read_csv(INPUT_CSV)

    desired_order = [
        "Simultaneous Fixed-Time",
        "Best Offset Fixed-Time 45s",
        "QMIX V2 transferred",
        "QMIX V2 trained on Scenario B",
    ]

    df["order"] = df["controller"].apply(lambda x: desired_order.index(x))
    df = df.sort_values("order")

    controllers = df["controller"]
    waiting_times = df["mean_total_waiting_time"]

    plt.figure(figsize=(10, 6))

    bars = plt.bar(controllers, waiting_times)

    plt.title("Scenario B Controller Comparison: Mean Total Waiting Time")
    plt.xlabel("Controller")
    plt.ylabel("Mean Total Waiting Time")
    plt.xticks(rotation=15, ha="right")
    plt.grid(axis="y", linestyle="--", alpha=0.5)

    for bar, value in zip(bars, waiting_times):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 3,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    plt.tight_layout()

    os.makedirs(os.path.dirname(OUTPUT_FIG), exist_ok=True)
    plt.savefig(OUTPUT_FIG, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Figure saved to: {OUTPUT_FIG}")


if __name__ == "__main__":
    main()