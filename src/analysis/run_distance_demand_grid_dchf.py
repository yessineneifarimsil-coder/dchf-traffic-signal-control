import os
import sys
import numpy as np
import pandas as pd

ROOT = os.getcwd()

sys.path.append(os.path.join(ROOT, "src", "baselines", "two_intersections"))
sys.path.append(os.path.join(ROOT, "src", "qmix"))

from run_distance_offset_sweep import run_distance_offset
from evaluate_qmix_distance_sensitivity import evaluate_qmix_for_distance


DISTANCES = [100, 200, 300, 500, 750, 1000]

DEMAND_LEVELS = {
    "low": 0.5,
    "medium": 1.0,
    "high": 1.5,
    "saturation": 2.0,
    "oversaturation": 2.5,
}

OFFSETS = list(range(0, 91, 5))

BASE_EXPECTED_VEHICLES = 2800

GRID_DIR = "sumo_scenarios/two_intersections/distance_demand_grid"

RAW_DIR = "results/raw"
TABLE_DIR = "results/tables"

OUT_OFFSET_SWEEP = f"{TABLE_DIR}/distance_demand_grid_offset_sweep_summary.csv"
OUT_CONTROLLER = f"{TABLE_DIR}/distance_demand_grid_controller_summary.csv"
OUT_DCHF = f"{TABLE_DIR}/distance_demand_grid_dchf_summary.csv"


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
    if gap <= 5:
        return "Effective coordination zone"
    if gap <= 10:
        return "Marginal coordination zone"
    return "Outside coordination horizon"


def classify_capacity(buffered_ratio):
    if pd.isna(buffered_ratio):
        return "Not available"
    if buffered_ratio < 0.01:
        return "Unconstrained"
    if buffered_ratio < 0.10:
        return "Mild insertion pressure"
    if buffered_ratio < 0.25:
        return "Capacity-limited"
    return "Oversaturated"


def safe_get(summary, key, default=np.nan):
    aliases = {
        "mean_total_waiting_time": ["mean_total_waiting_time", "qmix_waiting_time", "qmix_mean_total_waiting_time"],
        "mean_speed": ["mean_speed", "qmix_speed", "qmix_mean_speed"],
        "mean_total_queue": ["mean_total_queue", "qmix_queue", "qmix_mean_total_queue"],
        "max_total_queue": ["max_total_queue", "qmix_max_queue", "qmix_max_total_queue"],
        "total_departed": ["total_departed", "qmix_total_departed"],
        "total_arrived": ["total_arrived", "qmix_total_arrived"],
        "final_active": ["final_active", "qmix_final_active"],
    }

    for k in aliases.get(key, [key]):
        if k in summary:
            return summary[k]

    return default


def standardize_summary(
    distance,
    demand_name,
    demand_multiplier,
    scenario_label,
    controller,
    summary,
    expected_total_vehicles,
    offset=np.nan,
):
    total_departed = safe_get(summary, "total_departed")
    total_arrived = safe_get(summary, "total_arrived")
    final_active = safe_get(summary, "final_active")

    if pd.isna(total_departed):
        final_buffered = np.nan
        buffered_ratio = np.nan
    else:
        final_buffered = max(expected_total_vehicles - total_departed, 0)
        buffered_ratio = final_buffered / expected_total_vehicles

    return {
        "distance": distance,
        "demand_name": demand_name,
        "demand_multiplier": demand_multiplier,
        "scenario_label": scenario_label,
        "controller": controller,
        "offset": offset,
        "expected_total_vehicles": expected_total_vehicles,
        "mean_total_waiting_time": safe_get(summary, "mean_total_waiting_time"),
        "mean_speed": safe_get(summary, "mean_speed"),
        "mean_total_queue": safe_get(summary, "mean_total_queue"),
        "max_total_queue": safe_get(summary, "max_total_queue"),
        "total_departed": total_departed,
        "total_arrived": total_arrived,
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": buffered_ratio,
        "capacity_regime": classify_capacity(buffered_ratio),
    }


