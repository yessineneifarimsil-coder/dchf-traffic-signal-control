"""
Max Pressure central-link occupancy check for the DCHF paper.

PURPOSE
-------
The manuscript's spillback check (80% central-link occupancy threshold)
was instrumented only for the optimized offset and QMIX (Supplementary
Table S10). This script closes that gap: it reruns the Max Pressure
demand sweep episodes (5 demand levels x 5 seeds, d=300 m turning
variants) with per-step central-link occupancy logging.

PROVENANCE (no new logic)
-------------------------
- Controller + episode loop: copied verbatim from
  src/analysis/run_max_pressure_demand_sweep.py
  (the script that produced BR_MP = 0.0361 / 0.1440 / 0.2323).
- Occupancy computation: copied verbatim from
  src/baselines/two_intersections/analyze_spillback_demand.py
  (the script that produced the offset/QMIX rows of Table S10).

SELF-CHECK
----------
The per-seed buffered ratio is recomputed exactly as in the original
sweep. The five-seed BR means printed at the end must reproduce
high=0.0361, saturation=0.1440, oversaturation=0.2323 (low/medium=0.0).
If they do not, the runs are not comparable -- stop and investigate.

OUTPUTS
-------
results/raw/mp_occupancy_{demand}_seed{seed}.csv        -- per-step log
results/tables/max_pressure_occupancy_seed_summary.csv  -- per-seed
results/tables/max_pressure_occupancy_summary.csv       -- per demand level

Run from the repository root:
    conda activate traffic_rl
    python src/analysis/run_max_pressure_occupancy_check.py
"""

import os
import csv
import statistics

import traci


# ============================================================
# CONFIGURATION -- identical to run_max_pressure_demand_sweep.py
# ============================================================

SUMO_BINARY = "sumo"

DEMAND_SCENARIOS = {
    "low": {
        "folder":                  "demand_low",
        "expected_total_vehicles": 1396,
        "multiplier":              0.50,
    },
    "medium": {
        "folder":                  "demand_medium",
        "expected_total_vehicles": 2800,
        "multiplier":              1.00,
    },
    "high": {
        "folder":                  "demand_high",
        "expected_total_vehicles": 4204,
        "multiplier":              1.50,
    },
    "saturation": {
        "folder":                  "demand_saturation",
        "expected_total_vehicles": 5600,
        "multiplier":              2.00,
    },
    "oversaturation": {
        "folder":                  "demand_oversaturation",
        "expected_total_vehicles": 6996,
        "multiplier":              2.50,
    },
}

SEEDS = [0, 1, 2, 3, 4]

SIMULATION_STEPS = 3600
MIN_GREEN        = 10
YELLOW_DURATION  = 3

SIDE_GREEN  = 0
SIDE_YELLOW = 1
MAIN_GREEN  = 2
MAIN_YELLOW = 3

TL_IDS = ["J1", "J2"]

# Occupancy constants -- identical to analyze_spillback_demand.py
VEHICLE_STORAGE_SPACE       = 7.5
SPILLBACK_THRESHOLD         = 0.80
SEVERE_SPILLBACK_THRESHOLD  = 0.95

RAW_DIR      = "results/raw"
OUT_SEED     = "results/tables/max_pressure_occupancy_seed_summary.csv"
OUT_SUMMARY  = "results/tables/max_pressure_occupancy_summary.csv"

# Known five-seed BR means from the original sweep, for the self-check.
EXPECTED_BR = {
    "low": 0.0, "medium": 0.0,
    "high": 0.0361, "saturation": 0.1440, "oversaturation": 0.2323,
}


# ============================================================
# MAX PRESSURE LOGIC
# Copied verbatim from run_max_pressure_demand_sweep.py
# ============================================================

def get_vehicle_count():
    return len(traci.vehicle.getIDList())

def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v)
               for v in traci.vehicle.getIDList())

