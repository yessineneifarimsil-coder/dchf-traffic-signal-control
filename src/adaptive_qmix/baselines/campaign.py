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
import math
import os
import time

from .integrity import (
    BENCHMARK_MANIFEST_INDEX,
    assert_traffic_selection_allowed,
    sha256_file,
    verify_manifest_for_run,
)
from ..logging import RAW_LOG_SCHEMA_VERSION
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
SHARD_LEDGER_CSV = "campaign_ledger.shard{index:03d}of{count:03d}.csv"
SHARD_LEDGER_JSON = "campaign_ledger.shard{index:03d}of{count:03d}.json"
AGGREGATE_LEDGER_CSV = "campaign_ledger.aggregate.csv"
AGGREGATE_LEDGER_JSON = "campaign_ledger.aggregate.json"

# The ranking tie metric. A run is only usable if this is finite too, because
# a candidate whose tie-break value is missing cannot be ordered.
TIE_FIELD = "mean_completed_time_loss_s"
PRIMARY_FIELD = "J_primary_mean_scheduled_waiting_burden_s"

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


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def environment_identity(config, repository_root):
    """What a completed run was produced UNDER, not merely what it ran on.

    A marker that records only the manifest hashes would let a run made under
    a different baseline configuration or a different network be reused after
    either changed. Binding the config and network identity means such a run
    is rerun instead of silently carried forward.
    """
    network_path = os.path.join(
        os.path.abspath(repository_root), config["network"]["path"]
    )
    return {
        "baseline_config_sha256": config.get("_config_sha256"),
        "network_sha256": sha256_file(network_path),
        "network_git_blob": config["network"].get("git_blob"),
        "campaign_version": CAMPAIGN_VERSION,
        "raw_log_schema_version": RAW_LOG_SCHEMA_VERSION,
    }


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
                         manifest_index=BENCHMARK_MANIFEST_INDEX,
                         allow_generate=True):
    """Verify the shared manifest for one seed, generating it only if allowed.

    Workers run with allow_generate=False. Two concurrent workers that both
    found a manifest missing would otherwise write the same files at the same
    time, and the loser's partial write is what the winner would then hash.
    Generation happens once, before any worker starts.
    """
    from ..traffic import (
        derive_sumo_seed, generate_manifest_records, write_manifest,
    )

    assert_traffic_selection_allowed(family, seed, manifest_index)
    prefix = manifest_prefix_for(manifest_root, family, seed)
    sumo_seed = derive_sumo_seed(family, seed, manifest_index)
    if not os.path.isfile(prefix + ".metadata.json"):
        if not allow_generate:
            raise CampaignError(
                "No manifest for {} seed {} at {}. Workers consume manifests "
                "read-only; call prepare_seed_manifests once before starting "
                "them, so two workers cannot write the same files at "
                "once.".format(family, seed, prefix)
            )
        directory = os.path.dirname(prefix)
        if not os.path.isdir(directory):
            os.makedirs(directory)
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


def prepare_seed_manifests(manifest_root, config, family, seeds=None,
                           manifest_index=BENCHMARK_MANIFEST_INDEX):
    """Generate and verify every seed manifest once, before workers start."""
    seeds = tuple(required_seeds(family)) if seeds is None else tuple(seeds)
    return dict(
        (int(seed), ensure_seed_manifest(
            manifest_root, config, family, seed, manifest_index,
            allow_generate=True,
        ))
        for seed in sorted(seeds)
    )


