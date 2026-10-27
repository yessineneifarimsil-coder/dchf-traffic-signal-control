"""SUMO checks for the min-7 study: real simulations, nothing recorded as a result.

    python -B sumo_checks_min7.py [--root D:\QMIX_Results\fixed_timing_min7_2026-10-27]
        [--work-directory <empty directory>] [--repository-root <checkout of 8c14f32>]

By default it writes to <root>\checks, the only content the root may have
before `fixed_timing_min7.py prepare`; prepare reads <root>\checks\measure.json.

On a check-only traffic (family development, seed 9901: neither a search
seed nor one of the comparison traffics 9301-9305) it runs, through the frozen
run_baseline:
  * the old optimized fixed timing (19, 577, 9) = C 19, gH 8, gV 5, Delta 9;
  * the plan on the 20 s bound (20, 500, 10) = C 20, gH 7, gV 7, Delta 10;
  * a short admissible plan (25, 650, 0) = C 25, gH 12, gV 7, Delta 0;
and, through the frozen evaluate_checkpoint.py, one synthetic QMIX checkpoint
(untrained weights built by the frozen learner; it says nothing about QMIX).

For every fixed-plan run it checks, second by second, the phase SUMO actually
held at each intersection (read back from SUMO, not from the executor):
  1. it is the phase index the frozen schedule prescribes (J1 offset 0, J2
     Delta), and the COMPLETE red/yellow/green string SUMO showed is the one
     the frozen network's tlLogic defines for that index (network SHA-256
     checked);
  2. complete greens last exactly gH and gV, every yellow exactly 3 s, the
     cycle is C, and no complete green is shorter than the plan's minimum;
  3. the runner's own signal_phases.csv log agrees with SUMO;
and, for every run, that J_primary in evaluation_metrics.json equals
mean(waitingTime + departDelay) over the 2800 trips of tripinfo.xml (the
pipeline's metric, never SUMO's printed mean waiting).

It also reports the wall time and the bytes written per run: these are the
LOCAL measurements of the machine it runs on. Exit status 0 only if every
check passes.
"""

from __future__ import print_function

import argparse
import csv
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_timing_min7 as M  # noqa: E402
from adaptive_qmix.baselines import campaign  # noqa: E402
from adaptive_qmix.baselines import plans as P  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402

MINIMUM_FREE_BYTES = 5e9
CHECK_FAMILY = "development"
CHECK_SEED = 9901
PLANS = (("old_optimized_fixed_timing", (19, 577, 9), 5),
         ("min7_cycle_bound", (20, 500, 10), 7),
         ("min7_short_cycle", (25, 650, 0), 7))
PHASE_LETTER = {"H_GREEN": "H", "V_GREEN": "V", "H_TO_V_YELLOW": "Y",
                "V_TO_H_YELLOW": "Y"}


class RecordingTraci(object):
    """The traci module, unchanged, except that before every simulation step
    the phase and signal string SUMO holds at each light are read back."""

    def __init__(self, traci_module, tl_ids):
        self._traci = traci_module
        self._tl_ids = tuple(tl_ids)
        self.seconds = []

    def __getattr__(self, name):
        return getattr(self._traci, name)

    def simulationStep(self, *args, **kwargs):
        now = float(self._traci.simulation.getTime())
        row = {"time": now}
        for tl_id in self._tl_ids:
            row[tl_id] = (int(self._traci.trafficlight.getPhase(tl_id)),
                          self._traci.trafficlight.getRedYellowGreenState(tl_id),
                          self._traci.trafficlight.getProgram(tl_id))
        self.seconds.append(row)
        return self._traci.simulationStep(*args, **kwargs)


def spans(sequence):
    """[(letter, length)] of consecutive equal letters."""
    result = []
    for letter in sequence:
        if result and result[-1][0] == letter:
            result[-1][1] += 1
        else:
            result.append([letter, 1])
    return [tuple(item) for item in result]


