import os
import sys
import xml.etree.ElementTree as ET

import pandas as pd
import traci


# ============================================================
# PATHS
# ============================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "scalability")

sys.path.append(ENV_DIR)

from generic_corridor_env import GenericCorridorEnv
from qmix_agent import QMIXAgent


# ============================================================
# CONFIGURATION
# ============================================================

SUMO_BINARY = "sumo"

MODEL_PATH = "results/raw/qmix_n5_scalability_model.pth"

BENCHMARK_DCHF = "results/tables/n5_distance_demand_benchmark_dchf_summary.csv"

OUT_RAW = "results/raw/qmix_n5_distance_demand_evaluation_raw.csv"
OUT_QMIX = "results/tables/qmix_n5_distance_demand_summary.csv"
OUT_FULL_DCHF = "results/tables/n5_distance_demand_full_dchf_classification.csv"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3

N_AGENTS = 5
OBS_DIM = 3
STATE_DIM = 15
ACTION_DIM = 2

QUEUE_NORMALIZER = 300.0


# ============================================================
# UTILITIES
# ============================================================

def scenario_paths(distance, demand_name):
    scenario_dir = f"sumo_scenarios/scalability/corridor_5x2_d{distance}m_{demand_name}"
    return {
        "dir": scenario_dir,
        "cfg": os.path.join(scenario_dir, "corridor.sumocfg"),
        "rou": os.path.join(scenario_dir, "corridor.rou.xml"),
    }


def normalize_global_state(state):
    normalized = []
    for i in range(0, len(state), 3):
        normalized.append(state[i] / QUEUE_NORMALIZER)
        normalized.append(state[i + 1] / QUEUE_NORMALIZER)
        normalized.append(state[i + 2])
    return normalized


def split_observations(global_state):
    return [
        global_state[i:i + OBS_DIM]
        for i in range(0, len(global_state), OBS_DIM)
    ]


def get_expected_vehicles(route_file):
    tree = ET.parse(route_file)
    root = tree.getroot()

    expected = 0.0

    for flow in root.findall("flow"):
        begin = float(flow.attrib.get("begin", 0))
        end = float(flow.attrib.get("end", SIMULATION_STEPS))
        vehs_per_hour = float(flow.attrib.get("vehsPerHour", 0))
        expected += vehs_per_hour * ((end - begin) / 3600.0)

    return expected


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if not vehicles:
        return 0.0
    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def get_total_queue():
    total = 0
    for lane_id in traci.lane.getIDList():
        if not lane_id.startswith(":"):
            total += traci.lane.getLastStepHaltingNumber(lane_id)
    return total


def classify_gap(gap_percent):
    if gap_percent <= 5:
        return "Effective coordination zone"
    if gap_percent <= 10:
        return "Marginal coordination zone"
    return "Outside coordination horizon"


def classify_capacity(buffered_ratio):
    if buffered_ratio < 0.01:
        return "Unconstrained"
    if buffered_ratio < 0.10:
        return "Mild insertion pressure"
    if buffered_ratio < 0.25:
        return "Capacity-limited"
    return "Oversaturated"


def load_qmix_agent():
    qmix = QMIXAgent(
        n_agents=N_AGENTS,
        obs_dim=OBS_DIM,
        state_dim=STATE_DIM,
        action_dim=ACTION_DIM,
        learning_rate=5e-4,
        epsilon_start=0.0,
        epsilon_min=0.0,
        epsilon_decay=1.0,
        buffer_capacity=150_000,
        batch_size=128,
        target_update_freq=200,
    )

    qmix.load(MODEL_PATH)
    qmix.epsilon = 0.0
    return qmix


