"""Fair comparators for the robustness profiles R0-R4: search, validation, selection (prepared, not launched).

    python tools/comparators/comparator_search.py plan     --root D:\\QMIX_Results\\comparators_<date>
    python tools/comparators/comparator_search.py measure  --root ...          (3 runs, writes measure.json)
    python tools/comparators/comparator_search.py prepare  --root ... --approved-plan <fingerprint>
    python tools/comparators/comparator_search.py run      --root ... --stage <stage> --shard i/n
    python tools/comparators/comparator_search.py progress --root ... [--stage <stage>]
    python tools/comparators/comparator_search.py finalise --root ... --stage <stage>
    python tools/comparators/comparator_search.py verify-manifests --root ... --robustness-root <robustness root>

Comparators, per profile, all selected on that profile's own design (8c11-8c15) and validation (8c21-8c25)
seeds, never on the robustness evaluation seeds (8c01-8c05) nor on the reserved confirmation seeds (8c51-8c60):
  A1 OFT g5 and OFT min7: the original OFT procedure (grids.py): coarse (with short cycles and the floor
     extension) -> top 5 realized plans -> fine union -> top 10 -> validation -> select_timing_plan order
     (mean J, mean time loss, shorter cycle, realized key). The min-7 coarse plans are a subset of the g5 ones:
     each realized plan is simulated once per seed and shared.
  A2 actuated gap-out, minimum green 7 s: ACTUATED_GRID (27 settings) -> top 5 -> validation -> selection
     (mean J, mean time loss, then the grid order).
  A3 R3 only, plans by period (per version): each period [0,900), [900,2700), [2700,3600) ranks every plan
     with complete valid design runs on R3 (coarse + fine of that version, no new run) by its period J (mean of
     waitingTime + departDelay over the vehicles SCHEDULED in the period, plan run for the whole episode); top 3
     per period -> 27 time-of-day combinations run with the real transitions (controllers.py) on design ->
     top 5 -> validation -> selection.
  Then the selected comparators are evaluated once, with per-second service counters and full logs, on the
  robustness evaluation traffics 8c01-8c05 (stage robustness-eval), next to the existing robustness cells.

Validity (frozen rule): a candidate is valid only if each of its design (or validation) runs is CLEARED with a
valid, finite J and a finite time loss; invalid candidates are excluded, never imputed; a clearance failure is
a finished observation and is never rerun. Every order is written once (sealed with its SHA-256) by `finalise`
of the previous stage, which prints the exact number of runs before any is launched.

Run states and exit codes as in the robustness runner: complete / scientific failure (finished), corrupted
(preserved, never rerun, code 5), interrupted (renamed .incomplete1 and run once more), not started (code 3).
"""
from __future__ import absolute_import, print_function

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "robustness"))
PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")
sys.path.insert(0, os.path.join(PROTECTED, "src"))

import seeds as SD  # noqa: E402
import scenario_traffic as st  # noqa: E402

VERSIONS = (("g5", 5), ("min7", 7))
ACTUATED_GRID = [{"gap_s": g, "max_green_H_s": h, "max_green_V_s": v, "zone_m": 40}
                 for g in (2, 3, 4) for h in (30, 45, 60) for v in (15, 25, 35)]
ACTUATED_RETAINED = 5
TOD_PROFILE = "R3_time_varying"
TOD_PERIODS = ((0, 900), (900, 2700), (2700, 3600))
TOD_PER_PERIOD = 3
TOD_RETAINED = 5
DEFAULT_SECONDS_PER_RUN = (6.0, 15.0)     # range used before measure.json exists (see plan)
DEFAULT_BYTES = {"compact": 85000, "full": 2400000}
WORKERS = 4
CODE_FILES = ("comparator_search.py", "grids.py", "controllers.py", "evaluate_comparator.py", "seeds.py",
              os.path.join("..", "robustness", "evaluate_any.py"), os.path.join("..", "robustness", "n_adapter.py"),
              os.path.join("..", "robustness", "scenario_traffic.py"))
