import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg"

OUTPUT_CSV = "results/raw/queue_based_v2_2x2.csv"

SIMULATION_STEPS = 3600

GREEN_DURATION = 30
YELLOW_DURATION = 3
ALL_RED_DURATION = 2

# Correct phase-to-lane mapping obtained from inspect_phase_lanes_2x2.py
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


def collect_step_data(tl_id, step, phase, queue_0, queue_3):
    return {
        "step": step,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "phase": phase,
        "queue_phase_0": queue_0,
        "queue_phase_3": queue_3,
        "state": traci.trafficlight.getRedYellowGreenState(tl_id),
    }


def run_phase(tl_id, phase, duration, rows, step):
    traci.trafficlight.setPhase(tl_id, phase)
    traci.trafficlight.setPhaseDuration(tl_id, duration)

    for _ in range(duration):
        if step >= SIMULATION_STEPS:
            break

        traci.simulationStep()

        queue_0 = get_queue_on_lanes(PHASE_0_GREEN_LANES)
        queue_3 = get_queue_on_lanes(PHASE_3_GREEN_LANES)

        rows.append(collect_step_data(tl_id, step, phase, queue_0, queue_3))

        if step % 300 == 0:
            print(
                f"Step {step} | Vehicles: {get_vehicle_count()} | "
                f"Waiting: {get_total_waiting_time():.2f} | "
                f"Speed: {get_mean_speed():.2f} | "
                f"Q0: {queue_0} | Q3: {queue_3} | Phase: {phase}"
            )

        step += 1

    return step


def choose_green_phase():
    queue_0 = get_queue_on_lanes(PHASE_0_GREEN_LANES)
    queue_3 = get_queue_on_lanes(PHASE_3_GREEN_LANES)

    print(f"Queue phase 0: {queue_0} | Queue phase 3: {queue_3}")

    if queue_0 >= queue_3:
        return 0
    return 3


def transition_and_run(tl_id, previous_green, selected_green, rows, step):
    if previous_green == selected_green:
        print(f"Step {step}: keeping green phase {selected_green}")
        return run_phase(tl_id, selected_green, GREEN_DURATION, rows, step)

    if previous_green == 0 and selected_green == 3:
        print(f"Step {step}: transition 0 → 3")
        step = run_phase(tl_id, 1, YELLOW_DURATION, rows, step)
        step = run_phase(tl_id, 2, ALL_RED_DURATION, rows, step)
        step = run_phase(tl_id, 3, GREEN_DURATION, rows, step)
        return step

    if previous_green == 3 and selected_green == 0:
        print(f"Step {step}: transition 3 → 0")
        step = run_phase(tl_id, 4, YELLOW_DURATION, rows, step)
        step = run_phase(tl_id, 5, ALL_RED_DURATION, rows, step)
        step = run_phase(tl_id, 0, GREEN_DURATION, rows, step)
        return step

    raise ValueError(f"Unexpected transition: {previous_green} → {selected_green}")


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    if not traffic_lights:
        raise RuntimeError("No traffic light found.")

    tl_id = traffic_lights[0]
    print("Controlled traffic light:", tl_id)

    rows = []
    step = 0
    previous_green = None

    while step < SIMULATION_STEPS:
        selected_green = choose_green_phase()

        if previous_green is None:
            print(f"Step {step}: initial green phase {selected_green}")
            step = run_phase(tl_id, selected_green, GREEN_DURATION, rows, step)
            previous_green = selected_green
        else:
            step = transition_and_run(tl_id, previous_green, selected_green, rows, step)
            previous_green = selected_green

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("Corrected queue-based adaptive simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()