def load_programs(repository_root, config):
    """{light: {programID: [full signal string of each phase index]}} from the
    tlLogic of the frozen network file, whose SHA-256 is checked first."""
    import xml.etree.ElementTree as ET
    path = os.path.join(repository_root, config["network"]["path"])
    if M.sha256_file(path) != config["network"]["sha256"]:
        raise M.Min7Error("{} is not the frozen network.".format(path))
    programs = {}
    for logic in ET.parse(path).getroot().findall("tlLogic"):
        programs.setdefault(logic.get("id"), {})[logic.get("programID")] = [
            phase.get("state") for phase in logic.findall("phase")]
    return programs


def expected_phase(plan, phase_map, time_s, offset):
    """The phase index the frozen executor sets for this second (as
    executors._phase_index: a yellow is named by the green it ends)."""
    actual, logical, _served = P.state_at(plan, P.local_second(plan, time_s, offset))
    if actual == "H":
        return phase_map["H_GREEN"], actual
    if actual == "V":
        return phase_map["V_GREEN"], actual
    return phase_map["H_TO_V_YELLOW" if logical == "H" else "V_TO_H_YELLOW"], actual


def check_schedule(plan, config, seconds, min_green, programs):
    """Per light and per second: the phase index AND the complete
    red/yellow/green string SUMO held, against the frozen schedule and the
    frozen tlLogic; then realised durations, cycle and offset."""
    problems, summary = [], {}
    phase_map = config["network"]["phase_map"]
    index_to_name = dict((v, k) for k, v in phase_map.items())
    offsets = {"J1": 0, "J2": int(plan["offset_s"]) % int(plan["cycle_s"])}
    for tl_id, offset in sorted(offsets.items()):
        letters, index_mismatches, string_mismatches = [], 0, 0
        first_string_mismatch = None
        tl_programs = programs.get(tl_id) or {}
        for row in seconds:
            held = row[tl_id]
            phase, signals = held[0], held[1]
            program = held[2] if len(held) > 2 else None
            if program is None and len(tl_programs) == 1:
                program = list(tl_programs)[0]
            states = tl_programs.get(program)
            if states is None:
                problems.append("{} t={} runs program {!r}, not one of the frozen tlLogic "
                                "programs {}".format(tl_id, row["time"], program,
                                                     sorted(tl_programs)))
                continue
            name = index_to_name.get(phase)
            if name is None or phase >= len(states):
                problems.append("{} t={} holds unknown phase {}".format(tl_id, row["time"], phase))
                continue
            letters.append(PHASE_LETTER[name])
            expected_index, _actual = expected_phase(plan, phase_map, row["time"], offset)
            if phase != expected_index:
                index_mismatches += 1
            if signals != states[expected_index]:
                string_mismatches += 1
                if first_string_mismatch is None:
                    first_string_mismatch = (row["time"], signals, states[expected_index])
        if index_mismatches:
            problems.append("{}: {} seconds hold another phase index than the schedule".format(
                tl_id, index_mismatches))
        if string_mismatches:
            problems.append("{}: {} seconds show another signal string than the frozen "
                            "tlLogic prescribes; first at t={}: {} instead of {}".format(
                                tl_id, string_mismatches, *first_string_mismatch))
        complete = spans(letters)[1:-1]          # the first and last are censored
        lengths = {}
        for letter, length in complete:
            lengths.setdefault(letter, set()).add(length)
        expected = {"H": {plan["green_H_s"]}, "V": {plan["green_V_s"]}, "Y": {P.YELLOW_S}}
        if lengths != expected:
            problems.append("{}: realised spans {} != {}".format(tl_id, lengths, expected))
        short = [length for letter, length in complete if letter != "Y" and length < min_green]
        if short:
            problems.append("{}: complete greens shorter than {} s: {}".format(
                tl_id, min_green, short))
        cycle_lengths = set()
        starts = [i for i in range(1, len(letters)) if letters[i] == "H" and letters[i - 1] != "H"]
        for a, b in zip(starts, starts[1:]):
            cycle_lengths.add(b - a)
        if cycle_lengths != {plan["cycle_s"]}:
            problems.append("{}: realised cycles {}".format(tl_id, cycle_lengths))
        summary[tl_id] = {"seconds": len(letters), "complete_spans": len(complete),
                          "realised_lengths": dict((k, sorted(v)) for k, v in lengths.items()),
                          "realised_cycles": sorted(cycle_lengths),
                          "schedule_mismatches": index_mismatches,
                          "signal_string_mismatches": string_mismatches,
                          "first_H_start_s": starts[0] if starts else None}
    if all(summary.get(t, {}).get("first_H_start_s") is not None for t in offsets):
        lag = (summary["J2"]["first_H_start_s"] - summary["J1"]["first_H_start_s"]) % plan["cycle_s"]
        summary["J2_minus_J1_s"] = lag
        if lag != offsets["J2"]:
            problems.append("J2 lags J1 by {} s, not {}".format(lag, offsets["J2"]))
    return problems, summary


