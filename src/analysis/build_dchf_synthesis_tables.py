import os
import numpy as np
import pandas as pd


TABLE_DIR = "results/tables"

OUT_MASTER = f"{TABLE_DIR}/dchf_master_synthesis.csv"
OUT_DISTANCE = f"{TABLE_DIR}/dchf_two_intersection_distance_horizon.csv"
OUT_DEMAND = f"{TABLE_DIR}/dchf_two_intersection_demand_horizon.csv"
OUT_THREE_REF = f"{TABLE_DIR}/dchf_three_intersection_reference_horizon.csv"
OUT_THREE_D23 = f"{TABLE_DIR}/dchf_three_intersection_d23_horizon.csv"
OUT_KEY = f"{TABLE_DIR}/dchf_key_findings.csv"


# =========================================================
# Utility functions
# =========================================================

def read_csv(path):
    if not os.path.exists(path):
        print(f"Missing file: {path}")
        return None
    return pd.read_csv(path)


def ensure_buffered_ratio(df, expected_total_vehicles):
    """
    Some old result files contain 'buffered_ratio', while others only contain
    'final_buffered' or 'buffered_at_best_waiting'. This function standardizes
    the column so the DCHF synthesis script works with all previous outputs.
    """
    if df is None:
        return None

    df = df.copy()

    if "buffered_ratio" not in df.columns:
        if "final_buffered" in df.columns:
            df["buffered_ratio"] = df["final_buffered"] / expected_total_vehicles
        elif "buffered_at_best_waiting" in df.columns:
            df["buffered_ratio"] = df["buffered_at_best_waiting"] / expected_total_vehicles
        else:
            df["buffered_ratio"] = np.nan

    return df


def coordination_gain(sim_value, controller_value):
    """
    Coordination Gain for lower-is-better metrics such as waiting time or queue.

    CG = (M_sim - M_controller) / M_sim * 100

    Positive value  -> improvement over simultaneous fixed-time.
    Zero value      -> no improvement.
    Negative value  -> worse than simultaneous fixed-time.
    """
    if sim_value is None or controller_value is None:
        return np.nan

    if pd.isna(sim_value) or pd.isna(controller_value) or sim_value == 0:
        return np.nan

    return ((sim_value - controller_value) / sim_value) * 100


def qmix_gap(qmix_value, best_offset_value):
    """
    Gap between QMIX and the optimized fixed-offset benchmark.

    Gap = (QMIX - BestOffset) / BestOffset * 100

    Lower is better.
    """
    if best_offset_value is None or qmix_value is None:
        return np.nan

    if pd.isna(best_offset_value) or pd.isna(qmix_value) or best_offset_value == 0:
        return np.nan

    return ((qmix_value - best_offset_value) / best_offset_value) * 100


def classify_gap(gap):
    """
    Coordination-horizon classification based on the QMIX gap versus
    the optimized offset benchmark.
    """
    if pd.isna(gap):
        return "Not available"

    if gap <= 5:
        return "Effective coordination zone"

    if gap <= 10:
        return "Marginal coordination zone"

    return "Outside coordination horizon"


def classify_capacity(buffered_ratio):
    """
    Capacity regime based on buffered ratio.

    BR < 0.01        -> unconstrained
    0.01 <= BR < 0.10 -> mild insertion pressure
    0.10 <= BR < 0.25 -> capacity-limited
    BR >= 0.25       -> oversaturated
    """
    if pd.isna(buffered_ratio):
        return "Not available"

    if buffered_ratio < 0.01:
        return "Unconstrained"

    if buffered_ratio < 0.10:
        return "Mild insertion pressure"

    if buffered_ratio < 0.25:
        return "Capacity-limited"

    return "Oversaturated"


def max_available(*values):
    valid = [v for v in values if not pd.isna(v)]

    if not valid:
        return np.nan

    return max(valid)


# =========================================================
# 1. Two-intersection spatial horizon
# =========================================================

