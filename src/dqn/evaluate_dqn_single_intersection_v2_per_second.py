import os
import sys
import csv
import traci

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env")
sys.path.append(ENV_DIR)

from single_intersection_env import SingleIntersectionEnv
from dqn_agent import DQNAgent


MODEL_PATH = "results/raw/dqn_single_intersection_model_v2.pth"
OUTPUT_CSV = "results/raw/dqn_v2_per_second_2x2.csv"

SIMULATION_STEPS = 3600
GREEN_DURATION = 30
YELLOW_DURATION = 3
ALL_RED_DURATION = 2


def normalize_state(state):
    queue_0, queue_3, current_green = state
    return [
        queue_0 / 50.0,
        queue_3 / 50.0,
        current_green,
    ]


def collect_step_data(env, action, reward, done, decision):
    vehicles = traci.vehicle.getIDList()

    if vehicles:
        mean_speed = sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)
    else:
        mean_speed = 0.0

    total_waiting_time = sum(traci.vehicle.getWaitingTime(v) for v in vehicles)

    queue_0 = env.get_queue_on_lanes(env.phase_0_lanes)
    queue_3 = env.get_queue_on_lanes(env.phase_3_lanes)

    return {
        "decision": decision,
        "step": env.step_count,
        "action": action,
        "vehicle_count": len(vehicles),
        "total_waiting_time": total_waiting_time,
        "mean_speed": mean_speed,
        "current_green": env.current_green,
        "queue_phase_0": queue_0,
        "queue_phase_3": queue_3,
        "reward": reward,
        "done": done,
    }


def run_transition_with_logging(env, new_green, rows, action, decision):
    """
    Apply yellow + all-red transition manually and log every simulation second.
    """
    if env.current_green == new_green:
        return

    if env.current_green == 0 and new_green == 3:
        transition_phases = [
            (1, YELLOW_DURATION),
            (2, ALL_RED_DURATION),
        ]
    elif env.current_green == 3 and new_green == 0:
        transition_phases = [
            (4, YELLOW_DURATION),
            (5, ALL_RED_DURATION),
        ]
    else:
        raise ValueError(f"Unexpected transition: {env.current_green} -> {new_green}")

    for phase, duration in transition_phases:
        traci.trafficlight.setPhase(env.tl_id, phase)
        traci.trafficlight.setPhaseDuration(env.tl_id, duration)

        for _ in range(duration):
            if env.step_count >= SIMULATION_STEPS:
                return

            traci.simulationStep()
            env.step_count += 1

            rows.append(
                collect_step_data(
                    env=env,
                    action=action,
                    reward=0.0,
                    done=False,
                    decision=decision,
                )
            )

    env.current_green = new_green


def run_green_with_logging(env, green_phase, rows, action, decision):
    """
    Apply selected green phase and log every simulation second.
    """
    traci.trafficlight.setPhase(env.tl_id, green_phase)
    traci.trafficlight.setPhaseDuration(env.tl_id, GREEN_DURATION)

    cumulative_reward = 0.0

    for _ in range(GREEN_DURATION):
        if env.step_count >= SIMULATION_STEPS:
            break

        traci.simulationStep()
        env.step_count += 1

        total_waiting_time = env.get_total_waiting_time()
        reward = -total_waiting_time
        cumulative_reward += reward

        done = env.step_count >= SIMULATION_STEPS

        rows.append(
            collect_step_data(
                env=env,
                action=action,
                reward=reward,
                done=done,
                decision=decision,
            )
        )

    return cumulative_reward


def main():
    env = SingleIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        all_red_duration=ALL_RED_DURATION,
    )

    agent = DQNAgent(
        state_dim=3,
        action_dim=2,
        batch_size=64,
    )

    agent.load(MODEL_PATH)
    agent.epsilon = 0.0

    state = env.reset()
    state = normalize_state(state)

    rows = []
    decision = 0
    total_reward = 0.0

    while env.step_count < SIMULATION_STEPS:
        action = agent.select_action(state)
        selected_green = 0 if action == 0 else 3
        decision += 1

        run_transition_with_logging(
            env=env,
            new_green=selected_green,
            rows=rows,
            action=action,
            decision=decision,
        )

        reward = run_green_with_logging(
            env=env,
            green_phase=selected_green,
            rows=rows,
            action=action,
            decision=decision,
        )

        total_reward += reward

        next_state = env.get_state()
        state = normalize_state(next_state)

        if decision % 10 == 0 or env.step_count >= SIMULATION_STEPS:
            print(
                f"Decision {decision} | "
                f"Step: {env.step_count} | "
                f"Action: {action} | "
                f"Green: {selected_green} | "
                f"Total reward: {total_reward:.2f}"
            )

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nDQN V2 per-second evaluation finished.")
    print(f"Total reward: {total_reward:.2f}")
    print(f"Per-second results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()