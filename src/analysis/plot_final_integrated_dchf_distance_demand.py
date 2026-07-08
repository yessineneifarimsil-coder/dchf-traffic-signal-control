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

    if pd.isna(gap) or pd.isna(cg) or pd.isna(br):
        return np.nan, "Not available"

    # Capacity status takes precedence within approximation-effective cells.
    if gap <= 5 and br >= 0.10:
        return 2, "Algorithmically effective but capacity-constrained"

    if gap <= 5 and cg > 0 and br < 0.10:
        return 1, "Useful effective coordination"

    if gap <= 5 and cg <= 0 and br < 0.10:
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

    expected_counts = {1: 3, 2: 4, 3: 0, 4: 3, 5: 20}

    actual_counts = (
        df["final_integrated_dchf_code"]
        .value_counts()
        .reindex([1, 2, 3, 4, 5], fill_value=0)
        .astype(int)
        .to_dict()
    )

    assert actual_counts == expected_counts, (
        f"Unexpected integrated DCHF counts: {actual_counts}"
    )

    df.to_csv(OUT_CLASSES, index=False)

    class_labels = {
        1: "Useful effective coordination",
        2: "Algorithmically effective but capacity-constrained",
        3: "Algorithmically close but no practical gain",
        4: "Marginal coordination",
        5: "Outside coordination horizon",
    }

    counts = pd.DataFrame(
        {
            "final_integrated_dchf_code": [1, 2, 3, 4, 5],
            "final_integrated_dchf_label": [
                class_labels[1],
                class_labels[2],
                class_labels[3],
                class_labels[4],
                class_labels[5],
            ],
            "number_of_cases": [
                actual_counts[1],
                actual_counts[2],
                actual_counts[3],
                actual_counts[4],
                actual_counts[5],
            ],
        }
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
        "1=Useful, 2=Capacity-constrained, 3=Close/no gain, 4=Marginal, 5=Outside"
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