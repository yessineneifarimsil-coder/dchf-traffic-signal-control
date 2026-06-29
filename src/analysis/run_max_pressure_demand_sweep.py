"""
Max Pressure demand sweep for the DCHF paper.

PURPOSE
-------
Adds Max Pressure to the demand horizon analysis (H_D).
Runs the same Max Pressure algorithm as max_pressure_corridor.py
(the script that produced Scenario A: 149.911 +/- 2.640) across
all 5 demand levels at d=300 m, 5 seeds each.

OUTPUTS  (all in results/tables/ to match the existing project layout)
-------
results/tables/max_pressure_demand_sweep_seed_summary.csv   -- per-seed
results/tables/max_pressure_demand_sweep_summary.csv        -- mean +/- std per level
results/tables/max_pressure_demand_comparison.csv           -- G_QMIX, G_MP, best ctrl

Run from the repository root:
    conda activate traffic_rl
    python src/analysis/run_max_pressure_demand_sweep.py
"""

import os
import csv
import statistics

import traci


# ============================================================
# CONFIGURATION
# ============================================================

SUMO_BINARY = "sumo"   # change to "sumo-gui" for visual debugging

# Copied EXACTLY from evaluate_qmix_demand_sensitivity.py (authoritative source)
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

SEEDS = [0, 1, 2, 3, 4]   # first 5 seeds, same as multi-seed Scenario A

SIMULATION_STEPS = 3600
MIN_GREEN        = 10      # acyclic re-evaluation interval (Varaiya 2013)
YELLOW_DURATION  = 3

# Phase indices -- identical to max_pressure_corridor.py
SIDE_GREEN  = 0
SIDE_YELLOW = 1
MAIN_GREEN  = 2
MAIN_YELLOW = 3

TL_IDS = ["J1", "J2"]

# Input files -- match the project layout (results/tables/)
OFFSET_INPUT = "results/tables/demand_offset_best_summary.csv"
QMIX_INPUT   = "results/tables/qmix_demand_sensitivity_summary.csv"

# Output files -- same layout
RAW_DIR      = "results/raw"
OUT_SEED     = "results/tables/max_pressure_demand_sweep_seed_summary.csv"
OUT_SUMMARY  = "results/tables/max_pressure_demand_sweep_summary.csv"
OUT_COMPARE  = "results/tables/max_pressure_demand_comparison.csv"


# ============================================================
# MAX PRESSURE LOGIC
# Copied verbatim from max_pressure_corridor.py (the validated version)
# ============================================================

def get_vehicle_count():
    return len(traci.vehicle.getIDList())

def get_total_waiting_time():
    return sum(traci.vehicle.getWaitingTime(v)
               for v in traci.vehicle.getIDList())

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

def lane_count(lane_id):
    """Vehicle count on lane (|V_l| in the Max Pressure definition)."""
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

def collect_step_data(step, j1_group, j2_group,
                      j1_sp, j1_mp, j2_sp, j2_mp):
    return {
        "step":              step,
        "J1_phase_group":   j1_group,
        "J2_phase_group":   j2_group,
        "vehicle_count":    get_vehicle_count(),
        "total_waiting_time": get_total_waiting_time(),
        "mean_speed":       get_mean_speed(),
        "total_queue":      get_total_queue(),
        "J1_phase":         traci.trafficlight.getPhase("J1"),
        "J2_phase":         traci.trafficlight.getPhase("J2"),
        "J1_side_pressure": j1_sp,
        "J1_main_pressure": j1_mp,
        "J2_side_pressure": j2_sp,
        "J2_main_pressure": j2_mp,
    }


# ============================================================
# SINGLE-SEED RUN
# ============================================================

