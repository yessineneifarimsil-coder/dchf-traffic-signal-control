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

TLS_IDS = ["J1", "J2", "J3"]

OUTPUT_RAW = "results/raw/fixed_time_three_intersections.csv"
OUTPUT_SUMMARY = "results/tables/fixed_time_three_intersections_summary.csv"


def phase_from_cycle_time(t):
    t = t % CYCLE_LENGTH

    if t < GREEN_DURATION:
        return SIDE_GREEN

    if t < GREEN_DURATION + YELLOW_DURATION:
        return SIDE_YELLOW

    if t < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return MAIN_GREEN

    return MAIN_YELLOW


def phase_group_name(phase):
    if phase == SIDE_GREEN:
        return "side_green"
    if phase == SIDE_YELLOW:
        return "side_yellow"
    if phase == MAIN_GREEN:
        return "main_green"
    if phase == MAIN_YELLOW:
        return "main_yellow"
    return "unknown"


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


def collect_row(step, phase, departed_cumulative, arrived_cumulative):
    return {
        "step": step,
        "phase": phase,
        "phase_group": phase_group_name(phase),
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
    }


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

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

    print("Traffic lights:", TLS_IDS)

    for step in range(SIMULATION_STEPS):
        phase = phase_from_cycle_time(step)

        for tl_id in TLS_IDS:
            traci.trafficlight.setPhase(tl_id, phase)

        traci.simulationStep()

        departed_cumulative += traci.simulation.getDepartedNumber()
        arrived_cumulative += traci.simulation.getArrivedNumber()

        rows.append(
            collect_row(
                step=step + 1,
                phase=phase,
                departed_cumulative=departed_cumulative,
                arrived_cumulative=arrived_cumulative,
            )
        )

        if step % 300 == 0:
            print(
                f"Step {step} | Phase group: {phase_group_name(phase)} | "
                f"Vehicles: {get_vehicle_count()} | "
                f"Waiting: {get_total_waiting_time():.2f} | "
                f"Speed: {get_mean_speed():.2f} | "
                f"Queue: {get_total_queue()}"
            )

    final_active = get_vehicle_count()
    final_buffered = EXPECTED_TOTAL_VEHICLES - departed_cumulative

    traci.close()

    df = pd.DataFrame(rows).round(3)
    df.to_csv(OUTPUT_RAW, index=False)

    summary = {
        "controller": "Simultaneous Fixed-Time 3 Intersections",
        "simulation_steps": SIMULATION_STEPS,
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "total_departed": departed_cumulative,
        "total_arrived": arrived_cumulative,
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": final_buffered / EXPECTED_TOTAL_VEHICLES,
    }

    summary_df = pd.DataFrame([summary]).round(3)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    print("\nFixed-time 3-intersection simulation finished.")
    print(summary_df.to_string(index=False))
    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()