def get_total_queue():
    total = 0
    for lane_id in traci.lane.getIDList():
        if not lane_id.startswith(":"):
            total += traci.lane.getLastStepHaltingNumber(lane_id)
    return total

def lane_count(lane_id):
    if not lane_id:
        return 0
    try:
        return traci.lane.getLastStepVehicleNumber(lane_id)
    except Exception:
        return 0

def get_phase_state(tl_id, phase_index):
    logic = traci.trafficlight.getAllProgramLogics(tl_id)[0]
    return logic.phases[phase_index].state

def compute_phase_pressure(tl_id, phase_index):
    state    = get_phase_state(tl_id, phase_index)
    c_links  = traci.trafficlight.getControlledLinks(tl_id)
    pressure = 0.0
    for idx, sig in enumerate(state):
        if sig not in ("G", "g"):
            continue
        if idx >= len(c_links):
            continue
        for lt in c_links[idx]:
            pressure += lane_count(lt[0]) - lane_count(lt[1])
    return pressure

def choose_max_pressure_phase(tl_id):
    sp = compute_phase_pressure(tl_id, SIDE_GREEN)
    mp = compute_phase_pressure(tl_id, MAIN_GREEN)
    if sp > mp:
        return SIDE_GREEN, "side_green", sp, mp
    return MAIN_GREEN, "main_green", sp, mp

def apply_transition(tl_id, previous_phase, selected_phase):
    if previous_phase == selected_phase:
        return False
    if previous_phase == SIDE_GREEN and selected_phase == MAIN_GREEN:
        traci.trafficlight.setPhase(tl_id, SIDE_YELLOW)
        traci.trafficlight.setPhaseDuration(tl_id, YELLOW_DURATION)
        return True
    if previous_phase == MAIN_GREEN and selected_phase == SIDE_GREEN:
        traci.trafficlight.setPhase(tl_id, MAIN_YELLOW)
        traci.trafficlight.setPhaseDuration(tl_id, YELLOW_DURATION)
        return True
    return False


# ============================================================
# CENTRAL-LINK OCCUPANCY
# Copied verbatim from analyze_spillback_demand.py
# ============================================================

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
    return sum(traci.lane.getLastStepVehicleNumber(lane_id)
               for lane_id in lane_ids)

def get_central_link_spillback_metrics(e1_lanes, neg_e1_lanes,
                                       e1_capacity, neg_e1_capacity):
    e1_vehicle_count     = compute_direction_vehicle_count(e1_lanes)
    neg_e1_vehicle_count = compute_direction_vehicle_count(neg_e1_lanes)

    e1_occupancy_ratio = (
        e1_vehicle_count / e1_capacity if e1_capacity > 0 else 0.0
    )
    neg_e1_occupancy_ratio = (
        neg_e1_vehicle_count / neg_e1_capacity if neg_e1_capacity > 0 else 0.0
    )

    max_central_occupancy_ratio = max(e1_occupancy_ratio,
                                      neg_e1_occupancy_ratio)

    return {
        "E1_vehicle_count":            e1_vehicle_count,
        "neg_E1_vehicle_count":        neg_e1_vehicle_count,
        "E1_occupancy_ratio":          e1_occupancy_ratio,
        "neg_E1_occupancy_ratio":      neg_e1_occupancy_ratio,
        "max_central_occupancy_ratio": max_central_occupancy_ratio,
        "spillback_risk_80":  int(max_central_occupancy_ratio
                                  >= SPILLBACK_THRESHOLD),
        "severe_spillback_risk_95": int(max_central_occupancy_ratio
                                        >= SEVERE_SPILLBACK_THRESHOLD),
    }


# ============================================================
# SINGLE-SEED RUN (episode loop identical to the original sweep;
# only the occupancy sampling is added after each simulation step)
# ============================================================

