"""
Fully-paired multi-seed demand + spatial sweeps, VERSION 2.

Extends the validated run_fully_paired_sweeps.py with the three components the
original campaign did not log, closing reviewer items #3 (multi-seed Coordination
Gain / buffered ratio for the cells that drive the integrated DCHF class) and
#6 (secondary operational metric):

  1. SIMULTANEOUS FIXED-TIME as a fourth controller (offset 0 s), giving a
     per-seed Coordination Gain for every controller instead of carrying the
     single-seed exploratory-grid CG into the "final" integrated map.
  2. PER-CONTROLLER BUFFERED RATIO, computed from SUMO's --summary-output using
     buffered = max(0, expected - inserted), which is byte-identical to the
     published formula at run_max_pressure_demand_sweep.py:276.
  3. TRIPINFO secondary metrics (mean trip duration, mean time loss, mean
     per-vehicle waiting time, completed count) for every controller/seed, so
     the principal regime boundaries can be re-tested under a metric that is
     NOT the QMIX training objective.

DESIGN CONSTRAINTS (deliberate):
  * Writes to NEW output paths. results/tables/fully_paired_sweeps_raw.csv and
    ..._summary.csv are left untouched as the regression reference.
  * The first five raw columns (sweep, cell, seed, offset_wt, qmix_wt, mp_wt)
    are emitted FIRST and in the ORIGINAL ORDER so the shared columns can be
    diffed against the committed CSV. --summary-output and --tripinfo-output are
    output-only SUMO flags and must not perturb the simulation: any drift in
    those three columns means something else broke. STOP if that happens.
  * Loads the SAME original unseeded checkpoint (results/raw/qmix_corridor_
    model_v2.pth) as the published campaign. The seeded training checkpoints are
    a separate experiment and must not be mixed in here.
  * expected_total_vehicles uses the canonical per-demand values already defined
    in run_demand_offset_sweep.py / analyze_spillback_demand.py /
    evaluate_qmix_demand_sensitivity.py. It does NOT use the module-level
    EXPECTED_TOTAL_VEHICLES = 2800 constant inside run_distance_offset_sweep.py,
    which is correct only for medium demand.

PREREQUISITES (two small patches, see accompanying notes):
  * two_intersection_env.py       -> class attribute DEFAULT_EXTRA_ARGS + append
  * run_distance_offset_sweep.py  -> extra_args parameter on run_distance_offset

SANITY: d=300 m / medium QMIX gap must reproduce ~2.7 % (published five-seed
value 2.678 %). A QMIX gap > 150 % anywhere = broken run; STOP.

Run from repo root:
    conda activate traffic_rl
    python src\\analysis\\run_fully_paired_sweeps_v2.py
"""
import os
import sys
import csv
import glob
import xml.etree.ElementTree as ET

import numpy as np
from scipy.stats import wilcoxon

REPO_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "qmix"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "baselines", "two_intersections"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "env", "two_intersections"))

import traci
import evaluate_qmix_distance_sensitivity as qdist
import run_distance_offset_sweep as offsweep
import max_pressure_corridor as mpc
from two_intersection_env import TwoIntersectionEnv

if not hasattr(qdist, "np"):
    qdist.np = np  # distance module uses np.nan but only imports pandas

SEEDS = [0, 1, 2, 3, 4]

# Keep the raw per-vehicle XML after parsing? 220 runs x 2 files is large
# (tripinfo at oversaturation is ~7000 vehicles), so parse-then-delete by
# default and retain only the aggregates.
KEEP_XML = False

XML_DIR = "results/raw/paired_v2_xml"
OUT_RAW = "results/tables/fully_paired_sweeps_v2_raw.csv"
OUT_SUMMARY = "results/tables/fully_paired_sweeps_v2_summary.csv"
OUT_TRIPINFO = "results/tables/fully_paired_sweeps_v2_tripinfo.csv"

MEDIUM_EXPECTED = 2800