STAGES = ["coarse", "fine-g5", "fine-min7", "validation-g5", "validation-min7", "actuated-design",
          "actuated-validation", "tod-design-g5", "tod-design-min7", "tod-validation-g5", "tod-validation-min7",
          "robustness-eval"]
FINISHED = ("complete", "scientific_failure")
COMPACT_FILES = ("evaluation_metrics.json", "run_manifest.json", "episode_summary.csv", "tripinfo.xml.gz")
FULL_FILES = ("evaluation_metrics.json", "run_manifest.json", "episode_summary.csv", "tripinfo.xml",
              "signal_phases.csv", "reward_seconds.csv", "service_counters.csv")


class SearchError(RuntimeError):
    pass


def sha256_file(path):
    return st.sha256_file(path)


def sha_obj(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def read_json(path):
    with open(path) as handle:
        return json.load(handle)


def finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Specs and jobs.
# ---------------------------------------------------------------------------

def canonical_split(cycle, green_h):
    """Lowest split (thousandths) that the frozen make_plan rounds to green_h: the plan's canonical name."""
    usable = int(cycle) - 6
    for split in range(0, 1001):
        exact = Decimal(split) * Decimal(usable) / Decimal(1000)
        if int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) == int(green_h):
            return split
    raise SearchError("no split gives g_H={} at C={}".format(green_h, cycle))


def fixed_spec(key):
    cycle, g_h, g_v, offset = (int(v) for v in key)
    split = canonical_split(cycle, g_h)
    return {"kind": "fixed", "plan": {"cycle_s": cycle, "split_thousandths": split, "f_H": round(split / 1000.0, 3),
                                      "green_H_s": g_h, "green_V_s": g_v, "yellow_s": 3, "offset_s": offset % cycle}}


def tod_spec(keys):
    return {"kind": "tod", "periods": [[a, fixed_spec(k)["plan"]] for (a, _b), k in zip(TOD_PERIODS, keys)]}


def actuated_spec(params):
    return {"kind": "actuated", "params": dict(params)}


def job(profile, seed, spec, full=False):
    digest = sha_obj(spec)
    return {"profile": profile, "seed": int(seed), "spec": spec, "spec_sha256": digest, "full": bool(full),
            "directory": os.path.join("runs", profile, str(seed), "{}_{}{}".format(
                spec["kind"], digest[:16], "_full" if full else ""))}


def search_jobs(profile, role, specs):
    out = []
    for seed in SD.seeds(profile, role):
        SD.assert_search_seed(profile, seed)
        out.extend(job(profile, seed, spec) for spec in specs)
    return out


# ---------------------------------------------------------------------------
# Plan.
# ---------------------------------------------------------------------------

def code_hashes():
    return dict((os.path.basename(f), sha256_file(os.path.join(HERE, f))) for f in CODE_FILES)


def coarse_specs():
    import grids as G
    return [fixed_spec(k) for k in sorted(G.groups(G.coarse_labels(5)))]


def estimate(runs, measure, mode="compact"):
    if measure:
        lo = hi = float(measure["seconds_per_run"])
        size = float(measure["bytes_per_run_" + mode])
    else:
        lo, hi = DEFAULT_SECONDS_PER_RUN
        size = DEFAULT_BYTES[mode]
    return {"runs": runs, "wall_h_4_workers": [round(runs * lo / WORKERS / 3600.0, 1),
                                               round(runs * hi / WORKERS / 3600.0, 1)],
            "disk_gb": round(runs * size / 1e9, 2)}


