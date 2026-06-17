import os
import sys
import csv
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import traci


# ============================================================
# PATHS
# ============================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)

ENV_DIR = os.path.join(SRC_DIR, "env", "scalability")
QMIX_DIR = os.path.join(SRC_DIR, "qmix")

sys.path.append(ENV_DIR)
sys.path.append(QMIX_DIR)

from generic_corridor_env import GenericCorridorEnv
from qmix_agent import QMIXAgent


# ============================================================
# CONFIGURATION
# ============================================================

SUMO_BINARY = "sumo"

SCENARIO_DIR = "sumo_scenarios/scalability/corridor_10x2_d300m"
NOD_FILE = os.path.join(SCENARIO_DIR, "corridor.nod.xml")
EDG_FILE = os.path.join(SCENARIO_DIR, "corridor.edg.xml")
NET_FILE = os.path.join(SCENARIO_DIR, "corridor.net.xml")
ROUTE_FILE = os.path.join(SCENARIO_DIR, "corridor.rou.xml")
SUMO_CONFIG = os.path.join(SCENARIO_DIR, "corridor.sumocfg")

MODEL_PATH = "results/raw/qmix_n10_coarse_scalability_model.pth"
TRAINING_CSV = "results/raw/qmix_n10_coarse_training_log.csv"

OUT_OFFSET_SWEEP = "results/tables/n10_offset_sweep_summary.csv"
OUT_QMIX_EVAL = "results/tables/n10_qmix_evaluation_summary.csv"
OUT_DCHF = "results/tables/n10_coarse_scalability_dchf_summary.csv"

SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE = 90

N_AGENTS = 10
OBS_DIM = 3
STATE_DIM = N_AGENTS * OBS_DIM
ACTION_DIM = 2

DISTANCE_M = 300
QUEUE_NORMALIZER = 300.0

NUM_EPISODES = 500
MAX_DECISIONS_PER_EPISODE = 200

TRAIN_SEED = 0
EVAL_SEED = 0

OFFSET_CANDIDATES = [0, 15, 30, 45, 60, 75, 90]

MAIN_FLOW_PER_HOUR = 700
SIDE_FLOW_PER_HOUR = 320

os.makedirs(SCENARIO_DIR, exist_ok=True)
os.makedirs("results/raw", exist_ok=True)
os.makedirs("results/tables", exist_ok=True)


# ============================================================
# SAFE TRACI CLOSE
# ============================================================

def safe_close():
    try:
        traci.close()
    except Exception:
        pass


# ============================================================
# SCENARIO GENERATION
# ============================================================

def write_nodes():
    root = ET.Element("nodes")

    ET.SubElement(root, "node", {
        "id": "W",
        "x": str(-DISTANCE_M),
        "y": "0",
        "type": "priority",
    })

    ET.SubElement(root, "node", {
        "id": "E",
        "x": str(N_AGENTS * DISTANCE_M),
        "y": "0",
        "type": "priority",
    })

    for i in range(1, N_AGENTS + 1):
        x = str((i - 1) * DISTANCE_M)

        ET.SubElement(root, "node", {
            "id": f"J{i}",
            "x": x,
            "y": "0",
            "type": "priority",
        })

        ET.SubElement(root, "node", {
            "id": f"N{i}",
            "x": x,
            "y": str(DISTANCE_M),
            "type": "priority",
        })

        ET.SubElement(root, "node", {
            "id": f"S{i}",
            "x": x,
            "y": str(-DISTANCE_M),
            "type": "priority",
        })

    ET.ElementTree(root).write(NOD_FILE, encoding="utf-8", xml_declaration=True)
def add_edge(root, edge_id, from_node, to_node, priority="1"):
    ET.SubElement(root, "edge", {
        "id": edge_id,
        "from": from_node,
        "to": to_node,
        "priority": priority,
        "numLanes": "2",
        "speed": "13.9",
    })


