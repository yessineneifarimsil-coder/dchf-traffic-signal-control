import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


TABLE_DIR = "results/tables"
FIG_DIR = "results/figures"

INPUT_FILE = f"{TABLE_DIR}/distance_demand_grid_dchf_summary_updated.csv"

OUT_CLASSES = f"{TABLE_DIR}/final_distance_demand_integrated_dchf_classes.csv"
OUT_COUNTS = f"{TABLE_DIR}/final_distance_demand_integrated_dchf_counts.csv"

os.makedirs(TABLE_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

DEMAND_ORDER = ["low", "medium", "high", "saturation", "oversaturation"]
DISTANCE_ORDER = [100, 200, 300, 500, 750, 1000]


def classify_integrated(row):
    gap = row["qmix_gap_vs_optimized_offset_percent"]
    cg = row["qmix_coordination_gain_percent"]
    br = row["qmix_buffered_ratio"]

    if pd.isna(gap):
        return np.nan, "Not available"

    if gap <= 5 and cg > 0 and br < 0.25:
        return 1, "Useful effective coordination"

    if gap <= 5 and br >= 0.25:
        return 2, "Algorithmically effective but capacity-limited"

    if gap <= 5 and cg <= 0 and br < 0.25:
        return 3, "Algorithmically close but no practical gain"

    if gap <= 10:
        return 4, "Marginal coordination"

    return 5, "Outside coordination horizon"


def main():
    df = pd.read_csv(INPUT_FILE)

    codes = []
    labels = []

    for _, row in df.iterrows():
        code, label = classify_integrated(row)
        codes.append(code)
        labels.append(label)

    df["final_integrated_dchf_code"] = codes
    df["final_integrated_dchf_label"] = labels

    df.to_csv(OUT_CLASSES, index=False)

    counts = (
        df.groupby(["final_integrated_dchf_code", "final_integrated_dchf_label"])
        .size()
        .reset_index(name="number_of_cases")
        .sort_values("final_integrated_dchf_code")
    )

    counts.to_csv(OUT_COUNTS, index=False)

    pivot = df.pivot(
        index="distance",
        columns="demand_name",
        values="final_integrated_dchf_code",
    )

    pivot = pivot.reindex(index=DISTANCE_ORDER, columns=DEMAND_ORDER)
    matrix = pivot.values

    plt.figure(figsize=(9.2, 5.6))
    im = plt.imshow(matrix, aspect="auto", vmin=1, vmax=5)

    plt.xticks(range(len(DEMAND_ORDER)), DEMAND_ORDER, rotation=25, ha="right")
    plt.yticks(range(len(DISTANCE_ORDER)), [f"{d} m" for d in DISTANCE_ORDER])

    plt.xlabel("Demand regime")
    plt.ylabel("Inter-intersection distance")
    plt.title("Final integrated DCHF diagnosis: distance × demand")

    cbar = plt.colorbar(im)
    cbar.set_label(
        "1=Useful, 2=Capacity-limited, 3=Close/no gain, 4=Marginal, 5=Outside"
    )

    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix[i, j]
            if not np.isnan(value):
                plt.text(j, i, f"{int(value)}", ha="center", va="center", fontsize=9)

    plt.tight_layout()

    pdf_path = f"{FIG_DIR}/final_heatmap_distance_demand_integrated_dchf.pdf"
    png_path = f"{FIG_DIR}/final_heatmap_distance_demand_integrated_dchf.png"

    plt.savefig(pdf_path, bbox_inches="tight")
    plt.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close()

    print("\nFinal integrated DCHF diagnosis generated.")
    print(f"Saved classes: {OUT_CLASSES}")
    print(f"Saved counts: {OUT_COUNTS}")
    print(f"Saved figure: {pdf_path}")
    print(f"Saved figure: {png_path}")

    print("\nClass counts:")
    print(counts.to_string(index=False))


if __name__ == "__main__":
    main()