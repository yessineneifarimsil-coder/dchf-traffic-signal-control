import os
import sys
import csv
import numpy as np

# Allow imports from src/env and src/dqn
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env")
sys.path.append(ENV_DIR)

from single_intersection_env import SingleIntersectionEnv
from dqn_agent import DQNAgent


OUTPUT_CSV = "results/raw/dqn_training_single_intersection_v2.csv"
MODEL_PATH = "results/raw/dqn_single_intersection_model_v2.pth"

NUM_EPISODES = 100
MAX_DECISIONS_PER_EPISODE = 200


def normalize_state(state):
    """
    Simple normalization to help neural network learning.
    queue values are divided by 50.
    current_green already equals 0 or 1.
    """
    queue_0, queue_3, current_green = state
    return [
        queue_0 / 50.0,
        queue_3 / 50.0,
        current_green,
    ]


def main():
    env = SingleIntersectionEnv(
        sumo_binary="sumo",  # use "sumo-gui" if you want to watch
        simulation_steps=3600,
        green_duration=30,
        yellow_duration=3,
        all_red_duration=2,
    )

    agent = DQNAgent(
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
        state = normalize_state(state)

        done = False
        episode_reward = 0.0
        episode_losses = []
        decision = 0

        while not done and decision < MAX_DECISIONS_PER_EPISODE:
            action = agent.select_action(state)

            next_state, reward, done, info = env.step(action)
            next_state = normalize_state(next_state)

            # Reward scaling: waiting time can be large, so divide by 1000
            scaled_reward = reward / 1000.0

            agent.store_transition(state, action, scaled_reward, next_state, done)
            loss = agent.learn()

            if loss is not None:
                episode_losses.append(loss)

            state = next_state
            episode_reward += reward
            decision += 1

        avg_loss = np.mean(episode_losses) if episode_losses else 0.0

        row = {
            "episode": episode,
            "decisions": decision,
            "episode_reward": episode_reward,
            "avg_loss": avg_loss,
            "epsilon": agent.epsilon,
            "final_vehicle_count": info["vehicle_count"],
            "final_total_waiting_time": info["total_waiting_time"],
            "final_mean_speed": info["mean_speed"],
        }

        rows.append(row)

        print(
            f"Episode {episode}/{NUM_EPISODES} | "
            f"Decisions: {decision} | "
            f"Reward: {episode_reward:.2f} | "
            f"Avg loss: {avg_loss:.4f} | "
            f"Epsilon: {agent.epsilon:.3f} | "
            f"Final waiting: {info['total_waiting_time']:.2f} | "
            f"Final speed: {info['mean_speed']:.2f}"
        )

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    agent.save(MODEL_PATH)

    print("\nTraining finished.")
    print(f"Training log saved to: {OUTPUT_CSV}")
    print(f"Model saved to: {MODEL_PATH}")


if __name__ == "__main__":
    main()