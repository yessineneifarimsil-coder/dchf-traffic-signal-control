import os
import sys
import pandas as pd
import numpy as np


# =========================================================
# Paths
# =========================================================

ROOT = os.getcwd()

sys.path.append(os.path.join(ROOT, "src", "baselines", "two_intersections"))
sys.path.append(os.path.join(ROOT, "src", "baselines", "three_intersections"))
sys.path.append(os.path.join(ROOT, "src", "qmix"))
sys.path.append(os.path.join(ROOT, "src", "env"))

from run_distance_offset_sweep import run_distance_offset
from evaluate_qmix_distance_sensitivity import evaluate_qmix_for_distance

from run_three_intersection_d23_offset_sweep import run_offset_pattern as run_d23_offset_pattern
from evaluate_qmix_three_intersection_d23_sensitivity import run_qmix_for_d23


# =========================================================
# Configuration
# =========================================================

SEEDS = [0, 1, 2, 3, 4]

TWO_INTERSECTION_CASES = [
    {
        "validation_block": "Two-intersection spatial horizon",
        "case_type": "Effective case",
        "scenario": "d12 = 300 m",
        "distance": 300,
        "expected_reference_regime": "Effective coordination zone",
    },
    {
        "validation_block": "Two-intersection spatial horizon",
        "case_type": "Outside-horizon case",
        "scenario": "d12 = 1000 m",
        "distance": 1000,
        "expected_reference_regime": "Outside coordination horizon",
    },
]

THREE_INTERSECTION_CASES = [
    {
        "validation_block": "Three-intersection third-light horizon",
        "case_type": "Effective case",
        "scenario": "d12 = 300 m, d23 = 500 m",
        "d23": 500,
        "expected_reference_regime": "Effective coordination zone",
    },
    {
        "validation_block": "Three-intersection third-light horizon",
        "case_type": "Outside-horizon case",
        "scenario": "d12 = 300 m, d23 = 1000 m",
        "d23": 1000,
        "expected_reference_regime": "Outside coordination horizon",
    },
]

TABLE_DIR = "results/tables"
RAW_DIR = "results/raw"

DISTANCE_BEST_FILE = f"{TABLE_DIR}/distance_offset_best_summary.csv"
D23_BEST_FILE = f"{TABLE_DIR}/three_intersection_d23_offset_best_summary.csv"

OUT_CONTROLLER_RAW = f"{RAW_DIR}/multiseed_horizon_validation_controller_raw.csv"
OUT_SEED_METRICS = f"{TABLE_DIR}/multiseed_horizon_validation_seed_metrics.csv"
OUT_SUMMARY = f"{TABLE_DIR}/multiseed_horizon_validation_summary.csv"
OUT_REGIME = f"{TABLE_DIR}/multiseed_horizon_regime_stability.csv"


# =========================================================
# Metric functions
# =========================================================

def coordination_gain(sim_value, controller_value):
    if sim_value == 0 or pd.isna(sim_value) or pd.isna(controller_value):
        return np.nan

    return ((sim_value - controller_value) / sim_value) * 100


def qmix_gap(qmix_value, best_offset_value):
    if best_offset_value == 0 or pd.isna(qmix_value) or pd.isna(best_offset_value):
        return np.nan

    return ((qmix_value - best_offset_value) / best_offset_value) * 100


def classify_gap(gap):
    if pd.isna(gap):
        return "Not available"

    tolerance = 1e-3

    if gap <= 5 + tolerance:
        return "Effective coordination zone"

    if gap <= 10 + tolerance:
        return "Marginal coordination zone"

    return "Outside coordination horizon"