def write_edges():
    root = ET.Element("edges")

    add_edge(root, "W_J1", "W", "J1")
    add_edge(root, "J1_W", "J1", "W")

    add_edge(root, f"J{N_AGENTS}_E", f"J{N_AGENTS}", "E")
    add_edge(root, f"E_J{N_AGENTS}", "E", f"J{N_AGENTS}")

    for i in range(1, N_AGENTS):
        add_edge(root, f"J{i}_J{i+1}", f"J{i}", f"J{i+1}")
        add_edge(root, f"J{i+1}_J{i}", f"J{i+1}", f"J{i}")

    for i in range(1, N_AGENTS + 1):
        add_edge(root, f"N{i}_J{i}", f"N{i}", f"J{i}")
        add_edge(root, f"J{i}_N{i}", f"J{i}", f"N{i}")
        add_edge(root, f"S{i}_J{i}", f"S{i}", f"J{i}")
        add_edge(root, f"J{i}_S{i}", f"J{i}", f"S{i}")

    ET.ElementTree(root).write(EDG_FILE, encoding="utf-8", xml_declaration=True)


def run_netconvert():
    tls_ids = ",".join([f"J{i}" for i in range(1, N_AGENTS + 1)])

    cmd = [
        "netconvert",
        "--node-files", NOD_FILE,
        "--edge-files", EDG_FILE,
        "--output-file", NET_FILE,
        "--tls.set", tls_ids,
        "--no-turnarounds", "true",
    ]

    print("Running netconvert...")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def is_side_edge(edge_id):
    return edge_id.startswith("N") or edge_id.startswith("S")


def rewrite_tls_logic():
    tree = ET.parse(NET_FILE)
    root = tree.getroot()

    old_tls = list(root.findall("tlLogic"))
    for el in old_tls:
        root.remove(el)

    connections_by_tls = {}

    for conn in root.findall("connection"):
        tl_id = conn.attrib.get("tl")
        link_index = conn.attrib.get("linkIndex")

        if tl_id is None or link_index is None:
            continue

        if tl_id not in connections_by_tls:
            connections_by_tls[tl_id] = []

        connections_by_tls[tl_id].append(conn)

    for i in range(1, N_AGENTS + 1):
        tl_id = f"J{i}"
        conns = connections_by_tls.get(tl_id, [])

        if not conns:
            print(f"Warning: no controlled connections found for {tl_id}.")
            continue

        max_index = max(int(c.attrib["linkIndex"]) for c in conns)
        state_len = max_index + 1

        side_green = ["r"] * state_len
        side_yellow = ["r"] * state_len
        main_green = ["r"] * state_len
        main_yellow = ["r"] * state_len

        for conn in conns:
            idx = int(conn.attrib["linkIndex"])
            from_edge = conn.attrib.get("from", "")

            if is_side_edge(from_edge):
                side_green[idx] = "G"
                side_yellow[idx] = "y"
            else:
                main_green[idx] = "G"
                main_yellow[idx] = "y"

        tl = ET.SubElement(root, "tlLogic", {
            "id": tl_id,
            "type": "static",
            "programID": "0",
            "offset": "0",
        })

        ET.SubElement(tl, "phase", {
            "duration": str(GREEN_DURATION),
            "state": "".join(side_green),
        })

        ET.SubElement(tl, "phase", {
            "duration": str(YELLOW_DURATION),
            "state": "".join(side_yellow),
        })

        ET.SubElement(tl, "phase", {
            "duration": str(GREEN_DURATION),
            "state": "".join(main_green),
        })

        ET.SubElement(tl, "phase", {
            "duration": str(YELLOW_DURATION),
            "state": "".join(main_yellow),
        })

    tree.write(NET_FILE, encoding="utf-8", xml_declaration=True)


