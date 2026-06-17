import os
import sys
import pandas as pd
import traci


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
ENV_DIR = os.path.join(SRC_DIR, "env", "two_intersections")
QMIX_DIR = os.path.join(SRC_DIR, "qmix")

sys.path.append(ENV_DIR)
sys.path.insert(0, QMIX_DIR)

from two_intersection_env import TwoIntersectionEnv
from qmix_agent import QMIXAgent


SUMO_BINARY = "sumo"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE_LENGTH = 2 * (GREEN_DURATION + YELLOW_DURATION)

SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

MODEL_PATH = "results/raw/qmix_corridor_model_v2.pth"
BEST_OFFSET_FILE = "results/tables/demand_offset_best_summary.csv"

OUTPUT_RAW = "results/raw/spillback_demand_raw.csv"
OUTPUT_SUMMARY = "results/tables/spillback_demand_summary.csv"

# Approximate vehicle storage space:
# vehicle length = 5.0 m, minGap approximately 2.5 m
VEHICLE_STORAGE_SPACE = 7.5

SPILLBACK_THRESHOLD = 0.80
SEVERE_SPILLBACK_THRESHOLD = 0.95

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


def get_sumo_config(scenario_info):
    return (
        "sumo_scenarios/two_intersections/"
        f"demand_sensitivity/{scenario_info['folder']}/corridor_turning.sumocfg"
    )


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


def safe_lane_ids(edge_id):
    lane_ids = []

    for lane_id in traci.lane.getIDList():
        if lane_id.startswith(edge_id + "_"):
            lane_ids.append(lane_id)

    return lane_ids


def compute_direction_storage_capacity(lane_ids):
    capacity = 0.0

    for lane_id in lane_ids:
        lane_length = traci.lane.getLength(lane_id)
        capacity += lane_length / VEHICLE_STORAGE_SPACE

    return capacity


def compute_direction_vehicle_count(lane_ids):
    return sum(traci.lane.getLastStepVehicleNumber(lane_id) for lane_id in lane_ids)


def compute_direction_halting_count(lane_ids):
    return sum(traci.lane.getLastStepHaltingNumber(lane_id) for lane_id in lane_ids)


def get_central_link_spillback_metrics():
    """
    Measures storage pressure on the central corridor link J1 <-> J2.
    We compute occupancy ratio separately for E1 and -E1, then use the maximum
    directional ratio as the central spillback risk indicator.
    """
    e1_lanes = safe_lane_ids("E1")
    neg_e1_lanes = safe_lane_ids("-E1")

    e1_capacity = compute_direction_storage_capacity(e1_lanes)
    neg_e1_capacity = compute_direction_storage_capacity(neg_e1_lanes)

    e1_vehicle_count = compute_direction_vehicle_count(e1_lanes)
    neg_e1_vehicle_count = compute_direction_vehicle_count(neg_e1_lanes)

    e1_halting = compute_direction_halting_count(e1_lanes)
    neg_e1_halting = compute_direction_halting_count(neg_e1_lanes)

    e1_occupancy_ratio = (
        e1_vehicle_count / e1_capacity if e1_capacity > 0 else 0.0
    )
    neg_e1_occupancy_ratio = (
        neg_e1_vehicle_count / neg_e1_capacity if neg_e1_capacity > 0 else 0.0
    )

    max_central_occupancy_ratio = max(e1_occupancy_ratio, neg_e1_occupancy_ratio)

    return {
        "E1_vehicle_count": e1_vehicle_count,
        "neg_E1_vehicle_count": neg_e1_vehicle_count,
        "E1_halting": e1_halting,
        "neg_E1_halting": neg_e1_halting,
        "E1_occupancy_ratio": e1_occupancy_ratio,
        "neg_E1_occupancy_ratio": neg_e1_occupancy_ratio,
        "max_central_occupancy_ratio": max_central_occupancy_ratio,
        "spillback_risk_80": int(max_central_occupancy_ratio >= SPILLBACK_THRESHOLD),
        "severe_spillback_risk_95": int(
            max_central_occupancy_ratio >= SEVERE_SPILLBACK_THRESHOLD
        ),
    }


def collect_common_row(controller, demand_name, multiplier, step, stats):
    central_metrics = get_central_link_spillback_metrics()

    row = {
        "controller": controller,
        "demand_scenario": demand_name,
        "demand_multiplier": multiplier,
        "step": step,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "departed_cumulative": stats["departed"],
        "arrived_cumulative": stats["arrived"],
    }

    row.update(central_metrics)

    return row


def simulation_step_with_stats(stats):
    traci.simulationStep()
    stats["departed"] += traci.simulation.getDepartedNumber()
    stats["arrived"] += traci.simulation.getArrivedNumber()


def run_best_offset(demand_name, scenario_info, offset):
    sumo_config = get_sumo_config(scenario_info)
    expected_total = scenario_info["expected_total_vehicles"]

    traci.start([SUMO_BINARY, "-c", sumo_config, "--seed", "0"])

    rows = []
    stats = {"departed": 0, "arrived": 0}

    for step in range(SIMULATION_STEPS):
        j1_phase = phase_from_cycle_time(step)
        j2_phase = phase_from_cycle_time(step - offset)

        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhase("J2", j2_phase)

        simulation_step_with_stats(stats)

        rows.append(
            collect_common_row(
                controller="Best Offset Fixed-Time",
                demand_name=demand_name,
                multiplier=scenario_info["multiplier"],
                step=step + 1,
                stats=stats,
            )
        )

    final_active = get_vehicle_count()
    final_buffered = expected_total - stats["departed"]

    traci.close()

    return rows, final_active, final_buffered


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