def run_one_grid_scenario(distance, demand_name, demand_multiplier):
    scenario_label = f"d{distance}_{demand_name}"

    sumo_config = os.path.join(
        GRID_DIR,
        scenario_label,
        "corridor_turning.sumocfg",
    )

    if not os.path.exists(sumo_config):
        raise FileNotFoundError(f"Missing SUMO config: {sumo_config}")

    expected_total_vehicles = int(BASE_EXPECTED_VEHICLES * demand_multiplier)

    print("\n" + "=" * 80)
    print(f"Running grid scenario: {scenario_label}")
    print(f"distance={distance} | demand={demand_name} | multiplier={demand_multiplier}")
    print(f"expected_total_vehicles={expected_total_vehicles}")
    print("=" * 80)

    offset_rows = []

    for offset in OFFSETS:
        print(f"Offset sweep | {scenario_label} | offset={offset}")

        _, summary = run_distance_offset(
            distance=distance,
            offset=offset,
            sumo_seed=0,
            sumo_config_override=sumo_config,
            scenario_label=scenario_label,
        )

        row = standardize_summary(
            distance=distance,
            demand_name=demand_name,
            demand_multiplier=demand_multiplier,
            scenario_label=scenario_label,
            controller="Fixed offset",
            summary=summary,
            expected_total_vehicles=expected_total_vehicles,
            offset=offset,
        )

        offset_rows.append(row)

    offset_df = pd.DataFrame(offset_rows)

    sim_row = offset_df[offset_df["offset"] == 0].iloc[0]
    best_offset_row = offset_df.loc[offset_df["mean_total_waiting_time"].idxmin()]

    print(
        f"Best offset for {scenario_label}: "
        f"offset={best_offset_row['offset']} | "
        f"waiting={best_offset_row['mean_total_waiting_time']:.3f}"
    )

    print(f"Evaluating QMIX | {scenario_label}")

    _, qmix_summary = evaluate_qmix_for_distance(
        distance=distance,
        sumo_seed=0,
        sumo_config_override=sumo_config,
        scenario_label=scenario_label,
    )

    qmix_row = standardize_summary(
        distance=distance,
        demand_name=demand_name,
        demand_multiplier=demand_multiplier,
        scenario_label=scenario_label,
        controller="QMIX V2",
        summary=qmix_summary,
        expected_total_vehicles=expected_total_vehicles,
        offset=np.nan,
    )

    controller_rows = [
        sim_row.to_dict(),
        best_offset_row.to_dict(),
        qmix_row,
    ]

    sim_wait = sim_row["mean_total_waiting_time"]
    best_wait = best_offset_row["mean_total_waiting_time"]
    qmix_wait = qmix_row["mean_total_waiting_time"]

    cg_offset = coordination_gain(sim_wait, best_wait)
    cg_qmix = coordination_gain(sim_wait, qmix_wait)
    gap = qmix_gap(qmix_wait, best_wait)

    dchf_row = {
        "distance": distance,
        "demand_name": demand_name,
        "demand_multiplier": demand_multiplier,
        "scenario_label": scenario_label,
        "sim_waiting_time": sim_wait,
        "best_offset": best_offset_row["offset"],
        "optimized_offset_waiting_time": best_wait,
        "qmix_waiting_time": qmix_wait,
        "optimized_offset_coordination_gain_percent": cg_offset,
        "qmix_coordination_gain_percent": cg_qmix,
        "qmix_gap_vs_optimized_offset_percent": gap,
        "coordination_regime": classify_gap(gap),
        "sim_buffered_ratio": sim_row["buffered_ratio"],
        "optimized_offset_buffered_ratio": best_offset_row["buffered_ratio"],
        "qmix_buffered_ratio": qmix_row["buffered_ratio"],
        "qmix_capacity_regime": qmix_row["capacity_regime"],
    }

    return offset_rows, controller_rows, dchf_row


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(TABLE_DIR, exist_ok=True)

    all_offset_rows = []
    all_controller_rows = []
    all_dchf_rows = []

    for distance in DISTANCES:
        for demand_name, demand_multiplier in DEMAND_LEVELS.items():
            offset_rows, controller_rows, dchf_row = run_one_grid_scenario(
                distance=distance,
                demand_name=demand_name,
                demand_multiplier=demand_multiplier,
            )

            all_offset_rows.extend(offset_rows)
            all_controller_rows.extend(controller_rows)
            all_dchf_rows.append(dchf_row)

            pd.DataFrame(all_offset_rows).round(3).to_csv(OUT_OFFSET_SWEEP, index=False)
            pd.DataFrame(all_controller_rows).round(3).to_csv(OUT_CONTROLLER, index=False)
            pd.DataFrame(all_dchf_rows).round(3).to_csv(OUT_DCHF, index=False)

            print(f"Saved progress after {dchf_row['scenario_label']}")

    offset_df = pd.DataFrame(all_offset_rows).round(3)
    controller_df = pd.DataFrame(all_controller_rows).round(3)
    dchf_df = pd.DataFrame(all_dchf_rows).round(3)

    offset_df.to_csv(OUT_OFFSET_SWEEP, index=False)
    controller_df.to_csv(OUT_CONTROLLER, index=False)
    dchf_df.to_csv(OUT_DCHF, index=False)

    print("\n=== Distance × Demand DCHF Summary ===")
    print(dchf_df.to_string(index=False))

    print("\nSaved outputs:")
    print(f"- {OUT_OFFSET_SWEEP}")
    print(f"- {OUT_CONTROLLER}")
    print(f"- {OUT_DCHF}")


if __name__ == "__main__":
    main()