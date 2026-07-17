"""
Figure 4 - Integrated DCHF diagnosis over the 30-cell distance-demand grid.

Classification follows manuscript Eq. (5), Eq. (6), and the capacity-
precedence rule of Section 4.2.4: within the approximation-effective branch
only, BR >= 0.10 is classified as capacity-constrained.

Where five-seed paired evidence exists (spatial sweep, demand sweep, or
selected joint-grid boundary reruns), the five-seed mean gap supersedes the
single-seed exploratory gap. Coordination Gain and buffered ratio remain the
joint-grid diagnostics because the paired summary files contain gap evidence,
not multi-seed replacements for those two quantities.
"""

import ast
import os
import re

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch, Rectangle


matplotlib.rcParams["hatch.linewidth"] = 1.1

TABLE_DIR = "results/tables"
FIG_DIR = "results/figures"

GRID_FILE = (
    f"{TABLE_DIR}/distance_demand_grid_dchf_summary_updated.csv"
)
PAIRED_SWEEPS_FILE = (
    f"{TABLE_DIR}/fully_paired_sweeps_summary.csv"
)
BOUNDARY_FILE = (
    f"{TABLE_DIR}/joint_grid_boundary_multiseed_summary.csv"
)

OUT_CLASSES = (
    f"{TABLE_DIR}/final_distance_demand_integrated_dchf_classes.csv"
)
OUT_COUNTS = (
    f"{TABLE_DIR}/final_distance_demand_integrated_dchf_counts.csv"
)

