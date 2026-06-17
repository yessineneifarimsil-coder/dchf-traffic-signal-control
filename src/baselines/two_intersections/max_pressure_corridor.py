"""
Max-Pressure baseline for the two-intersection corridor (DCHF study).

Corrected implementation, consistent with the max-pressure definition in
Varaiya (2013) and Ducrocq & Farhi (2021), Sec. VI.C.1:

    pressure(p) = sum_{l in Lp_in} |V_l|  -  sum_{l in Lp_out} |V_l|

where |V_l| is the NUMBER OF VEHICLES on lane l (not only halting vehicles),
the controller re-decides after each minimum-green interval Tg_min, and the
phase with maximum pressure is selected.

Key corrections vs. the first draft:
  1. Pressure uses getLastStepVehicleNumber (|V_l|), not getLastStepHaltingNumber.
  2. The green phase is held only for MIN_GREEN seconds, then the controller
     re-evaluates pressure (acyclic max-pressure), instead of locking 42 s.
  3. A seed loop runs the same scenario over several seeds and reports
     mean +/- std of the run-level mean total waiting time, ready to drop into
     the Scenario A controller-comparison table next to QMIX and the offset.

Run:
    python max_pressure_baseline.py
Requires SUMO + TraCI on the machine (not runnable in this environment).
"""

import os
import csv
import statistics
import traci


# ============================================================
# CONFIGURATION
# ============================================================

SUMO_BINARY = "sumo"          # use "sumo-gui" for visual debugging
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.sumocfg"

# Per-seed raw step logs go here; the summary CSV is written once at the end.
# Keep these consistent with your results tree and your comparison script.
RAW_DIR = "results/raw"
SUMMARY_CSV = "results/tables/max_pressure_corridor_2x2_summary.csv"

# If your comparison script reads one CSV per controller with per-step rows,
# point it at the per-seed files in RAW_DIR (one per seed). If it reads a
# single run, set SEEDS = [0] and it will produce one raw file matching the
# original single-seed format exactly.

SIMULATION_STEPS = 3600       # 1 h, same horizon as the other controllers

# Re-evaluation interval for acyclic max-pressure.
# Matches Tg_min in Ducrocq & Farhi (2021). Keep this fixed across the study.
MIN_GREEN = 10
YELLOW_DURATION = 3

# Phase indices in the corridor traffic-light program (2-phase program).
SIDE_GREEN = 0
SIDE_YELLOW = 1
MAIN_GREEN = 2
MAIN_YELLOW = 3

TL_IDS = ["J1", "J2"]

# Seeds for the multi-seed comparison. Use the SAME seeds as your QMIX /
# offset multi-seed runs so the controllers are directly comparable.
SEEDS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs("results/tables", exist_ok=True)
os.makedirs(os.path.dirname(SUMMARY_CSV), exist_ok=True)


# ============================================================
# BASIC METRICS
# ============================================================

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


def lane_count(lane_id):
    """Number of vehicles on the lane: |V_l| in the max-pressure definition.

    This is the corrected metric. The earlier draft used
    getLastStepHaltingNumber (queue), which yields a queue-based pressure
    variant rather than the cited max-pressure controller.
    """
    if not lane_id:
        return 0
    try:
        return traci.lane.getLastStepVehicleNumber(lane_id)
    except Exception:
        return 0


# ============================================================
# MAX PRESSURE LOGIC
# ============================================================

def get_phase_state(tl_id, phase_index):
    logic = traci.trafficlight.getAllProgramLogics(tl_id)[0]
    return logic.phases[phase_index].state


def compute_phase_pressure(tl_id, phase_index):
    """Classical lane-pressure proxy for a candidate green phase.

    For each controlled movement receiving green:
        movement pressure = |V_in_lane| - |V_out_lane|
    Phase pressure = sum of all green-movement pressures.
    """
    state = get_phase_state(tl_id, phase_index)
    controlled_links = traci.trafficlight.getControlledLinks(tl_id)

    pressure = 0.0
    for link_index, signal_state in enumerate(state):
        if signal_state not in ("G", "g"):
            continue
        if link_index >= len(controlled_links):
            continue
        for link_tuple in controlled_links[link_index]:
            in_lane = link_tuple[0]
            out_lane = link_tuple[1]
            pressure += lane_count(in_lane) - lane_count(out_lane)
    return pressure


def choose_max_pressure_phase(tl_id):
    """2-phase program: argmax over {SIDE_GREEN, MAIN_GREEN} equals the full
    max-pressure argmax because only two green phases exist."""
    side_pressure = compute_phase_pressure(tl_id, SIDE_GREEN)
    main_pressure = compute_phase_pressure(tl_id, MAIN_GREEN)
    if side_pressure > main_pressure:
        return SIDE_GREEN, "side_green", side_pressure, main_pressure
    return MAIN_GREEN, "main_green", side_pressure, main_pressure


def apply_transition(tl_id, previous_phase, selected_phase):
    """Insert a yellow interval when switching between the two green phases."""
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


def collect_step_data(step, j1_group, j2_group,
                      j1_sp, j1_mp, j2_sp, j2_mp):
    return {
        "step": step,
        "J1_phase_group": j1_group,
        "J2_phase_group": j2_group,
        "vehicle_count": get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed": get_mean_speed(),
        "total_queue": get_total_queue(),
        "J1_phase": traci.trafficlight.getPhase("J1"),
        "J2_phase": traci.trafficlight.getPhase("J2"),
        "J1_side_pressure": j1_sp,
        "J1_main_pressure": j1_mp,
        "J2_side_pressure": j2_sp,
        "J2_main_pressure": j2_mp,
    }