def run_single_seed(demand_name, scenario_info, seed):
    """Run one 3600-step episode. Returns per-seed summary dict."""
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

    rows          = []
    step          = 0
    total_departed = 0
    total_arrived  = 0
    previous_phase = {"J1": MAIN_GREEN, "J2": MAIN_GREEN}

    try:
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
                    rows.append(collect_step_data(
                        step, "yellow_transition", "yellow_transition",
                        j1_sp, j1_mp, j2_sp, j2_mp))
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
                rows.append(collect_step_data(
                    step, j1_group, j2_group,
                    j1_sp, j1_mp, j2_sp, j2_mp))
                if step % 300 == 0:
                    n = len(rows)
                    print(f"  [seed {seed}] step {step} | "
                          f"J1 {j1_group} J2 {j2_group} | "
                          f"veh {get_vehicle_count()} | "
                          f"wait {get_total_waiting_time():.1f} | "
                          f"speed {get_mean_speed():.2f} | "
                          f"queue {get_total_queue()}")
                step += 1

            previous_phase["J1"] = j1_phase
            previous_phase["J2"] = j2_phase

    finally:
        try:
            traci.close()
        except Exception:
            pass

    # Per-step log
    raw_path = os.path.join(
        RAW_DIR,
        f"mp_demand_{demand_name}_seed{seed}.csv"
    )
    with open(raw_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # Summary metrics (mean over episode -- matches existing controller summaries)
    n = len(rows)
    mean_waiting  = sum(r["total_waiting_time"] for r in rows) / n
    mean_speed    = sum(r["mean_speed"]          for r in rows) / n
    mean_queue    = sum(r["total_queue"]          for r in rows) / n
    mean_vehicles = sum(r["vehicle_count"]        for r in rows) / n

    expected = scenario_info["expected_total_vehicles"]
    buffered = max(0, expected - total_departed)
    br       = buffered / expected if expected > 0 else 0.0

    summary = {
        "demand_scenario":    demand_name,
        "demand_multiplier":  scenario_info["multiplier"],
        "seed":               seed,
        "mean_waiting_time":  round(mean_waiting,  3),
        "mean_speed":         round(mean_speed,     3),
        "mean_queue":         round(mean_queue,     3),
        "mean_vehicle_count": round(mean_vehicles,  3),
        "total_departed":     total_departed,
        "total_arrived":      total_arrived,
        "buffered_ratio":     round(br, 4),
    }
    print(f"  [seed {seed}] DONE | "
          f"waiting={mean_waiting:.3f} | speed={mean_speed:.3f} | "
          f"BR={br:.4f} | raw -> {raw_path}")
    return summary


# ============================================================
# AGGREGATION
# ============================================================

def mean_std(values):
    vals = [float(v) for v in values]
    if not vals:
        return None, None
    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return m, s

def capacity_regime(br):
    if br < 0.01:  return "Unconstrained"
    if br < 0.10:  return "Mild insertion pressure"
    if br < 0.25:  return "Capacity-limited"
    return "Oversaturated"

def gap_regime(g):
    if g <= 5.0:   return "Effective"
    if g <= 10.0:  return "Marginal"
    return "Outside horizon"

def build_scenario_summary(seed_rows):
    from collections import defaultdict
    groups = defaultdict(list)
    for r in seed_rows:
        groups[r["demand_scenario"]].append(r)

    rows = []
    for name in DEMAND_SCENARIOS:
        g = groups.get(name, [])
        if not g:
            continue
        wt_m, wt_s = mean_std(r["mean_waiting_time"]  for r in g)
        sp_m, sp_s = mean_std(r["mean_speed"]          for r in g)
        q_m,  q_s  = mean_std(r["mean_queue"]          for r in g)
        br_m, br_s = mean_std(r["buffered_ratio"]       for r in g)
        rows.append({
            "demand_scenario":        name,
            "demand_multiplier":      g[0]["demand_multiplier"],
            "seeds_run":              len(g),
            "mp_waiting_mean":        round(wt_m, 3),
            "mp_waiting_std":         round(wt_s, 3),
            "mp_speed_mean":          round(sp_m, 3),
            "mp_speed_std":           round(sp_s, 3),
            "mp_queue_mean":          round(q_m,  3),
            "mp_queue_std":           round(q_s,  3),
            "mp_buffered_ratio_mean": round(br_m, 4),
            "mp_buffered_ratio_std":  round(br_s, 4),
            "mp_capacity_regime":     capacity_regime(br_m),
        })
    return rows


def build_comparison(mp_summary):
    """Merge with existing offset + QMIX results to produce G_QMIX, G_MP."""
    for path in (OFFSET_INPUT, QMIX_INPUT):
        if not os.path.exists(path):
            print(f"\nWARNING: {path} not found — skipping comparison table.")
            return None

    # Load offset: column 'best_waiting_time'
    offset = {}
    with open(OFFSET_INPUT, newline="") as f:
        for row in csv.DictReader(f):
            offset[row["demand_scenario"]] = row

    # Load QMIX: column 'mean_total_waiting_time'
    qmix = {}
    with open(QMIX_INPUT, newline="") as f:
        for row in csv.DictReader(f):
            qmix[row["demand_scenario"]] = row

    rows = []
    for mp in mp_summary:
        name = mp["demand_scenario"]
        off  = offset.get(name)
        qmx  = qmix.get(name)
        if not off or not qmx:
            print(f"  WARNING: no offset/QMIX entry for '{name}' — skipping.")
            continue

        offset_wait = float(off["best_waiting_time"])          # column confirmed
        qmix_wait   = float(qmx["mean_total_waiting_time"])   # column confirmed
        mp_wait     = float(mp["mp_waiting_mean"])

        g_qmix = ((qmix_wait - offset_wait) / offset_wait) * 100.0
        g_mp   = ((mp_wait   - offset_wait) / offset_wait) * 100.0
        br_mp  = float(mp["mp_buffered_ratio_mean"])

        best = min(
            {"Optimized offset": offset_wait,
             "QMIX V2":          qmix_wait,
             "Max Pressure":     mp_wait},
            key=lambda k: {"Optimized offset": offset_wait,
                           "QMIX V2": qmix_wait,
                           "Max Pressure": mp_wait}[k]
        )

        rows.append({
            "demand_scenario":          name,
            "demand_multiplier":        mp["demand_multiplier"],
            "offset_waiting":           round(offset_wait, 3),
            "qmix_waiting_single_seed": round(qmix_wait,   3),
            "mp_waiting_mean":          round(mp_wait,      3),
            "mp_waiting_std":           mp["mp_waiting_std"],
            "G_QMIX_pct":              round(g_qmix, 3),
            "G_MP_pct":                round(g_mp,   3),
            "mp_buffered_ratio":        round(br_mp, 4),
            "mp_capacity_regime":       capacity_regime(br_mp),
            "qmix_dchf_regime":         gap_regime(g_qmix),
            "mp_dchf_regime":           gap_regime(g_mp),
            "best_controller":          best,
        })
    return rows


# ============================================================
# MAIN
# ============================================================

def write_csv(path, rows):
    if not rows:
        print(f"  (nothing to write: {path})")
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"  Saved: {path}")


