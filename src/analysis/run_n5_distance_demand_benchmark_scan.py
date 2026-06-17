import os
import csv
import subprocess
import xml.etree.ElementTree as ET

import pandas as pd
import traci


# ============================================================
# CONFIGURATION
# ============================================================

SUMO_BINARY = "sumo"

N_AGENTS = 5
SIMULATION_STEPS = 3600
GREEN_DURATION = 42
YELLOW_DURATION = 3
CYCLE = 90

DISTANCES = [200, 300, 500, 750]
DEMAND_LEVELS = {
    "low": 0.5,
    "medium": 1.0,
    "high": 1.5,
    "saturation": 2.0,
}

OFFSET_CANDIDATES = list(range(0, 91, 5))

BASE_MAIN_FLOW = 700
BASE_SIDE_FLOW = 320

OUT_RAW = "results/raw/n5_distance_demand_benchmark_raw.csv"
OUT_SWEEP = "results/tables/n5_distance_demand_offset_sweep_summary.csv"
OUT_DCHF = "results/tables/n5_distance_demand_benchmark_dchf_summary.csv"

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

def scenario_paths(distance, demand_name):
    scenario_dir = f"sumo_scenarios/scalability/corridor_5x2_d{distance}m_{demand_name}"
    return {
        "dir": scenario_dir,
        "nod": os.path.join(scenario_dir, "corridor.nod.xml"),
        "edg": os.path.join(scenario_dir, "corridor.edg.xml"),
        "net": os.path.join(scenario_dir, "corridor.net.xml"),
        "rou": os.path.join(scenario_dir, "corridor.rou.xml"),
        "cfg": os.path.join(scenario_dir, "corridor.sumocfg"),
    }


def write_nodes(paths, distance):
    root = ET.Element("nodes")

    ET.SubElement(root, "node", {
        "id": "W",
        "x": str(-distance),
        "y": "0",
        "type": "priority",
    })

    ET.SubElement(root, "node", {
        "id": "E",
        "x": str(N_AGENTS * distance),
        "y": "0",
        "type": "priority",
    })

    for i in range(1, N_AGENTS + 1):
        x = str((i - 1) * distance)

        ET.SubElement(root, "node", {
            "id": f"J{i}",
            "x": x,
            "y": "0",
            "type": "priority",
        })

        ET.SubElement(root, "node", {
            "id": f"N{i}",
            "x": x,
            "y": str(distance),
            "type": "priority",
        })

        ET.SubElement(root, "node", {
            "id": f"S{i}",
            "x": x,
            "y": str(-distance),
            "type": "priority",
        })

    ET.ElementTree(root).write(paths["nod"], encoding="utf-8", xml_declaration=True)


def add_edge(root, edge_id, from_node, to_node):
    ET.SubElement(root, "edge", {
        "id": edge_id,
        "from": from_node,
        "to": to_node,
        "priority": "1",
        "numLanes": "2",
        "speed": "13.9",
    })


def write_edges(paths):
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

    ET.ElementTree(root).write(paths["edg"], encoding="utf-8", xml_declaration=True)


def run_netconvert(paths):
    tls_ids = ",".join([f"J{i}" for i in range(1, N_AGENTS + 1)])

    cmd = [
        "netconvert",
        "--node-files", paths["nod"],
        "--edge-files", paths["edg"],
        "--output-file", paths["net"],
        "--tls.set", tls_ids,
        "--no-turnarounds", "true",
    ]

    subprocess.run(cmd, check=True)


def is_side_edge(edge_id):
    return edge_id.startswith("N") or edge_id.startswith("S")


