import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.sumocfg"

OUTPUT_CSV = "results/raw/fixed_time_corridor_offset_20s_2x2.csv"

SIMULATION_STEPS = 3600

GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

OFFSET_J2 = 20

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3


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


def phase_from_cycle_time(t):
    """
    Cycle:
    0-41   : side green
    42-44  : side yellow
    45-86  : main green
    87-89  : main yellow
    """
    t = t % CYCLE_LENGTH

    if t < GREEN_DURATION:
        return SIDE_GREEN, "side_green"

    if t < GREEN_DURATION + YELLOW_DURATION:
        return SIDE_YELLOW, "side_yellow"

    if t < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return MAIN_GREEN, "main_green"

    return MAIN_YELLOW, "main_yellow"


def collect_step_data(step, j1_group, j2_group):
    return {
        "step": step,
        "offset_j2": OFFSET_J2,
        "J1_phase_group": j1_group,
        "J2_phase_group": j2_group,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "J1_phase": traci.trafficlight.getPhase("J1"),
        "J2_phase": traci.trafficlight.getPhase("J2"),
    }


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    print("Traffic lights:", traffic_lights)
    print(f"Using J2 offset: {OFFSET_J2} seconds")

    rows = []

    for step in range(SIMULATION_STEPS):
        j1_phase, j1_group = phase_from_cycle_time(step)
        j2_phase, j2_group = phase_from_cycle_time(step - OFFSET_J2)

        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhase("J2", j2_phase)

        traci.simulationStep()

        rows.append(collect_step_data(step, j1_group, j2_group))

        if step % 300 == 0:
            print(
                f"Step {step} | "
                f"J1: {j1_group} | J2: {j2_group} | "
                f"Vehicles: {get_vehicle_count()} | "
                f"Waiting: {get_total_waiting_time():.2f} | "
                f"Speed: {get_mean_speed():.2f} | "
                f"Queue: {get_total_queue()}"
            )

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nOffset fixed-time corridor simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()