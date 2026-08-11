import os
import pandas as pd
import traci


SUMO_BINARY = "sumo"

DISTANCES = [100, 200, 300, 500, 750, 1000]
OFFSETS = list(range(0, 91, 5))

SIMULATION_STEPS = 3600
EXPECTED_TOTAL_VEHICLES = 2800

GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

OUTPUT_RAW = "results/raw/distance_offset_sweep_raw.csv"
OUTPUT_SUMMARY = "results/tables/distance_offset_sweep_summary.csv"
OUTPUT_BEST = "results/tables/distance_offset_best_summary.csv"


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


def run_distance_offset(distance, offset, sumo_seed=0, sumo_config_override=None, scenario_label=None, extra_args=None):
    if sumo_config_override is None:
        sumo_config = (
            f"sumo_scenarios/two_intersections/"
            f"distance_{distance}m/corridor_turning.sumocfg"
        )
    else:
        sumo_config = sumo_config_override

    if not os.path.exists(sumo_config):
        raise FileNotFoundError(f"SUMO config not found: {sumo_config}")

    sumo_cmd = [
        SUMO_BINARY,
        "-c",
        sumo_config,
        "--seed",
        str(sumo_seed),
    ]

    if extra_args:
        sumo_cmd += list(extra_args)

    rows = []

    total_departed = 0
    total_arrived = 0

    try:
        traci.start(sumo_cmd)

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
                    "seed": sumo_seed,
                    "distance": distance,
                    "scenario_label": scenario_label,
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
        final_buffered = EXPECTED_TOTAL_VEHICLES - total_departed
        buffered_ratio = final_buffered / EXPECTED_TOTAL_VEHICLES

    finally:
        try:
            traci.close()
        except Exception:
            pass

    df = pd.DataFrame(rows)

    summary = {
        "seed": sumo_seed,
        "distance": distance,
        "scenario_label": scenario_label,
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
        "buffered_ratio": buffered_ratio,
    }

    return rows, summary


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    all_raw_rows = []
    all_summary_rows = []

    for distance in DISTANCES:
        print("\n" + "=" * 70)
        print(f"Running distance = {distance} m")
        print("=" * 70)

        for offset in OFFSETS:
            print(f"Running distance {distance} m | offset {offset} s")

            raw_rows, summary = run_distance_offset(
                distance=distance,
                offset=offset,
                sumo_seed=0,
            )

            all_raw_rows.extend(raw_rows)
            all_summary_rows.append(summary)

            print(
                f"distance={distance} | offset={offset} | "
                f"seed={summary['seed']} | "
                f"waiting={summary['mean_total_waiting_time']:.3f} | "
                f"speed={summary['mean_speed']:.3f} | "
                f"queue={summary['mean_total_queue']:.3f} | "
                f"departed={summary['total_departed']} | "
                f"buffered={summary['final_buffered']} | "
                f"buffered_ratio={summary['buffered_ratio']:.4f}"
            )

    raw_df = pd.DataFrame(all_raw_rows).round(3)
    summary_df = pd.DataFrame(all_summary_rows).round(3)

    raw_df.to_csv(OUTPUT_RAW, index=False)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    best_rows = []

    for distance in DISTANCES:
        distance_df = summary_df[summary_df["distance"] == distance].copy()

        best_waiting = distance_df.loc[
            distance_df["mean_total_waiting_time"].idxmin()
        ]

        best_speed = distance_df.loc[
            distance_df["mean_speed"].idxmax()
        ]

        best_queue = distance_df.loc[
            distance_df["mean_total_queue"].idxmin()
        ]

        best_rows.append(
            {
                "seed": 0,
                "distance": distance,
                "best_waiting_offset": best_waiting["offset"],
                "best_waiting_time": best_waiting["mean_total_waiting_time"],
                "waiting_at_best_speed_offset": best_speed["mean_total_waiting_time"],
                "best_speed_offset": best_speed["offset"],
                "best_speed": best_speed["mean_speed"],
                "best_queue_offset": best_queue["offset"],
                "best_queue": best_queue["mean_total_queue"],
                "departed_at_best_waiting": best_waiting["total_departed"],
                "buffered_at_best_waiting": best_waiting["final_buffered"],
                "buffered_ratio_at_best_waiting": best_waiting["buffered_ratio"],
                "max_queue_at_best_waiting": best_waiting["max_total_queue"],
            }
        )

    best_df = pd.DataFrame(best_rows).round(3)
    best_df.to_csv(OUTPUT_BEST, index=False)

    print("\n=== Distance Offset Sweep Summary ===")
    print(summary_df.to_string(index=False))

    print("\n=== Best Offset by Distance ===")
    print(best_df.to_string(index=False))

    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")
    print(f"Best-by-distance summary saved to: {OUTPUT_BEST}")


if __name__ == "__main__":
    main()