import os
import sys
import csv
import numpy as np


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")

sys.path.append(ENV_DIR)

from two_intersection_env_v3 import TwoIntersectionEnvV3
from qmix_agent import QMIXAgent


OUTPUT_CSV = "results/raw/qmix_corridor_training_v3.csv"
MODEL_PATH = "results/raw/qmix_corridor_model_v3.pth"

NUM_EPISODES = 500
MAX_DECISIONS_PER_EPISODE = 200

MAX_QUEUE_NORM = 100.0
MAX_SPEED = 13.89


def normalize_global_state_v3(state):
    """
    Global state dimension = 14.

    Per intersection:
    [
        side_queue,
        main_queue,
        side_density,
        main_density,
        side_speed,
        main_speed,
        current_green
    ]
    """

    normalized = []

    for i in range(0, len(state), 7):
        side_queue = state[i]
        main_queue = state[i + 1]
        side_density = state[i + 2]
        main_density = state[i + 3]
        side_speed = state[i + 4]
        main_speed = state[i + 5]
        current_green = state[i + 6]

        normalized.extend([
            side_queue / MAX_QUEUE_NORM,
            main_queue / MAX_QUEUE_NORM,
            side_density,
            main_density,
            side_speed / MAX_SPEED,
            main_speed / MAX_SPEED,
            current_green,
        ])

    return normalized


def split_observations_v3(global_state):
    """
    Agent 0 / J1 observes first 7 values.
    Agent 1 / J2 observes last 7 values.
    """
    return [
        global_state[0:7],
        global_state[7:14],
    ]


def count_switches(previous_actions, current_actions):
    if previous_actions is None:
        return 0

    switches = 0

    for old_action, new_action in zip(previous_actions, current_actions):
        if old_action != new_action:
            switches += 1

    return switches


def main():
    env = TwoIntersectionEnvV3(
        sumo_binary="sumo",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
        sumo_seed=0,
    )

    qmix = QMIXAgent(
        n_agents=2,
        obs_dim=7,
        state_dim=14,
        action_dim=2,
        learning_rate=3e-4,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_min=0.05,
        epsilon_decay=0.9997,
        buffer_capacity=150_000,
        batch_size=128,
        target_update_freq=200,
    )

    rows = []

    for episode in range(1, NUM_EPISODES + 1):
        raw_state = env.reset()
        global_state = normalize_global_state_v3(raw_state)
        observations = split_observations_v3(global_state)

        done = False
        decision = 0
        episode_reward = 0.0
        losses = []
        last_info = None
        previous_actions = None

        while not done and decision < MAX_DECISIONS_PER_EPISODE:
            actions = qmix.select_actions(observations)

            raw_next_state, reward, done, info = env.step(actions)

            next_global_state = normalize_global_state_v3(raw_next_state)
            next_observations = split_observations_v3(next_global_state)

            switch_count = count_switches(previous_actions, actions)

            queue_penalty = 5.0 * info["total_queue"]
            switch_penalty = 100.0 * switch_count

            enhanced_reward = reward - queue_penalty - switch_penalty
            scaled_reward = enhanced_reward / 10000.0

            qmix.store_transition(
                global_state=global_state,
                observations=observations,
                actions=actions,
                reward=scaled_reward,
                next_global_state=next_global_state,
                next_observations=next_observations,
                done=done,
            )

            loss = qmix.learn()
            if loss is not None:
                losses.append(loss)

            global_state = next_global_state
            observations = next_observations
            previous_actions = actions

            episode_reward += reward
            decision += 1
            last_info = info

        avg_loss = np.mean(losses) if losses else 0.0

        row = {
            "episode": episode,
            "decisions": decision,
            "episode_reward": episode_reward,
            "avg_loss": avg_loss,
            "epsilon": qmix.epsilon,
            "final_vehicle_count": last_info["vehicle_count"],
            "final_total_waiting_time": last_info["total_waiting_time"],
            "final_mean_speed": last_info["mean_speed"],
            "final_total_queue": last_info["total_queue"],
        }

        rows.append(row)

        print(
            f"Episode {episode}/{NUM_EPISODES} | "
            f"Reward: {episode_reward:.2f} | "
            f"Avg loss: {avg_loss:.4f} | "
            f"Epsilon: {qmix.epsilon:.3f} | "
            f"Waiting: {last_info['total_waiting_time']:.2f} | "
            f"Speed: {last_info['mean_speed']:.2f} | "
            f"Queue: {last_info['total_queue']}"
        )

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    qmix.save(MODEL_PATH)

    print("\nQMIX V3 corridor training finished.")
    print(f"Training log saved to: {OUTPUT_CSV}")
    print(f"QMIX V3 model saved to: {MODEL_PATH}")


if __name__ == "__main__":
    main()