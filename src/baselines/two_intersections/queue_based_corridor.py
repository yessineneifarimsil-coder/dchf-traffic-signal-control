import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.sumocfg"

OUTPUT_CSV = "results/raw/queue_based_corridor_2x2.csv"

SIMULATION_STEPS = 3600

GREEN_DURATION = 42
YELLOW_DURATION = 3

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

# Phase-to-lane mapping from inspect_two_intersections.py
J1_SIDE_LANES = ["E4_0", "E4_1", "E5_0", "E5_1"]
J1_MAIN_LANES = ["-E1_0", "-E1_1", "E0_0", "E0_1"]

J2_SIDE_LANES = ["E7_0", "E7_1", "E6_0", "E6_1"]
J2_MAIN_LANES = ["E2_0", "E2_1", "E1_0", "E1_1"]


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


def get_queue(lanes):
    return sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes)


def choose_phase(side_lanes, main_lanes):
    side_queue = get_queue(side_lanes)
    main_queue = get_queue(main_lanes)

    if side_queue > main_queue:
        return SIDE_GREEN, "side_green", side_queue, main_queue

    return MAIN_GREEN, "main_green", side_queue, main_queue


def apply_transition(tl_id, previous_phase, selected_phase):
    """
    Apply yellow transition if switching between side green and main green.
    """
    if previous_phase == selected_phase:
        return

    if previous_phase == SIDE_GREEN and selected_phase == MAIN_GREEN:
        traci.trafficlight.setPhase(tl_id, SIDE_YELLOW)
        traci.trafficlight.setPhaseDuration(tl_id, YELLOW_DURATION)

    elif previous_phase == MAIN_GREEN and selected_phase == SIDE_GREEN:
        traci.trafficlight.setPhase(tl_id, MAIN_YELLOW)
        traci.trafficlight.setPhaseDuration(tl_id, YELLOW_DURATION)


def collect_step_data(step, j1_group, j2_group, j1_side_q, j1_main_q, j2_side_q, j2_main_q):
    return {
        "step": step,
        "J1_phase_group": j1_group,
        "J2_phase_group": j2_group,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "J1_phase": traci.trafficlight.getPhase("J1"),
        "J2_phase": traci.trafficlight.getPhase("J2"),
        "J1_side_queue": j1_side_q,
        "J1_main_queue": j1_main_q,
        "J2_side_queue": j2_side_q,
        "J2_main_queue": j2_main_q,
    }


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    print("Traffic lights:", traci.trafficlight.getIDList())

    rows = []
    step = 0

    previous_j1_phase = MAIN_GREEN
    previous_j2_phase = MAIN_GREEN

    while step < SIMULATION_STEPS:
        j1_phase, j1_group, j1_side_q, j1_main_q = choose_phase(J1_SIDE_LANES, J1_MAIN_LANES)
        j2_phase, j2_group, j2_side_q, j2_main_q = choose_phase(J2_SIDE_LANES, J2_MAIN_LANES)

        apply_transition("J1", previous_j1_phase, j1_phase)
        apply_transition("J2", previous_j2_phase, j2_phase)

        # Run yellow transition if needed
        if previous_j1_phase != j1_phase or previous_j2_phase != j2_phase:
            for _ in range(YELLOW_DURATION):
                if step >= SIMULATION_STEPS:
                    break

                traci.simulationStep()

                rows.append(
                    collect_step_data(
                        step,
                        "yellow_transition",
                        "yellow_transition",
                        j1_side_q,
                        j1_main_q,
                        j2_side_q,
                        j2_main_q,
                    )
                )

                step += 1

        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhaseDuration("J1", GREEN_DURATION)

        traci.trafficlight.setPhase("J2", j2_phase)
        traci.trafficlight.setPhaseDuration("J2", GREEN_DURATION)

        for _ in range(GREEN_DURATION):
            if step >= SIMULATION_STEPS:
                break

            traci.simulationStep()

            rows.append(
                collect_step_data(
                    step,
                    j1_group,
                    j2_group,
                    j1_side_q,
                    j1_main_q,
                    j2_side_q,
                    j2_main_q,
                )
            )

            if step % 300 == 0:
                print(
                    f"Step {step} | "
                    f"J1: {j1_group} | J2: {j2_group} | "
                    f"Vehicles: {get_vehicle_count()} | "
                    f"Waiting: {get_total_waiting_time():.2f} | "
                    f"Speed: {get_mean_speed():.2f} | "
                    f"Queue: {get_total_queue()}"
                )

            step += 1

        previous_j1_phase = j1_phase
        previous_j2_phase = j2_phase

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nQueue-based corridor simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()