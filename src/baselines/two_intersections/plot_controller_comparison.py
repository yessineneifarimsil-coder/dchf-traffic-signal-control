import os
import pandas as pd
import matplotlib.pyplot as plt


INPUT_CSV = "results/tables/corridor_controller_comparison_with_qmix_v2.csv"
OUTPUT_FIG = "results/figures/controller_comparison_mean_waiting_time.png"


def main():
    df = pd.read_csv(INPUT_CSV)

    # Keep the controllers in the scientific order we want in the figure
    desired_order = [
        "Simultaneous Fixed-Time",
        "Best Offset Fixed-Time 45s",
        "Queue-Based Corridor",
        "Independent DQN",
        "QMIX V1",
        "QMIX V2",
    ]

    df["order"] = df["controller"].apply(lambda x: desired_order.index(x))
    df = df.sort_values("order")

    controllers = df["controller"]
    waiting_times = df["mean_total_waiting_time"]

    plt.figure(figsize=(12, 6))
    bars = plt.bar(controllers, waiting_times)

    plt.title("Comparison of Corridor Controllers by Mean Total Waiting Time")
    plt.xlabel("Controller")
    plt.ylabel("Mean Total Waiting Time")
    plt.xticks(rotation=20, ha="right")
    plt.grid(axis="y", linestyle="--", alpha=0.5)

    # Add value labels on top of bars
    for bar, value in zip(bars, waiting_times):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=9
        )

    plt.tight_layout()

    os.makedirs(os.path.dirname(OUTPUT_FIG), exist_ok=True)
    plt.savefig(OUTPUT_FIG, dpi=300, bbox_inches="tight")
    plt.show()

    print(f"Figure saved to: {OUTPUT_FIG}")


if __name__ == "__main__":
    main()