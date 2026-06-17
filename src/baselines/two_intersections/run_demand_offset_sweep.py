import os
import pandas as pd
import traci


SUMO_BINARY = "sumo"

DEMAND_SCENARIOS = {
    "low": {
        "folder": "demand_low",
        "expected_total_vehicles": 1396,
        "multiplier": 0.50,
    },
    "medium": {
        "folder": "demand_medium",
        "expected_total_vehicles": 2800,
        "multiplier": 1.00,
    },
    "high": {
        "folder": "demand_high",
        "expected_total_vehicles": 4204,
        "multiplier": 1.50,
    },
    "saturation": {
        "folder": "demand_saturation",
        "expected_total_vehicles": 5600,
        "multiplier": 2.00,
    },
    "oversaturation": {
        "folder": "demand_oversaturation",
        "expected_total_vehicles": 6996,
        "multiplier": 2.50,
    },
}

OFFSETS = list(range(0, 91, 5))

SIMULATION_STEPS = 3600

GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

OUTPUT_RAW = "results/raw/demand_offset_sweep_raw.csv"
OUTPUT_SUMMARY = "results/tables/demand_offset_sweep_summary.csv"
OUTPUT_BEST = "results/tables/demand_offset_best_summary.csv"


def phase_from_cycle_time(t):
    t = t % CYCLE_LENGTH

    if t < GREEN_DURATION:
        return SIDE_GREEN

    if t < GREEN_DURATION + YELLOW_DURATION:
        return SIDE_YELLOW

    if t < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return MAIN_GREEN

    return MAIN_YELLOW


def get_vehicle_count():
    return len(traci.vehicle.getIDList())


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()

    if not vehicles:
        return 0.0

    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def get_total_queue():
    total_queue = 0

    for lane_id in traci.lane.getIDList():
        if not lane_id.startswith(":"):
            total_queue += traci.lane.getLastStepHaltingNumber(lane_id)

    return total_queue


def run_demand_offset(demand_name, scenario_info, offset):
    sumo_config = (
        "sumo_scenarios/two_intersections/"
        f"demand_sensitivity/{scenario_info['folder']}/corridor_turning.sumocfg"
    )

    expected_total = scenario_info["expected_total_vehicles"]

    sumo_cmd = [
        SUMO_BINARY,
        "-c",
        sumo_config,
        "--seed",
        "0",
    ]

    traci.start(sumo_cmd)

    rows = []

    total_departed = 0
    total_arrived = 0

    for step in range(SIMULATION_STEPS):
        j1_phase = phase_from_cycle_time(step)
        j2_phase = phase_from_cycle_time(step - offset)

        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhase("J2", j2_phase)

        traci.simulationStep()

        total_departed += traci.simulation.getDepartedNumber()
        total_arrived += traci.simulation.getArrivedNumber()

        rows.append(
            {
                "demand_scenario": demand_name,
                "demand_multiplier": scenario_info["multiplier"],
                "offset": offset,
                "step": step + 1,
                "vehicle_count": get_vehicle_count(),
                "total_waiting_time": get_total_waiting_time(),
                "mean_speed": get_mean_speed(),
                "total_queue": get_total_queue(),
                "departed_cumulative": total_departed,
                "arrived_cumulative": total_arrived,
            }
        )

    final_active = get_vehicle_count()
    final_buffered = expected_total - total_departed

    traci.close()

    df = pd.DataFrame(rows)

    summary = {
        "demand_scenario": demand_name,
        "demand_multiplier": scenario_info["multiplier"],
        "offset": offset,
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "total_departed": total_departed,
        "total_arrived": total_arrived,
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": final_buffered / expected_total if expected_total > 0 else 0.0,
    }

    return rows, summary


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    all_raw_rows = []
    all_summary_rows = []

    for demand_name, scenario_info in DEMAND_SCENARIOS.items():
        print("\n" + "=" * 70)
        print(f"Running demand scenario = {demand_name}")
        print(f"Demand multiplier = {scenario_info['multiplier']}")
        print("=" * 70)

        for offset in OFFSETS:
            print(f"Running demand {demand_name} | offset {offset} s")

            raw_rows, summary = run_demand_offset(
                demand_name=demand_name,
                scenario_info=scenario_info,
                offset=offset,
            )

            all_raw_rows.extend(raw_rows)
            all_summary_rows.append(summary)

            print(
                f"demand={demand_name} | offset={offset} | "
                f"waiting={summary['mean_total_waiting_time']:.3f} | "
                f"speed={summary['mean_speed']:.3f} | "
                f"queue={summary['mean_total_queue']:.3f} | "
                f"departed={summary['total_departed']} | "
                f"buffered={summary['final_buffered']}"
            )

    raw_df = pd.DataFrame(all_raw_rows).round(3)
    summary_df = pd.DataFrame(all_summary_rows).round(3)

    raw_df.to_csv(OUTPUT_RAW, index=False)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    best_rows = []

    for demand_name in DEMAND_SCENARIOS.keys():
        demand_df = summary_df[summary_df["demand_scenario"] == demand_name].copy()

        best_waiting = demand_df.loc[
            demand_df["mean_total_waiting_time"].idxmin()
        ]

        best_speed = demand_df.loc[
            demand_df["mean_speed"].idxmax()
        ]

        best_queue = demand_df.loc[
            demand_df["mean_total_queue"].idxmin()
        ]

        best_rows.append(
            {
                "demand_scenario": demand_name,
                "demand_multiplier": best_waiting["demand_multiplier"],
                "best_waiting_offset": best_waiting["offset"],
                "best_waiting_time": best_waiting["mean_total_waiting_time"],
                "best_speed_offset": best_speed["offset"],
                "best_speed": best_speed["mean_speed"],
                "best_queue_offset": best_queue["offset"],
                "best_queue": best_queue["mean_total_queue"],
                "departed_at_best_waiting": best_waiting["total_departed"],
                "arrived_at_best_waiting": best_waiting["total_arrived"],
                "active_at_best_waiting": best_waiting["final_active"],
                "buffered_at_best_waiting": best_waiting["final_buffered"],
                "buffered_ratio_at_best_waiting": best_waiting["buffered_ratio"],
                "max_queue_at_best_waiting": best_waiting["max_total_queue"],
            }
        )

    best_df = pd.DataFrame(best_rows).round(3)
    best_df.to_csv(OUTPUT_BEST, index=False)

    print("\n=== Demand Offset Sweep Summary ===")
    print(summary_df.to_string(index=False))

    print("\n=== Best Offset by Demand Scenario ===")
    print(best_df.to_string(index=False))

    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")
    print(f"Best-by-demand summary saved to: {OUTPUT_BEST}")


if __name__ == "__main__":
    main()