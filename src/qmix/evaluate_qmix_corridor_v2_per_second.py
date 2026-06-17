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
OUTPUT_CSV = "results/raw/qmix_corridor_v2_per_second.csv"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3


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
    return [
        global_state[0:3],
        global_state[3:6],
    ]


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if not vehicles:
        return 0.0
    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


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


def collect_step_data(env, decision, actions, reward, done):
    return {
        "decision": decision,
        "step": env.step_count,
        "action_j1": actions[0],
        "action_j2": actions[1],
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


def run_yellow_with_logging(env, selected_phases, rows, decision, actions):
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
                    actions=actions,
                    reward=0.0,
                    done=False,
                )
            )


def run_green_with_logging(env, selected_phases, rows, decision, actions):
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
                actions=actions,
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

    qmix = QMIXAgent(
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
        batch_size=64,
    )

    qmix.load(MODEL_PATH)
    qmix.epsilon = 0.0

    raw_state = env.reset()
    global_state = normalize_global_state(raw_state)
    observations = split_observations(global_state)

    rows = []
    decision = 0
    total_reward = 0.0

    while env.step_count < SIMULATION_STEPS:
        actions = qmix.select_actions(observations)

        selected_phases = {
            "J1": action_to_phase(env, actions[0]),
            "J2": action_to_phase(env, actions[1]),
        }

        decision += 1

        run_yellow_with_logging(
            env=env,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
        )

        reward = run_green_with_logging(
            env=env,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
        )

        total_reward += reward

        next_state = env.get_state()
        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

        if decision % 10 == 0 or env.step_count >= SIMULATION_STEPS:
            print(
                f"Decision {decision} | "
                f"Step: {env.step_count} | "
                f"Actions: {actions} | "
                f"Waiting: {get_total_waiting_time():.2f} | "
                f"Speed: {get_mean_speed():.2f} | "
                f"Queue: {env.get_total_queue()}"
            )

    env.close()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nQMIX per-second evaluation finished.")
    print(f"Total reward: {total_reward:.2f}")
    print(f"Per-second evaluation log saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()