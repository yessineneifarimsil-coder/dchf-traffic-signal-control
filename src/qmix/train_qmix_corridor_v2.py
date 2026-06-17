import os
import sys
import csv
import numpy as np

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")

sys.path.append(ENV_DIR)

from two_intersection_env import TwoIntersectionEnv
from qmix_agent import QMIXAgent


OUTPUT_CSV = "results/raw/qmix_corridor_training_v2.csv"
MODEL_PATH = "results/raw/qmix_corridor_model_v2.pth"

NUM_EPISODES = 300
MAX_DECISIONS_PER_EPISODE = 200


def normalize_global_state(state):
    """
    State:
    [
        J1_side_queue,
        J1_main_queue,
        J1_current_green,
        J2_side_queue,
        J2_main_queue,
        J2_current_green
    ]
    """
    return [
        state[0] / 100.0,
        state[1] / 100.0,
        state[2],
        state[3] / 100.0,
        state[4] / 100.0,
        state[5],
    ]


def split_observations(global_state):
    """
    Returns local observations for the two agents.

    Agent 0 / J1 observes:
        [J1_side_queue, J1_main_queue, J1_current_green]

    Agent 1 / J2 observes:
        [J2_side_queue, J2_main_queue, J2_current_green]
    """
    obs_j1 = global_state[0:3]
    obs_j2 = global_state[3:6]
    return [obs_j1, obs_j2]


def main():
    env = TwoIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
    )

    qmix = QMIXAgent(
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
       learning_rate=5e-4,
       epsilon_start=1.0,
       epsilon_min=0.05,
       epsilon_decay=0.9995,
       buffer_capacity=100_000,
       batch_size=128,
       target_update_freq=200,
    )

    rows = []

    for episode in range(1, NUM_EPISODES + 1):
        raw_state = env.reset()
        global_state = normalize_global_state(raw_state)
        observations = split_observations(global_state)

        done = False
        decision = 0
        episode_reward = 0.0
        losses = []
        last_info = None

        while not done and decision < MAX_DECISIONS_PER_EPISODE:
            actions = qmix.select_actions(observations)

            raw_next_state, reward, done, info = env.step(actions)

            next_global_state = normalize_global_state(raw_next_state)
            next_observations = split_observations(next_global_state)

            # Reward scaling because SUMO waiting-time rewards are large
            scaled_reward = reward / 10000.0

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

    print("\nQMIX corridor training finished.")
    print(f"Training log saved to: {OUTPUT_CSV}")
    print(f"QMIX model saved to: {MODEL_PATH}")


if __name__ == "__main__":
    main()