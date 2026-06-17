import os
import sys
import csv
import traci

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")
DQN_DIR = os.path.join(SRC_DIR, "dqn")

sys.path.append(ENV_DIR)
sys.path.append(DQN_DIR)

from two_intersection_env import TwoIntersectionEnv
from dqn_agent import DQNAgent


MODEL_J1_PATH = "results/raw/independent_dqn_J1_model.pth"
MODEL_J2_PATH = "results/raw/independent_dqn_J2_model.pth"

OUTPUT_CSV = "results/raw/independent_dqn_corridor_evaluation.csv"

SIMULATION_STEPS = 3600


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


def collect_step_data(env, action_j1, action_j2, decision, reward, done):
    vehicles = traci.vehicle.getIDList()

    if vehicles:
        mean_speed = sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)
    else:
        mean_speed = 0.0

    total_waiting_time = sum(traci.vehicle.getWaitingTime(v) for v in vehicles)

    return {
        "decision": decision,
        "step": env.step_count,
        "action_j1": action_j1,
        "action_j2": action_j2,
        "vehicle_count": len(vehicles),
        "total_waiting_time": total_waiting_time,
        "mean_speed": mean_speed,
        "total_queue": env.get_total_queue(),
        "J1_phase": traci.trafficlight.getPhase("J1"),
        "J2_phase": traci.trafficlight.getPhase("J2"),
        "J1_side_queue": env.get_queue(env.J1_SIDE_LANES),
        "J1_main_queue": env.get_queue(env.J1_MAIN_LANES),
        "J2_side_queue": env.get_queue(env.J2_SIDE_LANES),
        "J2_main_queue": env.get_queue(env.J2_MAIN_LANES),
        "reward": reward,
        "done": done,
    }


def main():
    env = TwoIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=SIMULATION_STEPS,
        green_duration=42,
        yellow_duration=3,
    )

    agent_j1 = DQNAgent(state_dim=3, action_dim=2, batch_size=64)
    agent_j2 = DQNAgent(state_dim=3, action_dim=2, batch_size=64)

    agent_j1.load(MODEL_J1_PATH)
    agent_j2.load(MODEL_J2_PATH)

    # Evaluation mode: no random exploration
    agent_j1.epsilon = 0.0
    agent_j2.epsilon = 0.0

    state = env.reset()

    j1_state, j2_state = split_global_state(state)
    j1_state = normalize_local_state(j1_state)
    j2_state = normalize_local_state(j2_state)

    done = False
    decision = 0
    total_reward = 0.0
    rows = []

    while not done:
        action_j1 = agent_j1.select_action(j1_state)
        action_j2 = agent_j2.select_action(j2_state)

        next_state, reward, done, info = env.step([action_j1, action_j2])

        next_j1_state, next_j2_state = split_global_state(next_state)
        next_j1_state = normalize_local_state(next_j1_state)
        next_j2_state = normalize_local_state(next_j2_state)

        decision += 1
        total_reward += reward

        rows.append(
            collect_step_data(
                env=env,
                action_j1=action_j1,
                action_j2=action_j2,
                decision=decision,
                reward=reward,
                done=done,
            )
        )

        if decision % 10 == 0 or done:
            print(
                f"Decision {decision} | "
                f"Step: {info['step']} | "
                f"Actions: [{action_j1}, {action_j2}] | "
                f"Vehicles: {info['vehicle_count']} | "
                f"Waiting: {info['total_waiting_time']:.2f} | "
                f"Speed: {info['mean_speed']:.2f} | "
                f"Queue: {info['total_queue']} | "
                f"Reward: {reward:.2f}"
            )

        j1_state = next_j1_state
        j2_state = next_j2_state

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nIndependent DQN corridor evaluation finished.")
    print(f"Total reward: {total_reward:.2f}")
    print(f"Evaluation log saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()