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
OUTPUT_CSV = "results/raw/dqn_v2_step_log_2x2.csv"

SIMULATION_STEPS = 3600


def normalize_state(state):
    queue_0, queue_3, current_green = state
    return [
        queue_0 / 50.0,
        queue_3 / 50.0,
        current_green,
    ]


def main():
    env = SingleIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=SIMULATION_STEPS,
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
    agent.epsilon = 0.0  # pure evaluation, no random exploration

    state = env.reset()
    state = normalize_state(state)

    done = False
    rows = []
    decision = 0
    total_reward = 0.0

    while not done:
        action = agent.select_action(state)

        next_state, reward, done, info = env.step(action)
        next_state = normalize_state(next_state)

        total_reward += reward
        decision += 1

        rows.append({
            "decision": decision,
            "step": info["step"],
            "action": action,
            "vehicle_count": info["vehicle_count"],
            "total_waiting_time": info["total_waiting_time"],
            "mean_speed": info["mean_speed"],
            "current_green": info["current_green"],
            "queue_phase_0": info["queue_phase_0"],
            "queue_phase_3": info["queue_phase_3"],
            "reward": reward,
            "done": done,
        })

        if decision % 10 == 0 or done:
            print(
                f"Decision {decision} | "
                f"Step: {info['step']} | "
                f"Action: {action} | "
                f"Vehicles: {info['vehicle_count']} | "
                f"Waiting: {info['total_waiting_time']:.2f} | "
                f"Speed: {info['mean_speed']:.2f} | "
                f"Reward: {reward:.2f}"
            )

        state = next_state

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nDQN V2 step-level evaluation finished.")
    print(f"Total reward: {total_reward:.2f}")
    print(f"Step-level results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()