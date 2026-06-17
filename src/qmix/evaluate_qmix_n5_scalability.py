import os
import sys
import xml.etree.ElementTree as ET

import pandas as pd
import traci


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "scalability")

sys.path.append(ENV_DIR)

from generic_corridor_env import GenericCorridorEnv
from qmix_agent import QMIXAgent


SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/scalability/corridor_5x2_d300m/corridor.sumocfg"
ROUTE_FILE = "sumo_scenarios/scalability/corridor_5x2_d300m/corridor.rou.xml"

MODEL_PATH = "results/raw/qmix_n5_scalability_model.pth"

OUT_RAW = "results/raw/qmix_n5_scalability_evaluation_raw.csv"
OUT_SUMMARY = "results/tables/qmix_n5_scalability_summary.csv"
OUT_DCHF = "results/tables/n5_scalability_dchf_summary.csv"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3

N_AGENTS = 5
OBS_DIM = 3
STATE_DIM = 15
ACTION_DIM = 2

QUEUE_NORMALIZER = 300.0

BEST_OFFSET_SUMMARY = "results/tables/n5_best_progression_offset_summary.csv"
OFFSET_SWEEP_SUMMARY = "results/tables/n5_progression_offset_sweep_summary.csv"


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


def log_step(rows, decision, actions, total_departed, total_arrived):
    row = {
        "step": int(traci.simulation.getTime()),
        "decision": decision,
        "vehicle_count": len(traci.vehicle.getIDList()),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "departed_this_step": traci.simulation.getDepartedNumber(),
        "arrived_this_step": traci.simulation.getArrivedNumber(),
        "total_departed": total_departed,
        "total_arrived": total_arrived,
    }

    for i, action in enumerate(actions, start=1):
        row[f"action_j{i}"] = action
        row[f"J{i}_phase"] = traci.trafficlight.getPhase(f"J{i}")

    rows.append(row)


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


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    env = GenericCorridorEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=SUMO_CONFIG,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=0,
    )

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

    raw_state = env.reset()

    rows = []
    decision = 0
    total_departed = 0
    total_arrived = 0
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

                total_departed += traci.simulation.getDepartedNumber()
                total_arrived += traci.simulation.getArrivedNumber()

                log_step(rows, decision, actions, total_departed, total_arrived)

        for tl_id in env.tl_ids:
            traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
            traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
            env.current_green[tl_id] = selected_phases[tl_id]

        for _ in range(GREEN_DURATION):
            if env.step_count >= SIMULATION_STEPS:
                break

            traci.simulationStep()
            env.step_count += 1

            total_departed += traci.simulation.getDepartedNumber()
            total_arrived += traci.simulation.getArrivedNumber()

            log_step(rows, decision, actions, total_departed, total_arrived)

        raw_state = env.get_state()
        decision += 1
        done = env.step_count >= SIMULATION_STEPS

    env.close()

    df = pd.DataFrame(rows)
    df.to_csv(OUT_RAW, index=False)

    expected = get_expected_vehicles(ROUTE_FILE)
    buffered_ratio = max(0.0, (expected - total_departed) / expected) if expected > 0 else 0.0

    summary = {
        "controller": "QMIX 5 Agents",
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "total_expected": expected,
        "total_departed": total_departed,
        "total_arrived": total_arrived,
        "buffered_ratio": buffered_ratio,
        "capacity_regime": classify_capacity(buffered_ratio),
    }

    summary_df = pd.DataFrame([summary]).round(3)
    summary_df.to_csv(OUT_SUMMARY, index=False)

    best_df = pd.read_csv(BEST_OFFSET_SUMMARY)
    sweep_df = pd.read_csv(OFFSET_SWEEP_SUMMARY)

    best_wait = float(best_df.iloc[0]["mean_total_waiting_time"])
    best_controller = best_df.iloc[0]["controller"]
    sim_wait = float(
        sweep_df[sweep_df["offset"] == 0].iloc[0]["mean_total_waiting_time"]
    )

    qmix_wait = summary["mean_total_waiting_time"]

    coordination_gain = ((sim_wait - qmix_wait) / sim_wait) * 100
    qmix_gap = ((qmix_wait - best_wait) / best_wait) * 100

    dchf = {
        "scenario": "N5_d300_medium",
        "N": 5,
        "distance_m": 300,
        "demand": "medium",
        "simultaneous_waiting_time": sim_wait,
        "best_offset_controller": best_controller,
        "best_offset_waiting_time": best_wait,
        "qmix_waiting_time": qmix_wait,
        "coordination_gain_percent": coordination_gain,
        "qmix_gap_percent": qmix_gap,
        "dchf_regime": classify_gap(qmix_gap),
        "buffered_ratio": buffered_ratio,
        "capacity_regime": classify_capacity(buffered_ratio),
    }

    dchf_df = pd.DataFrame([dchf]).round(3)
    dchf_df.to_csv(OUT_DCHF, index=False)

    print("\nQMIX N=5 deterministic evaluation finished.")
    print("\nQMIX summary:")
    print(summary_df.to_string(index=False))

    print("\nDCHF comparison:")
    print(dchf_df.to_string(index=False))

    print(f"\nSaved raw evaluation: {OUT_RAW}")
    print(f"Saved summary: {OUT_SUMMARY}")
    print(f"Saved DCHF comparison: {OUT_DCHF}")


if __name__ == "__main__":
    main()