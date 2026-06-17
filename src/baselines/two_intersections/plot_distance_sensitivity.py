import os
import pandas as pd
import matplotlib.pyplot as plt


INPUT_CSV = "results/tables/distance_offset_best_summary.csv"

OUT_WAITING = "results/figures/distance_vs_best_waiting_time.png"
OUT_OFFSET = "results/figures/distance_vs_best_offset.png"
OUT_QUEUE = "results/figures/distance_vs_best_queue.png"


def save_line_plot(x, y, xlabel, ylabel, title, output_path):
    plt.figure(figsize=(9, 6))
    plt.plot(x, y, marker="o")
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, linestyle="--", alpha=0.5)

    for xi, yi in zip(x, y):
        plt.text(
            xi,
            yi,
            f"{yi:.1f}",
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
    df = pd.read_csv(INPUT_CSV)
    df = df.sort_values("distance")

    distances = df["distance"]

    save_line_plot(
        x=distances,
        y=df["best_waiting_time"],
        xlabel="Inter-Intersection Distance (m)",
        ylabel="Best Mean Total Waiting Time",
        title="Effect of Inter-Intersection Distance on Best Waiting Time",
        output_path=OUT_WAITING,
    )

    save_line_plot(
        x=distances,
        y=df["best_waiting_offset"],
        xlabel="Inter-Intersection Distance (m)",
        ylabel="Best Waiting-Time Offset (s)",
        title="Best Offset as a Function of Inter-Intersection Distance",
        output_path=OUT_OFFSET,
    )

    save_line_plot(
        x=distances,
        y=df["best_queue"],
        xlabel="Inter-Intersection Distance (m)",
        ylabel="Best Mean Total Queue",
        title="Effect of Inter-Intersection Distance on Best Queue Length",
        output_path=OUT_QUEUE,
    )


if __name__ == "__main__":
    main()