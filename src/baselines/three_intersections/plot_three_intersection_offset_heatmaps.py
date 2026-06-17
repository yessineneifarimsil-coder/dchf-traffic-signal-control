import os
import pandas as pd
import matplotlib.pyplot as plt


INPUT_CSV = "results/tables/three_intersection_offset_sweep_summary.csv"

OUT_WAITING = "results/figures/three_intersection_offset_heatmap_waiting_time.png"
OUT_SPEED = "results/figures/three_intersection_offset_heatmap_speed.png"
OUT_QUEUE = "results/figures/three_intersection_offset_heatmap_queue.png"


def save_heatmap(df, value_col, title, colorbar_label, output_path, best_mode):
    pivot = df.pivot(
        index="offset_j2",
        columns="offset_j3",
        values=value_col,
    )

    plt.figure(figsize=(10, 8))

    im = plt.imshow(
        pivot.values,
        origin="lower",
        aspect="auto",
        extent=[
            pivot.columns.min(),
            pivot.columns.max(),
            pivot.index.min(),
            pivot.index.max(),
        ],
    )

    plt.colorbar(im, label=colorbar_label)

    plt.xlabel("Offset of J3 relative to J1 (s)")
    plt.ylabel("Offset of J2 relative to J1 (s)")
    plt.title(title)

    if best_mode == "min":
        best_row = df.loc[df[value_col].idxmin()]
    elif best_mode == "max":
        best_row = df.loc[df[value_col].idxmax()]
    else:
        raise ValueError("best_mode must be 'min' or 'max'.")

    best_j2 = best_row["offset_j2"]
    best_j3 = best_row["offset_j3"]
    best_value = best_row[value_col]

    plt.scatter(
        best_j3,
        best_j2,
        marker="x",
        s=120,
        linewidths=3,
        label=f"Best: J2={best_j2:.0f}s, J3={best_j3:.0f}s",
    )

    plt.legend()

    plt.text(
        best_j3,
        best_j2,
        f"  {best_value:.2f}",
        va="center",
        fontsize=9,
    )

    plt.tight_layout()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {output_path}")


def main():
    df = pd.read_csv(INPUT_CSV)

    save_heatmap(
        df=df,
        value_col="mean_total_waiting_time",
        title="Three-Intersection Offset Surface: Mean Total Waiting Time",
        colorbar_label="Mean Total Waiting Time",
        output_path=OUT_WAITING,
        best_mode="min",
    )

    save_heatmap(
        df=df,
        value_col="mean_speed",
        title="Three-Intersection Offset Surface: Mean Speed",
        colorbar_label="Mean Speed",
        output_path=OUT_SPEED,
        best_mode="max",
    )

    save_heatmap(
        df=df,
        value_col="mean_total_queue",
        title="Three-Intersection Offset Surface: Mean Total Queue",
        colorbar_label="Mean Total Queue",
        output_path=OUT_QUEUE,
        best_mode="min",
    )


if __name__ == "__main__":
    main()