def check_runner_log(directory, seconds):
    """The runner's signal_phases.csv against what SUMO held."""
    path = os.path.join(directory, "signal_phases.csv")
    if not os.path.isfile(path):
        return ["signal_phases.csv absent"], None
    held = {}
    for row in seconds:
        for tl_id in ("J1", "J2"):
            held[(int(row["time"]), tl_id)] = row[tl_id][0]
    with open(path) as handle:
        logged = [r for r in csv.DictReader(handle)]
    best = None
    for shift in (0, -1, 1):
        agree = total = 0
        for r in logged:
            key = (int(float(r["time"])) + shift, r["intersection"])
            if key in held and r["actual_phase"] not in ("", None):
                total += 1
                letter = {"H": "H", "V": "V"}.get(r["actual_phase"], "Y")
                phase_letter = None
                for name, index in CONFIG["network"]["phase_map"].items():
                    if index == held[key]:
                        phase_letter = PHASE_LETTER[name]
                agree += int(letter == phase_letter)
        if total and (best is None or agree > best[1]):
            best = (shift, agree, total)
    if best is None:
        return ["signal_phases.csv has no comparable rows"], None
    shift, agree, total = best
    report = {"time_shift_s": shift, "agreeing_seconds": agree, "compared_seconds": total}
    return ([] if agree == total else ["runner log disagrees with SUMO on {} of {} "
                                       "seconds".format(total - agree, total)]), report


def check_metric(directory):
    with open(os.path.join(directory, campaign.METRICS_FILENAME)) as handle:
        metrics = json.load(handle)
    recomputed = M.recompute_j(directory)
    j = metrics.get(M.search.PRIMARY_FIELD)
    report = {"status": metrics.get("clearance_status"), "J_primary_valid":
              metrics.get("J_primary_valid"), "J_pipeline": j, "J_from_tripinfo": recomputed}
    problems = []
    if metrics.get("J_primary_valid"):
        if recomputed is None or abs(float(j) - recomputed) > M.J_RECOMPUTE_TOLERANCE:
            problems.append("J {} != recomputed {}".format(j, recomputed))
    elif recomputed is not None:
        problems.append("all 2800 trips arrived but J_primary_valid is false")
    return problems, report


def directory_bytes(directory):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _s, files in os.walk(directory)
               for f in files)


def synthetic_checkpoint(path, adaptive_config, seed=101):
    from adaptive_qmix.learner import MultiAgentLearner
    learner = MultiAgentLearner("qmix", seed, adaptive_config["training"], "cpu")
    learner.save_checkpoint(path, 1, adaptive_config["_config_sha256"],
                            {"local_init_J1": {"training_seed": seed}})
    return path


CONFIG = None


