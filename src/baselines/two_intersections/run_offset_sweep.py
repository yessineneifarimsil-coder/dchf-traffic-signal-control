import csv
import pandas as pd
import traci


SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.sumocfg"

OUTPUT_RAW_CSV = "results/raw/offset_sweep_raw_0_90_2x2.csv"
OUTPUT_SUMMARY_CSV = "results/tables/offset_sweep_summary_0_90_2x2.csv"


SIMULATION_STEPS = 3600

GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

OFFSETS = list(range(0, 91, 5))

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3


def phase_from_cycle_time(t):
    t = t % CYCLE_LENGTH

    if t < GREEN_DURATION:
        return SIDE_GREEN, "side_green"

    if t < GREEN_DURATION + YELLOW_DURATION:
        return SIDE_YELLOW, "side_yellow"

    if t < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return MAIN_GREEN, "main_green"

    return MAIN_YELLOW, "main_yellow"


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


def run_one_offset(offset):
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    rows = []

    for step in range(SIMULATION_STEPS):
        j1_phase, j1_group = phase_from_cycle_time(step)
        j2_phase, j2_group = phase_from_cycle_time(step - offset)

        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhase("J2", j2_phase)

        traci.simulationStep()

        rows.append({
            "offset": offset,
            "step": step,
            "J1_phase_group": j1_group,
            "J2_phase_group": j2_group,
            "vehicle_count": get_vehicle_count(),
            "total_waiting_time": get_total_waiting_time(),
            "mean_speed": get_mean_speed(),
            "total_queue": get_total_queue(),
            "J1_phase": traci.trafficlight.getPhase("J1"),
            "J2_phase": traci.trafficlight.getPhase("J2"),
        })

    traci.close()
    return rows


def main():
    all_rows = []

    for offset in OFFSETS:
        print(f"\nRunning offset = {offset} seconds")
        rows = run_one_offset(offset)
        all_rows.extend(rows)

    raw_df = pd.DataFrame(all_rows)
    raw_df.to_csv(OUTPUT_RAW_CSV, index=False)

    summary_df = (
        raw_df
        .groupby("offset")[[
            "vehicle_count",
            "total_waiting_time",
            "mean_speed",
            "total_queue"
        ]]
        .agg(["mean", "max"])
        .round(3)
    )

    summary_df.columns = ["_".join(col) for col in summary_df.columns]
    summary_df = summary_df.reset_index()

    summary_df.to_csv(OUTPUT_SUMMARY_CSV, index=False)

    print("\n=== Offset Sweep Summary ===")
    print(summary_df.to_string(index=False))

    best_waiting = summary_df.loc[summary_df["total_waiting_time_mean"].idxmin()]
    best_speed = summary_df.loc[summary_df["mean_speed_mean"].idxmax()]
    best_queue = summary_df.loc[summary_df["total_queue_mean"].idxmin()]

    print("\nBest offset by mean waiting time:")
    print(best_waiting.to_string())

    print("\nBest offset by mean speed:")
    print(best_speed.to_string())

    print("\nBest offset by mean queue:")
    print(best_queue.to_string())

    print(f"\nRaw results saved to: {OUTPUT_RAW_CSV}")
    print(f"Summary saved to: {OUTPUT_SUMMARY_CSV}")


if __name__ == "__main__":
    main()