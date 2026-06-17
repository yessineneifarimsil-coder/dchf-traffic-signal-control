import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.sumocfg"

OUTPUT_CSV = "results/raw/fixed_time_corridor_2x2.csv"

SIMULATION_STEPS = 3600

GREEN_DURATION = 42
YELLOW_DURATION = 3

TRAFFIC_LIGHTS = ["J1", "J2"]

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


def collect_step_data(step, phase_group):
    return {
        "step": step,
        "phase_group": phase_group,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "J1_phase": traci.trafficlight.getPhase("J1"),
        "J2_phase": traci.trafficlight.getPhase("J2"),
    }


def set_both_tls_phase(phase, duration):
    for tl_id in TRAFFIC_LIGHTS:
        traci.trafficlight.setPhase(tl_id, phase)
        traci.trafficlight.setPhaseDuration(tl_id, duration)


def run_phase(phase, duration, phase_group, rows, step):
    set_both_tls_phase(phase, duration)

    for _ in range(duration):
        if step >= SIMULATION_STEPS:
            break

        traci.simulationStep()

        rows.append(collect_step_data(step, phase_group))

        if step % 300 == 0:
            print(
                f"Step {step} | Phase group: {phase_group} | "
                f"Vehicles: {get_vehicle_count()} | "
                f"Waiting: {get_total_waiting_time():.2f} | "
                f"Speed: {get_mean_speed():.2f} | "
                f"Queue: {get_total_queue()}"
            )

        step += 1

    return step


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    print("Traffic lights:", traffic_lights)

    rows = []
    step = 0

    while step < SIMULATION_STEPS:
        # Side-road green at both intersections
        step = run_phase(SIDE_GREEN, GREEN_DURATION, "side_green", rows, step)
        step = run_phase(SIDE_YELLOW, YELLOW_DURATION, "side_yellow", rows, step)

        # Main corridor green at both intersections
        step = run_phase(MAIN_GREEN, GREEN_DURATION, "main_green", rows, step)
        step = run_phase(MAIN_YELLOW, YELLOW_DURATION, "main_yellow", rows, step)

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nFixed-time corridor simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()