# Spatial sweep: (distance, config, best offset at medium demand, expected)
SPATIAL = [
    (100,  "sumo_scenarios/two_intersections/distance_100m/corridor_turning.sumocfg",  25, MEDIUM_EXPECTED),
    (200,  "sumo_scenarios/two_intersections/distance_200m/corridor_turning.sumocfg",  45, MEDIUM_EXPECTED),
    (300,  "sumo_scenarios/two_intersections/distance_300m/corridor_turning.sumocfg",  45, MEDIUM_EXPECTED),
    (500,  "sumo_scenarios/two_intersections/distance_500m/corridor_turning.sumocfg",  70, MEDIUM_EXPECTED),
    (750,  "sumo_scenarios/two_intersections/distance_750m/corridor_turning.sumocfg",   0, MEDIUM_EXPECTED),
    (1000, "sumo_scenarios/two_intersections/distance_1000m/corridor_turning.sumocfg", 85, MEDIUM_EXPECTED),
]

# Demand sweep at d=300 m: (name, config, best offset, expected)
# expected values are the canonical repo constants, NOT 2800 x multiplier.
DEMAND = [
    ("low",            "sumo_scenarios/two_intersections/demand_sensitivity/demand_low/corridor_turning.sumocfg",            45, 1396),
    ("medium",         "sumo_scenarios/two_intersections/demand_sensitivity/demand_medium/corridor_turning.sumocfg",         45, 2800),
    ("high",           "sumo_scenarios/two_intersections/demand_sensitivity/demand_high/corridor_turning.sumocfg",           55, 4204),
    ("saturation",     "sumo_scenarios/two_intersections/demand_sensitivity/demand_saturation/corridor_turning.sumocfg",     45, 5600),
    ("oversaturation", "sumo_scenarios/two_intersections/demand_sensitivity/demand_oversaturation/corridor_turning.sumocfg", 50, 6996),
]


# ============================================================
# SUMO OUTPUT PLUMBING
# ============================================================

def _tag(sweep, cell, controller, seed):
    safe = str(cell).replace("=", "").replace(" ", "")
    return f"{sweep}_{safe}_{controller}_seed{seed}"


def _xml_paths(sweep, cell, controller, seed):
    os.makedirs(XML_DIR, exist_ok=True)
    tag = _tag(sweep, cell, controller, seed)
    return (
        os.path.join(XML_DIR, f"{tag}_summary.xml"),
        os.path.join(XML_DIR, f"{tag}_tripinfo.xml"),
    )


def _extra_args(summary_path, tripinfo_path):
    return [
        "--summary-output", summary_path,
        "--tripinfo-output", tripinfo_path,
        "--no-step-log", "true",
    ]


def parse_summary_inserted(summary_path):
    """Return cumulative inserted vehicles at the final logged step.

    SUMO's summary-output writes one <step> per second carrying cumulative
    'inserted' and instantaneous 'waiting' (the insertion backlog). 'inserted'
    is the same quantity the existing scripts accumulate via
    traci.simulation.getDepartedNumber().
    """
    if not os.path.exists(summary_path):
        return None
    inserted = None
    for _, elem in ET.iterparse(summary_path, events=("end",)):
        if elem.tag == "step":
            val = elem.get("inserted")
            if val is not None:
                inserted = int(float(val))
            elem.clear()
    return inserted


def parse_tripinfo(tripinfo_path):
    """Aggregate completed-trip statistics.

    Only vehicles that finished the trip appear here, so 'completed' is reported
    alongside the means: under capacity pressure the controllers do not complete
    identical vehicle sets, exactly as the buffered ratio documents for the
    waiting-state metric.
    """
    if not os.path.exists(tripinfo_path):
        return {}
    dur, loss, wait, depart_delay = [], [], [], []
    for _, elem in ET.iterparse(tripinfo_path, events=("end",)):
        if elem.tag == "tripinfo":
            dur.append(float(elem.get("duration", "nan")))
            loss.append(float(elem.get("timeLoss", "nan")))
            wait.append(float(elem.get("waitingTime", "nan")))
            depart_delay.append(float(elem.get("departDelay", "nan")))
            elem.clear()
    if not dur:
        return {}
    return {
        "completed": len(dur),
        "mean_trip_duration": float(np.mean(dur)),
        "mean_time_loss": float(np.mean(loss)),
        "mean_veh_waiting_time": float(np.mean(wait)),
        "mean_depart_delay": float(np.mean(depart_delay)),
        "total_time_loss_vehhours": float(np.sum(loss)) / 3600.0,
    }


