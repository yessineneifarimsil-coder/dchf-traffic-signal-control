import os
import re
import numpy as np
import pandas as pd


TABLE_DIR = "results/tables"

INPUT_MASTER = f"{TABLE_DIR}/dchf_master_synthesis.csv"

OUT_SCENARIO_THRESHOLDS = f"{TABLE_DIR}/dchf_threshold_sensitivity_by_scenario.csv"
OUT_HORIZON_THRESHOLDS = f"{TABLE_DIR}/dchf_horizon_summary_by_threshold.csv"
OUT_CG_SURFACE = f"{TABLE_DIR}/dchf_coordination_gain_surface_projection.csv"
OUT_CAPACITY = f"{TABLE_DIR}/dchf_capacity_horizon_summary.csv"


GAP_THRESHOLDS = [3, 5, 10]


def read_master():
    if not os.path.exists(INPUT_MASTER):
        raise FileNotFoundError(
            f"Missing {INPUT_MASTER}. Run build_dchf_synthesis_tables.py first."
        )

    df = pd.read_csv(INPUT_MASTER)

    required = [
        "horizon_type",
        "scenario",
        "sim_waiting_time",
        "optimized_offset_waiting_time",
        "qmix_waiting_time",
        "optimized_offset_coordination_gain_percent",
        "qmix_coordination_gain_percent",
        "qmix_gap_vs_optimized_offset_percent",
        "coordination_regime",
        "capacity_regime",
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Missing columns in dchf_master_synthesis.csv: {missing}")

    numeric_cols = [
        "sim_waiting_time",
        "optimized_offset_waiting_time",
        "qmix_waiting_time",
        "optimized_offset_coordination_gain_percent",
        "qmix_coordination_gain_percent",
        "qmix_gap_vs_optimized_offset_percent",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def classify_reference_regime(gap):
    """
    Reference DCHF classification:
    Effective: gap <= 5%
    Marginal:  5% < gap <= 10%
    Outside:   gap > 10%
    """
    if pd.isna(gap):
        return "Not available"

    tolerance = 1e-3

    if gap <= 5 + tolerance:
        return "Effective coordination zone"

    if gap <= 10 + tolerance:
        return "Marginal coordination zone"

    return "Outside coordination horizon"


def classify_binary_threshold(gap, threshold):
    """
    Threshold sensitivity:
    For a given threshold, we only ask:
    Is QMIX close enough to the optimized offset benchmark?
    """
    if pd.isna(gap):
        return "Not available"

    if gap <= threshold:
        return "Effective under threshold"

    return "Not effective under threshold"



    """
    Extract a def parse_condition_value(row):numeric condition value for horizon summaries.

    Spatial horizon:
        "100 m" -> 100
    Demand horizon:
        "medium (1.0x)" -> 1.0
    Third-light horizon:
        "d23=500 m" -> 500
    Three-intersection reference:
        N = 3
    """
    htype = str(row["horizon_type"]).lower()
    scenario = str(row["scenario"]).lower()

    if "demand" in htype:
        match = re.search(r"\(([\d.]+)x\)", scenario)
        if match:
            return float(match.group(1))
        return np.nan

    if "third-light" in htype or "d23" in scenario:
        match = re.search(r"d23\s*=\s*([\d.]+)", scenario)
        if match:
            return float(match.group(1))

        match = re.search(r"([\d.]+)\s*m", scenario)
        if match:
            return float(match.group(1))

        return np.nan

    if "spatial" in htype:
        match = re.search(r"([\d.]+)\s*m", scenario)
        if match:
            return float(match.group(1))
        return np.nan

    if "scalability" in htype:
        return 3.0

    return np.nan
def parse_condition_value(row):
    """
    Extract a numeric condition value for horizon summaries.

    Spatial horizon:
        "100 m" -> 100

    Demand horizon:
        "medium (1.0x)" -> 1.0

    Third-light horizon:
        "d23=500 m" -> 500

    Scalability horizon:
        N = 3 for the current three-intersection reference case
    """
    htype = str(row["horizon_type"]).lower()
    scenario = str(row["scenario"]).lower()

    # IMPORTANT: check scalability before d23,
    # because the scalability scenario text contains d23=300 m.
    if "scalability" in htype:
        return 3.0

    if "demand" in htype:
        match = re.search(r"\(([\d.]+)x\)", scenario)
        if match:
            return float(match.group(1))
        return np.nan

    if "third-light" in htype or "d23" in scenario:
        match = re.search(r"d23\s*=\s*([\d.]+)", scenario)
        if match:
            return float(match.group(1))

        match = re.search(r"([\d.]+)\s*m", scenario)
        if match:
            return float(match.group(1))

        return np.nan

    if "spatial" in htype:
        match = re.search(r"([\d.]+)\s*m", scenario)
        if match:
            return float(match.group(1))
        return np.nan

    return np.nan

def add_threshold_columns(df):
    df = df.copy()

    gap_col = "qmix_gap_vs_optimized_offset_percent"

    df["reference_regime_5_10"] = df[gap_col].apply(classify_reference_regime)

    for threshold in GAP_THRESHOLDS:
        df[f"classification_gap_le_{threshold}pct"] = df[gap_col].apply(
            lambda x: classify_binary_threshold(x, threshold)
        )

    df["condition_value"] = df.apply(parse_condition_value, axis=1)

    return df


def build_horizon_summary(df):
    rows = []

    gap_col = "qmix_gap_vs_optimized_offset_percent"

    for horizon_type, sub in df.groupby("horizon_type"):
        for threshold in GAP_THRESHOLDS:
            effective = sub[sub[gap_col] <= threshold].copy()

            effective_scenarios = effective["scenario"].tolist()

            if len(effective_scenarios) == 0:
                effective_text = "None"
                max_value = np.nan
            else:
                effective_text = ", ".join(effective_scenarios)
                max_value = effective["condition_value"].max()

            rows.append(
                {
                    "horizon_type": horizon_type,
                    "gap_threshold_percent": threshold,
                    "effective_scenarios_under_threshold": effective_text,
                    "max_tested_effective_condition_value": max_value,
                    "number_of_effective_scenarios": len(effective_scenarios),
                    "interpretation": (
                        "QMIX is considered effective where its approximation gap "
                        "to the optimized fixed-offset benchmark is below the threshold."
                    ),
                }
            )

    out = pd.DataFrame(rows).round(3)
    out.to_csv(OUT_HORIZON_THRESHOLDS, index=False)

    return out


def build_cg_surface_projection(df):
    """
    This table supports the equation:
    CG = F(d, rho, N, B)

    Existing experiments are projections of this latent surface:
    - spatial projection
    - demand projection
    - scalability projection
    - third-light spatial projection
    """
    rows = []

    for horizon_type, sub in df.groupby("horizon_type"):
        qmix_cg = sub["qmix_coordination_gain_percent"]
        offset_cg = sub["optimized_offset_coordination_gain_percent"]
        gap = sub["qmix_gap_vs_optimized_offset_percent"]

        effective_reference = sub[gap <= 5]

        rows.append(
            {
                "projection": horizon_type,
                "number_of_tested_scenarios": len(sub),
                "qmix_cg_min_percent": qmix_cg.min(),
                "qmix_cg_mean_percent": qmix_cg.mean(),
                "qmix_cg_max_percent": qmix_cg.max(),
                "offset_cg_mean_percent": offset_cg.mean(),
                "gap_min_percent": gap.min(),
                "gap_mean_percent": gap.mean(),
                "gap_max_percent": gap.max(),
                "effective_scenarios_reference_5pct": (
                    ", ".join(effective_reference["scenario"].tolist())
                    if len(effective_reference) > 0
                    else "None"
                ),
                "interpretation": (
                    "This row is one observed projection of the latent "
                    "Coordination Gain surface CG = F(d, rho, N, B)."
                ),
            }
        )

    out = pd.DataFrame(rows).round(3)
    out.to_csv(OUT_CG_SURFACE, index=False)

    return out


def build_capacity_summary(df):
    rows = []

    for horizon_type, sub in df.groupby("horizon_type"):
        regimes = sub["capacity_regime"].fillna("Not available")

        acceptable = sub[~regimes.isin(["Oversaturated"])]
        oversaturated = sub[regimes == "Oversaturated"]

        rows.append(
            {
                "horizon_type": horizon_type,
                "acceptable_capacity_scenarios": (
                    ", ".join(acceptable["scenario"].tolist())
                    if len(acceptable) > 0
                    else "None"
                ),
                "oversaturated_scenarios": (
                    ", ".join(oversaturated["scenario"].tolist())
                    if len(oversaturated) > 0
                    else "None"
                ),
                "capacity_horizon_interpretation": (
                    "Scenarios classified as oversaturated are beyond the "
                    "acceptable capacity horizon H_B under the current buffered-ratio rule."
                ),
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CAPACITY, index=False)

    return out


def build_scalability_projection(df):
    """
    Optional early scalability projection from existing results.

    Current available evidence:
    - N=2 can be represented by the two-intersection 300 m reference scenario.
    - N=3 is represented by the three-intersection reference scenario.

    This is still early scalability evidence, not full large-network scalability.
    """
    rows = []

    # N = 2 reference from two-intersection spatial horizon at 300 m
    n2 = df[
        (df["horizon_type"].str.contains("Two-intersection spatial", case=False, na=False))
        & (df["scenario"].astype(str).str.contains("300", na=False))
    ]

    if not n2.empty:
        r = n2.iloc[0]
        rows.append(
            {
                "N": 2,
                "scenario_source": r["scenario"],
                "qmix_coordination_gain_percent": r["qmix_coordination_gain_percent"],
                "qmix_gap_vs_optimized_offset_percent": r["qmix_gap_vs_optimized_offset_percent"],
                "reference_regime_5_10": r["reference_regime_5_10"],
            }
        )

    # N = 3 reference
    n3 = df[df["horizon_type"].str.contains("Three-intersection reference", case=False, na=False)]

    if not n3.empty:
        r = n3.iloc[0]
        rows.append(
            {
                "N": 3,
                "scenario_source": r["scenario"],
                "qmix_coordination_gain_percent": r["qmix_coordination_gain_percent"],
                "qmix_gap_vs_optimized_offset_percent": r["qmix_gap_vs_optimized_offset_percent"],
                "reference_regime_5_10": r["reference_regime_5_10"],
            }
        )

    out = pd.DataFrame(rows).round(3)
    out_path = f"{TABLE_DIR}/dchf_early_scalability_projection.csv"
    out.to_csv(out_path, index=False)

    return out, out_path


def main():
    os.makedirs(TABLE_DIR, exist_ok=True)

    df = read_master()
    df = add_threshold_columns(df)

    df.to_csv(OUT_SCENARIO_THRESHOLDS, index=False)

    horizon_summary = build_horizon_summary(df)
    cg_surface = build_cg_surface_projection(df)
    capacity_summary = build_capacity_summary(df)
    scalability_projection, scalability_path = build_scalability_projection(df)

    print("\n=== DCHF Threshold Sensitivity by Scenario ===")
    print(df[[
        "horizon_type",
        "scenario",
        "qmix_coordination_gain_percent",
        "qmix_gap_vs_optimized_offset_percent",
        "reference_regime_5_10",
        "classification_gap_le_3pct",
        "classification_gap_le_5pct",
        "classification_gap_le_10pct",
        "capacity_regime",
    ]].to_string(index=False))

    print("\n=== Horizon Summary by Threshold ===")
    print(horizon_summary.to_string(index=False))

    print("\n=== Coordination Gain Surface Projection ===")
    print(cg_surface.to_string(index=False))

    print("\n=== Capacity Horizon Summary ===")
    print(capacity_summary.to_string(index=False))

    print("\n=== Early Scalability Projection ===")
    print(scalability_projection.to_string(index=False))

    print("\nSaved outputs:")
    print(f"- {OUT_SCENARIO_THRESHOLDS}")
    print(f"- {OUT_HORIZON_THRESHOLDS}")
    print(f"- {OUT_CG_SURFACE}")
    print(f"- {OUT_CAPACITY}")
    print(f"- {scalability_path}")


if __name__ == "__main__":
    main()