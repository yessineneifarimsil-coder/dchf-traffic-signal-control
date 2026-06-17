import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


INPUT_CSV = "results/tables/spillback_demand_summary.csv"

OUT_BUFFER = "results/figures/capacity_buffered_ratio_by_demand.png"
OUT_OCCUPANCY = "results/figures/central_occupancy_ratio_by_demand.png"
OUT_MAX_QUEUE = "results/figures/capacity_max_queue_by_demand.png"

DEMAND_ORDER = ["low", "medium", "high", "saturation", "oversaturation"]
CONTROLLER_ORDER = ["Best Offset Fixed-Time", "QMIX V2 transferred"]


def prepare_df():
    df = pd.read_csv(INPUT_CSV)
    df["demand_order"] = df["demand_scenario"].apply(lambda x: DEMAND_ORDER.index(x))
    df["controller_order"] = df["controller"].apply(lambda x: CONTROLLER_ORDER.index(x))
    return df.sort_values(["demand_order", "controller_order"])


def grouped_bar(df, value_col, ylabel, title, output_path, multiply_by_100=False):
    pivot = df.pivot(
        index="demand_scenario",
        columns="controller",
        values=value_col,
    ).loc[DEMAND_ORDER]

    values_offset = pivot["Best Offset Fixed-Time"]
    values_qmix = pivot["QMIX V2 transferred"]

    if multiply_by_100:
        values_offset = values_offset * 100
        values_qmix = values_qmix * 100

    x = np.arange(len(DEMAND_ORDER))
    width = 0.35

    plt.figure(figsize=(11, 6))

    bars1 = plt.bar(
        x - width / 2,
        values_offset,
        width,
        label="Best offset fixed-time",
    )

    bars2 = plt.bar(
        x + width / 2,
        values_qmix,
        width,
        label="QMIX V2 transferred",
    )

    plt.xlabel("Demand Scenario")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.xticks(x, DEMAND_ORDER)
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.legend()

    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width() / 2,
                height,
                f"{height:.2f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {output_path}")


def main():
    df = prepare_df()

    grouped_bar(
        df=df,
        value_col="buffered_ratio",
        ylabel="Buffered Vehicles Ratio (%)",
        title="Capacity Limit under Demand Growth: Buffered Vehicles Ratio",
        output_path=OUT_BUFFER,
        multiply_by_100=True,
    )

    grouped_bar(
        df=df,
        value_col="max_central_occupancy_ratio",
        ylabel="Maximum Central Link Occupancy Ratio",
        title="Central Link Occupancy under Demand Growth",
        output_path=OUT_OCCUPANCY,
        multiply_by_100=False,
    )

    grouped_bar(
        df=df,
        value_col="max_total_queue",
        ylabel="Maximum Total Queue",
        title="Maximum Queue under Demand Growth",
        output_path=OUT_MAX_QUEUE,
        multiply_by_100=False,
    )


if __name__ == "__main__":
    main()