def rewrite_tls_logic(paths):
    tree = ET.parse(paths["net"])
    root = tree.getroot()

    connections_by_tls = {}

    for conn in root.iter("connection"):
        tl_id = conn.attrib.get("tl")
        link_index = conn.attrib.get("linkIndex")

        if tl_id is None or link_index is None:
            continue

        connections_by_tls.setdefault(tl_id, []).append(conn)

    existing_tls = {
        tl.attrib.get("id"): tl
        for tl in root.iter("tlLogic")
        if tl.attrib.get("id") is not None
    }

    for i in range(1, N_AGENTS + 1):
        tl_id = f"J{i}"
        conns = connections_by_tls.get(tl_id, [])

        if not conns:
            raise RuntimeError(f"No controlled connections found for {tl_id}")

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

        if tl_id in existing_tls:
            tl = existing_tls[tl_id]
            tl.attrib.clear()
            tl.attrib.update({
                "id": tl_id,
                "type": "static",
                "programID": "0",
                "offset": "0",
            })

            for child in list(tl):
                tl.remove(child)
        else:
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

    tree.write(paths["net"], encoding="utf-8", xml_declaration=True)


def write_routes(paths, multiplier):
    main_flow = BASE_MAIN_FLOW * multiplier
    side_flow = BASE_SIDE_FLOW * multiplier

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
        "vehsPerHour": str(main_flow),
        "departLane": "random",
        "departSpeed": "max",
    })

    ET.SubElement(root, "flow", {
        "id": "f_east_to_west",
        "type": "car",
        "route": "east_to_west",
        "begin": "0",
        "end": str(SIMULATION_STEPS),
        "vehsPerHour": str(main_flow),
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
            "vehsPerHour": str(side_flow),
            "departLane": "random",
            "departSpeed": "max",
        })

        ET.SubElement(root, "flow", {
            "id": f"f_south_to_north_{i}",
            "type": "car",
            "route": f"south_to_north_{i}",
            "begin": "0",
            "end": str(SIMULATION_STEPS),
            "vehsPerHour": str(side_flow),
            "departLane": "random",
            "departSpeed": "max",
        })

    ET.ElementTree(root).write(paths["rou"], encoding="utf-8", xml_declaration=True)


def write_sumocfg(paths):
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

    ET.ElementTree(root).write(paths["cfg"], encoding="utf-8", xml_declaration=True)


def build_scenario(distance, demand_name, multiplier):
    paths = scenario_paths(distance, demand_name)
    os.makedirs(paths["dir"], exist_ok=True)

    write_nodes(paths, distance)
    write_edges(paths)
    run_netconvert(paths)
    rewrite_tls_logic(paths)
    write_routes(paths, multiplier)
    write_sumocfg(paths)

    return paths


# ============================================================
# METRICS
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


def classify_capacity(br):
    if br < 0.01:
        return "Unconstrained"
    if br < 0.10:
        return "Mild insertion pressure"
    if br < 0.25:
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
    t = int(traci.simulation.getTime())

    for idx in range(N_AGENTS):
        tl_id = f"J{idx + 1}"
        offset = (idx * base_offset) % CYCLE
        pos = (t + offset) % CYCLE
        phase = phase_from_cycle_position(pos)
        traci.trafficlight.setPhase(tl_id, phase)


def run_offset_controller(paths, distance, demand_name, multiplier, offset, seed=0):
    safe_close()

    traci.start([
        SUMO_BINARY,
        "-c", paths["cfg"],
        "--no-step-log", "true",
        "--seed", str(seed),
    ])

    expected = get_expected_vehicles(paths["rou"])

    raw_rows = []
    total_departed = 0
    total_arrived = 0
    total_teleports = 0

    for step in range(SIMULATION_STEPS):
        apply_progression_offsets(offset)
        traci.simulationStep()

        departed = traci.simulation.getDepartedNumber()
        arrived = traci.simulation.getArrivedNumber()
        teleports = traci.simulation.getStartingTeleportNumber()

        total_departed += departed
        total_arrived += arrived
        total_teleports += teleports

        row = {
            "distance_m": distance,
            "demand": demand_name,
            "multiplier": multiplier,
            "offset": offset,
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
        }

        raw_rows.append(row)

    safe_close()

    df = pd.DataFrame(raw_rows)

    buffered_ratio = max(0.0, (expected - total_departed) / expected) if expected > 0 else 0.0

    summary = {
        "N": N_AGENTS,
        "distance_m": distance,
        "demand": demand_name,
        "multiplier": multiplier,
        "offset": offset,
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "total_expected": expected,
        "total_departed": total_departed,
        "total_arrived": total_arrived,
        "buffered_ratio": buffered_ratio,
        "capacity_regime": classify_capacity(buffered_ratio),
        "total_teleports": total_teleports,
    }

    return raw_rows, summary


