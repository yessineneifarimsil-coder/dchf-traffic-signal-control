"""State of one robustness cell, shared by the runner and the analysis (stdlib only).

A cell counts as finished only when its result is complete and verified:
  COMPLETE             evaluation_metrics.json readable, identity equal to the planned cell, status CLEARED,
                       and every file its controller type writes is present;
  SCIENTIFIC_FAILURE   the same, with status CLEARANCE_FAILURE: a finished observation, never rerun;
  CORRUPTED            evaluation_metrics.json exists but is unreadable, names another cell, has an unknown status,
                       or files required for the controller type are missing: preserved for diagnosis, never
                       rerun automatically, never counted as finished;
  INTERRUPTED          the directory exists without evaluation_metrics.json: a technical interruption before any
                       result (the runner's resume rule applies: one renamed, preserved retry);
  NOT_STARTED          no directory.

Required files are those the frozen evaluation stack writes for every controller (RunLogger tables,
tripinfo.xml, the per-second service counters of the robustness evaluator) plus, for shielded controllers
(learned and P5), the protection decisions and record. `check-smoke` applies the same rules to the engineering
smoke runs, so the list can be confirmed on real outputs before the robustness campaign.

    python tools/robustness/cell_state.py check-smoke --root D:\\QMIX_Results\\robustness_smoke_2026-10-29
"""
from __future__ import print_function

import argparse
import json
import os
import sys

COMPLETE = "complete"
SCIENTIFIC_FAILURE = "scientific_failure"
CORRUPTED = "corrupted"
INTERRUPTED = "interrupted"
NOT_STARTED = "not_started"
FINISHED = (COMPLETE, SCIENTIFIC_FAILURE)

METRICS = "evaluation_metrics.json"
COMMON_FILES = (METRICS, "run_manifest.json", "tripinfo.xml", "episode_summary.csv", "reward_seconds.csv",
                "signal_phases.csv", "service_counters.csv")
SHIELD_FILES = ("protection_decisions.csv", "protection_record.json")
SHIELDED_KINDS = ("learned", "p5")
STATUS_STATE = {"CLEARED": COMPLETE, "CLEARANCE_FAILURE": SCIENTIFIC_FAILURE}


def required_files(controller):
    kind = controller.split(":", 1)[0]
    return COMMON_FILES + (SHIELD_FILES if kind in SHIELDED_KINDS else ())


def _read_json(path):
    with open(path) as handle:
        return json.load(handle)


def classify(directory, cell, model_sha256=None, stamped=True):
    """(state, problems) for the planned cell whose outputs are in `directory`.

    cell: dict with scenario, seed, controller and, for learned cells, model (tag, e.g. qmix_seed101_t350000).
    model_sha256: the planned checkpoint hash of a learned cell; must equal the checkpoint_sha256 that
      evaluate_any.py stamps into evaluation_metrics.json.
    stamped: check the identity fields stamped by evaluate_any.py (traffic_seed, checkpoint_sha256). False only
      for outputs written before that stamp existed (check-smoke on the 2026-10-29 smoke runs).
    """
    if not os.path.isdir(directory):
        return NOT_STARTED, []
    metrics_path = os.path.join(directory, METRICS)
    if not os.path.isfile(metrics_path):
        return INTERRUPTED, ["no {} (technical interruption before any result)".format(METRICS)]
    try:
        metrics = _read_json(metrics_path)
    except (ValueError, OSError, UnicodeDecodeError) as error:
        return CORRUPTED, ["{} unreadable: {}".format(METRICS, error)]
    if not isinstance(metrics, dict):
        return CORRUPTED, ["{} is not a JSON object".format(METRICS)]
    problems = []
    missing = [name for name in required_files(cell["controller"])
               if not os.path.isfile(os.path.join(directory, name))]
    if missing:
        problems.append("required files missing: {}".format(", ".join(missing)))
    for field, expected in (("scenario", cell["scenario"]), ("controller", cell["controller"])):
        if metrics.get(field) != expected:
            problems.append("{} is {!r}, the plan expects {!r}".format(field, metrics.get(field), expected))
    status = metrics.get("clearance_status")
    if status not in STATUS_STATE:
        problems.append("unknown clearance_status {!r}".format(status))
    if stamped:
        try:
            seed_ok = int(metrics.get("traffic_seed")) == int(cell["seed"])
        except (TypeError, ValueError):
            seed_ok = False
        if not seed_ok:
            problems.append("traffic_seed is {!r}, the plan expects {}".format(metrics.get("traffic_seed"),
                                                                              cell["seed"]))
        if model_sha256 and metrics.get("checkpoint_sha256") != model_sha256:
            problems.append("checkpoint_sha256 is {!r}, the planned model {} has {}".format(
                metrics.get("checkpoint_sha256"), cell.get("model"), model_sha256))
    if problems:
        return CORRUPTED, problems
    return STATUS_STATE[status], []


def model_hashes(plan):
    return dict((m["tag"], m.get("sha256")) for m in plan.get("models", []))


def classify_planned(root, cell, hashes=None):
    return classify(os.path.join(root, cell["directory"]), cell, (hashes or {}).get(cell.get("model")))


def check_smoke(root, stamped=False):
    """Apply classify() to the engineering smoke runs (layout runs/<scenario>/<controller>). The 2026-10-29
    smoke runs predate the identity stamp, so by default only the files, scenario, controller and status are
    checked; --stamped also checks traffic_seed and the presence of checkpoint_sha256 (new smoke runs)."""
    report = []
    runs = os.path.join(root, "runs")
    for scenario in sorted(os.listdir(runs)):
        meta = _read_json(os.path.join(root, "manifests", [n for n in os.listdir(os.path.join(root, "manifests"))
                                                          if n.startswith(scenario) and
                                                          n.endswith(".metadata.json")][0]))
        for name in sorted(os.listdir(os.path.join(runs, scenario))):
            controller = name.replace("__", ":")
            cell = {"scenario": scenario, "seed": meta["seed_value"], "controller": controller}
            directory = os.path.join(runs, scenario, name)
            state, problems = classify(directory, cell, stamped=stamped)
            if stamped and controller.startswith("learned:") and state in FINISHED:
                digest = _read_json(os.path.join(directory, METRICS)).get("checkpoint_sha256")
                if not (isinstance(digest, str) and len(digest) == 64):
                    state, problems = CORRUPTED, ["checkpoint_sha256 not stamped"]
            report.append((scenario, controller, state, problems))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check-smoke",))
    parser.add_argument("--root", required=True)
    parser.add_argument("--stamped", action="store_true", help="smoke runs made with the identity stamp")
    args = parser.parse_args(argv)
    report = check_smoke(args.root, args.stamped)
    for scenario, controller, state, problems in report:
        print("{:32} {:28} {:20} {}".format(scenario, controller, state, "; ".join(problems)))
    bad = [r for r in report if r[2] not in FINISHED]
    print("finished {}/{}".format(len(report) - len(bad), len(report)))
    return 0 if report and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