def build_two_intersection_distance():
    comp = read_csv(f"{TABLE_DIR}/distance_best_offset_vs_qmix.csv")
    sweep = read_csv(f"{TABLE_DIR}/distance_offset_sweep_summary.csv")

    comp = ensure_buffered_ratio(comp, expected_total_vehicles=2800)
    sweep = ensure_buffered_ratio(sweep, expected_total_vehicles=2800)

    if comp is None or sweep is None:
        return pd.DataFrame()

    required_sweep_cols = [
        "distance",
        "offset",
        "mean_total_waiting_time",
        "mean_speed",
        "mean_total_queue",
        "buffered_ratio",
    ]

    missing = [c for c in required_sweep_cols if c not in sweep.columns]
    if missing:
        raise KeyError(f"Missing columns in distance_offset_sweep_summary.csv: {missing}")

    sim = sweep[sweep["offset"] == 0].copy()

    sim = sim[
        [
            "distance",
            "mean_total_waiting_time",
            "mean_speed",
            "mean_total_queue",
            "buffered_ratio",
        ]
    ]

    sim = sim.rename(
        columns={
            "mean_total_waiting_time": "sim_waiting_time",
            "mean_speed": "sim_speed",
            "mean_total_queue": "sim_queue",
            "buffered_ratio": "sim_buffered_ratio",
        }
    )

    df = comp.merge(sim, on="distance", how="left")

    rows = []

    for _, r in df.iterrows():
        best_wait = r["best_offset_waiting_time"]
        qmix_wait = r["qmix_waiting_time"]
        sim_wait = r["sim_waiting_time"]

        gap = qmix_gap(qmix_wait, best_wait)

        br = max_available(
            r.get("best_offset_buffered_ratio", np.nan),
            r.get("qmix_buffered_ratio", np.nan),
            r.get("sim_buffered_ratio", np.nan),
            r.get("buffered_ratio", np.nan),
        )

        rows.append(
            {
                "horizon_type": "Two-intersection spatial horizon",
                "scenario": f"{int(r['distance'])} m",
                "sim_waiting_time": sim_wait,
                "optimized_offset_waiting_time": best_wait,
                "qmix_waiting_time": qmix_wait,
                "optimized_offset_coordination_gain_percent": coordination_gain(sim_wait, best_wait),
                "qmix_coordination_gain_percent": coordination_gain(sim_wait, qmix_wait),
                "qmix_gap_vs_optimized_offset_percent": gap,
                "coordination_regime": classify_gap(gap),
                "capacity_regime": classify_capacity(br),
                "main_interpretation": "Distance effect on transferred QMIX generalization",
            }
        )

    out = pd.DataFrame(rows).round(3)
    out.to_csv(OUT_DISTANCE, index=False)

    return out


# =========================================================
# 2. Two-intersection demand horizon
# =========================================================

def build_two_intersection_demand():
    comp = read_csv(f"{TABLE_DIR}/demand_best_offset_vs_qmix.csv")
    sweep = read_csv(f"{TABLE_DIR}/demand_offset_sweep_summary.csv")

    # Demand files normally already include buffered_ratio.
    # This is only a fallback in case the column is missing.
    comp = ensure_buffered_ratio(comp, expected_total_vehicles=7000)
    sweep = ensure_buffered_ratio(sweep, expected_total_vehicles=7000)

    if comp is None or sweep is None:
        return pd.DataFrame()

    required_sweep_cols = [
        "demand_scenario",
        "demand_multiplier",
        "offset",
        "mean_total_waiting_time",
        "mean_speed",
        "mean_total_queue",
        "buffered_ratio",
    ]

    missing = [c for c in required_sweep_cols if c not in sweep.columns]
    if missing:
        raise KeyError(f"Missing columns in demand_offset_sweep_summary.csv: {missing}")

    sim = sweep[sweep["offset"] == 0].copy()

    sim = sim[
        [
            "demand_scenario",
            "demand_multiplier",
            "mean_total_waiting_time",
            "mean_speed",
            "mean_total_queue",
            "buffered_ratio",
        ]
    ]

    sim = sim.rename(
        columns={
            "mean_total_waiting_time": "sim_waiting_time",
            "mean_speed": "sim_speed",
            "mean_total_queue": "sim_queue",
            "buffered_ratio": "sim_buffered_ratio",
        }
    )

    df = comp.merge(
        sim,
        on=["demand_scenario", "demand_multiplier"],
        how="left",
    )

    rows = []

    for _, r in df.iterrows():
        best_wait = r["best_offset_waiting_time"]
        qmix_wait = r["qmix_waiting_time"]
        sim_wait = r["sim_waiting_time"]

        gap = qmix_gap(qmix_wait, best_wait)

        br = max_available(
            r.get("best_offset_buffered_ratio", np.nan),
            r.get("qmix_buffered_ratio", np.nan),
            r.get("sim_buffered_ratio", np.nan),
            r.get("buffered_ratio", np.nan),
        )

        rows.append(
            {
                "horizon_type": "Two-intersection demand horizon",
                "scenario": f"{r['demand_scenario']} ({r['demand_multiplier']}x)",
                "sim_waiting_time": sim_wait,
                "optimized_offset_waiting_time": best_wait,
                "qmix_waiting_time": qmix_wait,
                "optimized_offset_coordination_gain_percent": coordination_gain(sim_wait, best_wait),
                "qmix_coordination_gain_percent": coordination_gain(sim_wait, qmix_wait),
                "qmix_gap_vs_optimized_offset_percent": gap,
                "coordination_regime": classify_gap(gap),
                "capacity_regime": classify_capacity(br),
                "main_interpretation": "Demand and capacity effect on coordination",
            }
        )

    out = pd.DataFrame(rows).round(3)
    out.to_csv(OUT_DEMAND, index=False)

    return out


