"""The campaign state machine: a stage cannot run before its predecessors.

Ordering is what keeps the protocol honest. Selecting a checkpoint before the
baselines are frozen, or evaluating on final_test before the audit, would each
let a later choice be informed by an earlier result. So each stage produces a
hash-sealed completion artefact, and a stage refuses to start until every
earlier
artefact exists AND still hashes to what it recorded. An artefact edited after
the fact fails verification rather than quietly authorising the next stage.

Hash-sealed, not cryptographically signed: the artefact carries a digest of
its own payload, which detects modification but proves nothing about who wrote
it. There is no signature mechanism, and none is claimed.

A hash also proves nothing about whether the stage happened, so stages that
gate something carry a semantic validator as well. freeze_baseline_plans in
particular must record both selected classical plans with their selection
provenance and the configuration and network identity they were selected
under, because completing it is what authorises official training.

    1  baseline_design                        evaluate the candidate grids
    2  baseline_validation                    validate the shortlists
    3  freeze_baseline_plans                  offset and timing plans frozen
    4  train_learners                          IDQN, VDN, QMIX on seeds 101-110
    5  learner_validation_and_checkpoint_freeze  select and freeze checkpoints
    6  pre_final_audit                        independent review
    7  unlock_final_test                      explicit, separate, after review
    8  final_paired_evaluation                final_test seeds 3001-3010
    9  statistics                             the frozen statistical protocol
    10 mechanism_interpretation               why, not whether

Stage 7 is deliberately its own stage rather than a flag on stage 6: unlocking
the held-out data is an action someone takes and signs, not a side effect of
finishing an audit.
"""

from __future__ import absolute_import

import hashlib
import json
import os


PROTOCOL_VERSION = "campaign-stages-1.0"

BASELINE_DESIGN = "baseline_design"
BASELINE_VALIDATION = "baseline_validation"
FREEZE_BASELINE_PLANS = "freeze_baseline_plans"
TRAIN_LEARNERS = "train_learners"
LEARNER_VALIDATION = "learner_validation_and_checkpoint_freeze"
PRE_FINAL_AUDIT = "pre_final_audit"
UNLOCK_FINAL_TEST = "unlock_final_test"
FINAL_EVALUATION = "final_paired_evaluation"
STATISTICS = "statistics"
MECHANISM = "mechanism_interpretation"

STAGES = (
    BASELINE_DESIGN,
    BASELINE_VALIDATION,
    FREEZE_BASELINE_PLANS,
    TRAIN_LEARNERS,
    LEARNER_VALIDATION,
    PRE_FINAL_AUDIT,
    UNLOCK_FINAL_TEST,
    FINAL_EVALUATION,
    STATISTICS,
    MECHANISM,
)

STAGE_INDEX = dict((name, index) for index, name in enumerate(STAGES))

ARTEFACT_DIRECTORY = "campaign_state"
ARTEFACT_SUFFIX = ".stage.json"

# Stages after which final_test may exist at all.
FINAL_ACCESS_STAGES = (FINAL_EVALUATION, STATISTICS, MECHANISM)


class StageOrderError(RuntimeError):
    pass


class ArtefactError(RuntimeError):
    pass


def artefact_path(state_directory, stage):
    if stage not in STAGE_INDEX:
        raise StageOrderError("Unknown campaign stage {!r}.".format(stage))
    return os.path.join(state_directory, stage + ARTEFACT_SUFFIX)