def build_plan(root):
    import grids as G
    SD.check_disjoint()
    spec = st.load_spec()
    measure_path = os.path.join(root, "measure.json")
    measure = read_json(measure_path) if os.path.isfile(measure_path) else None
    n_coarse = len(coarse_specs())
    per_profile = {"coarse": n_coarse * 5, "fine_upper_bound_per_version": G.fine_bound(5)["upper_bound_new_plans"] * 5,
                   "validation_per_version": G.FINE_RETAINED * 5,
                   "actuated": len(ACTUATED_GRID) * 5 + ACTUATED_RETAINED * 5}
    n = len(SD.PROFILES)
    tod = 2 * (TOD_PER_PERIOD ** len(TOD_PERIODS) * 5 + TOD_RETAINED * 5)
    robust = n * 5 * 3 + 2 * 5
    known = n * (per_profile["coarse"] + 2 * per_profile["validation_per_version"] + per_profile["actuated"]) + tod
    worst = known + n * 2 * per_profile["fine_upper_bound_per_version"]
    plan = {"study": "fair_comparators_robustness_profiles", "root": os.path.abspath(root),
            "profiles": list(SD.PROFILES), "seed_registry": SD.registry(), "scenario_spec_sha256": spec["_sha256"],
            "versions": dict(VERSIONS), "grids": {"g5": G.report(5), "min7": G.report(7)},
            "coarse_plans_shared": n_coarse, "actuated_grid": ACTUATED_GRID, "tod_periods": [list(p) for p in TOD_PERIODS],
            "tod_per_period": TOD_PER_PERIOD, "code_sha256": code_hashes(), "stages": STAGES,
            "runs_per_profile": per_profile, "tod_runs": tod, "robustness_eval_runs": robust,
            "runs_known_before_coarse": known, "runs_upper_bound": worst + robust,
            "estimate_known": estimate(known, measure), "estimate_upper_bound": estimate(worst, measure),
            "estimate_robustness_eval": estimate(robust, measure, "full"),
            "measure": measure, "measure_sha256": sha256_file(measure_path) if measure else None}
    plan["fingerprint"] = sha_obj(plan)
    return plan


def load_plan(root):
    plan = read_json(os.path.join(root, "plan.json"))
    if plan["code_sha256"] != code_hashes():
        raise SearchError("code differs from the code fixed in plan.json")
    return plan


# ---------------------------------------------------------------------------
# Orders (sealed, written once).
# ---------------------------------------------------------------------------

def order_path(root, stage):
    return os.path.join(root, "orders", stage + ".json")


def write_order(root, stage, jobs, inputs):
    path = order_path(root, stage)
    if os.path.exists(path):
        raise SearchError("order {} already written (applied once)".format(stage))
    payload = {"stage": stage, "jobs": jobs, "inputs": inputs}
    payload["sha256"] = sha_obj({k: v for k, v in payload.items()})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    unique = len(set(j["directory"] for j in jobs))
    print("order {}: {} jobs ({} distinct run directories), sha256 {}".format(stage, len(jobs), unique,
                                                                            payload["sha256"]))
    return payload


def read_order(root, stage):
    path = order_path(root, stage)
    if not os.path.isfile(path):
        raise SearchError("order {} not written yet: finalise the previous stage".format(stage))
    payload = read_json(path)
    if payload["sha256"] != sha_obj({k: v for k, v in payload.items() if k != "sha256"}):
        raise SearchError("order {} does not match its seal".format(stage))
    return payload


def initial_orders(root, plan):
    jobs = []
    specs = coarse_specs()
    for profile in plan["profiles"]:
        jobs += search_jobs(profile, "comparator_design", specs)
    write_order(root, "coarse", jobs, {"coarse_plans": len(specs)})
    jobs = []
    for profile in plan["profiles"]:
        jobs += search_jobs(profile, "comparator_design", [actuated_spec(p) for p in ACTUATED_GRID])
    write_order(root, "actuated-design", jobs, {"settings": len(ACTUATED_GRID)})


# ---------------------------------------------------------------------------
# Run states.
# ---------------------------------------------------------------------------