def write_routes():
    root = ET.Element("routes")

    ET.SubElement(root, "vType", {
        "id": "car",
        "accel": "2.6",
        "decel": "4.5",
        "sigma": "0.5",
        "length": "5",
        "minGap": "2.5",
        "maxSpeed": "13.9",
    })

    west_to_east = ["W_J1"]
    west_to_east += [f"J{i}_J{i+1}" for i in range(1, N_AGENTS)]
    west_to_east += [f"J{N_AGENTS}_E"]

    east_to_west = [f"E_J{N_AGENTS}"]
    east_to_west += [f"J{i}_J{i-1}" for i in range(N_AGENTS, 1, -1)]
    east_to_west += ["J1_W"]

    ET.SubElement(root, "route", {
        "id": "west_to_east",
        "edges": " ".join(west_to_east),
    })

    ET.SubElement(root, "route", {
        "id": "east_to_west",
        "edges": " ".join(east_to_west),
    })

    ET.SubElement(root, "flow", {
        "id": "f_west_to_east",
        "type": "car",
        "route": "west_to_east",
        "begin": "0",
        "end": str(SIMULATION_STEPS),
        "vehsPerHour": str(MAIN_FLOW_PER_HOUR),
        "departLane": "random",
        "departSpeed": "max",
    })

    ET.SubElement(root, "flow", {
        "id": "f_east_to_west",
        "type": "car",
        "route": "east_to_west",
        "begin": "0",
        "end": str(SIMULATION_STEPS),
        "vehsPerHour": str(MAIN_FLOW_PER_HOUR),
        "departLane": "random",
        "departSpeed": "max",
    })

    for i in range(1, N_AGENTS + 1):
        ET.SubElement(root, "route", {
            "id": f"north_to_south_{i}",
            "edges": f"N{i}_J{i} J{i}_S{i}",
        })

        ET.SubElement(root, "route", {
            "id": f"south_to_north_{i}",
            "edges": f"S{i}_J{i} J{i}_N{i}",
        })

        ET.SubElement(root, "flow", {
            "id": f"f_north_to_south_{i}",
            "type": "car",
            "route": f"north_to_south_{i}",
            "begin": "0",
            "end": str(SIMULATION_STEPS),
            "vehsPerHour": str(SIDE_FLOW_PER_HOUR),
            "departLane": "random",
            "departSpeed": "max",
        })

        ET.SubElement(root, "flow", {
            "id": f"f_south_to_north_{i}",
            "type": "car",
            "route": f"south_to_north_{i}",
            "begin": "0",
            "end": str(SIMULATION_STEPS),
            "vehsPerHour": str(SIDE_FLOW_PER_HOUR),
            "departLane": "random",
            "departSpeed": "max",
        })

    ET.ElementTree(root).write(ROUTE_FILE, encoding="utf-8", xml_declaration=True)


def write_sumocfg():
    root = ET.Element("configuration")

    input_el = ET.SubElement(root, "input")
    ET.SubElement(input_el, "net-file", {"value": "corridor.net.xml"})
    ET.SubElement(input_el, "route-files", {"value": "corridor.rou.xml"})

    time_el = ET.SubElement(root, "time")
    ET.SubElement(time_el, "begin", {"value": "0"})
    ET.SubElement(time_el, "end", {"value": str(SIMULATION_STEPS)})

    report_el = ET.SubElement(root, "report")
    ET.SubElement(report_el, "verbose", {"value": "false"})
    ET.SubElement(report_el, "no-step-log", {"value": "true"})

    ET.ElementTree(root).write(SUMO_CONFIG, encoding="utf-8", xml_declaration=True)


def build_scenario():
    print("\n" + "=" * 80)
    print("BUILDING N=10 CORRIDOR SCENARIO")
    print("=" * 80)

    write_nodes()
    write_edges()
    run_netconvert()
    rewrite_tls_logic()
    write_routes()
    write_sumocfg()

    print(f"Scenario created: {SCENARIO_DIR}")
    print(f"SUMO config: {SUMO_CONFIG}")


# ============================================================
# COMMON METRICS
# ============================================================

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


def summarize_rows(rows, controller, seed, expected, total_departed, total_arrived, total_teleports):
    df = pd.DataFrame(rows)

    buffered_ratio = max(0.0, (expected - total_departed) / expected) if expected > 0 else 0.0

    return {
        "controller": controller,
        "seed": seed,
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


# ============================================================
# FIXED-TIME / OFFSET CONTROLLERS
# ============================================================

def phase_from_cycle_position(pos):
    if pos < GREEN_DURATION:
        return 0
    if pos < GREEN_DURATION + YELLOW_DURATION:
        return 1
    if pos < GREEN_DURATION + YELLOW_DURATION + GREEN_DURATION:
        return 2
    return 3


def apply_progression_offsets(base_offset):
    t = int(traci.simulation.getTime())

    for idx in range(N_AGENTS):
        tl_id = f"J{idx + 1}"
        offset = (idx * base_offset) % CYCLE
        pos = (t + offset) % CYCLE
        phase = phase_from_cycle_position(pos)
        traci.trafficlight.setPhase(tl_id, phase)


def run_offset_controller(seed, base_offset):
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
        rows=rows,
        controller=f"Progression Offset {base_offset}s",
        seed=seed,
        expected=expected,
        total_departed=total_departed,
        total_arrived=total_arrived,
        total_teleports=total_teleports,
    )


