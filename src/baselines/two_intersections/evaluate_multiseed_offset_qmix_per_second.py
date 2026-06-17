import os
import sys
import pandas as pd
import traci


# =========================
# Paths
# =========================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")
QMIX_DIR = os.path.join(SRC_DIR, "qmix")

sys.path.append(ENV_DIR)
sys.path.insert(0, QMIX_DIR)

from two_intersection_env import TwoIntersectionEnv
from qmix_agent import QMIXAgent


# =========================
# Configuration
# =========================
SUMO_BINARY = "sumo"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SEEDS = SEEDS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
BEST_OFFSET = 45

QMIX_V2_MODEL = "results/raw/qmix_corridor_model_v2.pth"

OUTPUT_RAW = "results/raw/multiseed_offset_qmix_per_second_raw.csv"
OUTPUT_SUMMARY = "results/tables/multiseed_offset_qmix_per_second_summary.csv"

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3


# =========================
# Shared metrics
# =========================
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


def summarize_rows(controller, seed, rows):
    df = pd.DataFrame(rows)

    return {
        "controller": controller,
        "seed": seed,
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
    }


# =========================
# Offset controller
# =========================
def phase_from_cycle_time(t):
    t = t % CYCLE_LENGTH

    if t < GREEN_DURATION:
        return SIDE_GREEN

    if t < GREEN_DURATION + YELLOW_DURATION:
        return SIDE_YELLOW

    if t < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return MAIN_GREEN

    return MAIN_YELLOW


def run_best_offset_per_second(seed):
    env = TwoIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    env.reset()
    rows = []

    while env.step_count < SIMULATION_STEPS:
        step = env.step_count

        j1_phase = phase_from_cycle_time(step)
        j2_phase = phase_from_cycle_time(step - BEST_OFFSET)

        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhase("J2", j2_phase)

        traci.simulationStep()
        env.step_count += 1

        rows.append({
            "controller": "Best Offset Fixed-Time 45s",
            "seed": seed,
            "step": env.step_count,
            "vehicle_count": get_vehicle_count(),
            "total_waiting_time": get_total_waiting_time(),
            "mean_speed": get_mean_speed(),
            "total_queue": get_total_queue(),
        })

    env.close()

    return rows, summarize_rows("Best Offset Fixed-Time 45s", seed, rows)


# =========================
# QMIX V2 per-second controller
# =========================
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


def collect_qmix_step_row(env, seed, decision, actions, reward, done):
    return {
        "controller": "QMIX V2",
        "seed": seed,
        "decision": decision,
        "step": env.step_count,
        "action_j1": actions[0],
        "action_j2": actions[1],
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "J1_phase": traci.trafficlight.getPhase("J1"),
        "J2_phase": traci.trafficlight.getPhase("J2"),
        "reward": reward,
        "done": done,
    }


def run_qmix_yellow_with_logging(env, seed, selected_phases, rows, decision, actions):
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
                collect_qmix_step_row(
                    env=env,
                    seed=seed,
                    decision=decision,
                    actions=actions,
                    reward=0.0,
                    done=False,
                )
            )


def run_qmix_green_with_logging(env, seed, selected_phases, rows, decision, actions):
    for tl_id in env.tl_ids:
        traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
        traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
        env.current_green[tl_id] = selected_phases[tl_id]

    for _ in range(GREEN_DURATION):
        if env.step_count >= SIMULATION_STEPS:
            break

        traci.simulationStep()
        env.step_count += 1

        reward = -get_total_waiting_time()
        done = env.step_count >= SIMULATION_STEPS

        rows.append(
            collect_qmix_step_row(
                env=env,
                seed=seed,
                decision=decision,
                actions=actions,
                reward=reward,
                done=done,
            )
        )


def run_qmix_v2_per_second(seed):
    env = TwoIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    qmix = QMIXAgent(
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
        batch_size=64,
    )

    qmix.load(QMIX_V2_MODEL)
    qmix.epsilon = 0.0

    raw_state = env.reset()
    global_state = normalize_global_state(raw_state)
    observations = split_observations(global_state)

    rows = []
    decision = 0

    while env.step_count < SIMULATION_STEPS:
        actions = qmix.select_actions(observations)

        selected_phases = {
            "J1": action_to_phase(env, actions[0]),
            "J2": action_to_phase(env, actions[1]),
        }

        decision += 1

        run_qmix_yellow_with_logging(
            env=env,
            seed=seed,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
        )

        run_qmix_green_with_logging(
            env=env,
            seed=seed,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
        )

        next_state = env.get_state()
        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

    env.close()

    return rows, summarize_rows("QMIX V2", seed, rows)


# =========================
# Main
# =========================
def main():
    raw_rows = []
    summary_rows = []

    for seed in SEEDS:
        print(f"\n===== Seed {seed} =====")

        print("Running Best Offset Fixed-Time 45s per-second...")
        offset_rows, offset_summary = run_best_offset_per_second(seed)
        raw_rows.extend(offset_rows)
        summary_rows.append(offset_summary)
        print(offset_summary)

        print("Running QMIX V2 per-second...")
        qmix_rows, qmix_summary = run_qmix_v2_per_second(seed)
        raw_rows.extend(qmix_rows)
        summary_rows.append(qmix_summary)
        print(qmix_summary)

    raw_df = pd.DataFrame(raw_rows).round(3)
    summary_seed_df = pd.DataFrame(summary_rows).round(3)

    raw_df.to_csv(OUTPUT_RAW, index=False)

    summary_df = (
        summary_seed_df
        .groupby("controller")
        .agg({
            "mean_total_waiting_time": ["mean", "std"],
            "mean_speed": ["mean", "std"],
            "mean_total_queue": ["mean", "std"],
            "mean_vehicle_count": ["mean", "std"],
        })
        .round(3)
    )

    summary_df.columns = ["_".join(col) for col in summary_df.columns]
    summary_df = summary_df.reset_index()

    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    print("\n=== Per-seed summary ===")
    print(summary_seed_df.to_string(index=False))

    print("\n=== Multi-seed per-second summary ===")
    print(summary_df.to_string(index=False))

    print(f"\nRaw per-second results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()