def classify(root, j):
    d = os.path.join(root, j["directory"])
    if not os.path.isdir(d):
        return "not_started", []
    path = os.path.join(d, "evaluation_metrics.json")
    if not os.path.isfile(path):
        return "interrupted", ["no evaluation_metrics.json"]
    try:
        m = read_json(path)
    except (ValueError, OSError, UnicodeDecodeError) as error:
        return "corrupted", ["evaluation_metrics.json unreadable: {}".format(error)]
    if not isinstance(m, dict):
        return "corrupted", ["evaluation_metrics.json is not an object"]
    problems = []
    for name in (FULL_FILES if j["full"] else COMPACT_FILES):
        if not os.path.isfile(os.path.join(d, name)):
            problems.append("missing " + name)
    if m.get("scenario") != j["profile"]:
        problems.append("scenario {!r}".format(m.get("scenario")))
    if not (finite(m.get("traffic_seed")) and int(m["traffic_seed"]) == j["seed"]):
        problems.append("traffic_seed {!r}".format(m.get("traffic_seed")))
    if m.get("comparator_spec_sha256") != j["spec_sha256"]:
        problems.append("comparator spec differs")
    status = m.get("clearance_status")
    if status not in ("CLEARED", "CLEARANCE_FAILURE"):
        problems.append("unknown clearance_status {!r}".format(status))
    if problems:
        return "corrupted", problems
    return ("complete" if status == "CLEARED" else "scientific_failure"), []


def manifest_prefix(root, profile, seed):
    return os.path.join(root, "manifests", "{}_{}".format(profile, seed))


def run(root, stage, shard):
    plan = load_plan(root)
    order = read_order(root, stage)
    import evaluate_comparator as ec
    i, n = (int(x) for x in shard.split("/"))
    seen, corrupted, unfinished = set(), [], []
    log = open(os.path.join(root, "run_log_{}_shard{}of{}.jsonl".format(stage, i, n)), "a")
    for pos, j in enumerate(order["jobs"]):
        if pos % n != i or j["directory"] in seen:
            continue
        seen.add(j["directory"])
        if j["profile"] not in plan["profiles"]:
            raise SearchError("unknown profile")
        if stage != "robustness-eval":
            SD.assert_search_seed(j["profile"], j["seed"])
        elif SD.role_of(j["profile"], j["seed"]) != "robustness_evaluation":
            raise SearchError("robustness-eval only uses the robustness evaluation seeds")
        state, why = classify(root, j)
        if state in FINISHED:
            continue
        if state == "corrupted":
            print("CORRUPTED, preserved, NOT rerun: {} ({})".format(j["directory"], "; ".join(why)))
            corrupted.append(j["directory"])
            continue
        d = os.path.join(root, j["directory"])
        if state == "interrupted":
            if os.path.exists(d + ".incomplete1"):
                print("INTERRUPTED TWICE, preserved, NOT rerun: {}".format(j["directory"]))
                unfinished.append(j["directory"])
                continue
            os.rename(d, d + ".incomplete1")
        t0 = time.time()
        try:
            ec.evaluate(j["spec"], manifest_prefix(root, j["profile"], j["seed"]), d, counters=j["full"],
                        compact=not j["full"])
        except Exception as error:  # noqa: BLE001 - technical interruption; the resume rule applies
            print("INTERRUPTED: {} ({!r})".format(j["directory"], error))
        state, why = classify(root, j)
        log.write(json.dumps({"stage": stage, "dir": j["directory"], "state": state, "problems": why,
                              "wall_s": time.time() - t0}) + "\n")
        log.flush()
        if state == "corrupted":
            corrupted.append(j["directory"])
        elif state not in FINISHED:
            unfinished.append(j["directory"])
    log.close()
    print("stage {} shard {}/{}: {} corrupted, {} not finished".format(stage, i, n, len(corrupted), len(unfinished)))
    return 5 if corrupted else (3 if unfinished else 0)


def stage_states(root, stage):
    order = read_order(root, stage)
    states = {}
    for j in {j["directory"]: j for j in order["jobs"]}.values():
        state, why = classify(root, j)
        states.setdefault(state, []).append((j["directory"], why))
    return order, states


def progress(root, stage=None):
    code = 0
    for s in ([stage] if stage else STAGES):
        if not os.path.isfile(order_path(root, s)):
            print("{:22} order not written yet".format(s))
            code = max(code, 3)
            continue
        _order, states = stage_states(root, s)
        total = sum(len(v) for v in states.values())
        done = sum(len(states.get(x, [])) for x in FINISHED)
        print("{:22} finished {}/{} (scientific failures {}) | corrupted {} | interrupted {} | not started {}".format(
            s, done, total, len(states.get("scientific_failure", [])), len(states.get("corrupted", [])),
            len(states.get("interrupted", [])), len(states.get("not_started", []))))
        if states.get("corrupted"):
            code = 5
        elif done < total:
            code = max(code, 3)
    return code