def main():
    os.makedirs(RAW_DIR,            exist_ok=True)
    os.makedirs("results/tables",   exist_ok=True)

    print("\n" + "=" * 70)
    print("MAX PRESSURE DEMAND SWEEP — DCHF paper (H_D horizon)")
    print(f"Scenarios : {list(DEMAND_SCENARIOS.keys())}")
    print(f"Seeds     : {SEEDS}")
    print(f"Steps/run : {SIMULATION_STEPS}")
    print("=" * 70)

    all_seed_rows = []
    for demand_name, scenario_info in DEMAND_SCENARIOS.items():
        print(f"\n--- {demand_name.upper()} "
              f"({scenario_info['multiplier']}x, "
              f"expected {scenario_info['expected_total_vehicles']} veh) ---")
        for seed in SEEDS:
            row = run_single_seed(demand_name, scenario_info, seed)
            all_seed_rows.append(row)

    print("\n" + "=" * 70)
    print("AGGREGATING")
    print("=" * 70)

    mp_summary = build_scenario_summary(all_seed_rows)
    comparison = build_comparison(mp_summary)

    write_csv(OUT_SEED,    all_seed_rows)
    write_csv(OUT_SUMMARY, mp_summary)
    if comparison:
        write_csv(OUT_COMPARE, comparison)

    if comparison:
        print("\n" + "=" * 70)
        print("RESULTS — send results/tables/max_pressure_demand_comparison.csv to Claude")
        print("=" * 70)
        fmt = "{:18s} {:>8s} {:>10s} {:>12s} {:>9s} {:>9s} {:>7s} {:>18s}"
        print(fmt.format(
            "Demand", "Offset", "QMIX(1sd)", "MP(mean±std)",
            "G_QMIX%", "G_MP%", "BR", "Best"))
        print("-" * 100)
        for r in comparison:
            mp_str = f"{r['mp_waiting_mean']:.3f}±{r['mp_waiting_std']:.3f}"
            print(fmt.format(
                r["demand_scenario"],
                f"{r['offset_waiting']:.3f}",
                f"{r['qmix_waiting_single_seed']:.3f}",
                mp_str,
                f"{r['G_QMIX_pct']:+.3f}",
                f"{r['G_MP_pct']:+.3f}",
                f"{r['mp_buffered_ratio']:.4f}",
                r["best_controller"],
            ))

    print("\nDONE.")


if __name__ == "__main__":
    main()
