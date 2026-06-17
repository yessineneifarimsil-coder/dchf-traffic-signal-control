import os
import sys
import csv
import traci

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")

sys.path.append(ENV_DIR)

from two_intersection_env import TwoIntersectionEnv
from qmix_agent import QMIXAgent


MODEL_PATH = "results/raw/qmix_corridor_model_v2.pth"
OUTPUT_CSV = "results/raw/qmix_corridor_evaluation_v2.csv"

SIMULATION_STEPS = 3600


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
    obs_j1 = global_state[0:3]
    obs_j2 = global_state[3:6]
    return [obs_j1, obs_j2]


def collect_step_data(env, decision, actions, reward, done):
    vehicles = traci.vehicle.getIDList()

    if vehicles:
        mean_speed = sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)
    else:
        mean_speed = 0.0

    total_waiting_time = sum(traci.vehicle.getWaitingTime(v) for v in vehicles)

    return {
        "decision": decision,
        "step": env.step_count,
        "action_j1": actions[0],
        "action_j2": actions[1],
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

    qmix = QMIXAgent(
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
        batch_size=64,
    )

    qmix.load(MODEL_PATH)

    # Evaluation mode: no random actions
    qmix.epsilon = 0.0

    raw_state = env.reset()
    global_state = normalize_global_state(raw_state)
    observations = split_observations(global_state)

    done = False
    decision = 0
    total_reward = 0.0
    rows = []

    while not done:
        actions = qmix.select_actions(observations)

        raw_next_state, reward, done, info = env.step(actions)

        next_global_state = normalize_global_state(raw_next_state)
        next_observations = split_observations(next_global_state)

        decision += 1
        total_reward += reward

        rows.append(
            collect_step_data(
                env=env,
                decision=decision,
                actions=actions,
                reward=reward,
                done=done,
            )
        )

        if decision % 10 == 0 or done:
            print(
                f"Decision {decision} | "
                f"Step: {info['step']} | "
                f"Actions: {actions} | "
                f"Vehicles: {info['vehicle_count']} | "
                f"Waiting: {info['total_waiting_time']:.2f} | "
                f"Speed: {info['mean_speed']:.2f} | "
                f"Queue: {info['total_queue']} | "
                f"Reward: {reward:.2f}"
            )

        global_state = next_global_state
        observations = next_observations

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nQMIX corridor evaluation finished.")
    print(f"Total reward: {total_reward:.2f}")
    print(f"Evaluation log saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()