def main(argv=None):
    global CONFIG
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=M.DEFAULTS["root"])
    parser.add_argument("--work-directory")
    parser.add_argument("--repository-root", default=M.REPOSITORY_ROOT)
    parser.add_argument("--quick", action="store_true",
                        help="only the 20 s bound plan and the metric check")
    parser.add_argument("--skip-qmix", action="store_true")
    parser.add_argument("--a002-driver")
    args = parser.parse_args(argv)
    work = os.path.abspath(args.work_directory or os.path.join(args.root, M.CHECKS_DIRECTORY))
    if os.path.exists(work) and os.listdir(work):
        print("REFUS : {} n'est pas vide.".format(work))
        return 2
    free = M.disk_free(work)
    print("Espace libre sous {} : {:.1f} Go".format(work, free / 1e9))
    if free < MINIMUM_FREE_BYTES:
        print("REFUS : moins de {:.0f} Go libres.".format(MINIMUM_FREE_BYTES / 1e9))
        return 2
    repository = M.REPOSITORY_ROOT
    head = M.git(repository, "rev-parse", "HEAD")
    if head != M.FROZEN_COMMIT:
        print("REFUS : depot a {} et non {}".format(head, M.FROZEN_COMMIT))
        return 2
    import traci
    from adaptive_qmix.baselines.runner import run_baseline
    a002 = M.A.Layout(os.path.join(work, "_o"), os.path.join(work, "_a"),
                      os.path.join(work, "_m"), withdrawn_root=os.path.join(work, "_w"))
    CONFIG = load_config(a002.config_path)
    adaptive = load_config(a002.adaptive_config_path)
    manifests = os.path.join(work, "manifests")
    manifest = campaign.prepare_seed_manifests(manifests, CONFIG, CHECK_FAMILY,
                                               seeds=(CHECK_SEED,))[CHECK_SEED]
    programs = load_programs(repository, CONFIG)
    results, failures = {"runtime": M.A.current_runtime(), "frozen_commit": head,
                         "driver_sha256": M.DRIVER_SHA256,
                         "a002_driver_sha256": M.A002_DRIVER_SHA256,
                         "sumo_checks_sha256": M.sha256_file(os.path.abspath(__file__)),
                         "network_sha256": CONFIG["network"]["sha256"],
                         "tl_programs": programs,
                         "complete": not (args.quick or args.skip_qmix),
                         "traffic": {"family": CHECK_FAMILY, "seed": CHECK_SEED}, "runs": {}}, []
    plans = PLANS[1:2] if args.quick else PLANS
    for name, key, min_green in plans:
        plan = P.make_plan(*key)
        directory = os.path.join(work, name)
        os.makedirs(directory)
        recorder = RecordingTraci(traci, CONFIG["network"]["traffic_lights"])
        start = time.time()
        try:
            run_baseline(recorder, CONFIG, repository, M.CONTROLLER,
                         manifest["prefix"] + ".csv", manifest["prefix"] + ".rou.xml",
                         CHECK_FAMILY, CHECK_SEED, manifest["sumo_seed"], directory, plan=plan,
                         manifest_index=0, manifest_prefix=manifest["prefix"])
        except Exception as error:  # noqa: BLE001 - a failed check, reported as such
            results["runs"][name] = {"plan_key": list(key), "wall_seconds": time.time() - start,
                                     "bytes": directory_bytes(directory),
                                     "problems": ["run_baseline raised {!r}".format(error)]}
            failures.append("{}: run_baseline raised {!r}".format(name, error))
            continue
        elapsed = time.time() - start
        schedule_problems, schedule = check_schedule(plan, CONFIG, recorder.seconds, min_green,
                                                     programs)
        log_problems, log = check_runner_log(directory, recorder.seconds)
        metric_problems, metric = check_metric(directory)
        problems = schedule_problems + log_problems + metric_problems
        results["runs"][name] = {"plan_key": list(key), "realized": list(M.A.realized_key(plan)),
                                 "wall_seconds": elapsed, "bytes": directory_bytes(directory),
                                 "schedule": schedule, "runner_log": log, "metric": metric,
                                 "problems": problems}
        failures.extend("{}: {}".format(name, p) for p in problems)
        print("{:<28} {} | {:.1f} s | {:.1f} Mo | J {} (tripinfo {}) | spans {} | "
              "decalage J2-J1 {} | {}".format(
                  name, M.describe(plan), elapsed, directory_bytes(directory) / 1e6,
                  metric["J_pipeline"], metric["J_from_tripinfo"],
                  dict((t, schedule[t]["realised_lengths"]) for t in ("J1", "J2")),
                  schedule.get("J2_minus_J1_s"), "OK" if not problems else problems))
    if not args.skip_qmix and not args.quick:
        checkpoint = synthetic_checkpoint(os.path.join(work, "synthetic_qmix.pth"), adaptive)
        directory = os.path.join(work, "synthetic_qmix")
        start = time.time()
        code = subprocess.call(
            [sys.executable, "-B", os.path.join(repository, "scripts", "adaptive_qmix",
                                                "evaluate_checkpoint.py"),
             "--checkpoint", checkpoint, "--manifest-csv", manifest["prefix"] + ".csv",
             "--route-xml", manifest["prefix"] + ".rou.xml", "--traffic-seed",
             str(CHECK_SEED), "--sumo-seed", str(manifest["sumo_seed"]),
             "--output-directory", directory, "--run-kind", "development_evaluation",
             "--lane-state-logging", "full", "--traci-access-mode", "subscription"],
            stdout=open(directory + ".log", "w"), stderr=subprocess.STDOUT, cwd=repository)
        elapsed = time.time() - start
        problems = ["frozen evaluator exited with {}".format(code)] if code else []
        metric = None
        if not code:
            metric_problems, metric = check_metric(directory)
            problems += metric_problems
        results["runs"]["synthetic_qmix"] = {"wall_seconds": elapsed,
                                             "bytes": directory_bytes(directory)
                                             if os.path.isdir(directory) else 0,
                                             "metric": metric, "problems": problems}
        failures.extend("synthetic_qmix: {}".format(p) for p in problems)
        print("{:<28} evaluateur fige | {:.1f} s | J {} | {}".format(
            "synthetic_qmix", elapsed, metric and metric["J_pipeline"],
            "OK" if not problems else problems))
    fixed = [r for n, r in results["runs"].items() if n != "synthetic_qmix"]
    results["measurement"] = {
        "seconds_per_run": max([r["wall_seconds"] for r in fixed] or [None]),
        "bytes_per_run": max([r["bytes"] for r in fixed] or [None]),
        "seconds_per_qmix_evaluation": results["runs"].get("synthetic_qmix", {}).get(
            "wall_seconds"),
        "measured_on": "this machine", "date": time.strftime("%Y-%m-%d %H:%M:%S")}
    results["verdict"] = "OK" if not failures else "ECHEC"
    with open(os.path.join(work, M.LOCAL_CHECK_REPORT), "w") as handle:
        json.dump(results, handle, indent=2, sort_keys=True, default=str)
    # The measurement is usable only with a complete and passing report;
    # prepare checks both, and their agreement, again.
    if results["verdict"] == "OK" and results["complete"]:
        with open(os.path.join(work, "measure.json"), "w") as handle:
            json.dump(results["measurement"], handle, indent=2, sort_keys=True)
        print("Mesure locale : {}".format(json.dumps(results["measurement"], sort_keys=True)))
    else:
        print("Aucune mesure ecrite : controles {}.".format(
            "en echec" if failures else "partiels"))
    print("VERIFICATIONS SUMO : {}{}".format(results["verdict"],
                                             "" if results["complete"] else " (partielles)"))
    for failure in failures:
        print("  " + failure)
    return 0 if not failures and results["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
