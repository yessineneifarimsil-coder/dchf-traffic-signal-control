"""Resumable, shardable execution of the already-frozen baseline search.

The search protocol is not decided here; it was frozen in baselines.search.
This module only executes it, and its whole job is to make a long campaign
interruptible without becoming untrustworthy.

Resume is the dangerous part. A campaign that trusts a leftover directory will
happily skip a run that crashed halfway and report the stale numbers, so a run
counts as complete only when its completion marker exists, records the hashes
of the manifest and route file it used, and those hashes still match what is
on disk and what the marker's own payload hashes to. Anything else -- absent,
partial, tampered, produced against a different manifest -- is rerun.

One manifest per benchmark seed, shared by every candidate. That is what makes
the comparison paired: candidate A and candidate B meet the identical traffic
realisation, verified rather than assumed. Candidate identity is in every
output path, so two candidates can never write to the same place.

Deliberately absent: adaptive early stopping and candidate pruning. Dropping
candidates that look poor after a few seeds would change the preregistered
1980 x 5 design evaluation into a different, data-dependent design, and the
saving is not worth quietly altering what was preregistered.
"""

from __future__ import absolute_import

import csv
import hashlib
import json
import os
import time

from .integrity import (
    BENCHMARK_MANIFEST_INDEX,
    assert_traffic_selection_allowed,
    sha256_file,
    verify_manifest_for_run,
)
from .plans import candidate_key, coarse_timing_candidates, \
    fine_timing_candidates, fixed_offset_candidates
from .search import (
    COARSE_RETAINED,
    DESIGN_FAMILY,
    FINAL_FAMILY,
    FINAL_SEEDS,
    FINE_RETAINED,
    OFFSET_RETAINED,
    VALIDATION_FAMILY,
    required_seeds,
)
from ..protocol import stages as protocol_stages


CAMPAIGN_VERSION = "baseline-campaign-1.0"

MARKER_FILENAME = "campaign_run.complete.json"
METRICS_FILENAME = "evaluation_metrics.json"
LEDGER_CSV = "campaign_ledger.csv"
LEDGER_JSON = "campaign_ledger.json"

STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED_COMPLETE = "SKIPPED_ALREADY_COMPLETE"

LEDGER_FIELDS = (
    "campaign_version", "controller", "candidate_key", "cycle_s",
    "split_thousandths", "offset_s", "traffic_family", "traffic_seed",
    "manifest_index", "sumo_seed", "manifest_csv_sha256", "route_xml_sha256",
    "run_directory", "status", "clearance_status", "J_primary",
    "elapsed_wall_s", "exit_status", "started_at", "finished_at",
)

# No pruning, no early stopping. Recorded so a reader can see it was a choice.
PRUNING_POLICY = (
    "Every candidate is evaluated on every preregistered seed. There is no "
    "adaptive early stopping and no candidate pruning: either would replace "
    "the preregistered design with a data-dependent one."
)


class CampaignError(RuntimeError):
    pass


