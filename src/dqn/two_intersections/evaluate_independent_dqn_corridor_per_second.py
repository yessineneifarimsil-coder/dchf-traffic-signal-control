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

OUTPUT_CSV = "results/raw/independent_dqn_corridor_per_second.csv"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3


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


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if not vehicles:
        return 0.0
    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def collect_step_data(env, decision, action_j1, action_j2, reward, done):
    return {
        "decision": decision,
        "step": env.step_count,
        "action_j1": action_j1,
        "action_j2": action_j2,
        "vehicle_count": len(traci.vehicle.getIDList()),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
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


def action_to_phase(env, action):
    if action == 0:
        return env.SIDE_GREEN
    if action == 1:
        return env.MAIN_GREEN
    raise ValueError("Invalid action.")


def yellow_phase_between(env, old_green, new_green):
    if old_green == new_green:
        return None

    if old_green == env.SIDE_GREEN and new_green == env.MAIN_GREEN:
        return env.SIDE_YELLOW

    if old_green == env.MAIN_GREEN and new_green == env.SIDE_GREEN:
        return env.MAIN_YELLOW

    raise ValueError(f"Unexpected transition: {old_green} -> {new_green}")


def run_yellow_with_logging(env, selected_phases, rows, decision, action_j1, action_j2):
    yellow_needed = False

    for tl_id in env.tl_ids:
        old_green = env.current_green[tl_id]
        new_green = selected_phases[tl_id]

        yellow_phase = yellow_phase_between(env, old_green, new_green)

        if yellow_phase is not None:
            traci.trafficlight.setPhase(tl_id, yellow_phase)
            traci.trafficlight.setPhaseDuration(tl_id, YELLOW_DURATION)
            yellow_needed = True

    if yellow_needed:
        for _ in range(YELLOW_DURATION):
            if env.step_count >= SIMULATION_STEPS:
                break

            traci.simulationStep()
            env.step_count += 1

            rows.append(
                collect_step_data(
                    env=env,
                    decision=decision,
                    action_j1=action_j1,
                    action_j2=action_j2,
                    reward=0.0,
                    done=False,
                )
            )


def run_green_with_logging(env, selected_phases, rows, decision, action_j1, action_j2):
    for tl_id in env.tl_ids:
        traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
        traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
        env.current_green[tl_id] = selected_phases[tl_id]

    cumulative_reward = 0.0

    for _ in range(GREEN_DURATION):
        if env.step_count >= SIMULATION_STEPS:
            break

        traci.simulationStep()
        env.step_count += 1

        reward = -get_total_waiting_time()
        cumulative_reward += reward
        done = env.step_count >= SIMULATION_STEPS

        rows.append(
            collect_step_data(
                env=env,
                decision=decision,
                action_j1=action_j1,
                action_j2=action_j2,
                reward=reward,
                done=done,
            )
        )

    return cumulative_reward


def main():
    env = TwoIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
    )

    agent_j1 = DQNAgent(state_dim=3, action_dim=2, batch_size=64)
    agent_j2 = DQNAgent(state_dim=3, action_dim=2, batch_size=64)

    agent_j1.load(MODEL_J1_PATH)
    agent_j2.load(MODEL_J2_PATH)

    agent_j1.epsilon = 0.0
    agent_j2.epsilon = 0.0

    state = env.reset()

    j1_state, j2_state = split_global_state(state)
    j1_state = normalize_local_state(j1_state)
    j2_state = normalize_local_state(j2_state)

    rows = []
    decision = 0
    total_reward = 0.0

    while env.step_count < SIMULATION_STEPS:
        action_j1 = agent_j1.select_action(j1_state)
        action_j2 = agent_j2.select_action(j2_state)

        selected_phases = {
            "J1": action_to_phase(env, action_j1),
            "J2": action_to_phase(env, action_j2),
        }

        decision += 1

        run_yellow_with_logging(
            env=env,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            action_j1=action_j1,
            action_j2=action_j2,
        )

        reward = run_green_with_logging(
            env=env,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            action_j1=action_j1,
            action_j2=action_j2,
        )

        total_reward += reward

        next_state = env.get_state()
        j1_state, j2_state = split_global_state(next_state)
        j1_state = normalize_local_state(j1_state)
        j2_state = normalize_local_state(j2_state)

        if decision % 10 == 0 or env.step_count >= SIMULATION_STEPS:
            print(
                f"Decision {decision} | "
                f"Step: {env.step_count} | "
                f"Actions: [{action_j1}, {action_j2}] | "
                f"Waiting: {get_total_waiting_time():.2f} | "
                f"Speed: {get_mean_speed():.2f} | "
                f"Queue: {env.get_total_queue()}"
            )

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nIndependent DQN per-second evaluation finished.")
    print(f"Total reward: {total_reward:.2f}")
    print(f"Per-second evaluation log saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()