def safe_get(summary, key, default=np.nan):
    """
    Robust metric extractor.

    Some scripts return standardized names:
        mean_total_waiting_time, mean_speed, mean_total_queue

    Other QMIX sensitivity scripts may return:
        qmix_waiting_time, qmix_speed, qmix_queue

    This function maps both formats to the same output structure.
    """

    alias_map = {
        "mean_vehicle_count": [
            "mean_vehicle_count",
            "qmix_mean_vehicle_count",
        ],
        "max_vehicle_count": [
            "max_vehicle_count",
            "qmix_max_vehicle_count",
        ],
        "mean_total_waiting_time": [
            "mean_total_waiting_time",
            "qmix_waiting_time",
            "qmix_mean_total_waiting_time",
        ],
        "max_total_waiting_time": [
            "max_total_waiting_time",
            "qmix_max_total_waiting_time",
        ],
        "mean_speed": [
            "mean_speed",
            "qmix_speed",
            "qmix_mean_speed",
        ],
        "min_mean_speed": [
            "min_mean_speed",
            "qmix_min_mean_speed",
        ],
        "mean_total_queue": [
            "mean_total_queue",
            "qmix_queue",
            "qmix_mean_total_queue",
        ],
        "max_total_queue": [
            "max_total_queue",
            "qmix_max_queue",
            "qmix_max_total_queue",
        ],
        "total_departed": [
            "total_departed",
            "qmix_total_departed",
        ],
        "total_arrived": [
            "total_arrived",
            "qmix_total_arrived",
        ],
        "final_active": [
            "final_active",
            "qmix_final_active",
        ],
        "final_buffered": [
            "final_buffered",
            "qmix_final_buffered",
        ],
        "buffered_ratio": [
            "buffered_ratio",
            "qmix_buffered_ratio",
        ],
    }

    candidate_keys = alias_map.get(key, [key])

    for candidate in candidate_keys:
        if candidate in summary:
            return summary[candidate]

    return default


def standardize_controller_summary(
    validation_block,
    case_type,
    scenario,
    seed,
    controller,
    summary,
    distance=None,
    d23=None,
    offset=None,
    offset_j2=None,
    offset_j3=None,
):
    return {
        "validation_block": validation_block,
        "case_type": case_type,
        "scenario": scenario,
        "seed": seed,
        "controller": controller,
        "distance": distance,
        "d23": d23,
        "offset": offset,
        "offset_j2": offset_j2,
        "offset_j3": offset_j3,
        "mean_vehicle_count": safe_get(summary, "mean_vehicle_count"),
        "max_vehicle_count": safe_get(summary, "max_vehicle_count"),
        "mean_total_waiting_time": safe_get(summary, "mean_total_waiting_time"),
        "max_total_waiting_time": safe_get(summary, "max_total_waiting_time"),
        "mean_speed": safe_get(summary, "mean_speed"),
        "min_mean_speed": safe_get(summary, "min_mean_speed"),
        "mean_total_queue": safe_get(summary, "mean_total_queue"),
        "max_total_queue": safe_get(summary, "max_total_queue"),
        "total_departed": safe_get(summary, "total_departed"),
        "total_arrived": safe_get(summary, "total_arrived"),
        "final_active": safe_get(summary, "final_active"),
        "final_buffered": safe_get(summary, "final_buffered"),
        "buffered_ratio": safe_get(summary, "buffered_ratio"),
    }


# =========================================================
# Best offset readers
# =========================================================

def get_best_offset_for_distance(distance):
    df = pd.read_csv(DISTANCE_BEST_FILE)
    row = df[df["distance"] == distance].iloc[0]
    return int(row["best_waiting_offset"])


def get_best_offsets_for_d23(d23):
    df = pd.read_csv(D23_BEST_FILE)
    row = df[df["d23"] == d23].iloc[0]
    return int(row["best_waiting_offset_j2"]), int(row["best_waiting_offset_j3"])


# =========================================================
# Two-intersection validation
# =========================================================

def run_two_intersection_case(case, seed):
    distance = case["distance"]
    best_offset = get_best_offset_for_distance(distance)

    print("\n" + "-" * 70)
    print(f"Two-intersection case | distance={distance} m | seed={seed}")
    print(f"Best offset used: {best_offset} s")
    print("-" * 70)

    controller_rows = []

    # Simultaneous fixed-time = offset 0
    _, sim_summary = run_distance_offset(
        distance=distance,
        offset=0,
        sumo_seed=seed,
    )

    controller_rows.append(
        standardize_controller_summary(
            validation_block=case["validation_block"],
            case_type=case["case_type"],
            scenario=case["scenario"],
            seed=seed,
            controller="Simultaneous fixed-time",
            summary=sim_summary,
            distance=distance,
            offset=0,
        )
    )

    # Optimized fixed offset
    _, offset_summary = run_distance_offset(
        distance=distance,
        offset=best_offset,
        sumo_seed=seed,
    )

    controller_rows.append(
        standardize_controller_summary(
            validation_block=case["validation_block"],
            case_type=case["case_type"],
            scenario=case["scenario"],
            seed=seed,
            controller="Optimized fixed offset",
            summary=offset_summary,
            distance=distance,
            offset=best_offset,
        )
    )

    # QMIX
    _, qmix_summary = evaluate_qmix_for_distance(
        distance=distance,
        sumo_seed=seed,
    )

    controller_rows.append(
        standardize_controller_summary(
            validation_block=case["validation_block"],
            case_type=case["case_type"],
            scenario=case["scenario"],
            seed=seed,
            controller="QMIX V2",
            summary=qmix_summary,
            distance=distance,
            offset=None,
        )
    )

    return controller_rows


