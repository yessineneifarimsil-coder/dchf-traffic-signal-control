import os
import sys
import numpy as np
import pandas as pd

ROOT = os.getcwd()

sys.path.append(os.path.join(ROOT, "src", "qmix"))

from evaluate_qmix_distance_sensitivity import evaluate_qmix_for_distance


DISTANCES = [100, 200, 300, 500, 750, 1000]

DEMAND_LEVELS = {
    "low": 0.5,
    "medium": 1.0,
    "high": 1.5,
    "saturation": 2.0,
    "oversaturation": 2.5,
}

BASE_EXPECTED_VEHICLES = 2800

GRID_DIR = "sumo_scenarios/two_intersections/distance_demand_grid"
TABLE_DIR = "results/tables"

INPUT_DCHF = f"{TABLE_DIR}/distance_demand_grid_dchf_summary.csv"
OUTPUT_QMIX_PATCH = f"{TABLE_DIR}/distance_demand_grid_qmix_buffer_patch.csv"
OUTPUT_DCHF_UPDATED = f"{TABLE_DIR}/distance_demand_grid_dchf_summary_updated.csv"


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


def main():
    patch_rows = []

    for distance in DISTANCES:
        for demand_name, multiplier in DEMAND_LEVELS.items():
            scenario_label = f"d{distance}_{demand_name}"
            sumo_config = os.path.join(
                GRID_DIR,
                scenario_label,
                "corridor_turning.sumocfg",
            )

            expected_total_vehicles = int(BASE_EXPECTED_VEHICLES * multiplier)

            print("\n" + "=" * 70)
            print(f"Running QMIX buffer patch: {scenario_label}")
            print("=" * 70)

            _, summary = evaluate_qmix_for_distance(
                distance=distance,
                sumo_seed=0,
                sumo_config_override=sumo_config,
                scenario_label=scenario_label,
            )

            total_departed = summary.get("total_departed", np.nan)
            total_arrived = summary.get("total_arrived", np.nan)
            final_active = summary.get("final_active", np.nan)

            if pd.isna(total_departed):
                final_buffered = np.nan
                buffered_ratio = np.nan
            else:
                final_buffered = max(expected_total_vehicles - total_departed, 0)
                buffered_ratio = final_buffered / expected_total_vehicles

            patch_rows.append(
                {
                    "scenario_label": scenario_label,
                    "distance": distance,
                    "demand_name": demand_name,
                    "demand_multiplier": multiplier,
                    "expected_total_vehicles": expected_total_vehicles,
                    "qmix_total_departed": total_departed,
                    "qmix_total_arrived": total_arrived,
                    "qmix_final_active": final_active,
                    "qmix_final_buffered": final_buffered,
                    "qmix_buffered_ratio_new": buffered_ratio,
                    "qmix_capacity_regime_new": classify_capacity(buffered_ratio),
                }
            )

            pd.DataFrame(patch_rows).round(4).to_csv(OUTPUT_QMIX_PATCH, index=False)

    patch_df = pd.DataFrame(patch_rows).round(4)
    patch_df.to_csv(OUTPUT_QMIX_PATCH, index=False)

    dchf_df = pd.read_csv(INPUT_DCHF)

    merged = dchf_df.merge(
        patch_df[
            [
                "scenario_label",
                "qmix_buffered_ratio_new",
                "qmix_capacity_regime_new",
                "qmix_total_departed",
                "qmix_total_arrived",
                "qmix_final_active",
                "qmix_final_buffered",
            ]
        ],
        on="scenario_label",
        how="left",
    )

    merged["qmix_buffered_ratio"] = merged["qmix_buffered_ratio_new"]
    merged["qmix_capacity_regime"] = merged["qmix_capacity_regime_new"]

    merged = merged.drop(
        columns=["qmix_buffered_ratio_new", "qmix_capacity_regime_new"],
        errors="ignore",
    )

    merged.round(4).to_csv(OUTPUT_DCHF_UPDATED, index=False)

    print("\nPatch completed.")
    print(f"Saved: {OUTPUT_QMIX_PATCH}")
    print(f"Saved: {OUTPUT_DCHF_UPDATED}")


if __name__ == "__main__":
    main()