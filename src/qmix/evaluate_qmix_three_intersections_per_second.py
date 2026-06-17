import os
import sys
import pandas as pd
import traci


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "three_intersections")

sys.path.append(ENV_DIR)

from three_intersection_env import ThreeIntersectionEnv
from qmix_agent import QMIXAgent


SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/three_intersections/corridor_3x2/corridor_3x2_through.sumocfg"

MODEL_PATH = "results/raw/qmix_three_intersections_model.pth"

OUTPUT_RAW = "results/raw/qmix_three_intersections_per_second.csv"
OUTPUT_SUMMARY = "results/tables/qmix_three_intersections_summary.csv"

SIMULATION_STEPS = 3600
EXPECTED_TOTAL_VEHICLES = 3400

GREEN_DURATION = 42
YELLOW_DURATION = 3

QUEUE_NORMALIZER = 200.0


def normalize_global_state(state):
    return [
        state[0] / QUEUE_NORMALIZER,
        state[1] / QUEUE_NORMALIZER,
        state[2],

        state[3] / QUEUE_NORMALIZER,
        state[4] / QUEUE_NORMALIZER,
        state[5],

        state[6] / QUEUE_NORMALIZER,
        state[7] / QUEUE_NORMALIZER,
        state[8],
    ]


def split_observations(global_state):
    return [
        global_state[0:3],
        global_state[3:6],
        global_state[6:9],
    ]


def action_to_phase(env, action):
    if action == 0:
        return env.SIDE_GREEN

    if action == 1:
        return env.MAIN_GREEN

    raise ValueError(f"Invalid action: {action}")


def yellow_phase_between(env, old_green, new_green):
    if old_green == new_green:
        return None

    if old_green == env.SIDE_GREEN and new_green == env.MAIN_GREEN:
        return env.SIDE_YELLOW

    if old_green == env.MAIN_GREEN and new_green == env.SIDE_GREEN:
        return env.MAIN_YELLOW

    raise ValueError(f"Unexpected transition: {old_green} -> {new_green}")


def get_vehicle_count():
    return len(traci.vehicle.getIDList())


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()

    if not vehicles:
        return 0.0

    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def get_total_queue():
    total_queue = 0

    for lane_id in traci.lane.getIDList():
        if not lane_id.startswith(":"):
            total_queue += traci.lane.getLastStepHaltingNumber(lane_id)

    return total_queue


def get_edge_queue(edge_id):
    total = 0

    for lane_id in traci.lane.getIDList():
        if lane_id.startswith(edge_id + "_"):
            total += traci.lane.getLastStepHaltingNumber(lane_id)

    return total


def simulation_step_with_stats(stats):
    traci.simulationStep()

    stats["departed"] += traci.simulation.getDepartedNumber()
    stats["arrived"] += traci.simulation.getArrivedNumber()


def collect_row(env, decision, actions, stats, reward, done):
    return {
        "decision": decision,
        "step": env.step_count,

        "action_j1": actions[0],
        "action_j2": actions[1],
        "action_j3": actions[2],

        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),

        "J1_phase": traci.trafficlight.getPhase("J1"),
        "J2_phase": traci.trafficlight.getPhase("J2"),
        "J3_phase": traci.trafficlight.getPhase("J3"),

        "E1_queue_J1_J2": get_edge_queue("E1"),
        "neg_E1_queue_J2_J1": get_edge_queue("-E1"),
        "E2_queue_J2_J3": get_edge_queue("E2"),
        "neg_E2_queue_J3_J2": get_edge_queue("-E2"),

        "departed_cumulative": stats["departed"],
        "arrived_cumulative": stats["arrived"],

        "reward": reward,
        "done": done,
    }


def run_yellow_with_logging(env, selected_phases, rows, decision, actions, stats):
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

            simulation_step_with_stats(stats)
            env.step_count += 1

            done = env.step_count >= SIMULATION_STEPS

            rows.append(
                collect_row(
                    env=env,
                    decision=decision,
                    actions=actions,
                    stats=stats,
                    reward=0.0,
                    done=done,
                )
            )


def run_green_with_logging(env, selected_phases, rows, decision, actions, stats):
    for tl_id in env.tl_ids:
        traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
        traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
        env.current_green[tl_id] = selected_phases[tl_id]

    for _ in range(GREEN_DURATION):
        if env.step_count >= SIMULATION_STEPS:
            break

        simulation_step_with_stats(stats)
        env.step_count += 1

        reward = -get_total_waiting_time()
        done = env.step_count >= SIMULATION_STEPS

        rows.append(
            collect_row(
                env=env,
                decision=decision,
                actions=actions,
                stats=stats,
                reward=reward,
                done=done,
            )
        )


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    env = ThreeIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=SUMO_CONFIG,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=0,
    )

    qmix = QMIXAgent(
        n_agents=3,
        obs_dim=3,
        state_dim=9,
        action_dim=2,
        batch_size=128,
    )

    qmix.load(MODEL_PATH)

    # Fully greedy evaluation.
    qmix.epsilon = 0.0

    raw_state = env.reset()
    global_state = normalize_global_state(raw_state)
    observations = split_observations(global_state)

    rows = []
    stats = {
        "departed": 0,
        "arrived": 0,
    }

    decision = 0
    total_reward = 0.0

    while env.step_count < SIMULATION_STEPS:
        actions = qmix.select_actions(observations)

        selected_phases = {
            "J1": action_to_phase(env, actions[0]),
            "J2": action_to_phase(env, actions[1]),
            "J3": action_to_phase(env, actions[2]),
        }

        decision += 1

        run_yellow_with_logging(
            env=env,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
            stats=stats,
        )

        run_green_with_logging(
            env=env,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
            stats=stats,
        )

        next_state = env.get_state()
        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

        if rows:
            total_reward += rows[-1]["reward"]

        if decision % 10 == 0 or env.step_count >= SIMULATION_STEPS:
            print(
                f"Decision {decision} | "
                f"Step {env.step_count} | "
                f"Actions {actions} | "
                f"Waiting {get_total_waiting_time():.2f} | "
                f"Speed {get_mean_speed():.2f} | "
                f"Queue {get_total_queue()}"
            )

    final_active = get_vehicle_count()
    final_buffered = EXPECTED_TOTAL_VEHICLES - stats["departed"]

    env.close()

    df = pd.DataFrame(rows).round(3)
    df.to_csv(OUTPUT_RAW, index=False)

    summary = {
        "controller": "QMIX 3 Agents",
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "total_departed": stats["departed"],
        "total_arrived": stats["arrived"],
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": final_buffered / EXPECTED_TOTAL_VEHICLES,
    }

    summary_df = pd.DataFrame([summary]).round(3)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    print("\nQMIX 3-agent per-second evaluation finished.")
    print(summary_df.to_string(index=False))
    print(f"\nRaw evaluation log saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()