# =========================================================
# Three-intersection d23 validation
# =========================================================

def run_three_intersection_case(case, seed):
    d23 = case["d23"]
    best_j2, best_j3 = get_best_offsets_for_d23(d23)

    print("\n" + "-" * 70)
    print(f"Three-intersection d23 case | d23={d23} m | seed={seed}")
    print(f"Best offset pattern used: J2={best_j2} s | J3={best_j3} s")
    print("-" * 70)

    controller_rows = []

    # Simultaneous fixed-time = offsets 0,0
    sim_summary = run_d23_offset_pattern(
        d23=d23,
        offset_j2=0,
        offset_j3=0,
        sumo_seed=seed,
    )

    controller_rows.append(
        standardize_controller_summary(
            validation_block=case["validation_block"],
            case_type=case["case_type"],
            scenario=case["scenario"],
            seed=seed,
            controller="Simultaneous fixed-time",
            summary=sim_summary,
            d23=d23,
            offset_j2=0,
            offset_j3=0,
        )
    )

    # Optimized fixed offset
    offset_summary = run_d23_offset_pattern(
        d23=d23,
        offset_j2=best_j2,
        offset_j3=best_j3,
        sumo_seed=seed,
    )

    controller_rows.append(
        standardize_controller_summary(
            validation_block=case["validation_block"],
            case_type=case["case_type"],
            scenario=case["scenario"],
            seed=seed,
            controller="Optimized fixed offset",
            summary=offset_summary,
            d23=d23,
            offset_j2=best_j2,
            offset_j3=best_j3,
        )
    )

    # QMIX
    _, qmix_summary = run_qmix_for_d23(
        d23=d23,
        sumo_seed=seed,
    )

    controller_rows.append(
        standardize_controller_summary(
            validation_block=case["validation_block"],
            case_type=case["case_type"],
            scenario=case["scenario"],
            seed=seed,
            controller="QMIX 3 agents",
            summary=qmix_summary,
            d23=d23,
            offset_j2=None,
            offset_j3=None,
        )
    )

    return controller_rows


# =========================================================
# Seed-level DCHF metrics
# =========================================================

def build_seed_metrics(controller_df):
    rows = []

    group_cols = [
        "validation_block",
        "case_type",
        "scenario",
        "seed",
    ]

    for keys, sub in controller_df.groupby(group_cols):
        validation_block, case_type, scenario, seed = keys

        sim = sub[sub["controller"] == "Simultaneous fixed-time"].iloc[0]
        opt = sub[sub["controller"] == "Optimized fixed offset"].iloc[0]
        qmix = sub[sub["controller"].str.contains("QMIX")].iloc[0]

        sim_wait = sim["mean_total_waiting_time"]
        opt_wait = opt["mean_total_waiting_time"]
        qmix_wait = qmix["mean_total_waiting_time"]

        cg_offset = coordination_gain(sim_wait, opt_wait)
        cg_qmix = coordination_gain(sim_wait, qmix_wait)
        gap = qmix_gap(qmix_wait, opt_wait)
        regime = classify_gap(gap)

        rows.append(
            {
                "validation_block": validation_block,
                "case_type": case_type,
                "scenario": scenario,
                "seed": seed,
                "sim_waiting_time": sim_wait,
                "optimized_offset_waiting_time": opt_wait,
                "qmix_waiting_time": qmix_wait,
                "sim_mean_speed": sim["mean_speed"],
                "optimized_offset_mean_speed": opt["mean_speed"],
                "qmix_mean_speed": qmix["mean_speed"],
                "sim_mean_queue": sim["mean_total_queue"],
                "optimized_offset_mean_queue": opt["mean_total_queue"],
                "qmix_mean_queue": qmix["mean_total_queue"],
                "optimized_offset_coordination_gain_percent": cg_offset,
                "qmix_coordination_gain_percent": cg_qmix,
                "qmix_gap_vs_optimized_offset_percent": gap,
                "coordination_regime": regime,
                "sim_buffered_ratio": sim["buffered_ratio"],
                "optimized_offset_buffered_ratio": opt["buffered_ratio"],
                "qmix_buffered_ratio": qmix["buffered_ratio"],
            }
        )

    return pd.DataFrame(rows).round(3)


