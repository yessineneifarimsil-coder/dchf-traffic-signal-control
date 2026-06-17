import os
import sys
import csv

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env")
sys.path.append(ENV_DIR)

from single_intersection_env import SingleIntersectionEnv
from dqn_agent import DQNAgent


MODEL_PATH = "results/raw/dqn_single_intersection_model_v2.pth"
OUTPUT_CSV = "results/raw/dqn_evaluation_single_intersection_v2.csv"

NUM_EPISODES = 5


def normalize_state(state):
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
        batch_size=64,
    )

    agent.load(MODEL_PATH)

    # Evaluation mode: no exploration
    agent.epsilon = 0.0

    rows = []

    for episode in range(1, NUM_EPISODES + 1):
        state = env.reset()
        state = normalize_state(state)

        done = False
        episode_reward = 0.0
        decisions = 0
        last_info = None

        while not done:
            action = agent.select_action(state)

            next_state, reward, done, info = env.step(action)
            next_state = normalize_state(next_state)

            episode_reward += reward
            decisions += 1
            state = next_state
            last_info = info

        row = {
            "episode": episode,
            "decisions": decisions,
            "episode_reward": episode_reward,
            "final_vehicle_count": last_info["vehicle_count"],
            "final_total_waiting_time": last_info["total_waiting_time"],
            "final_mean_speed": last_info["mean_speed"],
        }

        rows.append(row)

        print(
            f"Evaluation episode {episode}/{NUM_EPISODES} | "
            f"Reward: {episode_reward:.2f} | "
            f"Vehicles: {last_info['vehicle_count']} | "
            f"Waiting: {last_info['total_waiting_time']:.2f} | "
            f"Speed: {last_info['mean_speed']:.2f}"
        )

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nDQN evaluation finished.")
    print(f"Evaluation results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()