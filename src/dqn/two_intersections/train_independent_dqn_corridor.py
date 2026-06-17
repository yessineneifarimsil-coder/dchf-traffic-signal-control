import os
import sys
import csv
import numpy as np

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")
DQN_DIR = os.path.join(SRC_DIR, "dqn")

sys.path.append(ENV_DIR)
sys.path.append(DQN_DIR)

from two_intersection_env import TwoIntersectionEnv
from dqn_agent import DQNAgent


OUTPUT_CSV = "results/raw/independent_dqn_corridor_training.csv"
MODEL_J1_PATH = "results/raw/independent_dqn_J1_model.pth"
MODEL_J2_PATH = "results/raw/independent_dqn_J2_model.pth"

NUM_EPISODES = 100
MAX_DECISIONS_PER_EPISODE = 200


def normalize_local_state(local_state):
    side_q, main_q, current_green = local_state
    return [
        side_q / 100.0,
        main_q / 100.0,
        current_green,
    ]


def split_global_state(state):
    j1_state = state[0:3]
    j2_state = state[3:6]
    return j1_state, j2_state


def main():
    env = TwoIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
    )

    agent_j1 = DQNAgent(
        state_dim=3,
        action_dim=2,
        learning_rate=1e-3,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_min=0.10,
        epsilon_decay=0.999,
        buffer_capacity=50_000,
        batch_size=64,
        target_update_freq=100,
    )

    agent_j2 = DQNAgent(
        state_dim=3,
        action_dim=2,
        learning_rate=1e-3,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_min=0.10,
        epsilon_decay=0.999,
        buffer_capacity=50_000,
        batch_size=64,
        target_update_freq=100,
    )

    rows = []

    for episode in range(1, NUM_EPISODES + 1):
        state = env.reset()

        j1_state, j2_state = split_global_state(state)
        j1_state = normalize_local_state(j1_state)
        j2_state = normalize_local_state(j2_state)

        done = False
        decision = 0
        episode_reward = 0.0
        losses_j1 = []
        losses_j2 = []
        last_info = None

        while not done and decision < MAX_DECISIONS_PER_EPISODE:
            action_j1 = agent_j1.select_action(j1_state)
            action_j2 = agent_j2.select_action(j2_state)

            joint_action = [action_j1, action_j2]

            next_state, reward, done, info = env.step(joint_action)

            next_j1_state, next_j2_state = split_global_state(next_state)
            next_j1_state = normalize_local_state(next_j1_state)
            next_j2_state = normalize_local_state(next_j2_state)

            scaled_reward = reward / 10000.0

            agent_j1.store_transition(
                j1_state, action_j1, scaled_reward, next_j1_state, done
            )
            agent_j2.store_transition(
                j2_state, action_j2, scaled_reward, next_j2_state, done
            )

            loss_j1 = agent_j1.learn()
            loss_j2 = agent_j2.learn()

            if loss_j1 is not None:
                losses_j1.append(loss_j1)
            if loss_j2 is not None:
                losses_j2.append(loss_j2)

            j1_state = next_j1_state
            j2_state = next_j2_state

            episode_reward += reward
            decision += 1
            last_info = info

        avg_loss_j1 = np.mean(losses_j1) if losses_j1 else 0.0
        avg_loss_j2 = np.mean(losses_j2) if losses_j2 else 0.0

        row = {
            "episode": episode,
            "decisions": decision,
            "episode_reward": episode_reward,
            "avg_loss_j1": avg_loss_j1,
            "avg_loss_j2": avg_loss_j2,
            "epsilon_j1": agent_j1.epsilon,
            "epsilon_j2": agent_j2.epsilon,
            "final_vehicle_count": last_info["vehicle_count"],
            "final_total_waiting_time": last_info["total_waiting_time"],
            "final_mean_speed": last_info["mean_speed"],
            "final_total_queue": last_info["total_queue"],
        }

        rows.append(row)

        print(
            f"Episode {episode}/{NUM_EPISODES} | "
            f"Reward: {episode_reward:.2f} | "
            f"Loss J1: {avg_loss_j1:.4f} | "
            f"Loss J2: {avg_loss_j2:.4f} | "
            f"Eps J1: {agent_j1.epsilon:.3f} | "
            f"Eps J2: {agent_j2.epsilon:.3f} | "
            f"Waiting: {last_info['total_waiting_time']:.2f} | "
            f"Speed: {last_info['mean_speed']:.2f} | "
            f"Queue: {last_info['total_queue']}"
        )

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    agent_j1.save(MODEL_J1_PATH)
    agent_j2.save(MODEL_J2_PATH)

    print("\nIndependent DQN training finished.")
    print(f"Training log saved to: {OUTPUT_CSV}")
    print(f"J1 model saved to: {MODEL_J1_PATH}")
    print(f"J2 model saved to: {MODEL_J2_PATH}")


if __name__ == "__main__":
    main()