def build_summary(seed_metrics_df):
    group_cols = [
        "validation_block",
        "case_type",
        "scenario",
    ]

    value_cols = [
        "sim_waiting_time",
        "optimized_offset_waiting_time",
        "qmix_waiting_time",
        "sim_mean_speed",
        "optimized_offset_mean_speed",
        "qmix_mean_speed",
        "sim_mean_queue",
        "optimized_offset_mean_queue",
        "qmix_mean_queue",
        "optimized_offset_coordination_gain_percent",
        "qmix_coordination_gain_percent",
        "qmix_gap_vs_optimized_offset_percent",
        "sim_buffered_ratio",
        "optimized_offset_buffered_ratio",
        "qmix_buffered_ratio",
    ]

    summary = seed_metrics_df.groupby(group_cols)[value_cols].agg(["mean", "std"])
    summary.columns = [f"{col}_{stat}" for col, stat in summary.columns]
    summary = summary.reset_index().round(3)

    return summary


def build_regime_stability(seed_metrics_df):
    rows = []

    group_cols = [
        "validation_block",
        "case_type",
        "scenario",
    ]

    valid_regime_labels = [
        "Effective coordination zone",
        "Marginal coordination zone",
        "Outside coordination horizon",
    ]

    for keys, sub in seed_metrics_df.groupby(group_cols):
        validation_block, case_type, scenario = keys

        regimes = sub["coordination_regime"].tolist()

        available_regimes = [
            r for r in regimes
            if r in valid_regime_labels
        ]

        effective_count = available_regimes.count("Effective coordination zone")
        marginal_count = available_regimes.count("Marginal coordination zone")
        outside_count = available_regimes.count("Outside coordination horizon")
        not_available_count = len(regimes) - len(available_regimes)

        if len(available_regimes) == 0:
            dominant_regime = "Not available"
            regime_stability_percent = 0.0
        else:
            counts = {
                "Effective coordination zone": effective_count,
                "Marginal coordination zone": marginal_count,
                "Outside coordination horizon": outside_count,
            }

            dominant_regime = max(counts, key=counts.get)
            regime_stability_percent = (
                counts[dominant_regime] / len(regimes) * 100
            )

        rows.append(
            {
                "validation_block": validation_block,
                "case_type": case_type,
                "scenario": scenario,
                "seed_regimes": "; ".join(regimes),
                "effective_count": effective_count,
                "marginal_count": marginal_count,
                "outside_count": outside_count,
                "not_available_count": not_available_count,
                "dominant_regime": dominant_regime,
                "regime_stability_percent": regime_stability_percent,
            }
        )

    return pd.DataFrame(rows).round(3)


# =========================================================
# Main
# =========================================================

def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(TABLE_DIR, exist_ok=True)

    all_controller_rows = []

    for seed in SEEDS:
        print("\n" + "=" * 80)
        print(f"Running multi-seed horizon validation | seed={seed}")
        print("=" * 80)

        for case in TWO_INTERSECTION_CASES:
            all_controller_rows.extend(
                run_two_intersection_case(case, seed)
            )

        for case in THREE_INTERSECTION_CASES:
            all_controller_rows.extend(
                run_three_intersection_case(case, seed)
            )

    controller_df = pd.DataFrame(all_controller_rows).round(3)
    controller_df.to_csv(OUT_CONTROLLER_RAW, index=False)

    seed_metrics_df = build_seed_metrics(controller_df)
    seed_metrics_df.to_csv(OUT_SEED_METRICS, index=False)

    summary_df = build_summary(seed_metrics_df)
    summary_df.to_csv(OUT_SUMMARY, index=False)

    regime_df = build_regime_stability(seed_metrics_df)
    regime_df.to_csv(OUT_REGIME, index=False)

    print("\n=== Per-controller raw summary ===")
    print(controller_df.to_string(index=False))

    print("\n=== Seed-level DCHF metrics ===")
    print(seed_metrics_df.to_string(index=False))

    print("\n=== Multi-seed horizon validation summary ===")
    print(summary_df.to_string(index=False))

    print("\n=== Regime stability ===")
    print(regime_df.to_string(index=False))

    print("\nSaved outputs:")
    print(f"- {OUT_CONTROLLER_RAW}")
    print(f"- {OUT_SEED_METRICS}")
    print(f"- {OUT_SUMMARY}")
    print(f"- {OUT_REGIME}")


if __name__ == "__main__":
    main()
