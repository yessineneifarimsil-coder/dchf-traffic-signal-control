import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


TABLE_DIR = "results/tables"
FIG_DIR = "results/figures"

INPUT_FILE = f"{TABLE_DIR}/distance_demand_grid_dchf_summary.csv"

os.makedirs(FIG_DIR, exist_ok=True)

DEMAND_ORDER = ["low", "medium", "high", "saturation", "oversaturation"]
DISTANCE_ORDER = [100, 200, 300, 500, 750, 1000]


def save_heatmap(matrix, title, cbar_label, filename, annotate=True):
    plt.figure(figsize=(8.5, 5.2))

    im = plt.imshow(matrix, aspect="auto")

    plt.xticks(range(len(DEMAND_ORDER)), DEMAND_ORDER, rotation=25, ha="right")
    plt.yticks(range(len(DISTANCE_ORDER)), [f"{d} m" for d in DISTANCE_ORDER])

    plt.xlabel("Demand regime")
    plt.ylabel("Inter-intersection distance")
    plt.title(title)

    cbar = plt.colorbar(im)
    cbar.set_label(cbar_label)

    if annotate:
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                value = matrix[i, j]
                if not np.isnan(value):
                    plt.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=8)

    plt.tight_layout()

    pdf_path = f"{FIG_DIR}/{filename}.pdf"
    png_path = f"{FIG_DIR}/{filename}.png"

    plt.savefig(pdf_path, bbox_inches="tight")
    plt.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved: {pdf_path}")
    print(f"Saved: {png_path}")


def build_matrix(df, value_col):
    pivot = df.pivot(index="distance", columns="demand_name", values=value_col)
    pivot = pivot.reindex(index=DISTANCE_ORDER, columns=DEMAND_ORDER)
    return pivot.values


def build_regime_matrix(df):
    regime_map = {
        "Effective coordination zone": 1,
        "Marginal coordination zone": 2,
        "Outside coordination horizon": 3,
        "Not available": np.nan,
    }

    df = df.copy()
    df["regime_code"] = df["coordination_regime"].map(regime_map)

    pivot = df.pivot(index="distance", columns="demand_name", values="regime_code")
    pivot = pivot.reindex(index=DISTANCE_ORDER, columns=DEMAND_ORDER)

    return pivot.values


def main():
    df = pd.read_csv(INPUT_FILE)

    gap_matrix = build_matrix(df, "qmix_gap_vs_optimized_offset_percent")
    cg_matrix = build_matrix(df, "qmix_coordination_gain_percent")
    buffer_matrix = build_matrix(df, "optimized_offset_buffered_ratio")
    regime_matrix = build_regime_matrix(df)

    save_heatmap(
        gap_matrix,
        "Distance × Demand DCHF: QMIX approximation gap",
        "QMIX gap vs optimized offset (%)",
        "heatmap_distance_demand_qmix_gap",
    )

    save_heatmap(
        cg_matrix,
        "Distance × Demand DCHF: QMIX Coordination Gain",
        "Coordination Gain (%)",
        "heatmap_distance_demand_coordination_gain",
    )

    save_heatmap(
        buffer_matrix,
        "Distance × Demand DCHF: optimized-offset buffered ratio",
        "Buffered ratio",
        "heatmap_distance_demand_buffered_ratio",
    )

    save_heatmap(
        regime_matrix,
        "Distance × Demand DCHF: coordination regime",
        "1=Effective, 2=Marginal, 3=Outside",
        "heatmap_distance_demand_regime",
        annotate=False,
    )

    print("\nAll distance × demand heatmaps generated.")


if __name__ == "__main__":
    main()