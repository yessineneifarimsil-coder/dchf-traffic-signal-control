import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg"

OUTPUT_CSV = "results/raw/safe_fixed_time_2x2.csv"

SIMULATION_STEPS = 3600

GREEN_DURATION = 30
YELLOW_DURATION = 3
ALL_RED_DURATION = 2


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if not vehicles:
        return 0.0
    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def get_vehicle_count():
    return len(traci.vehicle.getIDList())


def apply_phase_and_run(tl_id, phase, duration, rows, current_step):
    traci.trafficlight.setPhase(tl_id, phase)
    traci.trafficlight.setPhaseDuration(tl_id, duration)

    for _ in range(duration):
        if current_step >= SIMULATION_STEPS:
            break

        traci.simulationStep()

        vehicles = get_vehicle_count()
        total_waiting = get_total_waiting_time()
        mean_speed = get_mean_speed()
        state = traci.trafficlight.getRedYellowGreenState(tl_id)

        rows.append({
            "step": current_step,
            "vehicle_count": vehicles,
            "total_waiting_time": total_waiting,
            "mean_speed": mean_speed,
            "phase": phase,
            "state": state
        })

        if current_step % 300 == 0:
            print(
                f"Step {current_step} | Vehicles: {vehicles} | "
                f"Waiting: {total_waiting:.2f} | Speed: {mean_speed:.2f} | Phase: {phase}"
            )

        current_step += 1

    return current_step


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    print("Traffic lights:", traffic_lights)

    if not traffic_lights:
        raise RuntimeError("No traffic light found.")

    tl_id = traffic_lights[0]
    print("Controlled traffic light:", tl_id)

    rows = []
    step = 0

    while step < SIMULATION_STEPS:
        # Direction 1
        print(f"Step {step}: green phase 0")
        step = apply_phase_and_run(tl_id, 0, GREEN_DURATION, rows, step)

        print(f"Step {step}: yellow phase 1")
        step = apply_phase_and_run(tl_id, 1, YELLOW_DURATION, rows, step)

        print(f"Step {step}: all-red phase 2")
        step = apply_phase_and_run(tl_id, 2, ALL_RED_DURATION, rows, step)

        # Direction 2
        print(f"Step {step}: green phase 3")
        step = apply_phase_and_run(tl_id, 3, GREEN_DURATION, rows, step)

        print(f"Step {step}: yellow phase 4")
        step = apply_phase_and_run(tl_id, 4, YELLOW_DURATION, rows, step)

        print(f"Step {step}: all-red phase 5")
        step = apply_phase_and_run(tl_id, 5, ALL_RED_DURATION, rows, step)

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("Safe fixed-time simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()