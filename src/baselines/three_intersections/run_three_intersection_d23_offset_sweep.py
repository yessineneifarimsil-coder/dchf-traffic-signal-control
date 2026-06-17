import os
import pandas as pd
import traci


SUMO_BINARY = "sumo"

D23_VALUES = [100, 200, 300, 500, 750, 1000]
OFFSETS = list(range(0, 91, 5))

SIMULATION_STEPS = 3600
EXPECTED_TOTAL_VEHICLES = 3400

GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

OUTPUT_SUMMARY = "results/tables/three_intersection_d23_offset_sweep_summary.csv"
OUTPUT_BEST = "results/tables/three_intersection_d23_offset_best_summary.csv"


def get_config_path(d23):
    return (
        "sumo_scenarios/three_intersections/"
        f"distance_sensitivity/d23_{d23}m/corridor_3x2_through.sumocfg"
    )


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


def run_offset_pattern(d23, offset_j2, offset_j3, sumo_seed=0):
    sumo_config = get_config_path(d23)

    sumo_cmd = [
        SUMO_BINARY,
        "-c",
        sumo_config,
        "--seed",
        str(sumo_seed),
        "--no-step-log",
        "true",
    ]

    traci.start(sumo_cmd)

    departed = 0
    arrived = 0

    vehicle_counts = []
    waiting_times = []
    speeds = []
    queues = []

    for step in range(SIMULATION_STEPS):
        phase_j1 = phase_from_cycle_time(step)
        phase_j2 = phase_from_cycle_time(step - offset_j2)
        phase_j3 = phase_from_cycle_time(step - offset_j3)

        traci.trafficlight.setPhase("J1", phase_j1)
        traci.trafficlight.setPhase("J2", phase_j2)
        traci.trafficlight.setPhase("J3", phase_j3)

        traci.simulationStep()

        departed += traci.simulation.getDepartedNumber()
        arrived += traci.simulation.getArrivedNumber()

        vehicle_counts.append(get_vehicle_count())
        waiting_times.append(get_total_waiting_time())
        speeds.append(get_mean_speed())
        queues.append(get_total_queue())

    final_active = get_vehicle_count()
    final_buffered = EXPECTED_TOTAL_VEHICLES - departed

    traci.close()

    summary = {
        "d23": d23,
        "seed": sumo_seed,
        "offset_j2": offset_j2,
        "offset_j3": offset_j3,
        "rows": SIMULATION_STEPS,
        "mean_vehicle_count": sum(vehicle_counts) / len(vehicle_counts),
        "max_vehicle_count": max(vehicle_counts),
        "mean_total_waiting_time": sum(waiting_times) / len(waiting_times),
        "max_total_waiting_time": max(waiting_times),
        "mean_speed": sum(speeds) / len(speeds),
        "min_mean_speed": min(speeds),
        "mean_total_queue": sum(queues) / len(queues),
        "max_total_queue": max(queues),
        "total_departed": departed,
        "total_arrived": arrived,
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": final_buffered / EXPECTED_TOTAL_VEHICLES,
    }

    return summary


def save_progress(summary_rows):
    summary_df = pd.DataFrame(summary_rows).round(3)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)


def build_best_summary(summary_df):
    best_rows = []

    for d23 in D23_VALUES:
        d23_df = summary_df[summary_df["d23"] == d23].copy()

        best_waiting = d23_df.loc[d23_df["mean_total_waiting_time"].idxmin()]
        best_speed = d23_df.loc[d23_df["mean_speed"].idxmax()]
        best_queue = d23_df.loc[d23_df["mean_total_queue"].idxmin()]

        best_rows.append(
            {
                "d23": d23,

                "best_waiting_offset_j2": best_waiting["offset_j2"],
                "best_waiting_offset_j3": best_waiting["offset_j3"],
                "best_waiting_time": best_waiting["mean_total_waiting_time"],
                "speed_at_best_waiting": best_waiting["mean_speed"],
                "queue_at_best_waiting": best_waiting["mean_total_queue"],
                "max_queue_at_best_waiting": best_waiting["max_total_queue"],
                "buffered_ratio_at_best_waiting": best_waiting["buffered_ratio"],

                "best_speed_offset_j2": best_speed["offset_j2"],
                "best_speed_offset_j3": best_speed["offset_j3"],
                "best_speed": best_speed["mean_speed"],
                "waiting_at_best_speed": best_speed["mean_total_waiting_time"],
                "queue_at_best_speed": best_speed["mean_total_queue"],

                "best_queue_offset_j2": best_queue["offset_j2"],
                "best_queue_offset_j3": best_queue["offset_j3"],
                "best_queue": best_queue["mean_total_queue"],
                "waiting_at_best_queue": best_queue["mean_total_waiting_time"],
                "speed_at_best_queue": best_queue["mean_speed"],

                "departed_at_best_waiting": best_waiting["total_departed"],
                "arrived_at_best_waiting": best_waiting["total_arrived"],
                "active_at_best_waiting": best_waiting["final_active"],
                "buffered_at_best_waiting": best_waiting["final_buffered"],
            }
        )

    best_df = pd.DataFrame(best_rows).round(3)
    best_df.to_csv(OUTPUT_BEST, index=False)

    return best_df


def main():
    os.makedirs("results/tables", exist_ok=True)

    summary_rows = []
    total_runs = len(D23_VALUES) * len(OFFSETS) * len(OFFSETS)
    run_id = 0

    for d23 in D23_VALUES:
        print("\n" + "=" * 80)
        print(f"Starting d23 distance scenario: {d23} m")
        print("=" * 80)

        for offset_j2 in OFFSETS:
            for offset_j3 in OFFSETS:
                run_id += 1

                print(
                    f"Run {run_id}/{total_runs} | "
                    f"d23={d23} m | J1=0 | J2={offset_j2} s | J3={offset_j3} s"
                )

                summary = run_offset_pattern(d23, offset_j2, offset_j3, sumo_seed=0)

                summary_rows.append(summary)

                print(
                    f"waiting={summary['mean_total_waiting_time']:.3f} | "
                    f"speed={summary['mean_speed']:.3f} | "
                    f"queue={summary['mean_total_queue']:.3f} | "
                    f"buffered={summary['final_buffered']}"
                )

                # Save after every run, so if the terminal closes, progress is not lost.
                save_progress(summary_rows)

    summary_df = pd.DataFrame(summary_rows).round(3)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    best_df = build_best_summary(summary_df)

    print("\n=== Three-Intersection d23 Offset Sweep: Best Summary ===")
    print(best_df.to_string(index=False))

    print(f"\nSummary saved to: {OUTPUT_SUMMARY}")
    print(f"Best summary saved to: {OUTPUT_BEST}")


if __name__ == "__main__":
    main()