def load_seed_manifests(manifest_root, config, family, seeds=None,
                        manifest_index=BENCHMARK_MANIFEST_INDEX):
    """Read-only view of the pre-generated manifests, for a worker."""
    seeds = tuple(required_seeds(family)) if seeds is None else tuple(seeds)
    return dict(
        (int(seed), ensure_seed_manifest(
            manifest_root, config, family, seed, manifest_index,
            allow_generate=False,
        ))
        for seed in sorted(seeds)
    )


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
                        manifest_csv_sha256, route_xml_sha256, sumo_seed,
                        environment=None):
    """Why this run may NOT be skipped on resume. Empty means it may.

    Clearing is necessary but not sufficient. A run is reusable only if it
    also produced a finite J_primary and a finite ranking tie metric, matches
    the identity it is being reused for, and was produced under the same
    baseline configuration and network. Anything else is rerun.
    """
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
    if not _finite(metrics.get(PRIMARY_FIELD)):
        problems.append(
            "recorded J_primary is not finite; clearing alone does not make a "
            "run usable evidence"
        )
    if not _finite(metrics.get(TIE_FIELD)):
        problems.append(
            "recorded {} is not finite, so the candidate could not be "
            "ordered".format(TIE_FIELD)
        )
    for field, expected in (
        ("controller", controller),
        ("traffic_family", family),
    ):
        if metrics.get(field) != expected:
            problems.append(
                "recorded metrics {} is {!r}, this run needs {!r}".format(
                    field, metrics.get(field), expected
                )
            )
    if metrics.get("traffic_seed") is not None and (
        int(metrics["traffic_seed"]) != int(seed)
    ):
        problems.append(
            "recorded metrics traffic_seed is {}, this run needs {}".format(
                metrics["traffic_seed"], seed
            )
        )
    recorded_plan = metrics.get("phase_parameters")
    if recorded_plan:
        try:
            recorded_key = candidate_key(recorded_plan)
        except (KeyError, TypeError):
            recorded_key = None
        if recorded_key != candidate_key(plan):
            problems.append(
                "recorded metrics describe candidate {}, not {}".format(
                    recorded_key, candidate_key(plan)
                )
            )
    if environment is not None:
        recorded_environment = marker.get("environment") or {}
        differences = [
            (field, recorded_environment.get(field), value)
            for field, value in sorted(environment.items())
            if recorded_environment.get(field) != value
        ]
        if differences:
            problems.append(
                "the run was produced under a different environment "
                "(field, recorded, current): {}".format(differences)
            )
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
                     traci_module=None, ledger_directory=None,
                     allow_manifest_generation=None):
    """Execute the work list, skipping only fully verified completed runs.

    'runner' is called for each run and must return the metrics dict; it is a
    parameter so the orchestration can be tested without SUMO.

    With more than one shard, manifests must already exist: workers consume
    them read-only, and each shard writes its own ledger so two workers never
    rewrite the same file.
    """
    work = plan_campaign(
        controller, plans, family, seeds, shard_index, shard_count
    )
    seeds_needed = sorted(set(item["seed"] for item in work))
    if allow_manifest_generation is None:
        allow_manifest_generation = int(shard_count) == 1
    manifests = dict(
        (seed, ensure_seed_manifest(
            manifest_root, config, family, seed,
            allow_generate=allow_manifest_generation,
        ))
        for seed in seeds_needed
    )
    environment = environment_identity(config, repository_root)
    ledger = []
    for item in work:
        manifest = manifests[item["seed"]]
        directory = run_directory_for(
            output_root, controller, item["plan"], family, item["seed"]
        )
        problems = completion_problems(
            directory, controller, item["plan"], family, item["seed"],
            manifest["manifest_csv_sha256"], manifest["route_xml_sha256"],
            manifest["sumo_seed"], environment,
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

        usable = (
            metrics is not None
            and metrics.get("clearance_status") == "CLEARED"
            and bool(metrics.get("J_primary_valid", False))
            and _finite(metrics.get(PRIMARY_FIELD))
            and _finite(metrics.get(TIE_FIELD))
        )
        if usable:
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
                "environment": dict(environment),
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

    write_ledger(
        ledger_directory or output_root, ledger,
        shard_index=shard_index, shard_count=shard_count,
    )
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


def ledger_names(shard_index=0, shard_count=1):
    """Per-shard filenames, so concurrent workers never rewrite one file."""
    if int(shard_count) <= 1:
        return LEDGER_CSV, LEDGER_JSON
    return (
        SHARD_LEDGER_CSV.format(
            index=int(shard_index), count=int(shard_count)
        ),
        SHARD_LEDGER_JSON.format(
            index=int(shard_index), count=int(shard_count)
        ),
    )


def aggregate_ledgers(directory):
    """Merge every per-shard ledger deterministically, refusing overlaps.

    Two shards claiming the same run means the split was wrong, which would
    silently halve or double the evidence, so it is an error rather than a
    de-duplication.
    """
    entries, sources = [], []
    for name in sorted(os.listdir(directory)):
        if not name.startswith("campaign_ledger.shard") or not (
            name.endswith(".json")
        ):
            continue
        path = os.path.join(directory, name)
        with open(path, "r") as handle:
            payload = json.load(handle)
        entries.extend(payload.get("entries", []))
        sources.append(name)
    seen = {}
    for entry in entries:
        key = (
            entry["controller"], tuple(entry["candidate_key"]),
            entry["traffic_family"], entry["traffic_seed"],
        )
        if key in seen:
            raise CampaignError(
                "Two shards both recorded {}; the shard split must "
                "partition the work exactly once.".format(key)
            )
        seen[key] = entry
    ordered = [seen[key] for key in sorted(seen)]
    write_ledger(directory, ordered, aggregate=True)
    return {"entries": ordered, "shard_ledgers": sources}


def write_ledger(directory, entries, shard_index=0, shard_count=1,
                 aggregate=False):
    if not os.path.isdir(directory):
        os.makedirs(directory)
    if aggregate:
        csv_name, json_name = AGGREGATE_LEDGER_CSV, AGGREGATE_LEDGER_JSON
    else:
        csv_name, json_name = ledger_names(shard_index, shard_count)
    csv_path = os.path.join(directory, csv_name)
    with open(csv_path, "w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(LEDGER_FIELDS), extrasaction="ignore"
        )
        writer.writeheader()
        for entry in entries:
            row = dict(entry)
            row["candidate_key"] = "{}_{}_{}".format(*entry["candidate_key"])
            writer.writerow(row)
    json_path = os.path.join(directory, json_name)
    with open(json_path, "w") as handle:
        json.dump({
            "campaign_version": CAMPAIGN_VERSION,
            "pruning_policy": PRUNING_POLICY,
            "shard_index": int(shard_index),
            "shard_count": int(shard_count),
            "aggregate": bool(aggregate),
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


def _write_shortlist_artefact(directory, stage, plans, provenance,
                             derivation):
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
        # Evidence that these are the candidates the runs actually chose. A
        # shortlist without it is a list of plans somebody liked.
        "derivation": dict(derivation),
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
    _verify_derivation(stage, artefact)
    return artefact


def _verify_derivation(stage, artefact):
    """A shortlist must be derivable from the scores it claims to rest on.

    Being the right length is not evidence. The artefact has to carry the
    complete scored candidate set the stage evaluated, and the retained plans
    have to be exactly the top N of that set under the frozen ranking. A
    hand-written list of ten plausible plans fails here, which is the point.
    """
    spec = CAMPAIGN_STAGES[stage]
    derivation = artefact.get("derivation")
    if not derivation:
        raise StageSequenceError(
            "The shortlist for {!r} carries no derivation evidence. Only the "
            "stage finaliser may produce an official shortlist, from the "
            "complete verified result set.".format(stage)
        )
    for field in ("expected_candidate_count", "verified_run_count",
                  "expected_run_count", "scores", "ranking"):
        if field not in derivation:
            raise StageSequenceError(
                "The shortlist for {!r} is missing derivation.{}.".format(
                    stage, field
                )
            )
    if derivation["verified_run_count"] != derivation["expected_run_count"]:
        raise StageSequenceError(
            "The shortlist for {!r} rests on {} verified runs but the stage "
            "expects {}.".format(
                stage, derivation["verified_run_count"],
                derivation["expected_run_count"],
            )
        )
    scores = derivation["scores"]
    if len(scores) != derivation["expected_candidate_count"]:
        raise StageSequenceError(
            "The shortlist for {!r} scores {} candidates; the stage evaluated "
            "{}.".format(stage, len(scores),
                         derivation["expected_candidate_count"])
        )
    if spec["retain"] is None:
        return True
    valid = [item for item in scores if item.get("valid")]
    ordered = sorted(
        valid,
        key=lambda item: (
            float(item["mean_J_primary_s"]), tuple(item["key"])
        ),
    )
    expected = [list(item["key"]) for item in ordered[: spec["retain"]]]
    retained = [list(key) for key in artefact["candidate_keys"]]
    if retained != expected:
        raise StageSequenceError(
            "The shortlist for {!r} is not the top {} of its own scores. "
            "Retained {}, but the recorded scores rank {}.".format(
                stage, spec["retain"], retained[:3], expected[:3]
            )
        )
    return True


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


# ---------------------------------------------------------------------------
# Stage finalisation.
#
# A stage is finished when its complete expected result set exists, every run
# verifies, and the shortlist has been DERIVED from those runs by the frozen
# ranking in search.py. There is deliberately no path where a caller supplies
# plans and declares them selected: that is what a finaliser is for, and an
# ordinary "write these ten" entry point would make every downstream guarantee
# rest on the caller's honesty.
# ---------------------------------------------------------------------------

SELECTED_PLAN_SUFFIX = ".selected.json"


def _expected_candidates(stage, shortlist_directory):
    plans, source = candidates_for_stage(stage, shortlist_directory)
    return ordered_candidates(plans), source


def collect_stage_runs(stage, plans, output_root, manifest_root, config,
                       repository_root):
    """Every run of the stage's complete candidate x seed set, verified.

    Returns (runs by candidate, problems). A missing or unverifiable run is a
    problem, not an absence to work around: ranking on a partial set would
    rank candidates on different amounts of evidence.

    The seed set is not a parameter. It is the preregistered set for the
    stage's family, so a caller cannot finalise on a convenient subset.
    """
    spec = CAMPAIGN_STAGES[stage]
    family = spec["family"]
    seeds = tuple(required_seeds(family))
    manifests = load_seed_manifests(
        manifest_root, config, family, seeds
    )
    environment = environment_identity(config, repository_root)
    runs_by_candidate, problems = [], []
    for plan in ordered_candidates(plans):
        key = candidate_key(plan)
        runs = []
        for seed in sorted(seeds):
            manifest = manifests[int(seed)]
            directory = run_directory_for(
                output_root, spec["controller"], plan, family, seed
            )
            faults = completion_problems(
                directory, spec["controller"], plan, family, seed,
                manifest["manifest_csv_sha256"],
                manifest["route_xml_sha256"], manifest["sumo_seed"],
                environment,
            )
            if faults:
                problems.append({
                    "candidate_key": list(key), "traffic_seed": int(seed),
                    "run_directory": directory, "problems": faults,
                })
                continue
            metrics = _load_metrics(directory)
            if metrics is None:
                problems.append({
                    "candidate_key": list(key), "traffic_seed": int(seed),
                    "run_directory": directory,
                    "problems": ["metrics could not be read"],
                })
                continue
            runs.append(metrics)
        runs_by_candidate.append((plan, runs))
    return runs_by_candidate, problems


def finalise_stage(stage, output_root, manifest_root, shortlist_directory,
                   config, repository_root, state_directory=None):
    """Verify the complete result set, rank it, and derive the shortlist.

    This is the only producer of an official shortlist or selected-plan
    artefact. It refuses an incomplete stage outright rather than ranking what
    happens to be present.
    """
    from . import search

    spec = CAMPAIGN_STAGES[stage]
    assert_campaign_stage_allowed(stage, shortlist_directory, state_directory)
    plans, source = _expected_candidates(stage, shortlist_directory)
    family = spec["family"]
    seeds = tuple(required_seeds(family))
    expected_runs = len(plans) * len(seeds)

    runs_by_candidate, problems = collect_stage_runs(
        stage, plans, output_root, manifest_root, config, repository_root
    )
    verified_runs = sum(len(runs) for _plan, runs in runs_by_candidate)
    if problems or verified_runs != expected_runs:
        raise StageSequenceError(
            "Stage {!r} is not complete: {} of {} expected runs verify ({} "
            "candidates x {} seeds). First problems: {}. A stage is finalised "
            "from its whole result set or not at all.".format(
                stage, verified_runs, expected_runs, len(plans), len(seeds),
                problems[:3],
            )
        )

    controller = spec["controller"]
    records = [
        search.summarise_candidate(plan, runs, family, controller)
        for plan, runs in runs_by_candidate
    ]
    search.assert_stage_traffic_pairing(
        [(candidate_key(plan), runs) for plan, runs in runs_by_candidate],
        family,
    )
    scores = [
        {
            "key": list(record["key"]),
            "valid": record["valid"],
            "mean_J_primary_s": record["mean_J_primary_s"],
            "mean_time_loss_s": record["mean_time_loss_s"],
            "failed_seeds": record["failed_seeds"],
        }
        for record in records
    ]
    derivation = {
        "expected_candidate_count": len(plans),
        "expected_run_count": expected_runs,
        "verified_run_count": verified_runs,
        "seeds": [int(seed) for seed in sorted(seeds)],
        "family": family,
        "controller": controller,
        "environment": environment_identity(config, repository_root),
        "ranking": "search.rank_by_design on mean design J_primary",
        "scores": scores,
        "derived_from_stage": None if source is None else source["stage"],
    }

    if spec["retain"] is not None:
        retained = search.rank_by_design(records, spec["retain"])
        path = _write_shortlist_artefact(
            shortlist_directory, stage,
            [record["plan"] for record in retained],
            {
                "ranked_on": family,
                "seeds": derivation["seeds"],
                "protocol": "design ranks; validation selects",
            },
            derivation,
        )
        return {
            "stage": stage, "artefact": path, "kind": "shortlist",
            "retained_keys": [record["key"] for record in retained],
            "candidate_count": len(plans), "verified_run_count": verified_runs,
        }

    selector = (
        search.select_offset_plan if controller == "optimized_fixed_offset"
        else search.select_timing_plan
    )
    selected = selector(records)
    path = _write_selected_plan_artefact(
        shortlist_directory, stage, controller, selected, derivation, config,
        repository_root, source,
    )
    return {
        "stage": stage, "artefact": path, "kind": "selected_plan",
        "selected_key": selected["key"], "candidate_count": len(plans),
        "verified_run_count": verified_runs,
    }


def selected_plan_path(directory, stage):
    return os.path.join(directory, stage + SELECTED_PLAN_SUFFIX)


def _write_selected_plan_artefact(directory, stage, controller, selected,
                                  derivation, config, repository_root,
                                  source):
    from . import search

    environment = environment_identity(config, repository_root)
    payload = {
        "campaign_version": CAMPAIGN_VERSION,
        "stage": stage,
        "controller": controller,
        "plan": dict(selected["plan"]),
        "selected_key": list(selected["key"]),
        "validation_mean_J_primary_s": selected["mean_J_primary_s"],
        "validation_mean_time_loss_s": selected["mean_time_loss_s"],
        "provenance": {
            "design_family": search.DESIGN_FAMILY,
            "design_seeds": list(search.DESIGN_SEEDS),
            "validation_family": search.VALIDATION_FAMILY,
            "validation_seeds": list(search.VALIDATION_SEEDS),
            "selected_key": list(selected["key"]),
            "protocol": (
                "ranked on {} then selected on {} with the frozen "
                "tie-break".format(
                    search.DESIGN_FAMILY, search.VALIDATION_FAMILY
                )
            ),
            "shortlist_stage": None if source is None else source["stage"],
        },
        "baseline_config_sha256": environment["baseline_config_sha256"],
        "network_sha256": environment["network_sha256"],
        "network_git_blob": environment["network_git_blob"],
        "derivation": derivation,
    }
    artefact = dict(payload)
    artefact["payload_sha256"] = _sha256_payload(payload)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    path = selected_plan_path(directory, stage)
    temporary = path + ".partial"
    with open(temporary, "w") as handle:
        json.dump(artefact, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def read_selected_plan_artefact(directory, stage):
    """The frozen winner of a validation stage, with its provenance."""
    path = selected_plan_path(directory, stage)
    if not os.path.isfile(path):
        raise StageSequenceError(
            "No selected-plan artefact for stage {!r} at {}.".format(
                stage, path
            )
        )
    with open(path, "r") as handle:
        artefact = json.load(handle)
    payload = dict(
        (key, value) for key, value in artefact.items()
        if key != "payload_sha256"
    )
    if artefact.get("payload_sha256") != _sha256_payload(payload):
        raise StageSequenceError(
            "The selected-plan artefact for {!r} has been modified since it "
            "was written.".format(stage)
        )
    for field in ("plan", "provenance", "baseline_config_sha256",
                  "network_sha256", "network_git_blob", "derivation"):
        if not artefact.get(field):
            raise StageSequenceError(
                "The selected-plan artefact for {!r} is missing {}.".format(
                    stage, field
                )
            )
    return artefact
