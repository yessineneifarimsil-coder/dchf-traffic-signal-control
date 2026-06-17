import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg"

OUTPUT_CSV = "results/raw/queue_based_v3_2x2.csv"

SIMULATION_STEPS = 3600

MIN_GREEN = 20
MAX_GREEN = 60
YELLOW_DURATION = 3
ALL_RED_DURATION = 2
SWITCH_THRESHOLD = 5

PHASE_0_GREEN_LANES = [
    "gneE0_0",
    "gneE0_1",
    "-gneE2_0",
    "-gneE2_1",
]

PHASE_3_GREEN_LANES = [
    "-gneE1_0",
    "-gneE1_1",
    "-gneE3_0",
    "-gneE3_1",
]


def get_vehicle_count():
    return len(traci.vehicle.getIDList())


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if not vehicles:
        return 0.0
    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def get_queue_on_lanes(lanes):
    return sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes)


def get_queues():
    queue_0 = get_queue_on_lanes(PHASE_0_GREEN_LANES)
    queue_3 = get_queue_on_lanes(PHASE_3_GREEN_LANES)
    return queue_0, queue_3


def collect_step_data(tl_id, step, phase, queue_0, queue_3, green_elapsed):
    return {
        "step": step,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "phase": phase,
        "queue_phase_0": queue_0,
        "queue_phase_3": queue_3,
        "green_elapsed": green_elapsed,
        "state": traci.trafficlight.getRedYellowGreenState(tl_id),
    }


def run_one_step(tl_id, step, phase, rows, green_elapsed):
    traci.simulationStep()

    queue_0, queue_3 = get_queues()

    rows.append(
        collect_step_data(
            tl_id=tl_id,
            step=step,
            phase=phase,
            queue_0=queue_0,
            queue_3=queue_3,
            green_elapsed=green_elapsed,
        )
    )

    if step % 300 == 0:
        print(
            f"Step {step} | Vehicles: {get_vehicle_count()} | "
            f"Waiting: {get_total_waiting_time():.2f} | "
            f"Speed: {get_mean_speed():.2f} | "
            f"Q0: {queue_0} | Q3: {queue_3} | "
            f"Phase: {phase} | Green elapsed: {green_elapsed}"
        )

    return step + 1


def run_transition(tl_id, previous_green, rows, step):
    if previous_green == 0:
        transition = [(1, YELLOW_DURATION), (2, ALL_RED_DURATION)]
        print(f"Step {step}: transition 0 → 3")
    elif previous_green == 3:
        transition = [(4, YELLOW_DURATION), (5, ALL_RED_DURATION)]
        print(f"Step {step}: transition 3 → 0")
    else:
        raise ValueError(f"Unexpected previous green phase: {previous_green}")

    for phase, duration in transition:
        traci.trafficlight.setPhase(tl_id, phase)
        traci.trafficlight.setPhaseDuration(tl_id, duration)

        for _ in range(duration):
            if step >= SIMULATION_STEPS:
                break
            step = run_one_step(tl_id, step, phase, rows, green_elapsed=0)

    return step


def should_switch(current_green, green_elapsed):
    queue_0, queue_3 = get_queues()

    if green_elapsed < MIN_GREEN:
        return False

    if green_elapsed >= MAX_GREEN:
        return True

    if current_green == 0:
        return queue_3 >= queue_0 + SWITCH_THRESHOLD

    if current_green == 3:
        return queue_0 >= queue_3 + SWITCH_THRESHOLD

    return False


def opposite_phase(current_green):
    if current_green == 0:
        return 3
    if current_green == 3:
        return 0
    raise ValueError(f"Unexpected green phase: {current_green}")


def choose_initial_green():
    queue_0, queue_3 = get_queues()
    if queue_0 >= queue_3:
        return 0
    return 3


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    if not traffic_lights:
        raise RuntimeError("No traffic light found.")

    tl_id = traffic_lights[0]
    print("Controlled traffic light:", tl_id)

    rows = []
    step = 0

    current_green = choose_initial_green()
    green_elapsed = 0

    traci.trafficlight.setPhase(tl_id, current_green)
    traci.trafficlight.setPhaseDuration(tl_id, MAX_GREEN)

    print(f"Step {step}: initial green phase {current_green}")

    while step < SIMULATION_STEPS:
        if should_switch(current_green, green_elapsed):
            next_green = opposite_phase(current_green)

            step = run_transition(tl_id, current_green, rows, step)

            current_green = next_green
            green_elapsed = 0

            traci.trafficlight.setPhase(tl_id, current_green)
            traci.trafficlight.setPhaseDuration(tl_id, MAX_GREEN)

            print(f"Step {step}: switched to green phase {current_green}")

        step = run_one_step(tl_id, step, current_green, rows, green_elapsed)
        green_elapsed += 1

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("Queue-based adaptive V3 simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()