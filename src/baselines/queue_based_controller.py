import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg"

OUTPUT_CSV = "results/raw/queue_based_2x2.csv"

SIMULATION_STEPS = 3600

GREEN_DURATION = 30
YELLOW_DURATION = 3
ALL_RED_DURATION = 2


def get_vehicle_count():
    return len(traci.vehicle.getIDList())


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if not vehicles:
        return 0.0
    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def get_halting_vehicles_on_lanes(lanes):
    """
    A halting vehicle is a vehicle with very low speed.
    This is a practical queue indicator.
    """
    total = 0
    for lane_id in lanes:
        total += traci.lane.getLastStepHaltingNumber(lane_id)
    return total


def collect_step_data(tl_id, step, phase):
    return {
        "step": step,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "phase": phase,
        "state": traci.trafficlight.getRedYellowGreenState(tl_id)
    }


def run_phase(tl_id, phase, duration, rows, step):
    traci.trafficlight.setPhase(tl_id, phase)
    traci.trafficlight.setPhaseDuration(tl_id, duration)

    for _ in range(duration):
        if step >= SIMULATION_STEPS:
            break

        traci.simulationStep()
        rows.append(collect_step_data(tl_id, step, phase))

        if step % 300 == 0:
            print(
                f"Step {step} | Vehicles: {get_vehicle_count()} | "
                f"Waiting: {get_total_waiting_time():.2f} | "
                f"Speed: {get_mean_speed():.2f} | Phase: {phase}"
            )

        step += 1

    return step


def choose_phase_by_queue(direction_1_lanes, direction_2_lanes):
    queue_1 = get_halting_vehicles_on_lanes(direction_1_lanes)
    queue_2 = get_halting_vehicles_on_lanes(direction_2_lanes)

    print(f"Queue direction 1: {queue_1} | Queue direction 2: {queue_2}")

    if queue_1 >= queue_2:
        return 0
    else:
        return 3


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    print("Traffic lights:", traffic_lights)

    if not traffic_lights:
        raise RuntimeError("No traffic light found.")

    tl_id = traffic_lights[0]
    print("Controlled traffic light:", tl_id)

    controlled_lanes = traci.trafficlight.getControlledLanes(tl_id)
    unique_lanes = list(dict.fromkeys(controlled_lanes))

    print("Controlled lanes:")
    for lane in unique_lanes:
        print("-", lane)

    # Simple split:
    # First half of lanes = direction 1
    # Second half of lanes = direction 2
    half = len(unique_lanes) // 2
    direction_1_lanes = unique_lanes[:half]
    direction_2_lanes = unique_lanes[half:]

    print("Direction 1 lanes:", direction_1_lanes)
    print("Direction 2 lanes:", direction_2_lanes)

    rows = []
    step = 0
    previous_green = None

    while step < SIMULATION_STEPS:
        selected_green = choose_phase_by_queue(direction_1_lanes, direction_2_lanes)

        if previous_green is None:
            print(f"Step {step}: initial green phase {selected_green}")
            step = run_phase(tl_id, selected_green, GREEN_DURATION, rows, step)
            previous_green = selected_green
            continue

        if selected_green == previous_green:
            print(f"Step {step}: keeping green phase {selected_green}")
            step = run_phase(tl_id, selected_green, GREEN_DURATION, rows, step)
        else:
            if previous_green == 0 and selected_green == 3:
                print(f"Step {step}: transition 0 → 3")
                step = run_phase(tl_id, 1, YELLOW_DURATION, rows, step)
                step = run_phase(tl_id, 2, ALL_RED_DURATION, rows, step)
                step = run_phase(tl_id, 3, GREEN_DURATION, rows, step)

            elif previous_green == 3 and selected_green == 0:
                print(f"Step {step}: transition 3 → 0")
                step = run_phase(tl_id, 4, YELLOW_DURATION, rows, step)
                step = run_phase(tl_id, 5, ALL_RED_DURATION, rows, step)
                step = run_phase(tl_id, 0, GREEN_DURATION, rows, step)

            previous_green = selected_green

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("Queue-based adaptive simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()