def log_current_qmix_second(
    env,
    rows,
    controller,
    demand_name,
    multiplier,
    stats,
):
    rows.append(
        collect_common_row(
            controller=controller,
            demand_name=demand_name,
            multiplier=multiplier,
            step=env.step_count,
            stats=stats,
        )
    )


def run_qmix_yellow(
    env,
    selected_phases,
    stats,
    rows,
    controller,
    demand_name,
    multiplier,
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

            log_current_qmix_second(
                env=env,
                rows=rows,
                controller=controller,
                demand_name=demand_name,
                multiplier=multiplier,
                stats=stats,
            )


def run_qmix_green(
    env,
    selected_phases,
    stats,
    rows,
    controller,
    demand_name,
    multiplier,
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

        log_current_qmix_second(
            env=env,
            rows=rows,
            controller=controller,
            demand_name=demand_name,
            multiplier=multiplier,
            stats=stats,
        )


def run_qmix_transferred(demand_name, scenario_info):
    sumo_config = get_sumo_config(scenario_info)
    expected_total = scenario_info["expected_total_vehicles"]
    multiplier = scenario_info["multiplier"]

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
    stats = {"departed": 0, "arrived": 0}

    while env.step_count < SIMULATION_STEPS:
        actions = qmix.select_actions(observations)

        selected_phases = {
            "J1": action_to_phase(env, actions[0]),
            "J2": action_to_phase(env, actions[1]),
        }

        run_qmix_yellow(
            env=env,
            selected_phases=selected_phases,
            stats=stats,
            rows=rows,
            controller="QMIX V2 transferred",
            demand_name=demand_name,
            multiplier=multiplier,
        )

        run_qmix_green(
            env=env,
            selected_phases=selected_phases,
            stats=stats,
            rows=rows,
            controller="QMIX V2 transferred",
            demand_name=demand_name,
            multiplier=multiplier,
        )

        next_state = env.get_state()
        global_state = normalize_global_state(next_state)
        observations = split_observations(global_state)

    final_active = get_vehicle_count()
    final_buffered = expected_total - stats["departed"]

    env.close()

    return rows, final_active, final_buffered


def summarize_rows(rows, final_active, final_buffered, expected_total):
    df = pd.DataFrame(rows)

    return {
        "controller": df["controller"].iloc[0],
        "demand_scenario": df["demand_scenario"].iloc[0],
        "demand_multiplier": df["demand_multiplier"].iloc[0],
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "mean_speed": df["mean_speed"].mean(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "mean_central_occupancy_ratio": df["max_central_occupancy_ratio"].mean(),
        "max_central_occupancy_ratio": df["max_central_occupancy_ratio"].max(),
        "spillback_frequency_80": df["spillback_risk_80"].mean(),
        "severe_spillback_frequency_95": df["severe_spillback_risk_95"].mean(),
        "mean_E1_halting": df["E1_halting"].mean(),
        "mean_neg_E1_halting": df["neg_E1_halting"].mean(),
        "final_active": final_active,
        "final_buffered": final_buffered,
        "buffered_ratio": final_buffered / expected_total if expected_total > 0 else 0.0,
    }


def main():
    os.makedirs("results/raw", exist_ok=True)
    os.makedirs("results/tables", exist_ok=True)

    best_offset_df = pd.read_csv(BEST_OFFSET_FILE)

    raw_rows = []
    summary_rows = []

    for demand_name, scenario_info in DEMAND_SCENARIOS.items():
        expected_total = scenario_info["expected_total_vehicles"]

        best_offset = int(
            best_offset_df[
                best_offset_df["demand_scenario"] == demand_name
            ]["best_waiting_offset"].iloc[0]
        )

        print("\n" + "=" * 70)
        print(f"Demand scenario: {demand_name}")
        print(f"Best offset: {best_offset} s")
        print("=" * 70)

        print("Running best offset spillback analysis...")
        offset_rows, offset_active, offset_buffered = run_best_offset(
            demand_name=demand_name,
            scenario_info=scenario_info,
            offset=best_offset,
        )

        raw_rows.extend(offset_rows)
        summary_rows.append(
            summarize_rows(
                rows=offset_rows,
                final_active=offset_active,
                final_buffered=offset_buffered,
                expected_total=expected_total,
            )
        )

        print("Running QMIX V2 transferred spillback analysis...")
        qmix_rows, qmix_active, qmix_buffered = run_qmix_transferred(
            demand_name=demand_name,
            scenario_info=scenario_info,
        )

        raw_rows.extend(qmix_rows)
        summary_rows.append(
            summarize_rows(
                rows=qmix_rows,
                final_active=qmix_active,
                final_buffered=qmix_buffered,
                expected_total=expected_total,
            )
        )

    raw_df = pd.DataFrame(raw_rows).round(3)
    summary_df = pd.DataFrame(summary_rows).round(3)

    raw_df.to_csv(OUTPUT_RAW, index=False)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    print("\n=== Spillback Demand Summary ===")
    print(summary_df.to_string(index=False))

    print(f"\nRaw spillback results saved to: {OUTPUT_RAW}")
    print(f"Spillback summary saved to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()