# ============================================================
# MAIN
# ============================================================

def main():
    all_raw_rows = []
    all_summaries = []
    dchf_rows = []

    for distance in DISTANCES:
        for demand_name, multiplier in DEMAND_LEVELS.items():
            print("\n" + "=" * 80)
            print(f"N=5 benchmark scan | distance={distance} m | demand={demand_name} ({multiplier}x)")
            print("=" * 80)

            paths = build_scenario(distance, demand_name, multiplier)

            scenario_summaries = []

            for offset in OFFSET_CANDIDATES:
                print(f"Running offset {offset}s...")

                raw_rows, summary = run_offset_controller(
                    paths=paths,
                    distance=distance,
                    demand_name=demand_name,
                    multiplier=multiplier,
                    offset=offset,
                    seed=0,
                )

                all_raw_rows.extend(raw_rows)
                all_summaries.append(summary)
                scenario_summaries.append(summary)

                print(
                    f"offset={offset:>3}s | "
                    f"wait={summary['mean_total_waiting_time']:.3f} | "
                    f"speed={summary['mean_speed']:.3f} | "
                    f"queue={summary['mean_total_queue']:.3f} | "
                    f"BR={summary['buffered_ratio']:.4f} | "
                    f"teleports={summary['total_teleports']}"
                )

            scenario_df = pd.DataFrame(scenario_summaries)

            sim_row = scenario_df[scenario_df["offset"] == 0].iloc[0]
            best_row = scenario_df.loc[scenario_df["mean_total_waiting_time"].idxmin()]

            sim_wait = sim_row["mean_total_waiting_time"]
            best_wait = best_row["mean_total_waiting_time"]
            offset_cg = ((sim_wait - best_wait) / sim_wait) * 100 if sim_wait > 0 else 0.0

            dchf_rows.append({
                "N": N_AGENTS,
                "distance_m": distance,
                "demand": demand_name,
                "multiplier": multiplier,
                "simultaneous_waiting_time": sim_wait,
                "best_offset_waiting_time": best_wait,
                "best_offset_s": int(best_row["offset"]),
                "offset_coordination_gain_percent": offset_cg,
                "best_offset_mean_speed": best_row["mean_speed"],
                "best_offset_mean_queue": best_row["mean_total_queue"],
                "buffered_ratio": best_row["buffered_ratio"],
                "capacity_regime": best_row["capacity_regime"],
                "total_teleports": best_row["total_teleports"],
            })

            print("\nBest offset for this scenario:")
            print(pd.DataFrame([dchf_rows[-1]]).round(3).to_string(index=False))

            pd.DataFrame(all_summaries).round(3).to_csv(OUT_SWEEP, index=False)
            pd.DataFrame(dchf_rows).round(3).to_csv(OUT_DCHF, index=False)

    pd.DataFrame(all_raw_rows).to_csv(OUT_RAW, index=False)
    pd.DataFrame(all_summaries).round(3).to_csv(OUT_SWEEP, index=False)
    pd.DataFrame(dchf_rows).round(3).to_csv(OUT_DCHF, index=False)

    print("\n" + "=" * 80)
    print("N=5 DISTANCE-DEMAND BENCHMARK SCAN FINISHED")
    print("=" * 80)
    print(f"Saved raw data: {OUT_RAW}")
    print(f"Saved offset sweep summary: {OUT_SWEEP}")
    print(f"Saved DCHF benchmark summary: {OUT_DCHF}")

    print("\nFinal DCHF benchmark summary:")
    print(pd.DataFrame(dchf_rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()