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
MODEL_PATH = "results/raw/qmix_three_intersections_model.pth"

BEST_OFFSET_FILE = "results/tables/three_intersection_d23_offset_best_summary.csv"

OUTPUT_RAW = "results/raw/qmix_three_intersection_d23_sensitivity_raw.csv"
OUTPUT_SUMMARY = "results/tables/three_intersection_d23_best_offset_vs_qmix.csv"

D23_VALUES = [100, 200, 300, 500, 750, 1000]

SIMULATION_STEPS = 3600
EXPECTED_TOTAL_VEHICLES = 3400

GREEN_DURATION = 42
YELLOW_DURATION = 3

QUEUE_NORMALIZER = 200.0


def get_config_path(d23):
    return (
        "sumo_scenarios/three_intersections/"
        f"distance_sensitivity/d23_{d23}m/corridor_3x2_through.sumocfg"
    )


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


def simulation_step_with_stats(stats):
    traci.simulationStep()
    stats["departed"] += traci.simulation.getDepartedNumber()
    stats["arrived"] += traci.simulation.getArrivedNumber()


def collect_row(d23, decision, actions, stats):
    return {
        "d23": d23,
        "decision": decision,
        "step": traci.simulation.getTime(),
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


def run_qmix_for_d23(d23, sumo_seed=0):
    env = ThreeIntersectionEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=get_config_path(d23),
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=sumo_seed,
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

        # Yellow transition, logged per second
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
                rows.append(collect_row(d23, decision, actions, stats))

        # Green phase, logged per second
        for tl_id in env.tl_ids:
            traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
            traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
            env.current_green[tl_id] = selected_phases[tl_id]

        for _ in range(GREEN_DURATION):
            if env.step_count >= SIMULATION_STEPS:
                break

            simulation_step_with_stats(stats)
            env.step_count += 1
            rows.append(collect_row(d23, decision, actions, stats))

        next_state = env.get_state()
        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

    final_active = get_vehicle_count()
    final_buffered = EXPECTED_TOTAL_VEHICLES - stats["departed"]

    env.close()

    df = pd.DataFrame(rows)

    summary = {
        "d23": d23,
        "seed": sumo_seed,
        "qmix_rows": len(df),
        "qmix_mean_vehicle_count": df["vehicle_count"].mean(),
        "qmix_max_vehicle_count": df["vehicle_count"].max(),
        "qmix_waiting_time": df["total_waiting_time"].mean(),
        "qmix_max_waiting_time": df["total_waiting_time"].max(),
        "qmix_speed": df["mean_speed"].mean(),
        "qmix_min_speed": df["mean_speed"].min(),
        "qmix_queue": df["total_queue"].mean(),
        "qmix_max_queue": df["total_queue"].max(),
        "qmix_total_departed": stats["departed"],
        "qmix_total_arrived": stats["arrived"],
        "qmix_final_active": final_active,
        "qmix_final_buffered": final_buffered,
        "qmix_buffered_ratio": final_buffered / EXPECTED_TOTAL_VEHICLES,
    }

    return rows, summary


def classify_gap(gap):
    if gap <= 5:
        return "Effective coordination zone"
    if gap <= 10:
        return "Marginal coordination zone"
    return "Outside coordination horizon"


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    best_offset_df = pd.read_csv(BEST_OFFSET_FILE)

    all_rows = []
    summary_rows = []

    for d23 in D23_VALUES:
        print("\n" + "=" * 70)
        print(f"Evaluating QMIX 3-agent transfer for d23={d23} m")
        print("=" * 70)

        rows, qmix_summary = run_qmix_for_d23(d23, sumo_seed=0)

        all_rows.extend(rows)

        best_row = best_offset_df[best_offset_df["d23"] == d23].iloc[0]

        best_waiting = best_row["best_waiting_time"]
        qmix_waiting = qmix_summary["qmix_waiting_time"]

        gap = ((qmix_waiting - best_waiting) / best_waiting) * 100

        combined = {
            "d23": d23,
            "best_offset_j2": best_row["best_waiting_offset_j2"],
            "best_offset_j3": best_row["best_waiting_offset_j3"],
            "best_offset_waiting_time": best_waiting,
            "qmix_waiting_time": qmix_waiting,
            "qmix_gap_vs_best_offset_percent": gap,
            "coordination_regime": classify_gap(gap),
            "best_offset_speed": best_row["speed_at_best_waiting"],
            "qmix_speed": qmix_summary["qmix_speed"],
            "best_offset_queue": best_row["queue_at_best_waiting"],
            "qmix_queue": qmix_summary["qmix_queue"],
            "best_offset_buffered_ratio": best_row["buffered_ratio_at_best_waiting"],
            "qmix_buffered_ratio": qmix_summary["qmix_buffered_ratio"],
            "qmix_total_departed": qmix_summary["qmix_total_departed"],
            "qmix_total_arrived": qmix_summary["qmix_total_arrived"],
            "qmix_final_active": qmix_summary["qmix_final_active"],
            "qmix_final_buffered": qmix_summary["qmix_final_buffered"],
        }

        summary_rows.append(combined)

        print(
            f"d23={d23} | "
            f"best_offset_waiting={best_waiting:.3f} | "
            f"qmix_waiting={qmix_waiting:.3f} | "
            f"gap={gap:.2f}% | "
            f"{classify_gap(gap)}"
        )

    raw_df = pd.DataFrame(all_rows).round(3)
    raw_df.to_csv(OUTPUT_RAW, index=False)

    summary_df = pd.DataFrame(summary_rows).round(3)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    print("\n=== Three-Intersection d23: Best Offset vs QMIX ===")
    print(summary_df.to_string(index=False))

    print(f"\nRaw results saved to: {OUTPUT_RAW}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()