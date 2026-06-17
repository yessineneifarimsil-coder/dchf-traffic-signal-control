import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path


INPUT_CSV = "results/tables/offset_sweep_turning_summary_0_90_2x2.csv"
OUTPUT_DIR = Path("results/figures")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def plot_metric(df, y_column, y_label, output_name):
    plt.figure(figsize=(8, 5))
    plt.plot(df["offset"], df[y_column], marker="o")
    plt.xlabel("Offset between J1 and J2 (seconds)")
    plt.ylabel(y_label)
    plt.title(f"Offset sensitivity: {y_label}")
    plt.grid(True)
    plt.tight_layout()

    output_path = OUTPUT_DIR / output_name
    plt.savefig(output_path, dpi=300)
    plt.close()

    print(f"Saved figure: {output_path}")


def main():
    df = pd.read_csv(INPUT_CSV)

    print("\n=== Offset sweep data ===")
    print(df.to_string(index=False))

    plot_metric(
        df,
        y_column="total_waiting_time_mean",
        y_label="Mean total waiting time",
        output_name="offset_turning_0_90_vs_waiting_time.png",
    )

    plot_metric(
        df,
        y_column="mean_speed_mean",
        y_label="Mean speed",
        output_name="offset_turning_0_90_vs_mean_speed.png",
    )

    plot_metric(
        df,
        y_column="total_queue_mean",
        y_label="Mean total queue",
        output_name="offset_turning_0_90_vs_queue.png",
    )

    print("\nAll offset sensitivity figures were generated.")


if __name__ == "__main__":
    main()