# ---------------------------------------------------------------------------
# Scores, ranking and selection (frozen rules).
# ---------------------------------------------------------------------------

def load_metrics(root, j):
    return read_json(os.path.join(root, j["directory"], "evaluation_metrics.json"))


def candidate_records(root, jobs, period=None):
    """spec_sha256 -> record over the exact seed set of the jobs (valid only if every run qualifies)."""
    by_spec = {}
    for j in jobs:
        by_spec.setdefault(j["spec_sha256"], []).append(j)
    records = {}
    for digest, js in by_spec.items():
        seeds = sorted(j["seed"] for j in js)
        if len(seeds) != len(set(seeds)):
            raise SearchError("duplicate seed for one candidate")
        values, losses, valid = [], [], True
        for j in js:
            state, why = classify(root, j)
            if state not in FINISHED:
                raise SearchError("{} is {} ({}): finalise needs every run finished".format(j["directory"], state, why))
            m = load_metrics(root, j)
            ok = (m["clearance_status"] == "CLEARED" and m.get("J_primary_valid") and
                  finite(m.get("J_primary_mean_scheduled_waiting_burden_s")) and
                  finite(m.get("mean_completed_time_loss_s")))
            if not ok:
                valid = False
                continue
            if period is None:
                values.append(float(m["J_primary_mean_scheduled_waiting_burden_s"]))
            else:
                values.append(period_j(root, j, period))
            losses.append(float(m["mean_completed_time_loss_s"]))
        records[digest] = {"spec": js[0]["spec"], "seeds": seeds, "valid": valid,
                           "mean_J": sum(values) / len(values) if valid else None,
                           "mean_time_loss": sum(losses) / len(losses) if valid else None}
    return records


def sort_key(record):
    spec = record["spec"]
    if spec["kind"] == "fixed":
        p = spec["plan"]
        return (p["cycle_s"], p["green_H_s"], p["green_V_s"], p["offset_s"])
    if spec["kind"] == "actuated":
        return (ACTUATED_GRID.index(spec["params"]),)
    return tuple(tuple((q["cycle_s"], q["green_H_s"], q["green_V_s"], q["offset_s"])) for _s, q in spec["periods"])


def rank(records, retain):
    valid = [r for r in records.values() if r["valid"]]
    if len(valid) < retain:
        raise SearchError("only {} valid candidates for a shortlist of {}; never padded".format(len(valid), retain))
    return sorted(valid, key=lambda r: (r["mean_J"], sort_key(r)))[:retain]


def select(records):
    valid = [r for r in records.values() if r["valid"]]
    if not valid:
        raise SearchError("every validation candidate failed: nothing may be selected")
    def key(r):
        cycle = r["spec"]["plan"]["cycle_s"] if r["spec"]["kind"] == "fixed" else 0
        return (r["mean_J"], r["mean_time_loss"], cycle, sort_key(r))
    return sorted(valid, key=key)[0]


def realized(spec):
    p = spec["plan"]
    return (p["cycle_s"], p["green_H_s"], p["green_V_s"], p["offset_s"])


_DEPARTS, _PERIOD_J = {}, {}


def scheduled_departs(root, profile, seed):
    key = (root, profile, int(seed))
    if key not in _DEPARTS:
        with open(manifest_prefix(root, profile, seed) + ".csv") as f:
            _DEPARTS[key] = dict((r["vehicle_id"], int(float(r["depart"]))) for r in csv.DictReader(f))
    return _DEPARTS[key]


