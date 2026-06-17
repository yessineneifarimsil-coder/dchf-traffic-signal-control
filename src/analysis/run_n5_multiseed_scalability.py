import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import traci


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
ENV_DIR = os.path.join(SRC_DIR, "env", "scalability")
QMIX_DIR = os.path.join(SRC_DIR, "qmix")

sys.path.append(ENV_DIR)
sys.path.append(QMIX_DIR)

from generic_corridor_env import GenericCorridorEnv
from qmix_agent import QMIXAgent


SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/scalability/corridor_5x2_d300m/corridor.sumocfg"
ROUTE_FILE = "sumo_scenarios/scalability/corridor_5x2_d300m/corridor.rou.xml"

MODEL_PATH = "results/raw/qmix_n5_scalability_model.pth"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE = 90

N_AGENTS = 5
OBS_DIM = 3
STATE_DIM = 15
ACTION_DIM = 2

QUEUE_NORMALIZER = 300.0

SEEDS = [0, 1, 2, 3, 4]
BEST_OFFSET = 45

OUT_CONTROLLER = "results/tables/n5_multiseed_scalability_controller_summary.csv"
OUT_BY_SEED = "results/tables/n5_multiseed_scalability_dchf_by_seed.csv"
OUT_FINAL = "results/tables/n5_multiseed_scalability_summary.csv"

os.makedirs("results/tables", exist_ok=True)
os.makedirs("results/raw", exist_ok=True)


def safe_close():
    try:
        traci.close()
    except Exception:
        pass


def get_expected_vehicles(route_file):
    tree = ET.parse(route_file)
    root = tree.getroot()

    expected = 0.0
    for flow in root.findall("flow"):
        begin = float(flow.attrib.get("begin", 0))
        end = float(flow.attrib.get("end", SIMULATION_STEPS))
        vehs_per_hour = float(flow.attrib.get("vehsPerHour", 0))
        expected += vehs_per_hour * ((end - begin) / 3600.0)

    return expected


def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())


def get_mean_speed():
    vehicles = traci.vehicle.getIDList()
    if not vehicles:
        return 0.0
    return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)


def get_total_queue():
    total = 0
    for lane_id in traci.lane.getIDList():
        if not lane_id.startswith(":"):
            total += traci.lane.getLastStepHaltingNumber(lane_id)
    return total


def classify_gap(gap_percent):
    if gap_percent <= 5:
        return "Effective coordination zone"
    if gap_percent <= 10:
        return "Marginal coordination zone"
    return "Outside coordination horizon"


def classify_capacity(buffered_ratio):
    if buffered_ratio < 0.01:
        return "Unconstrained"
    if buffered_ratio < 0.10:
        return "Mild insertion pressure"
    if buffered_ratio < 0.25:
        return "Capacity-limited"
    return "Oversaturated"


def phase_from_cycle_position(pos):
    if pos < GREEN_DURATION:
        return 0
    if pos < GREEN_DURATION + YELLOW_DURATION:
        return 1
    if pos < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return 2
    return 3


def apply_progression_offsets(base_offset):
    tl_ids = [f"J{i}" for i in range(1, N_AGENTS + 1)]
    t = int(traci.simulation.getTime())

    for idx, tl_id in enumerate(tl_ids):
        offset = (idx * base_offset) % CYCLE
        pos = (t + offset) % CYCLE
        phase = phase_from_cycle_position(pos)
        traci.trafficlight.setPhase(tl_id, phase)


def summarize_rows(rows, controller, seed, expected, total_departed, total_arrived, total_teleports):
    df = pd.DataFrame(rows)

    buffered_ratio = max(0.0, (expected - total_departed) / expected) if expected > 0 else 0.0

    return {
        "seed": seed,
        "controller": controller,
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "total_expected": expected,
        "total_departed": total_departed,
        "total_arrived": total_arrived,
        "buffered_ratio": buffered_ratio,
        "capacity_regime": classify_capacity(buffered_ratio),
        "total_teleports": total_teleports,
    }


def run_offset_controller(seed, base_offset, controller_name):
    safe_close()

    traci.start([
        SUMO_BINARY,
        "-c", SUMO_CONFIG,
        "--no-step-log", "true",
        "--seed", str(seed),
    ])

    expected = get_expected_vehicles(ROUTE_FILE)

    rows = []
    total_departed = 0
    total_arrived = 0
    total_teleports = 0

    for step in range(SIMULATION_STEPS):
        apply_progression_offsets(base_offset)
        traci.simulationStep()

        departed = traci.simulation.getDepartedNumber()
        arrived = traci.simulation.getArrivedNumber()
        teleports = traci.simulation.getStartingTeleportNumber()

        total_departed += departed
        total_arrived += arrived
        total_teleports += teleports

        rows.append({
            "step": step,
            "vehicle_count": len(traci.vehicle.getIDList()),
            "total_waiting_time": get_total_waiting_time(),
            "mean_speed": get_mean_speed(),
            "total_queue": get_total_queue(),
            "departed_this_step": departed,
            "arrived_this_step": arrived,
            "teleports_this_step": teleports,
            "total_departed": total_departed,
            "total_arrived": total_arrived,
            "total_teleports": total_teleports,
        })

    safe_close()

    return summarize_rows(
        rows,
        controller_name,
        seed,
        expected,
        total_departed,
        total_arrived,
        total_teleports,
    )