def run_offset_sweep():
    print("\n" + "=" * 80)
    print("RUNNING N=10 OFFSET SWEEP")
    print("=" * 80)

    rows = []

    for offset in OFFSET_CANDIDATES:
        print(f"\nRunning offset {offset}s...")
        summary = run_offset_controller(seed=EVAL_SEED, base_offset=offset)
        summary["offset"] = offset
        rows.append(summary)
        print(pd.DataFrame([summary]).round(3).to_string(index=False))

    df = pd.DataFrame(rows).round(3)
    df.to_csv(OUT_OFFSET_SWEEP, index=False)

    best_row = df.loc[df["mean_total_waiting_time"].idxmin()]
    best_offset = int(best_row["offset"])

    print("\nBest offset by mean total waiting time:")
    print(best_row.to_string())
    print(f"\nSaved offset sweep to: {OUT_OFFSET_SWEEP}")

    return best_offset, best_row


# ============================================================
# QMIX TRAINING
# ============================================================

def normalize_global_state(state):
    normalized = []

    for i in range(0, len(state), OBS_DIM):
        normalized.append(state[i] / QUEUE_NORMALIZER)
        normalized.append(state[i + 1] / QUEUE_NORMALIZER)
        normalized.append(state[i + 2])

    return normalized


def split_observations(global_state):
    return [
        global_state[i:i + OBS_DIM]
        for i in range(0, len(global_state), OBS_DIM)
    ]