def _cleanup(*paths):
    if KEEP_XML:
        return
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def _finalize(summary_path, tripinfo_path, expected, wt):
    inserted = parse_summary_inserted(summary_path)
    trip = parse_tripinfo(tripinfo_path)
    _cleanup(summary_path, tripinfo_path)

    if inserted is None:
        buffered, br = None, None
    else:
        buffered = max(0, expected - inserted)
        br = buffered / expected if expected > 0 else 0.0

    out = {
        "wt": float(wt),
        "inserted": inserted,
        "buffered": buffered,
        "buffered_ratio": br,
    }
    out.update(trip)
    return out


# ============================================================
# CONTROLLER RUNNERS
# ============================================================

def run_offset(config, offset, seed, distance, expected, sweep, cell, controller):
    """Fixed-time with a given offset. offset=0 is simultaneous fixed-time."""
    sp, tp = _xml_paths(sweep, cell, controller, seed)
    _, s = offsweep.run_distance_offset(
        distance=distance,
        offset=offset,
        sumo_seed=seed,
        sumo_config_override=config,
        scenario_label="paired_v2",
        extra_args=_extra_args(sp, tp),
    )
    # NOTE: s["buffered_ratio"] from the offset module uses its hardcoded
    # EXPECTED_TOTAL_VEHICLES = 2800 and is WRONG off medium demand. It is
    # deliberately discarded here in favour of the per-cell expected value.
    return _finalize(sp, tp, expected, s["mean_total_waiting_time"])


def run_qmix(config, seed, distance, expected, sweep, cell):
    """Frozen QMIX V2, original unseeded checkpoint, via the env class hook."""
    sp, tp = _xml_paths(sweep, cell, "qmix", seed)
    TwoIntersectionEnv.DEFAULT_EXTRA_ARGS = _extra_args(sp, tp)
    try:
        _, s = qdist.evaluate_qmix_for_distance(
            distance=distance,
            sumo_seed=seed,
            sumo_config_override=config,
            scenario_label="paired_v2",
        )
    finally:
        TwoIntersectionEnv.DEFAULT_EXTRA_ARGS = []
    return _finalize(sp, tp, expected, s["mean_total_waiting_time"])


def run_mp(config, seed, expected, sweep, cell):
    """Two-intersection Max Pressure, reusing the proven per-TL functions.

    Loop body is byte-identical to run_fully_paired_sweeps.py; only the
    traci.start argument list gains the output flags.
    """
    sp, tp = _xml_paths(sweep, cell, "mp", seed)
    traci.start([mpc.SUMO_BINARY, "-c", config, "--seed", str(seed)]
                + _extra_args(sp, tp))
    tls = list(traci.trafficlight.getIDList())
    prev = {tl: mpc.MAIN_GREEN for tl in tls}
    waits = []
    step = 0
    while step < mpc.SIMULATION_STEPS:
        chosen, any_yellow = {}, False
        for tl in tls:
            phase, *_ = mpc.choose_max_pressure_phase(tl)
            chosen[tl] = phase
            if mpc.apply_transition(tl, prev[tl], phase):
                any_yellow = True
        if any_yellow:
            for _ in range(mpc.YELLOW_DURATION):
                if step >= mpc.SIMULATION_STEPS:
                    break
                traci.simulationStep(); waits.append(mpc.get_total_waiting_time()); step += 1
        for tl in tls:
            traci.trafficlight.setPhase(tl, chosen[tl])
            traci.trafficlight.setPhaseDuration(tl, mpc.MIN_GREEN)
        for _ in range(mpc.MIN_GREEN):
            if step >= mpc.SIMULATION_STEPS:
                break
            traci.simulationStep(); waits.append(mpc.get_total_waiting_time()); step += 1
        for tl in tls:
            prev[tl] = chosen[tl]
    traci.close()
    return _finalize(sp, tp, expected, float(np.mean(waits)))


# ============================================================
# STATISTICS
# ============================================================