def normalize_global_state(state):
    normalized = []
    for i in range(0, len(state), 3):
        normalized.append(state[i] / QUEUE_NORMALIZER)
        normalized.append(state[i + 1] / QUEUE_NORMALIZER)
        normalized.append(state[i + 2])
    return normalized


def split_observations(global_state):
    return [
        global_state[i:i + OBS_DIM]
        for i in range(0, len(global_state), OBS_DIM)
    ]


def log_qmix_step(rows, decision, actions, total_departed, total_arrived, total_teleports):
    row = {
        "step": int(traci.simulation.getTime()),
        "decision": decision,
        "vehicle_count": len(traci.vehicle.getIDList()),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "departed_this_step": traci.simulation.getDepartedNumber(),
        "arrived_this_step": traci.simulation.getArrivedNumber(),
        "teleports_this_step": traci.simulation.getStartingTeleportNumber(),
        "total_departed": total_departed,
        "total_arrived": total_arrived,
        "total_teleports": total_teleports,
    }

    for i, action in enumerate(actions, start=1):
        row[f"action_j{i}"] = action
        row[f"J{i}_phase"] = traci.trafficlight.getPhase(f"J{i}")

    rows.append(row)


def run_qmix_controller(seed):
    safe_close()

    expected = get_expected_vehicles(ROUTE_FILE)

    env = GenericCorridorEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=SUMO_CONFIG,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=seed,
    )

    qmix = QMIXAgent(
        n_agents=N_AGENTS,
        obs_dim=OBS_DIM,
        state_dim=STATE_DIM,
        action_dim=ACTION_DIM,
        learning_rate=5e-4,
        epsilon_start=0.0,
        epsilon_min=0.0,
        epsilon_decay=1.0,
        buffer_capacity=150_000,
        batch_size=128,
        target_update_freq=200,
    )

    qmix.load(MODEL_PATH)
    qmix.epsilon = 0.0

    raw_state = env.reset()

    rows = []
    decision = 0
    total_departed = 0
    total_arrived = 0
    total_teleports = 0
    done = False

    while not done:
        global_state = normalize_global_state(raw_state)
        observations = split_observations(global_state)
        actions = qmix.select_actions(observations)

        selected_phases = {
            tl_id: env.action_to_phase(actions[i])
            for i, tl_id in enumerate(env.tl_ids)
        }

        yellow_needed = False

        for tl_id in env.tl_ids:
            old_green = env.current_green[tl_id]
            new_green = selected_phases[tl_id]

            if old_green != new_green:
                yellow_phase = (
                    env.PHASE0_YELLOW
                    if old_green == env.PHASE0_GREEN
                    else env.PHASE2_YELLOW
                )
                traci.trafficlight.setPhase(tl_id, yellow_phase)
                traci.trafficlight.setPhaseDuration(tl_id, YELLOW_DURATION)
                yellow_needed = True

        if yellow_needed:
            for _ in range(YELLOW_DURATION):
                if env.step_count >= SIMULATION_STEPS:
                    break

                traci.simulationStep()
                env.step_count += 1

                total_departed += traci.simulation.getDepartedNumber()
                total_arrived += traci.simulation.getArrivedNumber()
                total_teleports += traci.simulation.getStartingTeleportNumber()

                log_qmix_step(rows, decision, actions, total_departed, total_arrived, total_teleports)

        for tl_id in env.tl_ids:
            traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
            traci.trafficlight.setPhaseDuration(tl_id, GREEN_DURATION)
            env.current_green[tl_id] = selected_phases[tl_id]

        for _ in range(GREEN_DURATION):
            if env.step_count >= SIMULATION_STEPS:
                break

            traci.simulationStep()
            env.step_count += 1

            total_departed += traci.simulation.getDepartedNumber()
            total_arrived += traci.simulation.getArrivedNumber()
            total_teleports += traci.simulation.getStartingTeleportNumber()

            log_qmix_step(rows, decision, actions, total_departed, total_arrived, total_teleports)

        raw_state = env.get_state()
        decision += 1
        done = env.step_count >= SIMULATION_STEPS

    env.close()

    return summarize_rows(
        rows,
        "QMIX 5 Agents",
        seed,
        expected,
        total_departed,
        total_arrived,
        total_teleports,
    )


