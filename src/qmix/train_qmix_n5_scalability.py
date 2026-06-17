import os
import sys
import csv
import numpy as np


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "scalability")

sys.path.append(ENV_DIR)

from generic_corridor_env import GenericCorridorEnv
from qmix_agent import QMIXAgent


OUTPUT_CSV = "results/raw/qmix_n5_scalability_training.csv"
MODEL_PATH = "results/raw/qmix_n5_scalability_model.pth"

NUM_EPISODES = 500
MAX_DECISIONS_PER_EPISODE = 200

N_AGENTS = 5
OBS_DIM = 3
STATE_DIM = N_AGENTS * OBS_DIM
ACTION_DIM = 2

QUEUE_NORMALIZER = 300.0


def normalize_global_state(state):
    """
    Generic normalization for N-intersection corridor.

    Raw state format:
        [
            J1_phase0_queue, J1_phase2_queue, J1_current_green,
            J2_phase0_queue, J2_phase2_queue, J2_current_green,
            ...
        ]

    Queue values are divided by QUEUE_NORMALIZER.
    Current-green codes are kept as 0/1.
    """
    normalized = []

    for i in range(0, len(state), 3):
        normalized.append(state[i] / QUEUE_NORMALIZER)
        normalized.append(state[i + 1] / QUEUE_NORMALIZER)
        normalized.append(state[i + 2])

    return normalized


def split_observations(global_state):
    """
    Splits the global state into one local observation per agent.
    """
    return [
        global_state[i:i + OBS_DIM]
        for i in range(0, len(global_state), OBS_DIM)
    ]


def main():
    os.makedirs("results/raw", exist_ok=True)

    env = GenericCorridorEnv(
        sumo_binary="sumo",
        sumo_config="sumo_scenarios/scalability/corridor_5x2_d300m/corridor.sumocfg",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
        sumo_seed=0,
    )

    qmix = QMIXAgent(
        n_agents=N_AGENTS,
        obs_dim=OBS_DIM,
        state_dim=STATE_DIM,
        action_dim=ACTION_DIM,
        learning_rate=5e-4,
        epsilon_start=1.0,
        epsilon_min=0.05,
        epsilon_decay=0.9995,
        buffer_capacity=150_000,
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

            # Reward scaling because SUMO waiting-time rewards are large.
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

        # Save intermediate model every 50 episodes
        if episode % 50 == 0:
            qmix.save(MODEL_PATH)
            print(f"Intermediate model saved at episode {episode}: {MODEL_PATH}")

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    qmix.save(MODEL_PATH)

    print("\nQMIX N=5 scalability training finished.")
    print(f"Training log saved to: {OUTPUT_CSV}")
    print(f"QMIX model saved to: {MODEL_PATH}")


if __name__ == "__main__":
    main()