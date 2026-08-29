"""Getter-vs-subscription A/B equivalence harness.

Runs the same episode twice under identical network, route manifest, SUMO
seed, traffic schedule, learner initialisation, RNG streams, exploration draws
and starting state, changing only the TraCI transport, and compares every
quantity that could carry a difference.

Discrete quantities must match exactly. Floating-point quantities are compared
through repr(), which is exact for IEEE doubles in Python 3 and distinguishes
0.0 from -0.0, so this is a bit-identity check and not a tolerance check.

Scope. This harness compares exactly ONE episode, run to its natural end
(clearance or the 7200 s timeout). It does NOT call learner.update(), sample
replay, or train, and --max-transitions is an upper bound only: the loop stops
at the first episode termination, which on the qualification scenario is about
753 transitions, so raising it does not extend the comparison past one
episode and does not reach the 5000-transition replay warm-up. That is
sufficient for accepting a TRANSPORT change: the learner consumes only the
transition tuple, and every field of that tuple is compared here bit-for-bit.
It is not, and must not be described as, a training-loop equivalence gate.

Transport diagnostics such as transport_healed_subscriptions are reported
separately and excluded from the scientific comparison. A synthetic teleport
may legitimately require subscription healing in one transport and not the
other; what must be identical is the science, not the repair counter.

Usage on the target stack:

    python scripts\\adaptive_qmix\\ab_equivalence.py ^
        --output-directory results\\raw\\adaptive_ab\\qmix_seed101

Exit code 0 means the two transports produced an identical run.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.environment import AdaptiveTrafficEnvironment  # noqa: E402
from adaptive_qmix.logging import LANE_LOG_FULL  # noqa: E402
from adaptive_qmix.traci_access import GETTER, SUBSCRIPTION  # noqa: E402
from adaptive_qmix.traffic import (  # noqa: E402
    generate_manifest_records,
    write_manifest,
)


# Recorded for engineering visibility, deliberately not part of the
# scientific comparison.
TRANSPORT_DIAGNOSTIC_FIELDS = ("transport_healed_subscriptions",)

CAPTURED_TABLES = (
    "lane_states",
    "reward_seconds",
    "signal_phases",
    "vehicle_crossings",
)


def scientific_only(summary):
    """Drop transport diagnostics before comparing episode summaries."""
    return dict(
        (key, value) for key, value in summary.items()
        if key not in TRANSPORT_DIAGNOSTIC_FIELDS
    )


def canon(value):
    """Exact, comparable text for any logged scalar."""
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, bool):
        return "bool:" + str(value)
    if isinstance(value, (list, tuple)):
        return [canon(item) for item in value]
    if isinstance(value, dict):
        return dict((str(k), canon(v)) for k, v in sorted(value.items()))
    return str(value)


class CaptureLogger(object):
    """Records every logged row instead of writing files."""

    def __init__(self):
        self.rows = dict((name, []) for name in CAPTURED_TABLES)

    def write(self, table, row):
        if table in self.rows:
            self.rows[table].append(canon(row))

    def write_json_fields(self, table, row, field_names):
        self.write(table, row)

    def flush(self):
        pass

    def write_clearance_failure(self, residual_state):
        pass


def observation_internals(builder):
    """Arrival-window counts and lane membership, per agent and movement."""
    counts = {}
    members = {}
    for key in sorted(builder.arrival_counts, key=lambda k: (k[0], k[1])):
        name = "{}_{}".format(key[0], key[1])
        counts[name] = list(builder.arrival_counts[key])
        members[name] = sorted(builder.previous_members[key])
    return counts, members


def parse_tripinfo(path):
    if not os.path.isfile(path):
        return {}
    rows = {}
    for element in ET.parse(path).getroot().findall("tripinfo"):
        attributes = dict(element.attrib)
        rows[attributes["id"]] = dict(
            (k, attributes[k])
            for k in sorted(attributes)
            if k in ("depart", "departDelay", "arrival", "duration",
                     "waitingTime", "waitingCount", "timeLoss", "routeLength")
        )
    return rows


def run_mode(mode, config, manifest_prefix, sumo_seed, output_directory,
             method, training_seed, max_transitions):
    import traci

    from adaptive_qmix.learner import MultiAgentLearner, epsilon_at_transition
    from adaptive_qmix.rng import IndependentEpsilonStreams, configure_python_and_torch

    configure_python_and_torch(training_seed, deterministic=True)
    learner = MultiAgentLearner(method, training_seed, config["training"], "cpu")
    epsilon_streams = IndependentEpsilonStreams(training_seed, action_dim=2)

    logger = CaptureLogger()
    tripinfo_path = os.path.join(output_directory, "tripinfo_{}.xml".format(mode))
    environment = AdaptiveTrafficEnvironment(
        traci,
        config,
        REPOSITORY_ROOT,
        manifest_prefix + ".csv",
        manifest_prefix + ".rou.xml",
        tripinfo_path,
        sumo_seed,
        logger=logger,
        traci_access_mode=mode,
        lane_state_logging=LANE_LOG_FULL,
    )
    trace = []
    status = None
    try:
        observations, state, _info = environment.reset(0)
        index = 0
        while index < max_transitions:
            q_values = learner.local_q_values(observations)
            greedy = [int(values.argmax()) for values in q_values]
            epsilon = epsilon_at_transition(
                index,
                config["training"]["epsilon_start"],
                config["training"]["epsilon_end"],
                config["training"]["epsilon_decay_transitions"],
            )
            actions, exploration = epsilon_streams.select(greedy, epsilon)
            next_observations, next_state, reward, terminated, info = (
                environment.step(actions)
            )
            counts, members = observation_internals(environment.observations)
            trace.append({
                "index": index,
                "epsilon": canon(epsilon),
                "greedy": canon(greedy),
                "actions": canon(actions),
                "exploration": canon(exploration),
                "q_values": canon([list(row) for row in q_values]),
                "observations": canon([list(row) for row in observations]),
                "state": canon(list(state)),
                "next_observations": canon([list(row) for row in next_observations]),
                "next_state": canon(list(next_state)),
                "reward": canon(reward),
                "reward_components": canon(dict(
                    (k, v) for k, v in info["reward_components"].items()
                    if k != "seconds"
                )),
                "raw_observations": canon(info["raw_observations"]),
                "terminated": canon(terminated),
                "budget_truncated": canon(info["budget_truncated"]),
                "timeout_truncated": canon(info["timeout_truncated"]),
                "elapsed_seconds": canon(info["elapsed_seconds"]),
                "start_time": canon(info["start_time"]),
                "end_time": canon(info["end_time"]),
                "ledger": canon(info["ledger"]),
                "current_phase": canon(info["execution"]["current_phase"]),
                "green_elapsed": canon(info["execution"]["green_elapsed"]),
                "legacy_integral": canon(environment.legacy_waiting_integral),
                "legacy_samples": canon(environment.legacy_waiting_samples),
                "red_elapsed": canon(environment.red_elapsed),
                "arrival_counts": canon(counts),
                "lane_members": canon(members),
            })
            observations, state = next_observations, next_state
            index += 1
            if terminated:
                status = "CLEARED"
                break
            if info["timeout_truncated"]:
                status = "CLEARANCE_FAILURE"
                break
        if status is None:
            status = "BUDGET_TRUNCATED"
        summary = canon(environment.episode_summary(status))
        residual = canon(environment.complete_residual_state())
    finally:
        environment.close()

    return {
        "mode": mode,
        "status": status,
        "transitions": len(trace),
        "trace": trace,
        "logged": logger.rows,
        "summary": summary,
        "residual": residual,
        "tripinfo": parse_tripinfo(tripinfo_path),
    }


def compare_sequences(name, left, right, failures):
    if len(left) != len(right):
        failures.append(
            "{}: length differs, getter={} subscription={}".format(
                name, len(left), right and len(right)
            )
        )
    for position in range(min(len(left), len(right))):
        if left[position] != right[position]:
            failures.append(
                "{}: first difference at element {}\n  getter       = {}\n"
                "  subscription = {}".format(
                    name, position,
                    json.dumps(left[position], sort_keys=True)[:900],
                    json.dumps(right[position], sort_keys=True)[:900],
                )
            )
            return


def compare(getter, subscription):
    failures = []
    for field in ("status", "transitions"):
        if getter[field] != subscription[field]:
            failures.append("{}: getter={} subscription={}".format(
                field, getter[field], subscription[field]
            ))
    compare_sequences("transition trace", getter["trace"], subscription["trace"],
                      failures)
    for table in CAPTURED_TABLES:
        compare_sequences(
            "logged table '{}'".format(table),
            getter["logged"][table], subscription["logged"][table], failures,
        )
    left_summary = scientific_only(getter["summary"])
    right_summary = scientific_only(subscription["summary"])
    if left_summary != right_summary:
        failures.append("episode summary differs:\n  getter       = {}\n"
                        "  subscription = {}".format(
                            json.dumps(left_summary, sort_keys=True),
                            json.dumps(right_summary, sort_keys=True)))
    if getter["residual"] != subscription["residual"]:
        failures.append("residual clearance state differs")
    left, right = getter["tripinfo"], subscription["tripinfo"]
    if set(left) != set(right):
        failures.append("tripinfo vehicle sets differ: only-getter={} "
                        "only-subscription={}".format(
                            sorted(set(left) - set(right))[:5],
                            sorted(set(right) - set(left))[:5]))
    else:
        for vehicle_id in sorted(left):
            if left[vehicle_id] != right[vehicle_id]:
                failures.append("tripinfo differs for {}:\n  getter       = {}\n"
                                "  subscription = {}".format(
                                    vehicle_id, left[vehicle_id], right[vehicle_id]))
                break
    return failures


def digest(result):
    """SHA-256 of the scientific content only, excluding transport diagnostics."""
    payload = json.dumps(
        {"trace": result["trace"], "logged": result["logged"],
         "summary": scientific_only(result["summary"]),
         "tripinfo": result["tripinfo"]},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(
        REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"))
    parser.add_argument("--method", default="qmix", choices=("qmix", "vdn", "idqn"))
    parser.add_argument("--training-seed", type=int, default=101)
    parser.add_argument("--family", default="development")
    parser.add_argument("--manifest-index", type=int, default=0)
    parser.add_argument(
        "--max-transitions", type=int, default=800,
        help="upper bound only; the harness stops at the first episode "
             "termination, about 753 transitions at this demand. Raising it "
             "does not extend the comparison beyond one episode and does not "
             "reach the replay warm-up.")
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    output_directory = os.path.abspath(args.output_directory)
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)

    records = generate_manifest_records(
        config, args.family, args.training_seed, args.manifest_index)
    prefix = os.path.join(output_directory, "ab_manifest")
    metadata = write_manifest(
        records, config, prefix, args.family, args.training_seed,
        args.manifest_index)
    sumo_seed = int(metadata["sumo_seed"])

    print("A/B equivalence: getter versus subscription")
    print("  method            : {}".format(args.method))
    print("  training seed     : {}".format(args.training_seed))
    print("  manifest          : {} index {}".format(args.family, args.manifest_index))
    print("  SUMO seed         : {}".format(sumo_seed))
    print("  route sha256      : {}".format(metadata["route_xml_sha256"]))
    print("  max transitions   : {} (upper bound; stops at episode end)".format(
        args.max_transitions))
    print("  scope             : one full episode, no learner updates, no replay")
    print("")

    results = {}
    for mode in (GETTER, SUBSCRIPTION):
        print("running {} mode ...".format(mode))
        sys.stdout.flush()
        results[mode] = run_mode(
            mode, config, prefix, sumo_seed, output_directory,
            args.method, args.training_seed, args.max_transitions)
        print("  status={} transitions={} trace-digest={}".format(
            results[mode]["status"], results[mode]["transitions"],
            digest(results[mode])[:16]))
        sys.stdout.flush()

    failures = compare(results[GETTER], results[SUBSCRIPTION])
    same_digest = digest(results[GETTER]) == digest(results[SUBSCRIPTION])

    report = {
        "method": args.method,
        "training_seed": args.training_seed,
        "sumo_seed": sumo_seed,
        "route_xml_sha256": metadata["route_xml_sha256"],
        "transitions_compared": results[GETTER]["transitions"],
        "seconds_compared": len(results[GETTER]["logged"]["reward_seconds"]),
        "lane_rows_compared": len(results[GETTER]["logged"]["lane_states"]),
        "vehicles_compared": len(results[GETTER]["tripinfo"]),
        "getter_digest": digest(results[GETTER]),
        "subscription_digest": digest(results[SUBSCRIPTION]),
        "identical": bool(same_digest and not failures),
        "failures": failures,
        "scope": (
            "one episode run to natural termination; no learner.update(), no "
            "replay sampling, no training. Not a training-loop gate."
        ),
        "transport_diagnostics": dict(
            (mode, dict(
                (field, results[mode]["summary"].get(field))
                for field in TRANSPORT_DIAGNOSTIC_FIELDS
            ))
            for mode in (GETTER, SUBSCRIPTION)
        ),
    }
    path = os.path.join(output_directory, "ab_equivalence_report.json")
    with open(path, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)

    print("")
    print("transitions compared : {}".format(report["transitions_compared"]))
    print("simulated seconds    : {}".format(report["seconds_compared"]))
    print("lane rows compared   : {}".format(report["lane_rows_compared"]))
    print("vehicles compared    : {}".format(report["vehicles_compared"]))
    print("transport diagnostics: getter={} subscription={} (excluded from "
          "the comparison)".format(
              report["transport_diagnostics"][GETTER],
              report["transport_diagnostics"][SUBSCRIPTION]))
    print("report               : {}".format(path))
    print("")
    if report["identical"]:
        print("RESULT: IDENTICAL -- the two transports produced the same run.")
        return 0
    print("RESULT: DIFFERENT -- {} discrepancy group(s):".format(len(failures)))
    for failure in failures[:10]:
        print("  - {}".format(failure))
    return 1


if __name__ == "__main__":
    sys.exit(main())