# =========================================================
# 3. Three-intersection reference horizon
# =========================================================

def build_three_intersection_reference():
    comp = read_csv(f"{TABLE_DIR}/three_intersection_qmix_comparison.csv")

    if comp is None:
        return pd.DataFrame()

    sim_rows = comp[comp["controller"] == "Simultaneous Fixed-Time"]
    best_rows = comp[comp["controller"] == "Best Offset Pattern"]
    qmix_rows = comp[comp["controller"] == "QMIX 3 Agents"]

    if sim_rows.empty or best_rows.empty or qmix_rows.empty:
        raise ValueError(
            "three_intersection_qmix_comparison.csv must contain "
            "'Simultaneous Fixed-Time', 'Best Offset Pattern', and 'QMIX 3 Agents'."
        )

    sim = sim_rows.iloc[0]
    best = best_rows.iloc[0]
    qmix = qmix_rows.iloc[0]

    sim_wait = sim["mean_total_waiting_time"]
    best_wait = best["mean_total_waiting_time"]
    qmix_wait = qmix["mean_total_waiting_time"]

    gap = qmix_gap(qmix_wait, best_wait)

    br = max_available(
        sim.get("buffered_ratio", np.nan),
        best.get("buffered_ratio", np.nan),
        qmix.get("buffered_ratio", np.nan),
    )

    out = pd.DataFrame(
        [
            {
                "horizon_type": "Three-intersection reference scalability horizon",
                "scenario": "d12=300 m, d23=300 m",
                "sim_waiting_time": sim_wait,
                "optimized_offset_waiting_time": best_wait,
                "qmix_waiting_time": qmix_wait,
                "optimized_offset_coordination_gain_percent": coordination_gain(sim_wait, best_wait),
                "qmix_coordination_gain_percent": coordination_gain(sim_wait, qmix_wait),
                "qmix_gap_vs_optimized_offset_percent": gap,
                "coordination_regime": classify_gap(gap),
                "capacity_regime": classify_capacity(br),
                "main_interpretation": "QMIX scalability from two to three intersections",
            }
        ]
    ).round(3)

    out.to_csv(OUT_THREE_REF, index=False)

    return out


# =========================================================
# 4. Three-intersection d23 spatial horizon
# =========================================================

def build_three_intersection_d23():
    comp = read_csv(f"{TABLE_DIR}/three_intersection_d23_best_offset_vs_qmix.csv")
    sweep = read_csv(f"{TABLE_DIR}/three_intersection_d23_offset_sweep_summary.csv")

    comp = ensure_buffered_ratio(comp, expected_total_vehicles=3400)
    sweep = ensure_buffered_ratio(sweep, expected_total_vehicles=3400)

    if comp is None or sweep is None:
        return pd.DataFrame()

    required_sweep_cols = [
        "d23",
        "offset_j2",
        "offset_j3",
        "mean_total_waiting_time",
        "mean_speed",
        "mean_total_queue",
        "buffered_ratio",
    ]

    missing = [c for c in required_sweep_cols if c not in sweep.columns]
    if missing:
        raise KeyError(f"Missing columns in three_intersection_d23_offset_sweep_summary.csv: {missing}")

    sim = sweep[(sweep["offset_j2"] == 0) & (sweep["offset_j3"] == 0)].copy()

    sim = sim[
        [
            "d23",
            "mean_total_waiting_time",
            "mean_speed",
            "mean_total_queue",
            "buffered_ratio",
        ]
    ]

    sim = sim.rename(
        columns={
            "mean_total_waiting_time": "sim_waiting_time",
            "mean_speed": "sim_speed",
            "mean_total_queue": "sim_queue",
            "buffered_ratio": "sim_buffered_ratio",
        }
    )

    df = comp.merge(sim, on="d23", how="left")

    rows = []

    for _, r in df.iterrows():
        best_wait = r["best_offset_waiting_time"]
        qmix_wait = r["qmix_waiting_time"]
        sim_wait = r["sim_waiting_time"]

        gap = qmix_gap(qmix_wait, best_wait)

        br = max_available(
            r.get("best_offset_buffered_ratio", np.nan),
            r.get("qmix_buffered_ratio", np.nan),
            r.get("sim_buffered_ratio", np.nan),
            r.get("buffered_ratio", np.nan),
        )

        rows.append(
            {
                "horizon_type": "Three-intersection third-light spatial horizon",
                "scenario": f"d23={int(r['d23'])} m",
                "sim_waiting_time": sim_wait,
                "optimized_offset_waiting_time": best_wait,
                "qmix_waiting_time": qmix_wait,
                "optimized_offset_coordination_gain_percent": coordination_gain(sim_wait, best_wait),
                "qmix_coordination_gain_percent": coordination_gain(sim_wait, qmix_wait),
                "qmix_gap_vs_optimized_offset_percent": gap,
                "coordination_regime": classify_gap(gap),
                "capacity_regime": classify_capacity(br),
                "main_interpretation": "Effect of third-light position on QMIX generalization",
            }
        )

    out = pd.DataFrame(rows).round(3)
    out.to_csv(OUT_THREE_D23, index=False)

    return out


