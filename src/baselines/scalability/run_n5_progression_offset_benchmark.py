import os
import xml.etree.ElementTree as ET

import pandas as pd
import traci


SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/scalability/corridor_5x2_d300m/corridor.sumocfg"
ROUTE_FILE = "sumo_scenarios/scalability/corridor_5x2_d300m/corridor.rou.xml"

SIMULATION_STEPS = 3600
CYCLE = 90
GREEN = 42
YELLOW = 3

N_INTERSECTIONS = 5
TL_IDS = [f"J{i}" for i in range(1, N_INTERSECTIONS + 1)]

OUT_RAW = "results/raw/n5_progression_offset_raw.csv"
OUT_SWEEP = "results/tables/n5_progression_offset_sweep_summary.csv"
OUT_BEST = "results/tables/n5_best_progression_offset_summary.csv"

os.makedirs("results/raw", exist_ok=True)
os.makedirs("results/tables", exist_ok=True)


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


def phase_from_cycle_position(pos):
    if pos < GREEN:
        return 0
    if pos < GREEN + YELLOW:
        return 1
    if pos < GREEN + YELLOW + GREEN:
        return 2
    return 3


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


def apply_progression_offsets(base_offset):
    t = int(traci.simulation.getTime())

    for idx, tl_id in enumerate(TL_IDS):
        offset = (idx * base_offset) % CYCLE
        pos = (t + offset) % CYCLE
        phase = phase_from_cycle_position(pos)
        traci.trafficlight.setPhase(tl_id, phase)


def run_one_offset(base_offset, sumo_seed=0):
    traci.start([
        SUMO_BINARY,
        "-c",
        SUMO_CONFIG,
        "--no-step-log",
        "true",
        "--seed",
        str(sumo_seed),
    ])

    rows = []
    total_departed = 0
    total_arrived = 0

    for step in range(SIMULATION_STEPS):
        apply_progression_offsets(base_offset)
        traci.simulationStep()

        departed = traci.simulation.getDepartedNumber()
        arrived = traci.simulation.getArrivedNumber()

        total_departed += departed
        total_arrived += arrived

        rows.append({
            "offset": base_offset,
            "step": step,
            "vehicle_count": len(traci.vehicle.getIDList()),
            "total_waiting_time": get_total_waiting_time(),
            "mean_speed": get_mean_speed(),
            "total_queue": get_total_queue(),
            "departed_this_step": departed,
            "arrived_this_step": arrived,
            "total_departed": total_departed,
            "total_arrived": total_arrived,
        })

    traci.close()

    df = pd.DataFrame(rows)

    expected = get_expected_vehicles(ROUTE_FILE)
    buffered_ratio = max(0.0, (expected - total_departed) / expected) if expected > 0 else 0.0

    summary = {
        "controller": "Simultaneous Fixed-Time" if base_offset == 0 else f"Progression Offset {base_offset}s",
        "offset": base_offset,
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
    }

    return df, summary


def main():
    all_raw = []
    summaries = []

    offsets = list(range(0, CYCLE, 5))

    for offset in offsets:
        print("\n" + "=" * 70)
        print(f"Running N=5 progression offset benchmark: offset={offset}s")
        print("=" * 70)

        raw_df, summary = run_one_offset(offset, sumo_seed=0)

        all_raw.append(raw_df)
        summaries.append(summary)

        print(pd.DataFrame([summary]).round(3).to_string(index=False))

    raw_all = pd.concat(all_raw, ignore_index=True)
    sweep_df = pd.DataFrame(summaries).round(3)

    raw_all.to_csv(OUT_RAW, index=False)
    sweep_df.to_csv(OUT_SWEEP, index=False)

    best_row = sweep_df.loc[sweep_df["mean_total_waiting_time"].idxmin()].copy()
    best_row.to_frame().T.to_csv(OUT_BEST, index=False)

    print("\nN=5 progression benchmark finished.")
    print("\nBest offset by mean waiting time:")
    print(best_row.to_frame().T.to_string(index=False))
    print(f"\nSaved raw log: {OUT_RAW}")
    print(f"Saved sweep summary: {OUT_SWEEP}")
    print(f"Saved best summary: {OUT_BEST}")


if __name__ == "__main__":
    main()