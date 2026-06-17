import os
import pandas as pd
import traci


SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/three_intersections/corridor_3x2/corridor_3x2_through.sumocfg"

SIMULATION_STEPS = 3600
EXPECTED_TOTAL_VEHICLES = 3400

GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

OFFSETS = list(range(0, 91, 5))

OUTPUT_RAW = "results/raw/three_intersection_offset_sweep_raw.csv"
OUTPUT_SUMMARY = "results/tables/three_intersection_offset_sweep_summary.csv"
OUTPUT_BEST = "results/tables/three_intersection_offset_best_summary.csv"


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


def get_edge_queue(edge_id):
    total = 0

    for lane_id in traci.lane.getIDList():
        if lane_id.startswith(edge_id + "_"):
            total += traci.lane.getLastStepHaltingNumber(lane_id)

    return total


def run_offset_pattern(offset_j2, offset_j3):
    sumo_cmd = [
        SUMO_BINARY,
        "-c",
        SUMO_CONFIG,
        "--seed",
        "0",
    ]

    traci.start(sumo_cmd)

    rows = []

    departed_cumulative = 0
    arrived_cumulative = 0

    for step in range(SIMULATION_STEPS):
        phase_j1 = phase_from_cycle_time(step)
        phase_j2 = phase_from_cycle_time(step - offset_j2)
        phase_j3 = phase_from_cycle_time(step - offset_j3)

        traci.trafficlight.setPhase("J1", phase_j1)
        traci.trafficlight.setPhase("J2", phase_j2)
        traci.trafficlight.setPhase("J3", phase_j3)

        traci.simulationStep()

        departed_cumulative += traci.simulation.getDepartedNumber()
        arrived_cumulative += traci.simulation.getArrivedNumber()

        rows.append({
            "offset_j2": offset_j2,
            "offset_j3": offset_j3,
            "step": step + 1,
            "vehicle_count": get_vehicle_count(),
            "total_waiting_time": get_total_waiting_time(),
            "mean_speed": get_mean_speed(),
            "total_queue": get_total_queue(),
            "J1_phase": traci.trafficlight.getPhase("J1"),
            "J2_phase": traci.trafficlight.getPhase("J2"),
            "J3_phase": traci.trafficlight.getPhase("J3"),
            "E1_queue_J1_J2": get_edge_queue("E1"),
            "neg_E1_queue_J2_J1": get_edge_queue("-E1"),
            "E2_queue_J2_J3": get_edge_queue("E2"),
            "neg_E2_queue_J3_J2": get_edge_queue("-E2"),
            "departed_cumulative": departed_cumulative,
            "arrived_cumulative": arrived_cumulative,
        })

    final_active = get_vehicle_count()
    final_buffered = EXPECTED_TOTAL_VEHICLES - departed_cumulative

    traci.close()

    df = pd.DataFrame(rows)

    summary = {
        "offset_j2": offset_j2,
        "offset_j3": offset_j3,
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "mean_E1_queue_J1_J2": df["E1_queue_J1_J2"].mean(),
        "mean_neg_E1_queue_J2_J1": df["neg_E1_queue_J2_J1"].mean(),
        "mean_E2_queue_J2_J3": df["E2_queue_J2_J3"].mean(),
        "mean_neg_E2_queue_J3_J2": df["neg_E2_queue_J3_J2"].mean(),
        "total_departed": departed_cumulative,
        "total_arrived": arrived_cumulative,
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": final_buffered / EXPECTED_TOTAL_VEHICLES,
    }

    return rows, summary


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    all_raw_rows = []
    summary_rows = []

    total_runs = len(OFFSETS) * len(OFFSETS)
    run_id = 0

    for offset_j2 in OFFSETS:
        for offset_j3 in OFFSETS:
            run_id += 1

            print("\n" + "=" * 70)
            print(f"Run {run_id}/{total_runs}")
            print(f"Testing offset pattern: J1=0 s | J2={offset_j2} s | J3={offset_j3} s")
            print("=" * 70)

            rows, summary = run_offset_pattern(offset_j2, offset_j3)

            all_raw_rows.extend(rows)
            summary_rows.append(summary)

            print(
                f"offset_j2={offset_j2} | offset_j3={offset_j3} | "
                f"waiting={summary['mean_total_waiting_time']:.3f} | "
                f"speed={summary['mean_speed']:.3f} | "
                f"queue={summary['mean_total_queue']:.3f} | "
                f"departed={summary['total_departed']} | "
                f"buffered={summary['final_buffered']}"
            )

    raw_df = pd.DataFrame(all_raw_rows).round(3)
    summary_df = pd.DataFrame(summary_rows).round(3)

    raw_df.to_csv(OUTPUT_RAW, index=False)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    best_waiting = summary_df.loc[
        summary_df["mean_total_waiting_time"].idxmin()
    ]

    best_speed = summary_df.loc[
        summary_df["mean_speed"].idxmax()
    ]

    best_queue = summary_df.loc[
        summary_df["mean_total_queue"].idxmin()
    ]

    best_rows = [
        {
            "criterion": "minimum_waiting_time",
            "offset_j2": best_waiting["offset_j2"],
            "offset_j3": best_waiting["offset_j3"],
            "mean_total_waiting_time": best_waiting["mean_total_waiting_time"],
            "mean_speed": best_waiting["mean_speed"],
            "mean_total_queue": best_waiting["mean_total_queue"],
            "max_total_queue": best_waiting["max_total_queue"],
            "total_departed": best_waiting["total_departed"],
            "total_arrived": best_waiting["total_arrived"],
            "final_active": best_waiting["final_active"],
            "final_buffered": best_waiting["final_buffered"],
            "buffered_ratio": best_waiting["buffered_ratio"],
        },
        {
            "criterion": "maximum_mean_speed",
            "offset_j2": best_speed["offset_j2"],
            "offset_j3": best_speed["offset_j3"],
            "mean_total_waiting_time": best_speed["mean_total_waiting_time"],
            "mean_speed": best_speed["mean_speed"],
            "mean_total_queue": best_speed["mean_total_queue"],
            "max_total_queue": best_speed["max_total_queue"],
            "total_departed": best_speed["total_departed"],
            "total_arrived": best_speed["total_arrived"],
            "final_active": best_speed["final_active"],
            "final_buffered": best_speed["final_buffered"],
            "buffered_ratio": best_speed["buffered_ratio"],
        },
        {
            "criterion": "minimum_mean_queue",
            "offset_j2": best_queue["offset_j2"],
            "offset_j3": best_queue["offset_j3"],
            "mean_total_waiting_time": best_queue["mean_total_waiting_time"],
            "mean_speed": best_queue["mean_speed"],
            "mean_total_queue": best_queue["mean_total_queue"],
            "max_total_queue": best_queue["max_total_queue"],
            "total_departed": best_queue["total_departed"],
            "total_arrived": best_queue["total_arrived"],
            "final_active": best_queue["final_active"],
            "final_buffered": best_queue["final_buffered"],
            "buffered_ratio": best_queue["buffered_ratio"],
        },
    ]

    best_df = pd.DataFrame(best_rows).round(3)
    best_df.to_csv(OUTPUT_BEST, index=False)

    print("\n=== Three-Intersection Offset Sweep: Best Patterns ===")
    print(best_df.to_string(index=False))

    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")
    print(f"Best pattern summary saved to: {OUTPUT_BEST}")


if __name__ == "__main__":
    main()