os.makedirs(TABLE_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

DEMAND_ORDER = [
    "low",
    "medium",
    "high",
    "saturation",
    "oversaturation",
]
DISTANCE_ORDER = [100, 200, 300, 500, 750, 1000]

# Okabe-Ito palette, matching the graphical abstract.
CLASS_COLORS = {
    1: "#009E73",  # Useful effective
    2: "#CC79A7",  # Capacity-constrained
    3: "#56B4E9",  # Close / no practical gain
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

TEXT_COLORS = {
    1: "white",
    2: "white",
    3: "black",
    4: "black",
    5: "white",
}


def classify_integrated(gap, cg, br):
    """
    Apply the manuscript gap rule and capacity-precedence rule.

    Capacity precedence applies only inside the approximation-effective
    branch, G <= 5%.
    """
    if pd.isna(gap) or pd.isna(cg) or pd.isna(br):
        return np.nan

    if gap <= 5:
        if br >= 0.10:
            return 2

        if cg > 0:
            return 1

        return 3

    if gap <= 10:
        return 4

    return 5


def parse_ci(value):
    """Parse a two-value confidence interval stored as text."""
    if pd.isna(value):
        return np.nan, np.nan

    parsed = ast.literal_eval(str(value))

    if not isinstance(parsed, (list, tuple)) or len(parsed) != 2:
        raise ValueError(
            f"Invalid confidence interval: {value!r}"
        )

    return float(parsed[0]), float(parsed[1])


def register_evidence(
    store,
    key,
    gap,
    source,
    ci_low=np.nan,
    ci_high=np.nan,
    stability=np.nan,
):
    """
    Register one multi-seed gap.

    Duplicate evidence is allowed only when the reported mean gaps agree
    exactly. This covers cells appearing in more than one paired campaign.
    """
    record = {
        "gap": float(gap),
        "source": source,
        "ci_low": (
            float(ci_low) if not pd.isna(ci_low) else np.nan
        ),
        "ci_high": (
            float(ci_high) if not pd.isna(ci_high) else np.nan
        ),
        "stability": (
            float(stability)
            if not pd.isna(stability)
            else np.nan
        ),
    }

    if key not in store:
        store[key] = record
        return

    existing = store[key]

    if not np.isclose(
        existing["gap"],
        record["gap"],
        atol=1e-6,
    ):
        raise ValueError(
            f"Conflicting five-seed gaps for {key}: "
            f"{existing['gap']} from {existing['source']} versus "
            f"{record['gap']} from {source}"
        )

    existing_sources = existing["source"].split(" + ")

    if source not in existing_sources:
        existing["source"] += f" + {source}"

    # Prefer the most detailed available metadata.
    if not pd.isna(record["ci_low"]):
        existing["ci_low"] = record["ci_low"]

    if not pd.isna(record["ci_high"]):
        existing["ci_high"] = record["ci_high"]

    if not pd.isna(record["stability"]):
        existing["stability"] = record["stability"]


def load_multiseed_evidence():
    """
    Load all five-seed gaps that supersede exploratory grid gaps.

    Sources:
    - paired spatial sweep;
    - paired demand sweep;
    - selected joint-grid boundary reruns.
    """
    paired = pd.read_csv(PAIRED_SWEEPS_FILE)
    boundary = pd.read_csv(BOUNDARY_FILE)

    paired_required = {
        "sweep",
        "cell",
        "G_QMIX_mean",
        "G_QMIX_ci",
    }

    boundary_required = {
        "cell",
        "mean_gap_pct",
        "ci_low",
        "ci_high",
        "mean_regime",
        "regime_stability_pct",
    }

    missing_paired = paired_required.difference(
        paired.columns
    )
    missing_boundary = boundary_required.difference(
        boundary.columns
    )

    if missing_paired:
        raise ValueError(
            "Paired-sweep summary is missing columns: "
            + ", ".join(sorted(missing_paired))
        )

    if missing_boundary:
        raise ValueError(
            "Boundary summary is missing columns: "
            + ", ".join(sorted(missing_boundary))
        )

    evidence = {}

    for _, row in paired.iterrows():
        sweep = str(row["sweep"]).strip().lower()
        cell = str(row["cell"]).strip().lower()
        ci_low, ci_high = parse_ci(
            row["G_QMIX_ci"]
        )

        if sweep == "spatial":
            match = re.fullmatch(
                r"d=(\d+)m",
                cell,
            )

            if match is None:
                raise ValueError(
                    f"Cannot parse spatial cell: "
                    f"{row['cell']!r}"
                )

            key = (
                int(match.group(1)),
                "medium",
            )
            source = "5-seed spatial sweep"

        elif sweep == "demand":
            if cell not in DEMAND_ORDER:
                raise ValueError(
                    f"Unknown demand cell: "
                    f"{row['cell']!r}"
                )

            key = (300, cell)
            source = "5-seed demand sweep"

        else:
            raise ValueError(
                f"Unknown sweep type: "
                f"{row['sweep']!r}"
            )

        register_evidence(
            evidence,
            key,
            row["G_QMIX_mean"],
            source,
            ci_low,
            ci_high,
        )

    for _, row in boundary.iterrows():
        match = re.fullmatch(
            (
                r"d=(\d+),\s*"
                r"(low|medium|high|saturation|oversaturation)"
            ),
            str(row["cell"]).strip().lower(),
        )

        if match is None:
            raise ValueError(
                f"Cannot parse boundary cell: "
                f"{row['cell']!r}"
            )

        key = (
            int(match.group(1)),
            match.group(2),
        )

        register_evidence(
            evidence,
            key,
            row["mean_gap_pct"],
            "5-seed boundary rerun",
            row["ci_low"],
            row["ci_high"],
            row["regime_stability_pct"],
        )

    return evidence


def main():
    df = pd.read_csv(GRID_FILE)

    required_grid_columns = {
        "distance",
        "demand_name",
        "qmix_gap_vs_optimized_offset_percent",
        "qmix_coordination_gain_percent",
        "qmix_buffered_ratio",
    }

    missing_grid = required_grid_columns.difference(
        df.columns
    )

    if missing_grid:
        raise ValueError(
            "Joint-grid file is missing columns: "
            + ", ".join(sorted(missing_grid))
        )

    if len(df) != 30:
        raise ValueError(
            f"Expected 30 joint-grid cells, "
            f"found {len(df)}"
        )

    duplicate_cells = df.duplicated(
        ["distance", "demand_name"],
        keep=False,
    )

    if duplicate_cells.any():
        duplicates = df.loc[
            duplicate_cells,
            ["distance", "demand_name"],
        ]

        raise ValueError(
            "Duplicate joint-grid cells found:\n"
            + duplicates.to_string(index=False)
        )

    multiseed = load_multiseed_evidence()
    seen_keys = set()

    gaps_used = []
    evidence_levels = []
    evidence_sources = []
    ci_lows = []
    ci_highs = []
    stabilities = []
    codes = []

    for _, row in df.iterrows():
        key = (
            int(row["distance"]),
            str(row["demand_name"])
            .strip()
            .lower(),
        )

        seen_keys.add(key)

        single_gap = float(
            row[
                "qmix_gap_vs_optimized_offset_percent"
            ]
        )

        record = multiseed.get(key)

        if record is None:
            gap = single_gap
            evidence_level = "1-seed exploratory"
            source = "joint-grid single seed"
            ci_low = np.nan
            ci_high = np.nan
            stability = np.nan

        else:
            gap = record["gap"]
            evidence_level = "5-seed paired"
            source = record["source"]
            ci_low = record["ci_low"]
            ci_high = record["ci_high"]
            stability = record["stability"]

        code = classify_integrated(
            gap,
            row["qmix_coordination_gain_percent"],
            row["qmix_buffered_ratio"],
        )

        gaps_used.append(gap)
        evidence_levels.append(evidence_level)
        evidence_sources.append(source)
        ci_lows.append(ci_low)
        ci_highs.append(ci_high)
        stabilities.append(stability)
        codes.append(code)

    unused_evidence = sorted(
        set(multiseed).difference(seen_keys)
    )

    if unused_evidence:
        raise ValueError(
            "Five-seed evidence does not match a "
            "joint-grid cell: "
            + ", ".join(
                map(str, unused_evidence)
            )
        )

    df["gap_used_percent"] = gaps_used
    df["seed_evidence"] = evidence_levels
    df["gap_source"] = evidence_sources
    df["gap_ci_low"] = ci_lows
    df["gap_ci_high"] = ci_highs
    df["regime_stability_percent"] = stabilities
    df["final_integrated_dchf_code"] = codes
    df["final_integrated_dchf_label"] = [
        CLASS_LABELS.get(
            code,
            "Not available",
        )
        for code in codes
    ]

    if df[
        "final_integrated_dchf_code"
    ].isna().any():
        raise AssertionError(
            "Unclassified joint-grid cell present"
        )

    expected = {
        1: 3,
        2: 3,
        3: 0,
        4: 4,
        5: 20,
    }

    actual = (
        df["final_integrated_dchf_code"]
        .value_counts()
        .reindex(
            [1, 2, 3, 4, 5],
            fill_value=0,
        )
        .astype(int)
        .to_dict()
    )

    if actual != expected:
        raise AssertionError(
            "Unexpected integrated DCHF counts: "
            f"{actual}"
        )

    n_multiseed = int(
        df["seed_evidence"]
        .eq("5-seed paired")
        .sum()
    )

    if n_multiseed != 15:
        raise AssertionError(
            "Expected 15 distinct five-seed cells, "
            f"found {n_multiseed}"
        )

    useful = df[
        df[
            "final_integrated_dchf_code"
        ].eq(1)
    ]

    if not useful[
        "seed_evidence"
    ].eq("5-seed paired").all():
        raise AssertionError(
            "At least one useful-effective cell "
            "rests only on single-seed evidence"
        )

    critical_expected = {
        (300, "oversaturation"): (7.123, 4),
        (500, "saturation"): (7.406, 4),
        (500, "oversaturation"): (6.031, 4),
        (750, "oversaturation"): (12.333, 5),
        (1000, "saturation"): (1.768, 2),
        (1000, "oversaturation"): (1.794, 2),
    }

    for key, (
        expected_gap,
        expected_code,
    ) in critical_expected.items():
        target = df[
            df["distance"].eq(key[0])
            & df["demand_name"].eq(key[1])
        ]

        if len(target) != 1:
            raise AssertionError(
                "Expected one critical cell for "
                f"{key}"
            )

        target_row = target.iloc[0]

        if not np.isclose(
            target_row["gap_used_percent"],
            expected_gap,
            atol=1e-6,
        ):
            raise AssertionError(
                f"Unexpected gap for {key}: "
                f"{target_row['gap_used_percent']}"
            )

        if (
            int(
                target_row[
                    "final_integrated_dchf_code"
                ]
            )
            != expected_code
        ):
            raise AssertionError(
                f"Unexpected class for {key}: "
                f"{target_row['final_integrated_dchf_code']}"
            )

    df.to_csv(
        OUT_CLASSES,
        index=False,
    )

    counts = (
        df.groupby(
            [
                "final_integrated_dchf_code",
                "final_integrated_dchf_label",
            ]
        )
        .size()
        .reset_index(
            name="number_of_cases"
        )
        .sort_values(
            "final_integrated_dchf_code"
        )
    )

    counts = (
        counts.set_index("final_integrated_dchf_code")
        .reindex([1, 2, 3, 4, 5])
        .reset_index()
    )
    counts["final_integrated_dchf_label"] = (
        counts["final_integrated_dchf_code"].map(CLASS_LABELS)
    )
    counts["number_of_cases"] = (
        counts["number_of_cases"].fillna(0).astype(int)
    )

    counts.to_csv(
        OUT_COUNTS,
        index=False,
    )

    code_pivot = (
        df.pivot(
            index="distance",
            columns="demand_name",
            values=(
                "final_integrated_dchf_code"
            ),
        )
        .reindex(
            index=DISTANCE_ORDER,
            columns=DEMAND_ORDER,
        )
    )

    evidence_pivot = (
        df.pivot(
            index="distance",
            columns="demand_name",
            values="seed_evidence",
        )
        .reindex(
            index=DISTANCE_ORDER,
            columns=DEMAND_ORDER,
        )
    )

    matrix = code_pivot.to_numpy(
        dtype=float
    )
    evidence_matrix = (
        evidence_pivot.to_numpy()
    )

    cmap = ListedColormap(
        [
            CLASS_COLORS[code]
            for code in [1, 2, 3, 4, 5]
        ]
    )

    norm = BoundaryNorm(
        [
            0.5,
            1.5,
            2.5,
            3.5,
            4.5,
            5.5,
        ],
        cmap.N,
    )

    fig, ax = plt.subplots(
        figsize=(9.0, 5.4)
    )

    ax.imshow(
        matrix,
        aspect="auto",
        cmap=cmap,
        norm=norm,
    )

    for i in range(
        matrix.shape[0]
    ):
        for j in range(
            matrix.shape[1]
        ):
            value = matrix[i, j]

            if np.isnan(value):
                continue

            if (
                evidence_matrix[i, j]
                == "1-seed exploratory"
            ):
                ax.add_patch(
                    Rectangle(
                        (
                            j - 0.5,
                            i - 0.5,
                        ),
                        1,
                        1,
                        fill=False,
                        hatch="///",
                        edgecolor="white",
                        linewidth=0.0,
                        alpha=0.65,
                    )
                )

            ax.add_patch(
                Rectangle(
                    (
                        j - 0.5,
                        i - 0.5,
                    ),
                    1,
                    1,
                    fill=False,
                    edgecolor="white",
                    linewidth=1.4,
                )
            )

            code = int(value)

            ax.text(
                j,
                i,
                str(code),
                ha="center",
                va="center",
                fontsize=11,
                fontweight="bold",
                color=TEXT_COLORS[code],
            )

    ax.set_xticks(
        range(len(DEMAND_ORDER))
    )
    ax.set_xticklabels(
        DEMAND_ORDER,
        rotation=20,
        ha="right",
    )

    ax.set_yticks(
        range(len(DISTANCE_ORDER))
    )
    ax.set_yticklabels(
        [
            f"{distance} m"
            for distance in DISTANCE_ORDER
        ]
    )

    ax.set_xlabel("Demand regime")
    ax.set_ylabel(
        r"Inter-intersection distance $d$"
    )
    ax.set_title(
        r"Integrated DCHF diagnosis: "
        r"distance $\times$ demand"
    )

    class_counts = {
        code: int(
            (matrix == code).sum()
        )
        for code in [1, 2, 3, 4, 5]
    }

    handles = [
        Patch(
            facecolor=CLASS_COLORS[code],
            edgecolor="none",
            label=(
                f"{code} = "
                f"{CLASS_NAMES[code]} "
                f"({class_counts[code]})"
            ),
        )
        for code in [1, 2, 3, 4, 5]
    ]

    handles.append(
        Patch(
            facecolor="#777777",
            hatch="///",
            edgecolor="white",
            label="Single-seed exploratory",
        )
    )

    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
        ncol=3,
        frameon=False,
        fontsize=9,
    )

    fig.tight_layout()

    pdf_path = (
        f"{FIG_DIR}/"
        "final_heatmap_distance_demand_"
        "integrated_dchf.pdf"
    )
    png_path = (
        f"{FIG_DIR}/"
        "final_heatmap_distance_demand_"
        "integrated_dchf.png"
    )

    fig.savefig(
        pdf_path,
        bbox_inches="tight",
    )
    fig.savefig(
        png_path,
        dpi=300,
        bbox_inches="tight",
    )
    plt.close(fig)

    print(
        "\nIntegrated DCHF diagnosis regenerated."
    )
    print(
        f"Class counts    : {actual}"
    )
    print(
        f"Five-seed cells : {n_multiseed} / 30"
    )
    print(
        "Useful cells    : "
        "all five-seed validated"
    )
    print(
        f"Classes CSV     : {OUT_CLASSES}"
    )
    print(
        f"Counts CSV      : {OUT_COUNTS}"
    )
    print(
        f"Figure PDF      : {pdf_path}"
    )
    print(
        f"Figure PNG      : {png_path}"
    )
    print(
        "\nGrid "
        "(rows = distance, columns = demand):"
    )
    print(
        code_pivot.astype(int).to_string()
    )


if __name__ == "__main__":
    main()