def build_dchf_by_seed(controller_df):
    rows = []

    for seed in SEEDS:
        seed_df = controller_df[controller_df["seed"] == seed]

        sim = seed_df[seed_df["controller"] == "Simultaneous Fixed-Time"].iloc[0]
        off = seed_df[seed_df["controller"] == f"Progression Offset {BEST_OFFSET}s"].iloc[0]
        qmix = seed_df[seed_df["controller"] == "QMIX 5 Agents"].iloc[0]

        sim_wait = sim["mean_total_waiting_time"]
        off_wait = off["mean_total_waiting_time"]
        qmix_wait = qmix["mean_total_waiting_time"]

        offset_gain = ((sim_wait - off_wait) / sim_wait) * 100
        qmix_gain = ((sim_wait - qmix_wait) / sim_wait) * 100
        qmix_gap = ((qmix_wait - off_wait) / off_wait) * 100

        rows.append({
            "seed": seed,
            "scenario": "N5_d300_medium",
            "N": 5,
            "distance_m": 300,
            "demand": "medium",
            "simultaneous_waiting_time": sim_wait,
            "best_offset_waiting_time": off_wait,
            "qmix_waiting_time": qmix_wait,
            "offset_coordination_gain_percent": offset_gain,
            "qmix_coordination_gain_percent": qmix_gain,
            "qmix_gap_percent": qmix_gap,
            "dchf_regime": classify_gap(qmix_gap),
            "qmix_buffered_ratio": qmix["buffered_ratio"],
            "qmix_capacity_regime": qmix["capacity_regime"],
            "qmix_total_teleports": qmix["total_teleports"],
        })

    return pd.DataFrame(rows)


def build_final_summary(dchf_df):
    effective_rate = (dchf_df["dchf_regime"] == "Effective coordination zone").mean() * 100

    return pd.DataFrame([{
        "scenario": "N5_d300_medium",
        "N": 5,
        "seeds": len(dchf_df),
        "qmix_gap_mean": dchf_df["qmix_gap_percent"].mean(),
        "qmix_gap_std": dchf_df["qmix_gap_percent"].std(ddof=1),
        "qmix_gain_mean": dchf_df["qmix_coordination_gain_percent"].mean(),
        "qmix_gain_std": dchf_df["qmix_coordination_gain_percent"].std(ddof=1),
        "qmix_buffered_ratio_mean": dchf_df["qmix_buffered_ratio"].mean(),
        "qmix_buffered_ratio_std": dchf_df["qmix_buffered_ratio"].std(ddof=1),
        "qmix_total_teleports_mean": dchf_df["qmix_total_teleports"].mean(),
        "effective_regime_stability_percent": effective_rate,
        "final_interpretation": (
            "Stable effective scalability at N=5"
            if effective_rate == 100
            else "Partially stable scalability at N=5"
        ),
    }])


def main():
    controller_rows = []

    for seed in SEEDS:
        print("\n" + "=" * 80)
        print(f"Running N=5 multi-seed validation | seed={seed}")
        print("=" * 80)

        print("Running simultaneous fixed-time...")
        sim_summary = run_offset_controller(
            seed=seed,
            base_offset=0,
            controller_name="Simultaneous Fixed-Time",
        )
        controller_rows.append(sim_summary)
        print(pd.DataFrame([sim_summary]).round(3).to_string(index=False))

        print("\nRunning progression offset 45s...")
        offset_summary = run_offset_controller(
            seed=seed,
            base_offset=BEST_OFFSET,
            controller_name=f"Progression Offset {BEST_OFFSET}s",
        )
        controller_rows.append(offset_summary)
        print(pd.DataFrame([offset_summary]).round(3).to_string(index=False))

        print("\nRunning QMIX 5 agents...")
        qmix_summary = run_qmix_controller(seed=seed)
        controller_rows.append(qmix_summary)
        print(pd.DataFrame([qmix_summary]).round(3).to_string(index=False))

    controller_df = pd.DataFrame(controller_rows).round(3)
    controller_df.to_csv(OUT_CONTROLLER, index=False)

    dchf_df = build_dchf_by_seed(controller_df).round(3)
    dchf_df.to_csv(OUT_BY_SEED, index=False)

    final_df = build_final_summary(dchf_df).round(3)
    final_df.to_csv(OUT_FINAL, index=False)

    print("\n" + "=" * 80)
    print("N=5 MULTI-SEED DCHF VALIDATION FINISHED")
    print("=" * 80)

    print("\nDCHF by seed:")
    print(dchf_df.to_string(index=False))

    print("\nFinal summary:")
    print(final_df.to_string(index=False))

    print(f"\nSaved controller summary: {OUT_CONTROLLER}")
    print(f"Saved DCHF by seed: {OUT_BY_SEED}")
    print(f"Saved final summary: {OUT_FINAL}")


if __name__ == "__main__":
    main()