def run_single_seed(demand_name, scenario_info, seed):
    sumo_config = (
        "sumo_scenarios/two_intersections/"
        f"demand_sensitivity/{scenario_info['folder']}/corridor_turning.sumocfg"
    )
    if not os.path.exists(sumo_config):
        raise FileNotFoundError(f"SUMO config not found: {sumo_config}")

    traci.start([
        SUMO_BINARY,
        "-c", sumo_config,
        "--no-step-log", "true",
        "--seed", str(seed),
    ])

    rows           = []
    step           = 0
    total_departed = 0
    total_arrived  = 0
    previous_phase = {"J1": MAIN_GREEN, "J2": MAIN_GREEN}

    try:
        # Resolve central-link lanes and capacities once per episode.
        e1_lanes       = safe_lane_ids("E1")
        neg_e1_lanes   = safe_lane_ids("-E1")
        e1_capacity    = compute_direction_storage_capacity(e1_lanes)
        neg_e1_capacity = compute_direction_storage_capacity(neg_e1_lanes)

        if not e1_lanes or not neg_e1_lanes:
            raise RuntimeError(
                f"Central-link lanes not found (E1: {e1_lanes}, "
                f"-E1: {neg_e1_lanes}); check edge IDs in "
                f"{sumo_config}"
            )

        def sample(step_now):
            m = get_central_link_spillback_metrics(
                e1_lanes, neg_e1_lanes, e1_capacity, neg_e1_capacity)
            m["step"]        = step_now
            m["total_queue"] = get_total_queue()
            rows.append(m)

        while step < SIMULATION_STEPS:
            j1_phase, j1_group, j1_sp, j1_mp = choose_max_pressure_phase("J1")
            j2_phase, j2_group, j2_sp, j2_mp = choose_max_pressure_phase("J2")

            yellow_j1 = apply_transition("J1", previous_phase["J1"], j1_phase)
            yellow_j2 = apply_transition("J2", previous_phase["J2"], j2_phase)

            if yellow_j1 or yellow_j2:
                for _ in range(YELLOW_DURATION):
                    if step >= SIMULATION_STEPS:
                        break
                    traci.simulationStep()
                    total_departed += traci.simulation.getDepartedNumber()
                    total_arrived  += traci.simulation.getArrivedNumber()
                    sample(step)
                    step += 1

            traci.trafficlight.setPhase("J1", j1_phase)
            traci.trafficlight.setPhaseDuration("J1", MIN_GREEN)
            traci.trafficlight.setPhase("J2", j2_phase)
            traci.trafficlight.setPhaseDuration("J2", MIN_GREEN)

            for _ in range(MIN_GREEN):
                if step >= SIMULATION_STEPS:
                    break
                traci.simulationStep()
                total_departed += traci.simulation.getDepartedNumber()
                total_arrived  += traci.simulation.getArrivedNumber()
                sample(step)
                if step % 600 == 0:
                    last = rows[-1]
                    print(f"  [seed {seed}] step {step} | "
                          f"max occ {last['max_central_occupancy_ratio']:.3f} | "
                          f"queue {last['total_queue']}")
                step += 1

            previous_phase["J1"] = j1_phase
            previous_phase["J2"] = j2_phase

    finally:
        try:
            traci.close()
        except Exception:
            pass

    raw_path = os.path.join(
        RAW_DIR, f"mp_occupancy_{demand_name}_seed{seed}.csv")
    fieldnames = ["step", "E1_vehicle_count", "neg_E1_vehicle_count",
                  "E1_occupancy_ratio", "neg_E1_occupancy_ratio",
                  "max_central_occupancy_ratio",
                  "spillback_risk_80", "severe_spillback_risk_95",
                  "total_queue"]
    with open(raw_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    n = len(rows)
    max_occ   = max(r["max_central_occupancy_ratio"] for r in rows)
    mean_occ  = sum(r["max_central_occupancy_ratio"] for r in rows) / n
    freq_80   = sum(r["spillback_risk_80"] for r in rows) / n
    freq_95   = sum(r["severe_spillback_risk_95"] for r in rows) / n
    max_queue = max(r["total_queue"] for r in rows)

    expected = scenario_info["expected_total_vehicles"]
    buffered = max(0, expected - total_departed)
    br       = buffered / expected if expected > 0 else 0.0

    summary = {
        "demand_scenario":             demand_name,
        "demand_multiplier":           scenario_info["multiplier"],
        "seed":                        seed,
        "max_central_occupancy_ratio": round(max_occ, 4),
        "mean_central_occupancy_ratio": round(mean_occ, 4),
        "spillback_freq_80":           round(freq_80, 4),
        "severe_spillback_freq_95":    round(freq_95, 4),
        "max_total_queue":             max_queue,
        "total_departed":              total_departed,
        "total_arrived":               total_arrived,
        "buffered_ratio":              round(br, 4),
    }
    print(f"  [seed {seed}] DONE | max occ={max_occ:.4f} | "
          f"freq80={freq_80:.4f} | max queue={max_queue} | BR={br:.4f}")
    return summary


# ============================================================
# MAIN
# ============================================================

def mean_std(values):
    vals = list(values)
    if len(vals) < 2:
        return (vals[0] if vals else 0.0), 0.0
    return statistics.mean(vals), statistics.stdev(vals)


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_SEED), exist_ok=True)

    seed_rows = []
    for demand_name, info in DEMAND_SCENARIOS.items():
        print(f"\n=== Max Pressure occupancy check: {demand_name} "
              f"({info['multiplier']}x) ===")
        for seed in SEEDS:
            seed_rows.append(run_single_seed(demand_name, info, seed))

    with open(OUT_SEED, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=seed_rows[0].keys())
        writer.writeheader()
        writer.writerows(seed_rows)

    summary_rows = []
    print("\n===== SUMMARY (five seeds per level) =====")
    print(f"{'demand':<16}{'max occ (worst)':<17}{'mean of maxes':<20}"
          f"{'freq>=80%':<11}{'max queue':<11}{'BR mean':<9}{'BR expected'}")
    for demand_name, info in DEMAND_SCENARIOS.items():
        g = [r for r in seed_rows if r["demand_scenario"] == demand_name]
        occ_max_overall = max(r["max_central_occupancy_ratio"] for r in g)
        occ_m, occ_s    = mean_std(r["max_central_occupancy_ratio"] for r in g)
        f80_m, _        = mean_std(r["spillback_freq_80"] for r in g)
        q_max           = max(r["max_total_queue"] for r in g)
        br_m, br_s      = mean_std(r["buffered_ratio"] for r in g)

        summary_rows.append({
            "demand_scenario":               demand_name,
            "demand_multiplier":             info["multiplier"],
            "seeds_run":                     len(g),
            "max_occupancy_worst_seed":      round(occ_max_overall, 4),
            "max_occupancy_mean":            round(occ_m, 4),
            "max_occupancy_std":             round(occ_s, 4),
            "spillback_freq_80_mean":        round(f80_m, 4),
            "max_total_queue_worst_seed":    q_max,
            "buffered_ratio_mean":           round(br_m, 4),
            "buffered_ratio_std":            round(br_s, 4),
            "buffered_ratio_expected":       EXPECTED_BR[demand_name],
        })
        flag = "" if abs(br_m - EXPECTED_BR[demand_name]) < 0.005 else \
               "  <-- BR MISMATCH vs original sweep, investigate"
        print(f"{demand_name:<16}{occ_max_overall:<17.4f}"
              f"{occ_m:.4f} +/- {occ_s:<8.4f}"
              f"{f80_m:<11.4f}{q_max:<11}{br_m:<9.4f}"
              f"{EXPECTED_BR[demand_name]}{flag}")

    with open(OUT_SUMMARY, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_rows[0].keys())
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"\nWrote: {OUT_SEED}")
    print(f"Wrote: {OUT_SUMMARY}")
    print("\nIf every BR mean matches the expected value and no line shows "
          "a mismatch flag,\nthe occupancy numbers come from the identical "
          "controller as the published MP sweep.")


if __name__ == "__main__":
    main()