def bootstrap_ci(vals, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    a = np.array(vals, float)
    b = [np.mean(rng.choice(a, size=len(a), replace=True)) for _ in range(n)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def regime(gap):
    return "Effective" if gap <= 5 else ("Marginal" if gap <= 10 else "Outside horizon")


def integrated_class(gap, cg, br):
    """Eq. (14) of the manuscript, with capacity precedence inside the
    gap-effective branch only."""
    if gap is None or br is None or cg is None:
        return "undetermined"
    if gap <= 5:
        if br >= 0.10:
            return "capacity-constrained effective"
        if cg > 0:
            return "useful-effective"
        return "close/no-gain"
    if gap <= 10:
        return "marginal"
    return "outside horizon"


def paired_p(a, b):
    d = np.array(a) - np.array(b)
    if np.allclose(d, 0):
        return float("nan")
    try:
        return float(wilcoxon(a, b).pvalue)
    except Exception:
        return float("nan")


def _mean(vals):
    clean = [v for v in vals if v is not None and not (isinstance(v, float) and np.isnan(v))]
    return float(np.mean(clean)) if clean else None


# ============================================================
# MAIN LOOP
# ============================================================

def process(sweep, cells, is_spatial):
    raw, summ, trips = [], [], []
    for cell_spec in cells:
        if is_spatial:
            dist, config, offset, expected = cell_spec
            cell = f"d={dist}m"
        else:
            name, config, offset, expected = cell_spec
            dist, cell = 300, name

        if not os.path.exists(config):
            print(f"[WARN] missing config, skipping: {config}")
            continue

        print(f"\n=== {sweep}: {cell} (offset {offset}s, expected {expected}) ===")
        sims, offs, qms, mps = [], [], [], []

        for seed in SEEDS:
            si = run_offset(config, 0, seed, dist, expected, sweep, cell, "sim")
            of = run_offset(config, offset, seed, dist, expected, sweep, cell, "offset")
            qm = run_qmix(config, seed, dist, expected, sweep, cell)
            mp = run_mp(config, seed, expected, sweep, cell)

            sims.append(si); offs.append(of); qms.append(qm); mps.append(mp)

            row = {
                # --- original five columns, original order (regression check) ---
                "sweep": sweep,
                "cell": cell,
                "seed": seed,
                "offset_wt": round(of["wt"], 3),
                "qmix_wt": round(qm["wt"], 3),
                "mp_wt": round(mp["wt"], 3),
                # --- new ---
                "sim_wt": round(si["wt"], 3),
                "expected_total_vehicles": expected,
            }
            for label, d in (("sim", si), ("offset", of), ("qmix", qm), ("mp", mp)):
                row[f"{label}_inserted"] = d["inserted"]
                row[f"{label}_buffered_ratio"] = (
                    None if d["buffered_ratio"] is None else round(d["buffered_ratio"], 4)
                )
            # per-seed Coordination Gain against simultaneous fixed-time
            for label, d in (("offset", of), ("qmix", qm), ("mp", mp)):
                row[f"cg_{label}"] = round((1 - d["wt"] / si["wt"]) * 100, 3) if si["wt"] else None
            raw.append(row)

            for label, d in (("sim", si), ("offset", of), ("qmix", qm), ("mp", mp)):
                if "mean_trip_duration" in d:
                    trips.append({
                        "sweep": sweep, "cell": cell, "seed": seed, "controller": label,
                        "completed": d["completed"],
                        "mean_trip_duration": round(d["mean_trip_duration"], 3),
                        "mean_time_loss": round(d["mean_time_loss"], 3),
                        "mean_veh_waiting_time": round(d["mean_veh_waiting_time"], 3),
                        "mean_depart_delay": round(d["mean_depart_delay"], 3),
                        "total_time_loss_vehhours": round(d["total_time_loss_vehhours"], 3),
                        "waiting_state_metric": round(d["wt"], 3),
                    })

            print(f"  seed {seed}: sim={si['wt']:.2f} offset={of['wt']:.2f} "
                  f"qmix={qm['wt']:.2f} mp={mp['wt']:.2f} | "
                  f"BR_qmix={qm['buffered_ratio']} BR_mp={mp['buffered_ratio']}")

        o_wt = [d["wt"] for d in offs]
        q_wt = [d["wt"] for d in qms]
        m_wt = [d["wt"] for d in mps]
        s_wt = [d["wt"] for d in sims]

        g_q = [(q - o) / o * 100 for q, o in zip(q_wt, o_wt)]
        g_m = [(m - o) / o * 100 for m, o in zip(m_wt, o_wt)]
        cg_q = [(1 - q / s) * 100 for q, s in zip(q_wt, s_wt)]
        cg_off = [(1 - o / s) * 100 for o, s in zip(o_wt, s_wt)]

        gq_lo, gq_hi = bootstrap_ci(g_q)
        gm_lo, gm_hi = bootstrap_ci(g_m)
        cgq_lo, cgq_hi = bootstrap_ci(cg_q)

        br_q = _mean([d["buffered_ratio"] for d in qms])
        br_m = _mean([d["buffered_ratio"] for d in mps])
        br_o = _mean([d["buffered_ratio"] for d in offs])

        means = {"Simultaneous fixed-time": float(np.mean(s_wt)),
                 "Optimized offset": float(np.mean(o_wt)),
                 "QMIX": float(np.mean(q_wt)),
                 "Max Pressure": float(np.mean(m_wt))}
        best = min(means, key=means.get)

        summ.append({
            "sweep": sweep, "cell": cell, "offset": offset,
            "expected_total_vehicles": expected,
            "sim_wt_mean": round(means["Simultaneous fixed-time"], 3),
            "offset_wt_mean": round(means["Optimized offset"], 3),
            "offset_wt_std": round(float(np.std(o_wt, ddof=1)), 3),
            "qmix_wt_mean": round(means["QMIX"], 3),
            "qmix_wt_std": round(float(np.std(q_wt, ddof=1)), 3),
            "mp_wt_mean": round(means["Max Pressure"], 3),
            "mp_wt_std": round(float(np.std(m_wt, ddof=1)), 3),
            "G_QMIX_mean": round(float(np.mean(g_q)), 3),
            "G_QMIX_ci": f"[{gq_lo:.2f}, {gq_hi:.2f}]",
            "G_MP_mean": round(float(np.mean(g_m)), 3),
            "G_MP_ci": f"[{gm_lo:.2f}, {gm_hi:.2f}]",
            "CG_off_mean": round(float(np.mean(cg_off)), 3),
            "CG_QMIX_mean": round(float(np.mean(cg_q)), 3),
            "CG_QMIX_ci": f"[{cgq_lo:.2f}, {cgq_hi:.2f}]",
            "BR_offset_mean": None if br_o is None else round(br_o, 4),
            "BR_QMIX_mean": None if br_q is None else round(br_q, 4),
            "BR_MP_mean": None if br_m is None else round(br_m, 4),
            "p_offset_qmix": round(paired_p(o_wt, q_wt), 5),
            "p_offset_mp": round(paired_p(o_wt, m_wt), 5),
            "qmix_regime": regime(float(np.mean(g_q))),
            "qmix_integrated_class": integrated_class(
                float(np.mean(g_q)), float(np.mean(cg_q)), br_q),
            "best_controller": best,
        })

        print(f"  --> offset {means['Optimized offset']:.2f} | "
              f"QMIX {means['QMIX']:.2f} (G {np.mean(g_q):+.2f}%, "
              f"CG {np.mean(cg_q):+.2f}%, BR {br_q}) | "
              f"MP {means['Max Pressure']:.2f} (G {np.mean(g_m):+.2f}%) | best {best}")

    return raw, summ, trips


def _write(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"Saved: {path}  ({len(rows)} rows)")


def main():
    os.makedirs("results/tables", exist_ok=True)
    raw_all, summ_all, trip_all = [], [], []
    for sweep, cells, spatial in [("spatial", SPATIAL, True), ("demand", DEMAND, False)]:
        r, s, t = process(sweep, cells, spatial)
        raw_all += r; summ_all += s; trip_all += t

    _write(OUT_RAW, raw_all)
    _write(OUT_SUMMARY, summ_all)
    _write(OUT_TRIPINFO, trip_all)

    print("\n========== REGRESSION CHECK ==========")
    print("Compare the three shared columns against the committed reference:")
    print("  python src\\analysis\\check_paired_v2_regression.py")
    print("d=300m / medium QMIX gap should reproduce ~2.68% (published five-seed).")
    print("Paired Wilcoxon at n=5: minimum attainable p is 0.0625; report CIs.")


if __name__ == "__main__":
    main()
