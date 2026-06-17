import os
import pandas as pd
import matplotlib.pyplot as plt


INPUT_CSV = "results/tables/corridor_controller_comparison_with_qmix_v2.csv"
OUTPUT_DIR = "results/figures"

WAITING_FIG = os.path.join(OUTPUT_DIR, "controller_comparison_waiting_time.png")
SPEED_FIG = os.path.join(OUTPUT_DIR, "controller_comparison_mean_speed.png")
QUEUE_FIG = os.path.join(OUTPUT_DIR, "controller_comparison_mean_queue.png")


ORDER = [
    "Simultaneous Fixed-Time",
    "Best Offset Fixed-Time 45s",
    "Queue-Based Corridor",
    "Independent DQN",
    "QMIX V1",
    "QMIX V2",
]


def prepare_data():
    df = pd.read_csv(INPUT_CSV)
    df["order"] = df["controller"].apply(lambda x: ORDER.index(x))
    return df.sort_values("order")


def plot_bar(df, column, ylabel, title, output_path):
    plt.figure(figsize=(12, 6))

    bars = plt.bar(df["controller"], df[column])

    plt.title(title)
    plt.xlabel("Controller")
    plt.ylabel(ylabel)
    plt.xticks(rotation=20, ha="right")
    plt.grid(axis="y", linestyle="--", alpha=0.5)

    for bar, value in zip(bars, df[column]):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(df[column]) * 0.01,
            f"{value:.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure: {output_path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df = prepare_data()

    print("\n=== Controller comparison data ===")
    print(df.to_string(index=False))

    plot_bar(
        df,
        column="mean_total_waiting_time",
        ylabel="Mean Total Waiting Time",
        title="Controller Comparison: Mean Total Waiting Time",
        output_path=WAITING_FIG,
    )

    plot_bar(
        df,
        column="mean_speed",
        ylabel="Mean Speed",
        title="Controller Comparison: Mean Speed",
        output_path=SPEED_FIG,
    )

    plot_bar(
        df,
        column="mean_total_queue",
        ylabel="Mean Total Queue",
        title="Controller Comparison: Mean Total Queue",
        output_path=QUEUE_FIG,
    )

    print("\nAll controller metric figures generated.")


if __name__ == "__main__":
    main()