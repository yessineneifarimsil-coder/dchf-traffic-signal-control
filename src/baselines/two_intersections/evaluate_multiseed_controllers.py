import os
import sys
import csv
import pandas as pd
import traci


# =========================
# Paths
# =========================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")
DQN_DIR = os.path.join(SRC_DIR, "dqn")
QMIX_DIR = os.path.join(SRC_DIR, "qmix")

sys.path.append(ENV_DIR)

# Put QMIX before DQN because both folders contain replay_buffer.py
sys.path.insert(0, QMIX_DIR)

from two_intersection_env import TwoIntersectionEnv
from qmix_agent import QMIXAgent


# =========================
# Configuration
# =========================
SUMO_BINARY = "sumo"
SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SEEDS = [0, 1, 2, 3, 4]

BEST_OFFSET = 45

QMIX_V2_MODEL = "results/raw/qmix_corridor_model_v2.pth"

OUTPUT_RAW = "results/raw/multiseed_controller_results.csv"
OUTPUT_SUMMARY = "results/tables/multiseed_controller_summary.csv"


SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3


# =========================
# Shared metrics
# =========================
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


def summarize_rows(controller, seed, rows):
    df = pd.DataFrame(rows)

    return {
        "controller": controller,
        "seed": seed,
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
    }


# =========================
# Best offset fixed-time
# =========================
def phase_from_cycle_time(t):
    t = t % CYCLE_LENGTH

    if t < GREEN_DURATION:
        return SIDE_GREEN

    if t < GREEN_DURATION + YELLOW_DURATION:
        return SIDE_YELLOW

    if t < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return MAIN_GREEN

    return MAIN_YELLOW


def run_best_offset(seed):
    env = TwoIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    env.reset()

    rows = []

    for step in range(SIMULATION_STEPS):
        j1_phase = phase_from_cycle_time(step)
        j2_phase = phase_from_cycle_time(step - BEST_OFFSET)

        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhase("J2", j2_phase)

        traci.simulationStep()
        env.step_count += 1

        rows.append({
            "vehicle_count": get_vehicle_count(),
            "total_waiting_time": get_total_waiting_time(),
            "mean_speed": get_mean_speed(),
            "total_queue": get_total_queue(),
        })

    env.close()

    return summarize_rows("Best Offset Fixed-Time 45s", seed, rows)


# =========================
# Independent DQN
# =========================
def normalize_local_state(local_state):
    side_q, main_q, current_green = local_state
    return [
        side_q / 100.0,
        main_q / 100.0,
        current_green,
    ]


def split_global_state(state):
    return state[0:3], state[3:6]


def run_independent_dqn(seed):
    env = TwoIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    agent_j1 = DQNAgent(state_dim=3, action_dim=2, batch_size=64)
    agent_j2 = DQNAgent(state_dim=3, action_dim=2, batch_size=64)

    agent_j1.load(INDEPENDENT_DQN_J1_MODEL)
    agent_j2.load(INDEPENDENT_DQN_J2_MODEL)

    agent_j1.epsilon = 0.0
    agent_j2.epsilon = 0.0

    state = env.reset()

    j1_state, j2_state = split_global_state(state)
    j1_state = normalize_local_state(j1_state)
    j2_state = normalize_local_state(j2_state)

    rows = []

    while env.step_count < SIMULATION_STEPS:
        action_j1 = agent_j1.select_action(j1_state)
        action_j2 = agent_j2.select_action(j2_state)

        next_state, reward, done, info = env.step([action_j1, action_j2])

        # We collect one row after each decision here.
        # For multi-seed robustness, this is acceptable as a compact evaluation.
        # The per-second detailed evaluation is already available separately.
        rows.append({
            "vehicle_count": info["vehicle_count"],
            "total_waiting_time": info["total_waiting_time"],
            "mean_speed": info["mean_speed"],
            "total_queue": info["total_queue"],
        })

        next_j1_state, next_j2_state = split_global_state(next_state)
        j1_state = normalize_local_state(next_j1_state)
        j2_state = normalize_local_state(next_j2_state)

        if done:
            break

    env.close()

    return summarize_rows("Independent DQN", seed, rows)


# =========================
# QMIX V2
# =========================
def normalize_global_state(state):
    return [
        state[0] / 100.0,
        state[1] / 100.0,
        state[2],
        state[3] / 100.0,
        state[4] / 100.0,
        state[5],
    ]


def split_observations(global_state):
    return [
        global_state[0:3],
        global_state[3:6],
    ]


def run_qmix_v2(seed):
    env = TwoIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    qmix = QMIXAgent(
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
        batch_size=64,
    )

    qmix.load(QMIX_V2_MODEL)
    qmix.epsilon = 0.0

    raw_state = env.reset()
    global_state = normalize_global_state(raw_state)
    observations = split_observations(global_state)

    rows = []

    while env.step_count < SIMULATION_STEPS:
        actions = qmix.select_actions(observations)

        next_state, reward, done, info = env.step(actions)

        rows.append({
            "vehicle_count": info["vehicle_count"],
            "total_waiting_time": info["total_waiting_time"],
            "mean_speed": info["mean_speed"],
            "total_queue": info["total_queue"],
        })

        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

        if done:
            break

    env.close()

    return summarize_rows("QMIX V2", seed, rows)


# =========================
# Main
# =========================
def main():
    all_results = []

    for seed in SEEDS:
        print(f"\n===== Seed {seed} =====")

        print("Running Best Offset Fixed-Time 45s...")
        result = run_best_offset(seed)
        all_results.append(result)
        print(result)


        print("Running QMIX V2...")
        result = run_qmix_v2(seed)
        all_results.append(result)
        print(result)

    raw_df = pd.DataFrame(all_results).round(3)
    raw_df.to_csv(OUTPUT_RAW, index=False)

    summary_df = (
        raw_df
        .groupby("controller")
        .agg({
            "mean_total_waiting_time": ["mean", "std"],
            "mean_speed": ["mean", "std"],
            "mean_total_queue": ["mean", "std"],
            "mean_vehicle_count": ["mean", "std"],
        })
        .round(3)
    )

    summary_df.columns = ["_".join(col) for col in summary_df.columns]
    summary_df = summary_df.reset_index()

    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    print("\n=== Multi-seed raw results ===")
    print(raw_df.to_string(index=False))

    print("\n=== Multi-seed summary ===")
    print(summary_df.to_string(index=False))

    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()