def _payload_sha256(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


# Stage-specific payload requirements. A hash proves an artefact has not been
# edited; it says nothing about whether the stage actually happened. These
# validators are what make completion mean something, so that a stage cannot
# be marked done by writing a hash-consistent file with nothing in it.
REQUIRED_PAYLOAD_FIELDS = {
    FREEZE_BASELINE_PLANS: (
        "optimized_fixed_offset", "optimized_fixed_timing",
        "adaptive_config_sha256", "baseline_config_sha256", "network_sha256",
        "network_git_blob",
    ),
}

REQUIRED_PLAN_FIELDS = (
    "plan", "provenance", "selected_key", "baseline_config_sha256",
    "network_sha256", "network_git_blob",
    "selected_plan_artefact_path", "selected_plan_artefact_sha256",
)

REQUIRED_PLAN_PROVENANCE = (
    "design_family", "design_seeds", "validation_family", "validation_seeds",
    "selected_key", "protocol",
)

# The provenance the classical search protocol fixes. Anything else means the
# plan was selected under a different design and is not the frozen winner.
EXPECTED_DESIGN_FAMILY = "benchmark_design"
EXPECTED_DESIGN_SEEDS = [2001, 2002, 2003, 2004, 2005]
EXPECTED_VALIDATION_FAMILY = "benchmark_validation"
EXPECTED_VALIDATION_SEEDS = [2101, 2102, 2103, 2104, 2105]


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class StagePayloadError(ArtefactError):
    """Raised when a stage artefact is well-formed but says nothing."""


def _validate_freeze_baseline_plans(payload):
    """Both classical plans, each with real selection provenance and identity.

    Completing this stage is what authorises official training, so an empty or
    hand-written payload here would let a learner be trained against baselines
    that were never actually settled.
    """
    problems = []
    for field in REQUIRED_PAYLOAD_FIELDS[FREEZE_BASELINE_PLANS]:
        if not payload.get(field):
            problems.append("{} is missing".format(field))
    for track in ("optimized_fixed_offset", "optimized_fixed_timing"):
        entry = payload.get(track)
        if not isinstance(entry, dict):
            continue
        for field in REQUIRED_PLAN_FIELDS:
            if not entry.get(field):
                problems.append("{}.{} is missing".format(track, field))
        provenance = entry.get("provenance") or {}
        for field in REQUIRED_PLAN_PROVENANCE:
            if field not in provenance:
                problems.append(
                    "{}.provenance.{} is missing".format(track, field)
                )
        if provenance.get("design_family") != EXPECTED_DESIGN_FAMILY:
            problems.append(
                "{} was ranked on {!r}, not {}".format(
                    track, provenance.get("design_family"),
                    EXPECTED_DESIGN_FAMILY,
                )
            )
        if provenance.get("validation_family") != EXPECTED_VALIDATION_FAMILY:
            problems.append(
                "{} was selected on {!r}, not {}".format(
                    track, provenance.get("validation_family"),
                    EXPECTED_VALIDATION_FAMILY,
                )
            )
        for field, expected in (
            ("design_seeds", EXPECTED_DESIGN_SEEDS),
            ("validation_seeds", EXPECTED_VALIDATION_SEEDS),
        ):
            recorded = provenance.get(field)
            if recorded is not None and sorted(
                int(seed) for seed in recorded
            ) != expected:
                problems.append(
                    "{}.provenance.{} is {}, not exactly {}".format(
                        track, field, list(recorded), expected
                    )
                )
        if entry.get("selected_key") is not None and provenance.get(
            "selected_key"
        ) is not None and list(entry["selected_key"]) != list(
            provenance["selected_key"]
        ):
            problems.append(
                "{}.selected_key {} disagrees with its own provenance "
                "{}".format(
                    track, entry["selected_key"], provenance["selected_key"]
                )
            )
        for field in ("baseline_config_sha256", "network_sha256",
                      "network_git_blob"):
            if entry.get(field) and payload.get(field) and (
                entry[field] != payload[field]
            ):
                problems.append(
                    "{}.{} disagrees with the stage payload".format(
                        track, field
                    )
                )
        # The freeze is only as good as the artefacts it claims to rest on.
        artefact_path = entry.get("selected_plan_artefact_path")
        recorded_hash = entry.get("selected_plan_artefact_sha256")
        if artefact_path and recorded_hash:
            if not os.path.isfile(artefact_path):
                problems.append(
                    "{}.selected_plan_artefact_path {} does not exist".format(
                        track, artefact_path
                    )
                )
            elif _file_sha256(artefact_path) != recorded_hash:
                problems.append(
                    "{} selected-plan artefact at {} no longer hashes to the "
                    "value the freeze recorded".format(track, artefact_path)
                )
    if problems:
        raise StagePayloadError(
            "The {} artefact does not record a real baseline freeze: {}. A "
            "hash-consistent file is not evidence that the plans were "
            "selected.".format(FREEZE_BASELINE_PLANS, problems)
        )
    return True


STAGE_VALIDATORS = {
    FREEZE_BASELINE_PLANS: _validate_freeze_baseline_plans,
}


def validate_stage_payload(stage, payload):
    """Semantic check for stages that have one; a no-op for the rest."""
    validator = STAGE_VALIDATORS.get(stage)
    if validator is None:
        return True
    if not isinstance(payload, dict):
        raise StagePayloadError(
            "Stage {!r} requires a structured payload.".format(stage)
        )
    return validator(payload)


def write_stage_artefact(state_directory, stage, payload):
    """Record a stage as complete, with a hash over exactly what it recorded."""
    if stage not in STAGE_INDEX:
        raise StageOrderError("Unknown campaign stage {!r}.".format(stage))
    validate_stage_payload(stage, payload)
    if not os.path.isdir(state_directory):
        os.makedirs(state_directory)
    artefact = {
        "protocol_version": PROTOCOL_VERSION,
        "stage": stage,
        "stage_index": STAGE_INDEX[stage],
        "payload": payload,
        "payload_sha256": _payload_sha256(payload),
    }
    path = artefact_path(state_directory, stage)
    with open(path, "w") as handle:
        json.dump(artefact, handle, indent=2, sort_keys=True)
    return path


def read_stage_artefact(state_directory, stage):
    path = artefact_path(state_directory, stage)
    if not os.path.isfile(path):
        raise ArtefactError(
            "Stage {!r} has no completion artefact at {}.".format(stage, path)
        )
    with open(path, "r") as handle:
        return json.load(handle)


def verify_stage_artefact(state_directory, stage):
    """The artefact must still hash to what it claimed when written."""
    artefact = read_stage_artefact(state_directory, stage)
    if artefact.get("stage") != stage:
        raise ArtefactError(
            "Artefact at {} declares stage {!r}, not {!r}.".format(
                artefact_path(state_directory, stage),
                artefact.get("stage"), stage,
            )
        )
    recorded = artefact.get("payload_sha256")
    actual = _payload_sha256(artefact.get("payload"))
    if recorded != actual:
        raise ArtefactError(
            "Stage {!r} artefact has been modified since it was written: "
            "recorded {} but its payload hashes to {}. A stage cannot "
            "authorise the next one on evidence that changed "
            "afterwards.".format(stage, recorded, actual)
        )
    # Semantic as well as cryptographic: an intact hash over an empty payload
    # would otherwise read as a completed stage.
    validate_stage_payload(stage, artefact.get("payload"))
    return artefact


def completed_stages(state_directory):
    done = []
    for stage in STAGES:
        try:
            verify_stage_artefact(state_directory, stage)
        except (ArtefactError, StageOrderError):
            continue
        done.append(stage)
    return done


def assert_stage_allowed(state_directory, stage):
    """Refuse a stage until every earlier one is complete and verifies."""
    if stage not in STAGE_INDEX:
        raise StageOrderError("Unknown campaign stage {!r}.".format(stage))
    index = STAGE_INDEX[stage]
    missing = []
    for earlier in STAGES[:index]:
        try:
            verify_stage_artefact(state_directory, earlier)
        except ArtefactError as error:
            missing.append((earlier, str(error).split("\n")[0]))
    if missing:
        raise StageOrderError(
            "Stage {!r} (step {}) cannot start: {}. Each stage's freeze "
            "artefact must exist and hash correctly before the next one runs, "
            "so a later choice can never be informed by a result that was "
            "still moving.".format(
                stage, index + 1,
                "; ".join("{} incomplete ({})".format(name, why)
                          for name, why in missing),
            )
        )
    return True


def next_stage(state_directory):
    done = completed_stages(state_directory)
    for stage in STAGES:
        if stage not in done:
            return stage
    return None


def state_machine_definition():
    return {
        "protocol_version": PROTOCOL_VERSION,
        "stages": list(STAGES),
        "stage_count": len(STAGES),
        "rule": (
            "A stage may not execute until every previous stage's freeze "
            "artefact exists and hashes correctly."
        ),
        "final_access_stages": list(FINAL_ACCESS_STAGES),
        "unlock_is_its_own_stage": True,
    }