def period_js(root, j):
    """Period J of one cleared run for every TOD period, from one pass over its tripinfo (cached)."""
    key = (root, j["directory"])
    if key in _PERIOD_J:
        return _PERIOD_J[key]
    departs = scheduled_departs(root, j["profile"], j["seed"])
    totals = [[0.0, 0] for _p in TOD_PERIODS]
    with gzip.open(os.path.join(root, j["directory"], "tripinfo.xml.gz")) as f:
        for _event, el in ET.iterparse(f):
            if el.tag == "tripinfo":
                d = departs.get(el.get("id"))
                if d is None:
                    raise SearchError("{}: trip {} not in the manifest".format(j["directory"], el.get("id")))
                for k, (a, b) in enumerate(TOD_PERIODS):
                    if a <= d < b:
                        totals[k][0] += float(el.get("waitingTime")) + float(el.get("departDelay"))
                        totals[k][1] += 1
                el.clear()
    out = {}
    for k, period in enumerate(TOD_PERIODS):
        expected = sum(1 for d in departs.values() if period[0] <= d < period[1])
        if totals[k][1] != expected:
            raise SearchError("{}: {} trips in period {} but {} scheduled".format(
                j["directory"], totals[k][1], period, expected))
        out[tuple(period)] = totals[k][0] / expected if expected else 0.0
    _PERIOD_J[key] = out
    return out


def period_j(root, j, period):
    return period_js(root, j)[tuple(period)]


