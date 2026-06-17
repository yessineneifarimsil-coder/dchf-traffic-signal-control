import os
import sys
import pandas as pd
import traci


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")

sys.path.append(ENV_DIR)

from two_intersection_env import TwoIntersectionEnv
from qmix_agent import QMIXAgent


SUMO_BINARY = "sumo"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3

MODEL_PATH = "results/raw/qmix_corridor_model_v2.pth"

DEMAND_SCENARIOS = {
    "low": {
        "folder": "demand_low",
        "expected_total_vehicles": 1396,
        "multiplier": 0.50,
    },
    "medium": {
        "folder": "demand_medium",
        "expected_total_vehicles": 2800,
        "multiplier": 1.00,
    },
    "high": {
        "folder": "demand_high",
        "expected_total_vehicles": 4204,
        "multiplier": 1.50,
    },
    "saturation": {
        "folder": "demand_saturation",
        "expected_total_vehicles": 5600,
        "multiplier": 2.00,
    },
    "oversaturation": {
        "folder": "demand_oversaturation",
        "expected_total_vehicles": 6996,
        "multiplier": 2.50,
    },
}

OUTPUT_RAW = "results/raw/qmix_demand_sensitivity_raw.csv"
OUTPUT_SUMMARY = "results/tables/qmix_demand_sensitivity_summary.csv"
OUTPUT_COMPARISON = "results/tables/demand_best_offset_vs_qmix.csv"

BEST_OFFSET_FILE = "results/tables/demand_offset_best_summary.csv"


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


def collect_row(env, demand_name, demand_multiplier, decision, actions, reward, done, stats):
    return {
        "demand_scenario": demand_name,
        "demand_multiplier": demand_multiplier,
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
        "departed_cumulative": stats["departed"],
        "arrived_cumulative": stats["arrived"],
        "reward": reward,
        "done": done,
    }


def simulation_step_with_stats(stats):
    traci.simulationStep()
    stats["departed"] += traci.simulation.getDepartedNumber()
    stats["arrived"] += traci.simulation.getArrivedNumber()


def run_yellow_with_logging(
    env,
    demand_name,
    demand_multiplier,
    selected_phases,
    rows,
    decision,
    actions,
    stats,
):
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
                collect_row(
                    env=env,
                    demand_name=demand_name,
                    demand_multiplier=demand_multiplier,
                    decision=decision,
                    actions=actions,
                    reward=0.0,
                    done=False,
                    stats=stats,
                )
            )


def run_green_with_logging(
    env,
    demand_name,
    demand_multiplier,
    selected_phases,
    rows,
    decision,
    actions,
    stats,
):
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
                demand_name=demand_name,
                demand_multiplier=demand_multiplier,
                decision=decision,
                actions=actions,
                reward=reward,
                done=done,
                stats=stats,
            )
        )


def evaluate_qmix_for_demand(demand_name, scenario_info):
    sumo_config = (
        "sumo_scenarios/two_intersections/"
        f"demand_sensitivity/{scenario_info['folder']}/corridor_turning.sumocfg"
    )

    expected_total = scenario_info["expected_total_vehicles"]
    demand_multiplier = scenario_info["multiplier"]

    env = TwoIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=sumo_config,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=0,
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
    stats = {
        "departed": 0,
        "arrived": 0,
    }

    while env.step_count < SIMULATION_STEPS:
        actions = qmix.select_actions(observations)

        selected_phases = {
            "J1": action_to_phase(env, actions[0]),
            "J2": action_to_phase(env, actions[1]),
        }

        decision += 1

        run_yellow_with_logging(
            env=env,
            demand_name=demand_name,
            demand_multiplier=demand_multiplier,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
            stats=stats,
        )

        run_green_with_logging(
            env=env,
            demand_name=demand_name,
            demand_multiplier=demand_multiplier,
            selected_phases=selected_phases,
            rows=rows,
            decision=decision,
            actions=actions,
            stats=stats,
        )

        next_state = env.get_state()
        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

    final_active = get_vehicle_count()
    final_buffered = expected_total - stats["departed"]

    env.close()

    df = pd.DataFrame(rows)

    summary = {
        "demand_scenario": demand_name,
        "demand_multiplier": demand_multiplier,
        "controller": "QMIX V2 transferred",
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
        "buffered_ratio": final_buffered / expected_total if expected_total > 0 else 0.0,
    }

    return rows, summary


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    all_raw_rows = []
    summary_rows = []

    for demand_name, scenario_info in DEMAND_SCENARIOS.items():
        print("\n" + "=" * 70)
        print(f"Evaluating QMIX V2 transferred under demand = {demand_name}")
        print("=" * 70)

        rows, summary = evaluate_qmix_for_demand(demand_name, scenario_info)

        all_raw_rows.extend(rows)
        summary_rows.append(summary)

        print(
            f"demand={demand_name} | "
            f"waiting={summary['mean_total_waiting_time']:.3f} | "
            f"speed={summary['mean_speed']:.3f} | "
            f"queue={summary['mean_total_queue']:.3f} | "
            f"departed={summary['total_departed']} | "
            f"buffered={summary['final_buffered']}"
        )

    raw_df = pd.DataFrame(all_raw_rows).round(3)
    summary_df = pd.DataFrame(summary_rows).round(3)

    raw_df.to_csv(OUTPUT_RAW, index=False)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    best_offset_df = pd.read_csv(BEST_OFFSET_FILE)

    comparison_rows = []

    for _, qmix_row in summary_df.iterrows():
        demand_name = qmix_row["demand_scenario"]

        best_row = best_offset_df[
            best_offset_df["demand_scenario"] == demand_name
        ].iloc[0]

        qmix_waiting = qmix_row["mean_total_waiting_time"]
        best_waiting = best_row["best_waiting_time"]

        gap_percent = ((qmix_waiting - best_waiting) / best_waiting) * 100

        comparison_rows.append(
            {
                "demand_scenario": demand_name,
                "demand_multiplier": qmix_row["demand_multiplier"],
                "best_offset": best_row["best_waiting_offset"],
                "best_offset_waiting_time": best_waiting,
                "qmix_waiting_time": qmix_waiting,
                "qmix_gap_vs_best_offset_percent": gap_percent,
                "best_offset_speed": best_row["best_speed"],
                "qmix_speed": qmix_row["mean_speed"],
                "best_offset_queue": best_row["best_queue"],
                "qmix_queue": qmix_row["mean_total_queue"],
                "best_offset_buffered_ratio": best_row["buffered_ratio_at_best_waiting"],
                "qmix_buffered_ratio": qmix_row["buffered_ratio"],
            }
        )

    comparison_df = pd.DataFrame(comparison_rows).round(3)
    comparison_df.to_csv(OUTPUT_COMPARISON, index=False)

    print("\n=== QMIX Demand Sensitivity Summary ===")
    print(summary_df.to_string(index=False))

    print("\n=== Best Offset vs QMIX by Demand Scenario ===")
    print(comparison_df.to_string(index=False))

    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"QMIX summary saved to: {OUTPUT_SUMMARY}")
    print(f"Comparison saved to: {OUTPUT_COMPARISON}")


if __name__ == "__main__":
    main()