def run_qmix_scenario(distance, demand_name, multiplier, seed=0):
    paths = scenario_paths(distance, demand_name)

    if not os.path.exists(paths["cfg"]):
        raise FileNotFoundError(f"Missing SUMO config: {paths['cfg']}")

    if not os.path.exists(paths["rou"]):
        raise FileNotFoundError(f"Missing route file: {paths['rou']}")

    env = GenericCorridorEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=paths["cfg"],
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    qmix = load_qmix_agent()

    raw_state = env.reset()

    rows = []
    decision = 0
    total_departed = 0
    total_arrived = 0
    total_teleports = 0
    done = False

    while not done:
        global_state = normalize_global_state(raw_state)
        observations = split_observations(global_state)

        actions = qmix.select_actions(observations)

        selected_phases = {
            tl_id: env.action_to_phase(actions[i])
            for i, tl_id in enumerate(env.tl_ids)
        }

        yellow_needed = False

        for tl_id in env.tl_ids:
            old_green = env.current_green[tl_id]
            new_green = selected_phases[tl_id]

            if old_green != new_green:
                yellow_phase = (
                    env.PHASE0_YELLOW
                    if old_green == env.PHASE0_GREEN
                    else env.PHASE2_YELLOW
                )
                traci.trafficlight.setPhase(tl_id, yellow_phase)
                traci.trafficlight.setPhaseDuration(tl_id, YELLOW_DURATION)
                yellow_needed = True

        if yellow_needed:
            for _ in range(YELLOW_DURATION):
                if env.step_count >= SIMULATION_STEPS:
                    break

                traci.simulationStep()
                env.step_count += 1

                departed = traci.simulation.getDepartedNumber()
                arrived = traci.simulation.getArrivedNumber()
                teleports = traci.simulation.getStartingTeleportNumber()

                total_departed += departed
                total_arrived += arrived
                total_teleports += teleports

                rows.append({
                    "N": N_AGENTS,
                    "distance_m": distance,
                    "demand": demand_name,
                    "multiplier": multiplier,
                    "seed": seed,
                    "step": int(traci.simulation.getTime()),
                    "decision": decision,
                    "vehicle_count": len(traci.vehicle.getIDList()),
                    "total_waiting_time": get_total_waiting_time(),
                    "mean_speed": get_mean_speed(),
                    "total_queue": get_total_queue(),
                    "departed_this_step": departed,
                    "arrived_this_step": arrived,
                    "teleports_this_step": teleports,
                    "total_departed": total_departed,
                    "total_arrived": total_arrived,
                    "total_teleports": total_teleports,
                    **{f"action_j{i+1}": actions[i] for i in range(N_AGENTS)},
                })

        for tl_id in env.tl_ids:
            traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
            traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
            env.current_green[tl_id] = selected_phases[tl_id]

        for _ in range(GREEN_DURATION):
            if env.step_count >= SIMULATION_STEPS:
                break

            traci.simulationStep()
            env.step_count += 1

            departed = traci.simulation.getDepartedNumber()
            arrived = traci.simulation.getArrivedNumber()
            teleports = traci.simulation.getStartingTeleportNumber()

            total_departed += departed
            total_arrived += arrived
            total_teleports += teleports

            rows.append({
                "N": N_AGENTS,
                "distance_m": distance,
                "demand": demand_name,
                "multiplier": multiplier,
                "seed": seed,
                "step": int(traci.simulation.getTime()),
                "decision": decision,
                "vehicle_count": len(traci.vehicle.getIDList()),
                "total_waiting_time": get_total_waiting_time(),
                "mean_speed": get_mean_speed(),
                "total_queue": get_total_queue(),
                "departed_this_step": departed,
                "arrived_this_step": arrived,
                "teleports_this_step": teleports,
                "total_departed": total_departed,
                "total_arrived": total_arrived,
                "total_teleports": total_teleports,
                **{f"action_j{i+1}": actions[i] for i in range(N_AGENTS)},
            })

        raw_state = env.get_state()
        decision += 1
        done = env.step_count >= SIMULATION_STEPS

    env.close()

    df = pd.DataFrame(rows)

    expected = get_expected_vehicles(paths["rou"])
    buffered_ratio = max(0.0, (expected - total_departed) / expected) if expected > 0 else 0.0

    summary = {
        "N": N_AGENTS,
        "distance_m": distance,
        "demand": demand_name,
        "multiplier": multiplier,
        "seed": seed,
        "controller": "QMIX N5 transferred",
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "total_expected": expected,
        "total_departed": total_departed,
        "total_arrived": total_arrived,
        "buffered_ratio": buffered_ratio,
        "capacity_regime": classify_capacity(buffered_ratio),
        "total_teleports": total_teleports,
    }

    return rows, summary


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    benchmark_df = pd.read_csv(BENCHMARK_DCHF)

    all_raw_rows = []
    qmix_summaries = []

    for _, row in benchmark_df.iterrows():
        distance = int(row["distance_m"])
        demand_name = str(row["demand"])
        multiplier = float(row["multiplier"])

        print("\n" + "=" * 80)
        print(f"Running QMIX N=5 evaluation | distance={distance} m | demand={demand_name}")
        print("=" * 80)

        raw_rows, summary = run_qmix_scenario(
            distance=distance,
            demand_name=demand_name,
            multiplier=multiplier,
            seed=0,
        )

        all_raw_rows.extend(raw_rows)
        qmix_summaries.append(summary)

        print(pd.DataFrame([summary]).round(3).to_string(index=False))

        pd.DataFrame(all_raw_rows).to_csv(OUT_RAW, index=False)
        pd.DataFrame(qmix_summaries).round(3).to_csv(OUT_QMIX, index=False)

    qmix_df = pd.DataFrame(qmix_summaries)

    merged = benchmark_df.merge(
        qmix_df,
        on=["N", "distance_m", "demand", "multiplier"],
        how="left",
        suffixes=("_benchmark", "_qmix"),
    )

    merged["qmix_waiting_time"] = merged["mean_total_waiting_time"]

    merged["qmix_coordination_gain_percent"] = (
        (merged["simultaneous_waiting_time"] - merged["qmix_waiting_time"])
        / merged["simultaneous_waiting_time"]
    ) * 100

    merged["qmix_gap_percent"] = (
        (merged["qmix_waiting_time"] - merged["best_offset_waiting_time"])
        / merged["best_offset_waiting_time"]
    ) * 100

    merged["dchf_regime"] = merged["qmix_gap_percent"].apply(classify_gap)

    merged["final_capacity_regime"] = merged["buffered_ratio_qmix"].apply(classify_capacity)

    final_columns = [
        "N",
        "distance_m",
        "demand",
        "multiplier",
        "simultaneous_waiting_time",
        "best_offset_waiting_time",
        "best_offset_s",
        "offset_coordination_gain_percent",
        "qmix_waiting_time",
        "qmix_coordination_gain_percent",
        "qmix_gap_percent",
        "dchf_regime",
        "buffered_ratio_benchmark",
        "buffered_ratio_qmix",
        "final_capacity_regime",
        "total_teleports_benchmark",
        "total_teleports_qmix",
    ]

    final_df = merged[final_columns].round(3)
    final_df.to_csv(OUT_FULL_DCHF, index=False)

    print("\n" + "=" * 80)
    print("N=5 DISTANCE-DEMAND QMIX EVALUATION FINISHED")
    print("=" * 80)

    print("\nFinal DCHF classification:")
    print(final_df.to_string(index=False))

    print(f"\nSaved raw QMIX evaluation: {OUT_RAW}")
    print(f"Saved QMIX summary: {OUT_QMIX}")
    print(f"Saved full DCHF classification: {OUT_FULL_DCHF}")


if __name__ == "__main__":
    main()