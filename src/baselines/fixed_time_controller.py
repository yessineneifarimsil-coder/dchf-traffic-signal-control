import csv
import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg"

OUTPUT_CSV = "results/raw/fixed_time_single_intersection.csv"

SIMULATION_STEPS = 3600

# We use only green phases from the observed program.
# Later we will inspect all phases more rigorously.
GREEN_PHASES = [0, 3]

GREEN_DURATION = 30


def get_total_waiting_time():
    total_waiting = 0.0
    for veh_id in traci.vehicle.getIDList():
        total_waiting += traci.vehicle.getWaitingTime(veh_id)
    return total_waiting


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if len(vehicles) == 0:
        return 0.0

    total_speed = 0.0
    for veh_id in vehicles:
        total_speed += traci.vehicle.getSpeed(veh_id)

    return total_speed / len(vehicles)


def get_vehicle_count():
    return len(traci.vehicle.getIDList())


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    print("Traffic lights:", traffic_lights)

    if not traffic_lights:
        raise RuntimeError("No traffic light found in the SUMO scenario.")

    tl_id = traffic_lights[0]
    print("Controlled traffic light:", tl_id)

    current_phase_index = 0
    current_phase = GREEN_PHASES[current_phase_index]

    traci.trafficlight.setPhase(tl_id, current_phase)
    traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)

    rows = []

    for step in range(SIMULATION_STEPS):
        # Change phase every GREEN_DURATION seconds
        if step % GREEN_DURATION == 0:
            current_phase = GREEN_PHASES[current_phase_index]
            traci.trafficlight.setPhase(tl_id, current_phase)
            traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)

            print(f"Step {step}: forced green phase {current_phase}")

            current_phase_index = (current_phase_index + 1) % len(GREEN_PHASES)

        traci.simulationStep()

        vehicle_count = get_vehicle_count()
        total_waiting = get_total_waiting_time()
        mean_speed = get_mean_speed()
        phase = traci.trafficlight.getPhase(tl_id)
        state = traci.trafficlight.getRedYellowGreenState(tl_id)

        rows.append({
            "step": step,
            "vehicle_count": vehicle_count,
            "total_waiting_time": total_waiting,
            "mean_speed": mean_speed,
            "phase": phase,
            "state": state
        })

        if step % 300 == 0:
            print(
                f"Step {step} | Vehicles: {vehicle_count} | "
                f"Waiting: {total_waiting:.2f} | Speed: {mean_speed:.2f} | Phase: {phase}"
            )

    traci.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("Simulation finished.")
    print(f"Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()