def train_qmix_n10():
    print("\n" + "=" * 80)
    print("TRAINING N=10 QMIX")
    print("=" * 80)

    env = GenericCorridorEnv(
        sumo_binary=SUMO_BINARY,
        sumo_config=SUMO_CONFIG,
        simulation_steps=SIMULATION_STEPS,
        green_duration=GREEN_DURATION,
        yellow_duration=YELLOW_DURATION,
        sumo_seed=TRAIN_SEED,
    )

    qmix = QMIXAgent(
        n_agents=N_AGENTS,
        obs_dim=OBS_DIM,
        state_dim=STATE_DIM,
        action_dim=ACTION_DIM,
        learning_rate=5e-4,
        epsilon_start=1.0,
        epsilon_min=0.05,
        epsilon_decay=0.995,
        buffer_capacity=200_000,
        batch_size=128,
        target_update_freq=200,
    )

    rows = []

    for episode in range(1, NUM_EPISODES + 1):
        raw_state = env.reset()

        global_state = normalize_global_state(raw_state)
        observations = split_observations(global_state)

        done = False
        decision = 0
        episode_reward = 0.0
        losses = []
        last_info = {
            "vehicle_count": 0,
            "total_waiting_time": 0,
            "mean_speed": 0,
            "total_queue": 0,
        }

        while not done and decision < MAX_DECISIONS_PER_EPISODE:
            actions = qmix.select_actions(observations)

            raw_next_state, reward, done, info = env.step(actions)

            next_global_state = normalize_global_state(raw_next_state)
            next_observations = split_observations(next_global_state)

            scaled_reward = reward / 10000.0

            qmix.store_transition(
                global_state=global_state,
                observations=observations,
                actions=actions,
                reward=scaled_reward,
                next_global_state=next_global_state,
                next_observations=next_observations,
                done=done,
            )

            loss = qmix.learn()

            if loss is not None:
                losses.append(loss)

            global_state = next_global_state
            observations = next_observations

            episode_reward += reward
            decision += 1
            last_info = info

        avg_loss = np.mean(losses) if losses else 0.0

        row = {
            "episode": episode,
            "decisions": decision,
            "episode_reward": episode_reward,
            "avg_loss": avg_loss,
            "epsilon": qmix.epsilon,
            "final_vehicle_count": last_info["vehicle_count"],
            "final_total_waiting_time": last_info["total_waiting_time"],
            "final_mean_speed": last_info["mean_speed"],
            "final_total_queue": last_info["total_queue"],
        }

        rows.append(row)

        print(
            f"Episode {episode}/{NUM_EPISODES} | "
            f"Reward: {episode_reward:.2f} | "
            f"Avg loss: {avg_loss:.4f} | "
            f"Epsilon: {qmix.epsilon:.3f} | "
            f"Waiting: {last_info['total_waiting_time']:.2f} | "
            f"Speed: {last_info['mean_speed']:.2f} | "
            f"Queue: {last_info['total_queue']}"
        )

        if episode % 50 == 0:
            qmix.save(MODEL_PATH)
            print(f"Intermediate model saved at episode {episode}: {MODEL_PATH}")

    env.close()

    with open(TRAINING_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    qmix.save(MODEL_PATH)

    print("\nN=10 QMIX training finished.")
    print(f"Training log saved to: {TRAINING_CSV}")
    print(f"QMIX model saved to: {MODEL_PATH}")


# ============================================================
# QMIX EVALUATION
# ============================================================

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
        try:
            row[f"J{i}_phase"] = traci.trafficlight.getPhase(f"J{i}")
        except Exception:
            row[f"J{i}_phase"] = None

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
        buffer_capacity=200_000,
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

                log_qmix_step(
                    rows,
                    decision,
                    actions,
                    total_departed,
                    total_arrived,
                    total_teleports,
                )

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

            log_qmix_step(
                rows,
                decision,
                actions,
                total_departed,
                total_arrived,
                total_teleports,
            )

        raw_state = env.get_state()
        decision += 1
        done = env.step_count >= SIMULATION_STEPS

    env.close()

    return summarize_rows(
        rows=rows,
        controller="QMIX 10 Agents",
        seed=seed,
        expected=expected,
        total_departed=total_departed,
        total_arrived=total_arrived,
        total_teleports=total_teleports,
    )


# ============================================================
# DCHF SUMMARY
# ============================================================

def build_dchf_summary(sim_row, best_offset_row, qmix_row, best_offset):
    sim_wait = sim_row["mean_total_waiting_time"]
    offset_wait = best_offset_row["mean_total_waiting_time"]
    qmix_wait = qmix_row["mean_total_waiting_time"]

    offset_gain = ((sim_wait - offset_wait) / sim_wait) * 100
    qmix_gain = ((sim_wait - qmix_wait) / sim_wait) * 100
    qmix_gap = ((qmix_wait - offset_wait) / offset_wait) * 100

    dchf = {
        "scenario": "N10_d300_medium_coarse_probe",
        "N": N_AGENTS,
        "distance_m": DISTANCE_M,
        "demand": "medium",
        "best_offset_s": best_offset,
        "simultaneous_waiting_time": sim_wait,
        "best_offset_waiting_time": offset_wait,
        "qmix_waiting_time": qmix_wait,
        "offset_coordination_gain_percent": offset_gain,
        "qmix_coordination_gain_percent": qmix_gain,
        "qmix_gap_percent": qmix_gap,
        "dchf_regime": classify_gap(qmix_gap),
        "qmix_buffered_ratio": qmix_row["buffered_ratio"],
        "qmix_capacity_regime": qmix_row["capacity_regime"],
        "qmix_total_teleports": qmix_row["total_teleports"],
        "interpretation": (
            "Coarse N=10 scalability probe. Do not use as final article evidence "
            "until repeated across multiple seeds."
        ),
    }

    return pd.DataFrame([dchf]).round(3)


# ============================================================
# MAIN
# ============================================================

def main():
    build_scenario()

    best_offset, best_offset_row = run_offset_sweep()

    sim_df = pd.read_csv(OUT_OFFSET_SWEEP)
    sim_row = sim_df[sim_df["offset"] == 0].iloc[0]

    train_qmix_n10()

    print("\n" + "=" * 80)
    print("EVALUATING TRAINED N=10 QMIX")
    print("=" * 80)

    qmix_summary = run_qmix_controller(seed=EVAL_SEED)
    qmix_df = pd.DataFrame([qmix_summary]).round(3)
    qmix_df.to_csv(OUT_QMIX_EVAL, index=False)

    dchf_df = build_dchf_summary(
        sim_row=sim_row,
        best_offset_row=best_offset_row,
        qmix_row=qmix_summary,
        best_offset=best_offset,
    )

    dchf_df.to_csv(OUT_DCHF, index=False)

    print("\n" + "=" * 80)
    print("N=10 COARSE SCALABILITY PROBE FINISHED")
    print("=" * 80)

    print("\nQMIX evaluation:")
    print(qmix_df.to_string(index=False))

    print("\nDCHF summary:")
    print(dchf_df.to_string(index=False))

    print(f"\nSaved offset sweep: {OUT_OFFSET_SWEEP}")
    print(f"Saved training log: {TRAINING_CSV}")
    print(f"Saved QMIX evaluation: {OUT_QMIX_EVAL}")
    print(f"Saved DCHF summary: {OUT_DCHF}")


if __name__ == "__main__":
    main()