def write_selection(root, name, payload):
    path = os.path.join(root, "selections", name + ".json")
    if os.path.exists(path):
        raise SearchError("selection {} already written".format(name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = dict(payload, sha256=sha_obj(payload))
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    print("selected {}: {}".format(name, payload["selected"]["spec"]))


def finalise(root, stage):
    import grids as G
    plan = load_plan(root)
    order, states = stage_states(root, stage)
    missing = [d for s, v in states.items() if s not in FINISHED for d, _w in v]
    if missing:
        raise SearchError("{} runs of {} are not finished, e.g. {}".format(len(missing), stage, missing[:3]))
    profiles = plan["profiles"]
    if stage == "coarse":
        report = {}
        for version, g in VERSIONS:
            jobs, admissible_keys = [], set(G.groups(G.coarse_labels(g)))
            for profile in profiles:
                recs = candidate_records(root, [j for j in order["jobs"] if j["profile"] == profile
                                                and realized(j["spec"]) in admissible_keys])
                winners = rank(recs, G.COARSE_RETAINED)
                done = set(admissible_keys)
                new = [k for k in (realized(fixed_spec(G.realized_key(p))) for p in
                                   G.fine_union([realized(w["spec"]) for w in winners], g)) if k not in done]
                jobs += search_jobs(profile, "comparator_design", [fixed_spec(k) for k in new])
                report[profile + "/" + version] = {"winners": [realized(w["spec"]) for w in winners],
                                                   "new_fine_plans": len(new)}
            write_order(root, "fine-" + version, jobs, {"coarse_order": order["sha256"], "report": report})
        return 0
    if stage.startswith("fine-"):
        version = stage.split("-", 1)[1]
        g = dict(VERSIONS)[version]
        coarse = read_order(root, "coarse")
        jobs, report = [], {}
        for profile in profiles:
            pool = [j for j in coarse["jobs"] + order["jobs"] if j["profile"] == profile and
                    G.admissible(j["spec"]["plan"], g)]
            top = rank(candidate_records(root, pool), G.FINE_RETAINED)
            jobs += search_jobs(profile, "comparator_validation", [t["spec"] for t in top])
            report[profile] = [realized(t["spec"]) for t in top]
        write_order(root, "validation-" + version, jobs, {"fine_order": order["sha256"], "top10": report})
        if TOD_PROFILE in profiles:
            tod_order(root, version, coarse, order)
        return 0
    if stage.startswith("validation-") or stage in ("actuated-validation",) or stage.startswith("tod-validation-"):
        for profile in profiles:
            jobs = [j for j in order["jobs"] if j["profile"] == profile]
            if not jobs:
                continue
            recs = candidate_records(root, jobs)
            chosen = select(recs)
            name = "{}__{}".format(profile, stage.replace("validation-", "").replace("actuated-validation", "actuated")
                                   .replace("tod-", "tod-"))
            write_selection(root, name, {"profile": profile, "stage": stage, "order": order["sha256"],
                                         "selected": chosen, "candidates": sorted(recs.values(), key=sort_key)})
        if all(os.path.isfile(order_path(root, s)) for s in ("validation-g5", "validation-min7")):
            maybe_robustness_order(root, plan)
        return 0
    if stage == "actuated-design":
        jobs = []
        for profile in profiles:
            top = rank(candidate_records(root, [j for j in order["jobs"] if j["profile"] == profile]),
                       ACTUATED_RETAINED)
            jobs += search_jobs(profile, "comparator_validation", [t["spec"] for t in top])
        write_order(root, "actuated-validation", jobs, {"design_order": order["sha256"]})
        return 0
    if stage.startswith("tod-design-"):
        version = stage.split("-", 2)[2]
        top = rank(candidate_records(root, order["jobs"]), TOD_RETAINED)
        write_order(root, "tod-validation-" + version, search_jobs(TOD_PROFILE, "comparator_validation",
                                                                   [t["spec"] for t in top]),
                    {"design_order": order["sha256"]})
        return 0
    raise SearchError("nothing to finalise for stage {}".format(stage))


def tod_order(root, version, coarse, fine):
    import grids as G
    g = dict(VERSIONS)[version]
    pool = [j for j in coarse["jobs"] + fine["jobs"] if j["profile"] == TOD_PROFILE and G.admissible(j["spec"]["plan"], g)]
    best = []
    for period in TOD_PERIODS:
        best.append([realized(r["spec"]) for r in rank(candidate_records(root, pool, period), TOD_PER_PERIOD)])
    combos = [(a, b, c) for a in best[0] for b in best[1] for c in best[2]]
    write_order(root, "tod-design-" + version, search_jobs(TOD_PROFILE, "comparator_design",
                                                           [tod_spec(k) for k in combos]),
                {"per_period_top": best, "fine_order": fine["sha256"]})


def maybe_robustness_order(root, plan):
    needed = ["{}__{}".format(p, v) for p in plan["profiles"] for v in ("g5", "min7", "actuated")]
    needed += ["{}__tod-{}".format(TOD_PROFILE, v) for v, _g in VERSIONS]
    paths = [os.path.join(root, "selections", n + ".json") for n in needed]
    if not all(os.path.isfile(p) for p in paths) or os.path.isfile(order_path(root, "robustness-eval")):
        return
    jobs = []
    for path in paths:
        sel = read_json(path)
        for seed in SD.seeds(sel["profile"], "robustness_evaluation"):
            jobs.append(job(sel["profile"], seed, sel["selected"]["spec"], full=True))
    write_order(root, "robustness-eval", jobs, {"selections": dict((os.path.basename(p), sha256_file(p))
                                                                    for p in paths)})


# ---------------------------------------------------------------------------
# Preparation and measurement.
# ---------------------------------------------------------------------------

def write_manifests(root, roles):
    from adaptive_qmix.config import load_config
    import evaluate_any as ea
    config = load_config(os.path.join(ea.PROTECTED, ea.CONFIG_REL))
    spec = st.load_spec()
    for profile in SD.PROFILES:
        for role in roles:
            for seed in SD.seeds(profile, role):
                prefix = manifest_prefix(root, profile, seed)
                if not os.path.exists(prefix + ".metadata.json"):
                    st.write(spec, profile, seed, st.generate(spec, profile, seed), prefix,
                             config["demand"]["vehicle_type"])


def verify_manifests(root, robustness_root):
    """The regenerated robustness evaluation manifests must equal those of the robustness campaign."""
    bad, checked = [], 0
    for profile in SD.PROFILES:
        for seed in SD.seeds(profile, "robustness_evaluation"):
            for ext in (".csv", ".rou.xml", ".metadata.json"):
                name = "{}_{}{}".format(profile, seed, ext)
                mine, theirs = os.path.join(root, "manifests", name), os.path.join(robustness_root, "manifests", name)
                checked += 1
                if not (os.path.isfile(mine) and os.path.isfile(theirs) and sha256_file(mine) == sha256_file(theirs)):
                    bad.append(name)
    print("robustness evaluation manifests checked {}, different or missing {}".format(checked, len(bad)))
    for name in bad[:10]:
        print("  DIFFERS:", name)
    return 1 if bad else 0


def prepare(root, approved):
    plan = build_plan(root)
    if approved != plan["fingerprint"]:
        print("REFUSED: --approved-plan must be", plan["fingerprint"])
        return 2
    if os.path.exists(os.path.join(root, "plan.json")):
        print("REFUSED: already prepared")
        return 2
    write_manifests(root, ("comparator_design", "comparator_validation", "robustness_evaluation"))
    hashes = dict((n, sha256_file(os.path.join(root, "manifests", n)))
                  for n in sorted(os.listdir(os.path.join(root, "manifests"))))
    with open(os.path.join(root, "manifests_sha256.json"), "w") as f:
        json.dump(hashes, f, indent=1, sort_keys=True)
    with open(os.path.join(root, "plan.json"), "w") as f:
        json.dump(plan, f, indent=1, sort_keys=True)
    initial_orders(root, plan)
    print("prepared", root)
    return 0


def measure(root):
    """Three engineering runs on one design seed (R0, 8011): time and size per run on THIS machine."""
    import evaluate_comparator as ec
    if os.path.exists(os.path.join(root, "measure.json")):
        print("REFUSED: measure.json exists")
        return 2
    write_manifests(root, ("comparator_design",))
    profile, seed = "R0_reference", SD.seeds("R0_reference", "comparator_design")[0]
    specs = [fixed_spec((19, 8, 5, 9)), actuated_spec(ACTUATED_GRID[13]), {"kind": "canonical_mp"}]
    walls, sizes = [], {"compact": [], "full": []}
    for k, spec in enumerate(specs):
        for mode in ("compact", "full"):
            d = os.path.join(root, "measure_runs", "{}_{}".format(k, mode))
            m = ec.evaluate(spec, manifest_prefix(root, profile, seed), d, counters=False, compact=(mode == "compact"))
            walls.append(m["wall_s"])
            sizes[mode].append(sum(os.path.getsize(os.path.join(a, f)) for a, _d, fs in os.walk(d) for f in fs))
    payload = {"machine_note": "measured by comparator_search.py measure on the machine that will run the stages",
               "seconds_per_run": max(walls), "bytes_per_run_compact": max(sizes["compact"]),
               "bytes_per_run_full": int(max(sizes["full"]) * 1.25), "walls_s": walls, "sizes": sizes,
               "note_full": "x1.25 for the per-second service counters absent from these runs"}
    with open(os.path.join(root, "measure.json"), "w") as f:
        json.dump(payload, f, indent=1)
    print(json.dumps(payload))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "measure", "prepare", "run", "progress", "finalise",
                                       "verify-manifests"))
    ap.add_argument("--robustness-root")
    ap.add_argument("--root", required=True)
    ap.add_argument("--approved-plan")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args(argv)
    try:
        if a.action == "plan":
            plan = build_plan(a.root)
            print(json.dumps({k: plan[k] for k in ("runs_per_profile", "tod_runs", "robustness_eval_runs",
                                                   "runs_known_before_coarse", "runs_upper_bound", "estimate_known",
                                                   "estimate_upper_bound", "estimate_robustness_eval", "measure")},
                             indent=1))
            print("plan fingerprint:", plan["fingerprint"])
            return 0
        if a.action == "measure":
            return measure(a.root)
        if a.action == "prepare":
            return prepare(a.root, a.approved_plan)
        if a.action == "verify-manifests":
            return verify_manifests(a.root, a.robustness_root)
        if a.action == "progress":
            return progress(a.root, a.stage)
        if not a.stage:
            raise SearchError("--stage is required")
        if a.action == "run":
            return run(a.root, a.stage, a.shard)
        return finalise(a.root, a.stage)
    except SearchError as error:
        print("STOP:", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
