import os
import sys
import pandas as pd
import traci


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
ENV_DIR = os.path.join(SRC_DIR, "env", "three_intersections")
QMIX_DIR = os.path.join(SRC_DIR, "qmix")

sys.path.append(ENV_DIR)
sys.path.insert(0, QMIX_DIR)

from three_intersection_env import ThreeIntersectionEnv
from qmix_agent import QMIXAgent


SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/three_intersections/corridor_3x2/corridor_3x2_through.sumocfg"

MODEL_PATH = "results/raw/qmix_three_intersections_model.pth"

SIMULATION_STEPS = 3600
EXPECTED_TOTAL_VEHICLES = 3400

GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

QUEUE_NORMALIZER = 200.0

SEEDS = [0, 1, 2, 3, 4]

OUTPUT_RAW = "results/raw/multiseed_three_intersection_controllers_raw.csv"
OUTPUT_SUMMARY = "results/tables/multiseed_three_intersection_controllers_summary.csv"


def phase_from_cycle_time(t):
    t = t % CYCLE_LENGTH

    if t < GREEN_DURATION:
        return SIDE_GREEN

    if t < GREEN_DURATION + YELLOW_DURATION:
        return SIDE_YELLOW

    if t < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return MAIN_GREEN

    return MAIN_YELLOW


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


def run_fixed_or_offset(seed, controller_name, offset_j2, offset_j3):
    sumo_cmd = [
        SUMO_BINARY,
        "-c",
        SUMO_CONFIG,
        "--seed",
        str(seed),
        "--no-step-log",
        "true",
    ]

    traci.start(sumo_cmd)

    rows = []

    departed = 0
    arrived = 0

    for step in range(SIMULATION_STEPS):
        phase_j1 = phase_from_cycle_time(step)
        phase_j2 = phase_from_cycle_time(step - offset_j2)
        phase_j3 = phase_from_cycle_time(step - offset_j3)

        traci.trafficlight.setPhase("J1", phase_j1)
        traci.trafficlight.setPhase("J2", phase_j2)
        traci.trafficlight.setPhase("J3", phase_j3)

        traci.simulationStep()

        departed += traci.simulation.getDepartedNumber()
        arrived += traci.simulation.getArrivedNumber()

        rows.append({
            "seed": seed,
            "controller": controller_name,
            "step": step + 1,
            "vehicle_count": get_vehicle_count(),
            "total_waiting_time": get_total_waiting_time(),
            "mean_speed": get_mean_speed(),
            "total_queue": get_total_queue(),
            "departed_cumulative": departed,
            "arrived_cumulative": arrived,
        })

    final_active = get_vehicle_count()
    final_buffered = EXPECTED_TOTAL_VEHICLES - departed

    traci.close()

    df = pd.DataFrame(rows)

    summary = {
        "seed": seed,
        "controller": controller_name,
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "total_departed": departed,
        "total_arrived": arrived,
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": final_buffered / EXPECTED_TOTAL_VEHICLES,
    }

    return rows, summary


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


def simulation_step_with_stats(stats):
    traci.simulationStep()
    stats["departed"] += traci.simulation.getDepartedNumber()
    stats["arrived"] += traci.simulation.getArrivedNumber()


def collect_qmix_row(seed, decision, actions, stats):
    return {
        "seed": seed,
        "controller": "QMIX 3 Agents",
        "step": traci.simulation.getTime(),
        "decision": decision,
        "action_j1": actions[0],
        "action_j2": actions[1],
        "action_j3": actions[2],
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "departed_cumulative": stats["departed"],
        "arrived_cumulative": stats["arrived"],
    }


def run_qmix_yellow(env, seed, selected_phases, stats, rows, decision, actions):
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

            rows.append(
                collect_qmix_row(
                    seed=seed,
                    decision=decision,
                    actions=actions,
                    stats=stats,
                )
            )


def run_qmix_green(env, seed, selected_phases, stats, rows, decision, actions):
    for tl_id in env.tl_ids:
        traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
        traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
        env.current_green[tl_id] = selected_phases[tl_id]

    for _ in range(GREEN_DURATION):
        if env.step_count >= SIMULATION_STEPS:
            break

        simulation_step_with_stats(stats)
        env.step_count += 1

        rows.append(
            collect_qmix_row(
                seed=seed,
                decision=decision,
                actions=actions,
                stats=stats,
            )
        )