# =========================================================
# Key findings
# =========================================================

def list_scenarios(df, regime):
    if df.empty:
        return "Not available"

    vals = df[df["coordination_regime"] == regime]["scenario"].tolist()

    return ", ".join(vals) if vals else "None"


def build_key_findings(distance_df, demand_df, three_ref_df, d23_df):
    rows = []

    if not distance_df.empty:
        rows.append(
            {
                "finding": "Two-intersection tested effective spatial horizon",
                "value": list_scenarios(distance_df, "Effective coordination zone"),
            }
        )
        rows.append(
            {
                "finding": "Two-intersection marginal spatial horizon",
                "value": list_scenarios(distance_df, "Marginal coordination zone"),
            }
        )
        rows.append(
            {
                "finding": "Two-intersection outside spatial horizon",
                "value": list_scenarios(distance_df, "Outside coordination horizon"),
            }
        )

    if not demand_df.empty:
        rows.append(
            {
                "finding": "Two-intersection effective demand horizon",
                "value": list_scenarios(demand_df, "Effective coordination zone"),
            }
        )
        rows.append(
            {
                "finding": "Two-intersection marginal demand horizon",
                "value": list_scenarios(demand_df, "Marginal coordination zone"),
            }
        )
        rows.append(
            {
                "finding": "Two-intersection outside demand horizon",
                "value": list_scenarios(demand_df, "Outside coordination horizon"),
            }
        )

    if not three_ref_df.empty:
        r = three_ref_df.iloc[0]

        rows.append(
            {
                "finding": "Three-intersection reference QMIX gap",
                "value": f"{r['qmix_gap_vs_optimized_offset_percent']:.3f}%",
            }
        )
        rows.append(
            {
                "finding": "Three-intersection reference regime",
                "value": r["coordination_regime"],
            }
        )

    if not d23_df.empty:
        best_row = d23_df.loc[d23_df["optimized_offset_waiting_time"].idxmin()]

        rows.append(
            {
                "finding": "Best tested third-light distance",
                "value": (
                    f"{best_row['scenario']} with optimized offset waiting time = "
                    f"{best_row['optimized_offset_waiting_time']:.3f}"
                ),
            }
        )
        rows.append(
            {
                "finding": "Three-intersection tested effective d23 horizon",
                "value": list_scenarios(d23_df, "Effective coordination zone"),
            }
        )
        rows.append(
            {
                "finding": "Three-intersection marginal d23 horizon",
                "value": list_scenarios(d23_df, "Marginal coordination zone"),
            }
        )
        rows.append(
            {
                "finding": "Three-intersection outside d23 horizon",
                "value": list_scenarios(d23_df, "Outside coordination horizon"),
            }
        )

    key = pd.DataFrame(rows)
    key.to_csv(OUT_KEY, index=False)

    return key


# =========================================================
# Main
# =========================================================

def main():
    os.makedirs(TABLE_DIR, exist_ok=True)

    distance_df = build_two_intersection_distance()
    demand_df = build_two_intersection_demand()
    three_ref_df = build_three_intersection_reference()
    d23_df = build_three_intersection_d23()

    dfs = [distance_df, demand_df, three_ref_df, d23_df]
    dfs = [df for df in dfs if df is not None and not df.empty]

    if dfs:
        master = pd.concat(dfs, ignore_index=True).round(3)
    else:
        master = pd.DataFrame()

    master.to_csv(OUT_MASTER, index=False)

    key = build_key_findings(distance_df, demand_df, three_ref_df, d23_df)

    print("\n=== DCHF Master Synthesis ===")
    print(master.to_string(index=False))

    print("\n=== DCHF Key Findings ===")
    print(key.to_string(index=False))

    print(f"\nSaved master synthesis to: {OUT_MASTER}")
    print(f"Saved key findings to: {OUT_KEY}")


if __name__ == "__main__":
    main()