def _sha256_payload(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def candidate_directory_name(controller, plan):
    """Candidate identity, in the path itself."""
    cycle, split, offset = candidate_key(plan)
    return "{}__C{:03d}_f{:03d}_D{:03d}".format(
        controller, int(cycle), int(split), int(offset)
    )


def run_directory_for(root, controller, plan, family, seed):
    return os.path.join(
        os.path.abspath(root),
        candidate_directory_name(controller, plan),
        "{}_seed{:04d}".format(family, int(seed)),
    )


def ordered_candidates(plans):
    """Deterministic candidate ordering, independent of how they arrived."""
    return sorted(plans, key=candidate_key)


def shard(items, shard_index, shard_count):
    """Split deterministically so shards never overlap and never lose a run."""
    shard_index, shard_count = int(shard_index), int(shard_count)
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise CampaignError(
            "Invalid shard {} of {}.".format(shard_index, shard_count)
        )
    return [
        item for position, item in enumerate(items)
        if position % shard_count == shard_index
    ]


def manifest_prefix_for(manifest_root, family, seed):
    """One manifest per benchmark seed, reused by every candidate."""
    return os.path.join(
        os.path.abspath(manifest_root),
        "{}_seed{:04d}".format(family, int(seed)),
    )


def ensure_seed_manifest(manifest_root, config, family, seed,
                         manifest_index=BENCHMARK_MANIFEST_INDEX):
    """Generate the shared manifest for one seed, or verify the existing one."""
    from ..traffic import (
        derive_sumo_seed, generate_manifest_records, write_manifest,
    )

    assert_traffic_selection_allowed(family, seed, manifest_index)
    prefix = manifest_prefix_for(manifest_root, family, seed)
    directory = os.path.dirname(prefix)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    sumo_seed = derive_sumo_seed(family, seed, manifest_index)
    if not os.path.isfile(prefix + ".metadata.json"):
        write_manifest(
            generate_manifest_records(config, family, seed, manifest_index),
            config, prefix, family, seed, manifest_index,
        )
    metadata, verified = verify_manifest_for_run(
        prefix, family, seed, manifest_index, sumo_seed=sumo_seed
    )
    return {
        "prefix": prefix,
        "metadata": metadata,
        "manifest_csv_sha256": verified["csv_sha256"],
        "route_xml_sha256": verified["route_xml_sha256"],
        "sumo_seed": int(verified["sumo_seed"]),
    }


def write_completion_marker(run_directory, payload):
    """Atomic: written to a temporary name, then renamed into place.

    A marker that exists is therefore always complete; a crash mid-write
    leaves the temporary file, which resume ignores.
    """
    marker = dict(payload)
    marker["marker_sha256"] = _sha256_payload(payload)
    path = os.path.join(run_directory, MARKER_FILENAME)
    temporary = path + ".partial"
    with open(temporary, "w") as handle:
        json.dump(marker, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def read_completion_marker(run_directory):
    path = os.path.join(run_directory, MARKER_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except ValueError:
        return None


def completion_problems(run_directory, controller, plan, family, seed,
                        manifest_csv_sha256, route_xml_sha256, sumo_seed):
    """Why this run may NOT be skipped on resume. Empty means it may."""
    marker = read_completion_marker(run_directory)
    if marker is None:
        return ["no completion marker"]
    problems = []
    recorded = marker.get("marker_sha256")
    payload = dict((k, v) for k, v in marker.items() if k != "marker_sha256")
    if recorded != _sha256_payload(payload):
        problems.append(
            "the completion marker has been modified since it was written"
        )
    expected = {
        "controller": controller,
        "candidate_key": list(candidate_key(plan)),
        "traffic_family": family,
        "traffic_seed": int(seed),
        "manifest_csv_sha256": manifest_csv_sha256,
        "route_xml_sha256": route_xml_sha256,
        "sumo_seed": int(sumo_seed),
    }
    for field, value in sorted(expected.items()):
        found = marker.get(field)
        if field == "candidate_key" and found is not None:
            found = list(found)
        if found != value:
            problems.append(
                "marker {} is {!r}, this run needs {!r}".format(
                    field, found, value
                )
            )
    metrics_path = os.path.join(run_directory, METRICS_FILENAME)
    if not os.path.isfile(metrics_path):
        problems.append("evaluation_metrics.json is absent")
        return problems
    if marker.get("metrics_sha256") != sha256_file(metrics_path):
        problems.append(
            "evaluation_metrics.json has changed since the marker was written"
        )
    try:
        with open(metrics_path, "r") as handle:
            metrics = json.load(handle)
    except ValueError:
        problems.append("evaluation_metrics.json is not readable JSON")
        return problems
    if metrics.get("clearance_status") != "CLEARED":
        problems.append(
            "recorded run did not clear ({!r})".format(
                metrics.get("clearance_status")
            )
        )
    if not metrics.get("J_primary_valid", False):
        problems.append("recorded run has no valid J_primary")
    return problems


def is_complete(*args, **kwargs):
    return not completion_problems(*args, **kwargs)


def plan_campaign(controller, plans, family, seeds=None, shard_index=0,
                  shard_count=1):
    """The deterministic work list, before anything is executed."""
    if family == FINAL_FAMILY:
        raise CampaignError(
            "The baseline campaign never touches {}.".format(FINAL_FAMILY)
        )
    seeds = tuple(required_seeds(family)) if seeds is None else tuple(seeds)
    trespassing = sorted(set(seeds) & set(FINAL_SEEDS))
    if trespassing:
        raise CampaignError(
            "Seeds {} are held out for the final test.".format(trespassing)
        )
    work = [
        {"plan": dict(plan), "key": candidate_key(plan), "family": family,
         "seed": int(seed), "controller": controller}
        for plan in ordered_candidates(plans)
        for seed in seeds
    ]
    return shard(work, shard_index, shard_count)


def execute_campaign(runner, controller, plans, family, config,
                     output_root, manifest_root, repository_root,
                     seeds=None, shard_index=0, shard_count=1,
                     traci_module=None, ledger_directory=None):
    """Execute the work list, skipping only hash-verified completed runs.

    'runner' is called for each run and must return the metrics dict; it is a
    parameter so the orchestration can be tested without SUMO.
    """
    work = plan_campaign(
        controller, plans, family, seeds, shard_index, shard_count
    )
    seeds_needed = sorted(set(item["seed"] for item in work))
    manifests = dict(
        (seed, ensure_seed_manifest(manifest_root, config, family, seed))
        for seed in seeds_needed
    )
    ledger = []
    for item in work:
        manifest = manifests[item["seed"]]
        directory = run_directory_for(
            output_root, controller, item["plan"], family, item["seed"]
        )
        problems = completion_problems(
            directory, controller, item["plan"], family, item["seed"],
            manifest["manifest_csv_sha256"], manifest["route_xml_sha256"],
            manifest["sumo_seed"],
        )
        started = time.time()
        if not problems:
            entry = _ledger_entry(
                item, manifest, directory, STATUS_SKIPPED_COMPLETE,
                started, started, metrics=_load_metrics(directory),
                exit_status=0,
            )
            ledger.append(entry)
            continue
        if not os.path.isdir(directory):
            os.makedirs(directory)
        try:
            metrics = runner(
                traci_module, config, repository_root, controller,
                manifest["prefix"] + ".csv",
                manifest["prefix"] + ".rou.xml",
                family, item["seed"], manifest["sumo_seed"], directory,
                plan=item["plan"], manifest_index=BENCHMARK_MANIFEST_INDEX,
                manifest_prefix=manifest["prefix"],
            )
            exit_status = 0
            failure = None
        except Exception as error:  # noqa: BLE001 - recorded, not swallowed
            metrics, exit_status, failure = None, 1, repr(error)
        finished = time.time()

        if metrics is not None and metrics.get("clearance_status") == "CLEARED":
            metrics_path = os.path.join(directory, METRICS_FILENAME)
            write_completion_marker(directory, {
                "campaign_version": CAMPAIGN_VERSION,
                "controller": controller,
                "candidate_key": list(item["key"]),
                "plan": dict(item["plan"]),
                "traffic_family": family,
                "traffic_seed": int(item["seed"]),
                "manifest_index": BENCHMARK_MANIFEST_INDEX,
                "manifest_csv_sha256": manifest["manifest_csv_sha256"],
                "route_xml_sha256": manifest["route_xml_sha256"],
                "sumo_seed": int(manifest["sumo_seed"]),
                "metrics_sha256": sha256_file(metrics_path),
                "elapsed_wall_s": finished - started,
            })
            status = STATUS_COMPLETED
        else:
            status = STATUS_FAILED
        entry = _ledger_entry(
            item, manifest, directory, status, started, finished,
            metrics=metrics, exit_status=exit_status,
        )
        if failure is not None:
            entry["failure"] = failure
        ledger.append(entry)

    write_ledger(ledger_directory or output_root, ledger)
    return ledger


def _load_metrics(directory):
    path = os.path.join(directory, METRICS_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except ValueError:
        return None


def _ledger_entry(item, manifest, directory, status, started, finished,
                  metrics=None, exit_status=0):
    metrics = metrics or {}
    cycle, split, offset = item["key"]
    return {
        "campaign_version": CAMPAIGN_VERSION,
        "controller": item["controller"],
        "candidate_key": list(item["key"]),
        "cycle_s": cycle,
        "split_thousandths": split,
        "offset_s": offset,
        "traffic_family": item["family"],
        "traffic_seed": item["seed"],
        "manifest_index": BENCHMARK_MANIFEST_INDEX,
        "sumo_seed": manifest["sumo_seed"],
        "manifest_csv_sha256": manifest["manifest_csv_sha256"],
        "route_xml_sha256": manifest["route_xml_sha256"],
        "run_directory": directory,
        "status": status,
        "clearance_status": metrics.get("clearance_status"),
        "J_primary": metrics.get(
            "J_primary_mean_scheduled_waiting_burden_s"
        ),
        "elapsed_wall_s": round(finished - started, 6),
        "exit_status": exit_status,
        "started_at": started,
        "finished_at": finished,
    }


def write_ledger(directory, entries):
    if not os.path.isdir(directory):
        os.makedirs(directory)
    csv_path = os.path.join(directory, LEDGER_CSV)
    with open(csv_path, "w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(LEDGER_FIELDS), extrasaction="ignore"
        )
        writer.writeheader()
        for entry in entries:
            row = dict(entry)
            row["candidate_key"] = "{}_{}_{}".format(*entry["candidate_key"])
            writer.writerow(row)
    json_path = os.path.join(directory, LEDGER_JSON)
    with open(json_path, "w") as handle:
        json.dump({
            "campaign_version": CAMPAIGN_VERSION,
            "pruning_policy": PRUNING_POLICY,
            "entries": entries,
        }, handle, indent=2, sort_keys=True)
    return {"csv": csv_path, "json": json_path}


# ---------------------------------------------------------------------------
# Campaign stage graph.
#
# The search protocol is frozen; this is the order its stages must execute in,
# and what each one is allowed to consume. A validation stage never takes a
# shortlist somebody typed: it reads the hash-sealed artefact the preceding
# stage produced, so the ten candidates it evaluates are provably the ten that
# ranked best on design rather than ten chosen afterwards.
#
# The fine timing stage is a DESIGN-family stage. It refines the neighbourhood
# of the coarse winners and is ranked on benchmark_design, exactly like the
# coarse stage; only the last stage of each track uses benchmark_validation.
# ---------------------------------------------------------------------------

OFFSET_DESIGN = "offset_design"
OFFSET_VALIDATION = "offset_validation"
TIMING_COARSE_DESIGN = "timing_coarse_design"
TIMING_FINE_DESIGN = "timing_fine_design"
TIMING_VALIDATION = "timing_validation"

CAMPAIGN_STAGES = {
    OFFSET_DESIGN: {
        "controller": "optimized_fixed_offset",
        "family": DESIGN_FAMILY,
        "requires": None,
        "retain": OFFSET_RETAINED,
        "protocol_stage": protocol_stages.BASELINE_DESIGN,
        "candidates": "all 90 fixed offsets",
    },
    OFFSET_VALIDATION: {
        "controller": "optimized_fixed_offset",
        "family": VALIDATION_FAMILY,
        "requires": OFFSET_DESIGN,
        "retain": None,
        "protocol_stage": protocol_stages.BASELINE_VALIDATION,
        "candidates": "the design shortlist",
    },
    TIMING_COARSE_DESIGN: {
        "controller": "optimized_fixed_timing",
        "family": DESIGN_FAMILY,
        "requires": None,
        "retain": COARSE_RETAINED,
        "protocol_stage": protocol_stages.BASELINE_DESIGN,
        "candidates": "the 1980 coarse candidates",
    },
    TIMING_FINE_DESIGN: {
        "controller": "optimized_fixed_timing",
        "family": DESIGN_FAMILY,
        "requires": TIMING_COARSE_DESIGN,
        "retain": FINE_RETAINED,
        "protocol_stage": protocol_stages.BASELINE_DESIGN,
        "candidates": "the fine neighbourhood of the five coarse winners",
    },
    TIMING_VALIDATION: {
        "controller": "optimized_fixed_timing",
        "family": VALIDATION_FAMILY,
        "requires": TIMING_FINE_DESIGN,
        "retain": None,
        "protocol_stage": protocol_stages.BASELINE_VALIDATION,
        "candidates": "the fine shortlist",
    },
}

SHORTLIST_SUFFIX = ".shortlist.json"


class StageSequenceError(RuntimeError):
    pass


def shortlist_path(directory, stage):
    if stage not in CAMPAIGN_STAGES:
        raise StageSequenceError("Unknown campaign stage {!r}.".format(stage))
    return os.path.join(directory, stage + SHORTLIST_SUFFIX)


def write_shortlist_artefact(directory, stage, plans, provenance):
    """Hash-seal the candidates a stage retained, for the next stage to read."""
    spec = CAMPAIGN_STAGES[stage]
    if spec["retain"] is not None and len(plans) != spec["retain"]:
        raise StageSequenceError(
            "Stage {!r} must retain exactly {} candidates; got {}. The "
            "shortlist size is part of the frozen protocol.".format(
                stage, spec["retain"], len(plans)
            )
        )
    payload = {
        "campaign_version": CAMPAIGN_VERSION,
        "stage": stage,
        "controller": spec["controller"],
        "family": spec["family"],
        "plans": [dict(plan) for plan in plans],
        "candidate_keys": [list(candidate_key(plan)) for plan in plans],
        "provenance": dict(provenance),
    }
    artefact = dict(payload)
    artefact["payload_sha256"] = _sha256_payload(payload)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    path = shortlist_path(directory, stage)
    temporary = path + ".partial"
    with open(temporary, "w") as handle:
        json.dump(artefact, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def read_shortlist_artefact(directory, stage):
    """Read the preceding stage's shortlist, refusing anything unverified."""
    path = shortlist_path(directory, stage)
    if not os.path.isfile(path):
        raise StageSequenceError(
            "Stage {!r} produced no shortlist artefact at {}. A later stage "
            "may not proceed on a shortlist that was never "
            "generated.".format(stage, path)
        )
    with open(path, "r") as handle:
        artefact = json.load(handle)
    recorded = artefact.get("payload_sha256")
    payload = dict(
        (key, value) for key, value in artefact.items()
        if key != "payload_sha256"
    )
    if recorded != _sha256_payload(payload):
        raise StageSequenceError(
            "The shortlist artefact for stage {!r} has been modified since it "
            "was written. A validation stage runs the candidates design "
            "selected, not candidates edited afterwards.".format(stage)
        )
    if artefact.get("stage") != stage:
        raise StageSequenceError(
            "Artefact at {} declares stage {!r}.".format(
                path, artefact.get("stage")
            )
        )
    spec = CAMPAIGN_STAGES[stage]
    if artefact.get("controller") != spec["controller"]:
        raise StageSequenceError(
            "Shortlist for {!r} was produced by controller {!r}, not "
            "{!r}.".format(stage, artefact.get("controller"),
                           spec["controller"])
        )
    if spec["retain"] is not None and len(artefact["plans"]) != spec["retain"]:
        raise StageSequenceError(
            "Shortlist for {!r} holds {} candidates; the protocol retains "
            "{}.".format(stage, len(artefact["plans"]), spec["retain"])
        )
    return artefact


def candidates_for_stage(stage, shortlist_directory):
    """What a stage runs, derived structurally rather than supplied by hand."""
    spec = CAMPAIGN_STAGES[stage]
    required = spec["requires"]
    if required is None:
        if stage == OFFSET_DESIGN:
            return fixed_offset_candidates(), None
        return coarse_timing_candidates(), None
    artefact = read_shortlist_artefact(shortlist_directory, required)
    if stage == TIMING_FINE_DESIGN:
        # The fine neighbourhood is regenerated from the verified winners, so
        # it cannot be widened by editing a file.
        return fine_timing_candidates(artefact["plans"]), artefact
    return [dict(plan) for plan in artefact["plans"]], artefact


def assert_campaign_stage_allowed(stage, shortlist_directory,
                                  state_directory=None):
    """Refuse a stage until its predecessor's shortlist exists and verifies."""
    if stage not in CAMPAIGN_STAGES:
        raise StageSequenceError("Unknown campaign stage {!r}.".format(stage))
    spec = CAMPAIGN_STAGES[stage]
    required = spec["requires"]
    if required is not None:
        # Raises with the reason if absent, tampered or the wrong shape.
        read_shortlist_artefact(shortlist_directory, required)
    if state_directory is not None:
        protocol_stages.assert_stage_allowed(
            state_directory, spec["protocol_stage"]
        )
    return True