# ============================================================
# SINGLE-SEED RUN
# ============================================================

def run_single_seed(seed, verify_outlanes=False):
    """Run one 3600 s episode under max-pressure control with the given seed.

    Returns a dict with the run-level summary metrics (mean over the episode)
    and writes the per-step log to results/raw/.
    """
    traci.start([
        SUMO_BINARY,
        "-c", SUMO_CONFIG,
        "--no-step-log", "true",
        "--seed", str(seed),
    ])

    # One-time sanity check that out-lanes resolve (helps catch the pressure
    # collapse described in the review). Prints once, then continues.
    if verify_outlanes:
        for tl in TL_IDS:
            links = traci.trafficlight.getControlledLinks(tl)
            sample = [(lt[0], lt[1]) for grp in links for lt in grp][:6]
            print(f"[seed {seed}] {tl} sample (in_lane, out_lane): {sample}")

    rows = []
    step = 0
    previous_phase = {"J1": MAIN_GREEN, "J2": MAIN_GREEN}

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
                rows.append(collect_step_data(
                    step, "yellow_transition", "yellow_transition",
                    j1_sp, j1_mp, j2_sp, j2_mp))
                step += 1

        # Apply selected green phases, then HOLD ONLY MIN_GREEN before
        # re-deciding (acyclic max-pressure), instead of locking a fixed cycle.
        traci.trafficlight.setPhase("J1", j1_phase)
        traci.trafficlight.setPhaseDuration("J1", MIN_GREEN)

        traci.trafficlight.setPhase("J2", j2_phase)
        traci.trafficlight.setPhaseDuration("J2", MIN_GREEN)

        for _ in range(MIN_GREEN):
            if step >= SIMULATION_STEPS:
                break
            traci.simulationStep()
            rows.append(collect_step_data(
                step, j1_group, j2_group, j1_sp, j1_mp, j2_sp, j2_mp))
            if step % 300 == 0:
                print(f"[seed {seed}] step {step} | "
                      f"J1 {j1_group} J2 {j2_group} | "
                      f"veh {get_vehicle_count()} | "
                      f"wait {get_total_waiting_time():.1f} | "
                      f"speed {get_mean_speed():.2f} | "
                      f"queue {get_total_queue()}")
            step += 1

        previous_phase["J1"] = j1_phase
        previous_phase["J2"] = j2_phase

    traci.close()

    # Write per-step log for this seed.
    raw_path = os.path.join(RAW_DIR, f"max_pressure_corridor_2x2_seed{seed}.csv")
    with open(raw_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # Run-level summary: mean over the episode of the step metrics, matching
    # the way the other controllers are summarized for the DCHF tables.
    n = len(rows)
    mean_waiting = sum(r["total_waiting_time"] for r in rows) / n
    mean_speed = sum(r["mean_speed"] for r in rows) / n
    mean_queue = sum(r["total_queue"] for r in rows) / n
    mean_vehicles = sum(r["vehicle_count"] for r in rows) / n

    print(f"[seed {seed}] DONE  mean_waiting={mean_waiting:.3f}  "
          f"raw -> {raw_path}")

    return {
        "seed": seed,
        "mean_waiting": mean_waiting,
        "mean_speed": mean_speed,
        "mean_queue": mean_queue,
        "mean_vehicles": mean_vehicles,
    }


# ============================================================
# MULTI-SEED DRIVER
# ============================================================

def main():
    per_seed = []
    for i, seed in enumerate(SEEDS):
        # verify out-lanes only on the first seed
        per_seed.append(run_single_seed(seed, verify_outlanes=(i == 0)))

    def mean_std(key):
        vals = [r[key] for r in per_seed]
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) > 1 else 0.0
        return m, s

    mw, sw = mean_std("mean_waiting")
    msp, ssp = mean_std("mean_speed")
    mq, sq = mean_std("mean_queue")
    mv, sv = mean_std("mean_vehicles")

    # Write the summary CSV (one row per seed + an aggregate row).
    with open(SUMMARY_CSV, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["seed", "mean_waiting", "mean_speed",
                           "mean_queue", "mean_vehicles"])
        writer.writeheader()
        writer.writerows(per_seed)
        writer.writerow({
            "seed": "MEAN+-STD",
            "mean_waiting": f"{mw:.3f}+-{sw:.3f}",
            "mean_speed": f"{msp:.3f}+-{ssp:.3f}",
            "mean_queue": f"{mq:.3f}+-{sq:.3f}",
            "mean_vehicles": f"{mv:.3f}+-{sv:.3f}",
        })

    print("\n==================== MAX-PRESSURE SUMMARY ====================")
    print(f"Seeds: {SEEDS}")
    print(f"Mean total waiting time : {mw:.3f} +/- {sw:.3f}")
    print(f"Mean speed              : {msp:.3f} +/- {ssp:.3f}")
    print(f"Mean total queue        : {mq:.3f} +/- {sq:.3f}")
    print(f"Mean vehicles           : {mv:.3f} +/- {sv:.3f}")
    print(f"\nSummary CSV -> {SUMMARY_CSV}")
    print("\nDrop the mean +/- std waiting time into the Scenario A")
    print("controller-comparison table, next to QMIX V2 and the optimized offset.")
    print("Coordination Gain vs. simultaneous fixed-time:")
    print("   CG = (1 - mean_waiting_MP / mean_waiting_sim) * 100")
    print("Approximation gap vs. optimized offset:")
    print("   it is a non-learning classical baseline, so report its CG and its")
    print("   waiting time; the QMIX gap is computed against the offset, not MP.")


if __name__ == "__main__":
    main()