def run_qmix(seed):
    env = ThreeIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=SUMO_CONFIG,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    qmix = QMIXAgent(
        n_agents=3,
        obs_dim=3,
        state_dim=9,
        action_dim=2,
        batch_size=128,
    )

    qmix.load(MODEL_PATH)
    qmix.epsilon = 0.0

    raw_state = env.reset()
    global_state = normalize_global_state(raw_state)
    observations = split_observations(global_state)

    rows = []
    stats = {"departed": 0, "arrived": 0}
    decision = 0

    while env.step_count < SIMULATION_STEPS:
        actions = qmix.select_actions(observations)

        selected_phases = {
            "J1": action_to_phase(env, actions[0]),
            "J2": action_to_phase(env, actions[1]),
            "J3": action_to_phase(env, actions[2]),
        }

        decision += 1

        run_qmix_yellow(
            env=env,
            seed=seed,
            selected_phases=selected_phases,
            stats=stats,
            rows=rows,
            decision=decision,
            actions=actions,
        )

        run_qmix_green(
            env=env,
            seed=seed,
            selected_phases=selected_phases,
            stats=stats,
            rows=rows,
            decision=decision,
            actions=actions,
        )

        next_state = env.get_state()
        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

    final_active = get_vehicle_count()
    final_buffered = EXPECTED_TOTAL_VEHICLES - stats["departed"]

    env.close()

    df = pd.DataFrame(rows)

    summary = {
        "seed": seed,
        "controller": "QMIX 3 Agents",
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

    return rows, summary


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    all_rows = []
    summary_rows = []

    for seed in SEEDS:
        print("\n" + "=" * 70)
        print(f"Running seed {seed}")
        print("=" * 70)

        configs = [
            ("Simultaneous Fixed-Time", 0, 0),
            ("Best Offset Pattern", 45, 0),
        ]

        for controller_name, offset_j2, offset_j3 in configs:
            print(f"Evaluating {controller_name} | seed={seed}")
            rows, summary = run_fixed_or_offset(
                seed=seed,
                controller_name=controller_name,
                offset_j2=offset_j2,
                offset_j3=offset_j3,
            )

            all_rows.extend(rows)
            summary_rows.append(summary)

            print(
                f"{controller_name} | seed={seed} | "
                f"waiting={summary['mean_total_waiting_time']:.3f} | "
                f"speed={summary['mean_speed']:.3f} | "
                f"queue={summary['mean_total_queue']:.3f}"
            )

        print(f"Evaluating QMIX 3 Agents | seed={seed}")
        rows, summary = run_qmix(seed=seed)

        all_rows.extend(rows)
        summary_rows.append(summary)

        print(
            f"QMIX 3 Agents | seed={seed} | "
            f"waiting={summary['mean_total_waiting_time']:.3f} | "
            f"speed={summary['mean_speed']:.3f} | "
            f"queue={summary['mean_total_queue']:.3f}"
        )

    raw_df = pd.DataFrame(all_rows).round(3)
    raw_df.to_csv(OUTPUT_RAW, index=False)

    seed_summary_df = pd.DataFrame(summary_rows).round(3)

    grouped = (
        seed_summary_df
        .groupby("controller")
        .agg({
            "mean_total_waiting_time": ["mean", "std"],
            "mean_speed": ["mean", "std"],
            "mean_total_queue": ["mean", "std"],
            "mean_vehicle_count": ["mean", "std"],
            "buffered_ratio": ["mean", "std"],
        })
    )

    grouped.columns = [
        "_".join(col).strip()
        for col in grouped.columns.values
    ]

    grouped = grouped.reset_index().round(3)
    grouped.to_csv(OUTPUT_SUMMARY, index=False)

    print("\n=== Per-Seed Summary ===")
    print(seed_summary_df.to_string(index=False))

    print("\n=== Multi-Seed Controller Summary ===")
    print(grouped.to_string(index=False))

    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()