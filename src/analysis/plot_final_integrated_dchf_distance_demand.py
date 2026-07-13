"""
Figure 4 — Integrated DCHF diagnosis over the 30-cell distance-demand grid.

Classification follows manuscript Eq. (5) + Eq. (6) and the capacity-precedence
rule of Section 4.2.4 (BR >= 0.10 => capacity-constrained, within the
approximation-effective branch only).

Where five-seed paired evidence exists (spatial sweep, demand sweep, joint-grid
boundary reruns), the five-seed gap supersedes the single-seed exploratory gap.
The buffered ratio is taken from the grid run: BR is demand-driven and varies
negligibly across seeds.
"""
import os
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch, Rectangle

matplotlib.rcParams["hatch.linewidth"] = 1.1   # hatch must render, not vanish

TABLE_DIR = "results/tables"
FIG_DIR = "results/figures"

INPUT_FILE = f"{TABLE_DIR}/distance_demand_grid_dchf_summary_updated.csv"
OUT_CLASSES = f"{TABLE_DIR}/final_distance_demand_integrated_dchf_classes.csv"
OUT_COUNTS = f"{TABLE_DIR}/final_distance_demand_integrated_dchf_counts.csv"

os.makedirs(TABLE_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

DEMAND_ORDER = ["low", "medium", "high", "saturation", "oversaturation"]
DISTANCE_ORDER = [100, 200, 300, 500, 750, 1000]

# --- Five-seed paired gaps: (distance_m, demand) -> G_QMIX mean (%) ----------
# Spatial sweep (Table 11)     : fully_paired_sweeps_summary.csv, sweep == spatial
# Demand sweep (Table 12)      : fully_paired_sweeps_summary.csv, sweep == demand
# Boundary reruns (Table S-new): joint_grid_boundary_multiseed_summary.csv
MULTISEED_GAP = {
    (100,  "medium"):          8.573,
    (200,  "medium"):          3.769,
    (300,  "medium"):          2.678,
    (500,  "medium"):         25.487,
    (750,  "medium"):         69.378,
    (1000, "medium"):         59.062,
    (300,  "low"):            76.864,
    (300,  "high"):            2.740,
    (300,  "saturation"):      0.985,
    (300,  "oversaturation"):  7.123,
    (500,  "saturation"):      7.406,
    (500,  "oversaturation"):  6.031,
    (750,  "oversaturation"): 12.333,
    (1000, "saturation"):      1.768,
    (1000, "oversaturation"):  1.794,
}

# GA palette (Okabe-Ito) - must match figures/dchf_graphical_abstract.tex
CLASS_COLORS = {
    1: "#009E73",  # Useful effective
    2: "#CC79A7",  # Capacity-constrained
    3: "#56B4E9",  # Close / no practical gain (empty in this grid)
    4: "#E69F00",  # Marginal
    5: "#D55E00",  # Outside horizon
}
CLASS_NAMES = {
    1: "Useful effective",
    2: "Capacity-constrained",
    3: "Close / no gain",
    4: "Marginal",
    5: "Outside horizon",
}
CLASS_LABELS = {
    1: "Useful effective coordination",
    2: "Algorithmically effective but capacity-constrained",
    3: "Algorithmically close but no practical gain",
    4: "Marginal coordination",
    5: "Outside coordination horizon",
}


def classify_integrated(gap, cg, br):
    """Manuscript Eq. (5)+(6) with the Section 4.2.4 capacity-precedence rule."""
    if pd.isna(gap) or pd.isna(cg) or pd.isna(br):
        return np.nan
    if gap <= 5 and br >= 0.10:
        return 2
    if gap <= 5 and cg > 0 and br < 0.10:
        return 1
    if gap <= 5 and cg <= 0 and br < 0.10:
        return 3
    if gap <= 10:
        return 4
    return 5


def main():
    df = pd.read_csv(INPUT_FILE)

    codes, gaps_used, evidence = [], [], []
    for _, row in df.iterrows():
        key = (int(row["distance"]), row["demand_name"])
        single = row["qmix_gap_vs_optimized_offset_percent"]
        gap = MULTISEED_GAP.get(key, single)
        evidence.append("5-seed paired" if key in MULTISEED_GAP else "1-seed exploratory")
        gaps_used.append(gap)
        codes.append(
            classify_integrated(gap,
                                row["qmix_coordination_gain_percent"],
                                row["qmix_buffered_ratio"])
        )

    df["gap_used_percent"] = gaps_used
    df["seed_evidence"] = evidence
    df["final_integrated_dchf_code"] = codes
    df["final_integrated_dchf_label"] = [
        CLASS_LABELS.get(c, "Not available") for c in codes
    ]

    # --- guards: these numbers are load-bearing in the manuscript -------------
    assert df["final_integrated_dchf_code"].notna().all(), "Unclassified cell present"

    expected = {1: 3, 2: 3, 3: 0, 4: 4, 5: 20}
    actual = (df["final_integrated_dchf_code"].value_counts()
              .reindex([1, 2, 3, 4, 5], fill_value=0).astype(int).to_dict())
    assert actual == expected, f"Unexpected integrated DCHF counts: {actual}"

    n_multi = int((df["seed_evidence"] == "5-seed paired").sum())
    assert n_multi == 15, f"Expected 15 five-seed cells, got {n_multi}"

    # every useful-effective cell must rest on five-seed evidence
    useful = df[df["final_integrated_dchf_code"] == 1]
    assert (useful["seed_evidence"] == "5-seed paired").all(), \
        "A useful-effective cell rests on single-seed evidence"

    df.to_csv(OUT_CLASSES, index=False)
    (df.groupby(["final_integrated_dchf_code", "final_integrated_dchf_label"])
       .size().reset_index(name="number_of_cases")
       .sort_values("final_integrated_dchf_code")
       .to_csv(OUT_COUNTS, index=False))

    code_pv = df.pivot(index="distance", columns="demand_name",
                       values="final_integrated_dchf_code").reindex(
                       index=DISTANCE_ORDER, columns=DEMAND_ORDER)
    ev_pv = df.pivot(index="distance", columns="demand_name",
                     values="seed_evidence").reindex(
                     index=DISTANCE_ORDER, columns=DEMAND_ORDER)
    matrix, ev = code_pv.values, ev_pv.values

    cmap = ListedColormap([CLASS_COLORS[k] for k in [1, 2, 3, 4, 5]])
    norm = BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5, 5.5], cmap.N)

    fig, ax = plt.subplots(figsize=(9.0, 5.4))
    ax.imshow(matrix, aspect="auto", cmap=cmap, norm=norm)

    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix[i, j]
            if np.isnan(value):
                continue
            # hatching = single-seed exploratory (as promised in the caption)
            if ev[i, j] == "1-seed exploratory":
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1,
                                       fill=False, hatch="///",
                                       edgecolor="white", linewidth=0.0,
                                       alpha=0.55))
            ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1,
                                   fill=False, edgecolor="white",
                                   linewidth=1.4))
            # class code: keeps the figure readable in greyscale print
            ax.text(j, i, f"{int(value)}", ha="center", va="center",
                    fontsize=11, fontweight="bold", color="white")

    ax.set_xticks(range(len(DEMAND_ORDER)))
    ax.set_xticklabels(DEMAND_ORDER, rotation=20, ha="right")
    ax.set_yticks(range(len(DISTANCE_ORDER)))
    ax.set_yticklabels([f"{d} m" for d in DISTANCE_ORDER])
    ax.set_xlabel("Demand regime")
    ax.set_ylabel("Inter-intersection distance $d$")
    ax.set_title("Integrated DCHF diagnosis: distance $\\times$ demand")

    counts = {k: int((matrix == k).sum()) for k in [1, 2, 3, 4, 5]}
    handles = [Patch(facecolor=CLASS_COLORS[k], edgecolor="none",
                     label=f"{k} = {CLASS_NAMES[k]} ({counts[k]})")
               for k in [1, 2, 4, 5]]
    handles.append(Patch(facecolor="#BBBBBB", hatch="///", edgecolor="white",
                         label="Single-seed exploratory"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.20),
              ncol=3, frameon=False, fontsize=9)

    fig.tight_layout()
    for ext, kw in (("pdf", {}), ("png", {"dpi": 300})):
        fig.savefig(
            f"{FIG_DIR}/final_heatmap_distance_demand_integrated_dchf.{ext}",
            bbox_inches="tight", **kw)
    plt.close(fig)

    print("\nIntegrated DCHF diagnosis regenerated.")
    print(f"Class counts     : {actual}")
    print(f"Five-seed cells  : {n_multi} / 30")
    print(f"Useful cells     : all five-seed validated")
    print(f"Figure           : {FIG_DIR}/final_heatmap_distance_demand_integrated_dchf.pdf")
    print("\nGrid (rows = d, cols = demand):")
    print(code_pv.astype(int).to_string())


if __name__ == "__main__":
    main()