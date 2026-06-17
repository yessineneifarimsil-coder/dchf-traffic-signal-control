import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


TABLE_DIR = "results/tables"
FIG_DIR = "results/figures"

INPUT_FILE = f"{TABLE_DIR}/distance_demand_grid_dchf_summary_updated.csv"

os.makedirs(FIG_DIR, exist_ok=True)

DEMAND_ORDER = ["low", "medium", "high", "saturation", "oversaturation"]
DISTANCE_ORDER = [100, 200, 300, 500, 750, 1000]


def save_heatmap(matrix, title, cbar_label, filename, annotate=True):
    plt.figure(figsize=(8.8, 5.4))

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
                    plt.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8)

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


def build_capacity_matrix(df):
    capacity_map = {
        "Unconstrained": 1,
        "Mild insertion pressure": 2,
        "Capacity-limited": 3,
        "Oversaturated": 4,
        "Not available": np.nan,
    }

    df = df.copy()
    df["capacity_code"] = df["qmix_capacity_regime"].map(capacity_map)

    pivot = df.pivot(index="distance", columns="demand_name", values="capacity_code")
    pivot = pivot.reindex(index=DISTANCE_ORDER, columns=DEMAND_ORDER)

    return pivot.values


def build_integrated_dchf_matrix(df):
    """
    1 = Useful effective coordination:
        gap <= 5%, CG > 0, qmix_buffered_ratio < 0.25
    2 = Algorithmically effective but capacity-limited:
        gap <= 5%, qmix_buffered_ratio >= 0.25
    3 = Marginal:
        5% < gap <= 10%
    4 = Outside:
        gap > 10%
    """
    codes = []

    for _, row in df.iterrows():
        gap = row["qmix_gap_vs_optimized_offset_percent"]
        cg = row["qmix_coordination_gain_percent"]
        br = row["qmix_buffered_ratio"]

        if pd.isna(gap):
            code = np.nan
        elif gap <= 5 and cg > 0 and br < 0.25:
            code = 1
        elif gap <= 5 and br >= 0.25:
            code = 2
        elif gap <= 10:
            code = 3
        else:
            code = 4

        codes.append(code)

    df = df.copy()
    df["integrated_dchf_code"] = codes

    pivot = df.pivot(index="distance", columns="demand_name", values="integrated_dchf_code")
    pivot = pivot.reindex(index=DISTANCE_ORDER, columns=DEMAND_ORDER)

    return pivot.values


def main():
    df = pd.read_csv(INPUT_FILE)

    save_heatmap(
        build_matrix(df, "qmix_gap_vs_optimized_offset_percent"),
        "Distance × Demand DCHF: QMIX approximation gap",
        "QMIX gap vs optimized offset (%)",
        "updated_heatmap_distance_demand_qmix_gap",
    )

    save_heatmap(
        build_matrix(df, "qmix_coordination_gain_percent"),
        "Distance × Demand DCHF: QMIX Coordination Gain",
        "Coordination Gain (%)",
        "updated_heatmap_distance_demand_coordination_gain",
    )

    save_heatmap(
        build_matrix(df, "qmix_buffered_ratio"),
        "Distance × Demand DCHF: QMIX buffered ratio",
        "QMIX buffered ratio",
        "updated_heatmap_distance_demand_qmix_buffered_ratio",
    )

    save_heatmap(
        build_regime_matrix(df),
        "Distance × Demand DCHF: coordination regime",
        "1=Effective, 2=Marginal, 3=Outside",
        "updated_heatmap_distance_demand_regime",
        annotate=False,
    )

    save_heatmap(
        build_capacity_matrix(df),
        "Distance × Demand DCHF: QMIX capacity regime",
        "1=Unconstrained, 2=Mild, 3=Capacity-limited, 4=Oversaturated",
        "updated_heatmap_distance_demand_qmix_capacity_regime",
        annotate=False,
    )

    save_heatmap(
        build_integrated_dchf_matrix(df),
        "Distance × Demand DCHF: integrated coordination-capacity diagnosis",
        "1=Useful, 2=Effective/capacity-limited, 3=Marginal, 4=Outside",
        "updated_heatmap_distance_demand_integrated_dchf",
        annotate=False,
    )

    print("\nUpdated distance × demand heatmaps generated.")


if __name__ == "__main__":
    main()