"""The pre-final freeze artefact, and what unlocking final_test requires.

Everything that could still be chosen must be pinned before the held-out data
exists. The artefact records the configurations, the network, both selected
baseline plans with their provenance, the selected checkpoint for each learned
method, and the versions of the statistical and GO/NO-GO protocols. If any one
of those is absent the artefact is incomplete, and an incomplete freeze cannot
unlock anything -- there would still be a decision left to make with the final
data in view.

Artefacts here are hash-sealed rather than cryptographically signed: a digest
detects modification, but proves nothing about authorship. No signature
mechanism exists and none is claimed.

Unlocking is two things, not one. The freeze artefact says what was frozen;
the unlock is a separate, explicit action recording who authorised it, after
independent review. Requiring both means the artefact cannot unlock itself,
and the reviewer's approval cannot be inferred from the mere existence of a
file someone generated.

This module implements the requirement and refuses; the unlock action itself
is deliberately left unimplemented until after independent review, so nothing
in this batch can open final_test.
"""

from __future__ import absolute_import

import hashlib
import json
import os

from . import decision, semantics, statistics, stages


FREEZE_SCHEMA_VERSION = "pre-final-freeze-1.0"
FREEZE_FILENAME = "pre_final_freeze.json"
UNLOCK_FILENAME = "final_test_unlock.json"

LEARNED_METHODS = decision.LEARNED_METHODS

REQUIRED_FIELDS = (
    "freeze_schema_version",
    "adaptive_config_sha256",
    "baseline_config_sha256",
    "network_sha256",
    "network_git_blob",
    "primary_semantics_sha256",
    "selected_optimized_fixed_offset",
    "selected_optimized_fixed_timing",
    "selected_checkpoints",
    "statistical_protocol_version",
    "statistical_protocol_sha256",
    "go_no_go_protocol_version",
    "go_no_go_protocol_sha256",
)

REQUIRED_PLAN_FIELDS = ("plan", "provenance")
REQUIRED_PLAN_PROVENANCE = (
    "design_family", "design_seeds", "validation_family", "validation_seeds",
    "selected_key", "protocol",
)
REQUIRED_CHECKPOINT_FIELDS = (
    "training_seed", "transition_index", "checkpoint_sha256",
    "checkpoint_path", "selected_on_family", "selected_on_seeds",
    "validation_mean_J_primary_s", "validation_mean_time_loss_s",
)

# A hash that matches nothing is decoration. Each record names the file it
# froze, and the hash is checked against those bytes: otherwise "frozen"
# would mean only that somebody wrote down sixty-four hex characters.
CHECKPOINT_HASH_PATTERN = "64 lowercase hex characters"

# The inferential unit is the training seed, so every method carries ten
# independently selected policies -- one per training seed -- and not a single
# representative. Freezing one would silently discard nine of the ten
# measurements the whole statistical design rests on.
REQUIRED_TRAINING_SEEDS = statistics.TRAINING_SEEDS
REQUIRED_SELECTION_SEEDS = statistics.LEARNER_VALIDATION_SEEDS


class FreezeError(RuntimeError):
    pass


class UnlockRefused(RuntimeError):
    """Raised whenever final_test access is requested. It is not available."""


def _sha256(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def freeze_schema():
    """The schema, so a reviewer can see what must be pinned before unlock."""
    return {
        "freeze_schema_version": FREEZE_SCHEMA_VERSION,
        "required_fields": list(REQUIRED_FIELDS),
        "required_plan_fields": list(REQUIRED_PLAN_FIELDS),
        "required_plan_provenance": list(REQUIRED_PLAN_PROVENANCE),
        "required_checkpoint_fields": list(REQUIRED_CHECKPOINT_FIELDS),
        "learned_methods": list(LEARNED_METHODS),
        "unlock_requires": [
            "a complete freeze artefact that verifies",
            "the campaign stage machine at or past {}".format(
                stages.PRE_FINAL_AUDIT
            ),
            "a separate explicit unlock action, recorded, after independent "
            "review",
        ],
        "unlock_implemented": False,
        "unlock_note": (
            "The unlock action is deliberately not implemented. Nothing in "
            "this batch can open final_test."
        ),
    }


def build_freeze_artefact(adaptive_config_sha256, baseline_config_sha256,
                          network_sha256, network_git_blob,
                          selected_offset, selected_timing,
                          selected_checkpoints, notes=""):
    """Assemble the artefact. Completeness is checked separately, on purpose."""
    artefact = {
        "freeze_schema_version": FREEZE_SCHEMA_VERSION,
        "adaptive_config_sha256": adaptive_config_sha256,
        "baseline_config_sha256": baseline_config_sha256,
        "network_sha256": network_sha256,
        "network_git_blob": network_git_blob,
        "primary_semantics_sha256": semantics.specification_sha256(),
        "primary_semantics_version": semantics.SPECIFICATION_VERSION,
        "selected_optimized_fixed_offset": selected_offset,
        "selected_optimized_fixed_timing": selected_timing,
        "selected_checkpoints": selected_checkpoints,
        "statistical_protocol_version": statistics.PROTOCOL_VERSION,
        "statistical_protocol_sha256": statistics.protocol_sha256(),
        "go_no_go_protocol_version": decision.PROTOCOL_VERSION,
        "go_no_go_protocol_sha256": decision.protocol_sha256(),
        "stage_protocol_version": stages.PROTOCOL_VERSION,
        "notes": str(notes),
    }
    artefact["freeze_sha256"] = _sha256(
        dict((k, v) for k, v in artefact.items() if k != "freeze_sha256")
    )
    return artefact


def verify_freeze_hash(artefact):
    recorded = artefact.get("freeze_sha256")
    actual = _sha256(
        dict((k, v) for k, v in artefact.items() if k != "freeze_sha256")
    )
    if recorded != actual:
        raise FreezeError(
            "The freeze artefact has been modified since it was written: "
            "recorded {} but it hashes to {}.".format(recorded, actual)
        )
    return True


def _missing_plan_problems(label, entry):
    problems = []
    if not isinstance(entry, dict):
        return ["{} is missing entirely".format(label)]
    for field in REQUIRED_PLAN_FIELDS:
        if not entry.get(field):
            problems.append("{}.{} is missing".format(label, field))
    provenance = entry.get("provenance") or {}
    for field in REQUIRED_PLAN_PROVENANCE:
        if field not in provenance:
            problems.append(
                "{}.provenance.{} is missing".format(label, field)
            )
    return problems


def _normalise_seed_keys(entries):
    """Accept integer or string training-seed keys, which JSON round-trips."""
    normalised = {}
    for key, value in entries.items():
        try:
            normalised[int(key)] = value
        except (TypeError, ValueError):
            normalised[key] = value
    return normalised


def _checkpoint_problems(method, entries):
    """Exactly ten independently selected policies, one per training seed."""
    label = "selected_checkpoints.{}".format(method)
    if not entries:
        return ["{} is missing".format(label)]
    if not isinstance(entries, dict):
        return [
            "{} must map each training seed to its own selected checkpoint; "
            "one checkpoint per method would discard nine of the ten "
            "measurements the design rests on".format(label)
        ]
    if "transition_index" in entries or "checkpoint_sha256" in entries:
        # A single flat checkpoint record rather than one per training seed.
        return [
            "{} is one checkpoint record; it must map each training seed to "
            "its own selected checkpoint. One per method would discard nine "
            "of the ten measurements the design rests on".format(label)
        ]
    entries = _normalise_seed_keys(entries)
    problems = []
    seeds = sorted(key for key in entries if isinstance(key, int))
    foreign = sorted(key for key in entries if not isinstance(key, int))
    if foreign:
        problems.append(
            "{} has non-numeric training seeds {}".format(label, foreign)
        )
    missing = sorted(set(REQUIRED_TRAINING_SEEDS) - set(seeds))
    extra = sorted(set(seeds) - set(REQUIRED_TRAINING_SEEDS))
    if missing:
        problems.append(
            "{} is missing training seeds {}".format(label, missing)
        )
    if extra:
        problems.append(
            "{} carries foreign training seeds {}".format(label, extra)
        )
    if len(seeds) != len(set(seeds)):
        problems.append("{} repeats a training seed".format(label))

    for seed in seeds:
        entry = entries[seed]
        entry_label = "{}.{}".format(label, seed)
        if not isinstance(entry, dict):
            problems.append("{} is not a checkpoint record".format(entry_label))
            continue
        for field in REQUIRED_CHECKPOINT_FIELDS:
            if field not in entry or entry[field] in (None, "", []):
                problems.append(
                    "{}.{} is missing".format(entry_label, field)
                )
        declared = entry.get("training_seed")
        if declared is not None and int(declared) != int(seed):
            problems.append(
                "{}.training_seed is {}, which is not the key it is filed "
                "under".format(entry_label, declared)
            )
        family = entry.get("selected_on_family")
        if family and family != statistics.LEARNER_VALIDATION_FAMILY:
            problems.append(
                "{} was selected on {!r}; only {!r} may select a "
                "checkpoint".format(
                    entry_label, family, statistics.LEARNER_VALIDATION_FAMILY
                )
            )
        selection_seeds = entry.get("selected_on_seeds")
        if selection_seeds is not None:
            actual = tuple(sorted(int(value) for value in selection_seeds))
            if actual != REQUIRED_SELECTION_SEEDS:
                problems.append(
                    "{}.selected_on_seeds is {}; selection requires exactly "
                    "{}".format(
                        entry_label, list(actual),
                        list(REQUIRED_SELECTION_SEEDS),
                    )
                )
        index = entry.get("transition_index")
        if index is not None and int(index) not in (
            statistics.CHECKPOINT_TRANSITIONS
        ):
            problems.append(
                "{}.transition_index {} is not a preregistered "
                "checkpoint".format(entry_label, index)
            )
        problems.extend(_checkpoint_file_problems(entry_label, entry))
    return problems


def _checkpoint_file_problems(entry_label, entry):
    """The recorded hash must be the hash of the file actually frozen."""
    digest = entry.get("checkpoint_sha256")
    path = entry.get("checkpoint_path")
    problems = []
    if digest and not (
        len(str(digest)) == 64
        and all(character in "0123456789abcdef" for character in str(digest))
    ):
        problems.append(
            "{}.checkpoint_sha256 is not {}".format(
                entry_label, CHECKPOINT_HASH_PATTERN
            )
        )
    if not path:
        return problems
    if not os.path.isfile(path):
        problems.append(
            "{}.checkpoint_path {} does not exist, so its hash binds "
            "nothing".format(entry_label, path)
        )
        return problems
    actual = _sha256_file(path)
    if digest and actual != digest:
        problems.append(
            "{}.checkpoint_sha256 is {} but {} hashes to {}".format(
                entry_label, digest, path, actual
            )
        )
    return problems


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def freeze_problems(artefact):
    """Everything that would stop this artefact from authorising an unlock."""
    problems = []
    for field in REQUIRED_FIELDS:
        if artefact.get(field) in (None, "", {}, []):
            problems.append("{} is missing".format(field))

    problems.extend(_missing_plan_problems(
        "selected_optimized_fixed_offset",
        artefact.get("selected_optimized_fixed_offset"),
    ))
    problems.extend(_missing_plan_problems(
        "selected_optimized_fixed_timing",
        artefact.get("selected_optimized_fixed_timing"),
    ))

    checkpoints = artefact.get("selected_checkpoints") or {}
    for method in LEARNED_METHODS:
        problems.extend(_checkpoint_problems(method, checkpoints.get(method)))

    if artefact.get("statistical_protocol_sha256") != (
        statistics.protocol_sha256()
    ):
        problems.append(
            "statistical_protocol_sha256 does not match the protocol in this "
            "code; the protocol changed after the freeze"
        )
    if artefact.get("go_no_go_protocol_sha256") != decision.protocol_sha256():
        problems.append(
            "go_no_go_protocol_sha256 does not match the protocol in this "
            "code; the decision rule changed after the freeze"
        )
    if artefact.get("primary_semantics_sha256") != (
        semantics.specification_sha256()
    ):
        problems.append(
            "primary_semantics_sha256 does not match the frozen control "
            "specification in this code"
        )
    return problems


def assert_freeze_complete(artefact):
    verify_freeze_hash(artefact)
    problems = freeze_problems(artefact)
    if problems:
        raise FreezeError(
            "The pre-final freeze is incomplete, so nothing may be unlocked. "
            "An incomplete freeze means a choice is still open that the final "
            "data could inform. Missing or wrong: {}".format(problems)
        )
    return True


def write_freeze_artefact(directory, artefact):
    assert_freeze_complete(artefact)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    path = os.path.join(directory, FREEZE_FILENAME)
    with open(path, "w") as handle:
        json.dump(artefact, handle, indent=2, sort_keys=True)
    return path


def read_freeze_artefact(directory):
    path = os.path.join(directory, FREEZE_FILENAME)
    if not os.path.isfile(path):
        raise FreezeError(
            "No pre-final freeze artefact at {}.".format(path)
        )
    with open(path, "r") as handle:
        return json.load(handle)


def assert_final_test_unlock(directory, state_directory=None):
    """Refuse final_test access. Always, in this batch.

    The preconditions are checked first so the refusal reports what would
    still be needed, rather than hiding an incomplete freeze behind a blanket
    "not implemented". The unlock action itself does not exist yet by design.
    """
    outstanding = []
    try:
        artefact = read_freeze_artefact(directory)
    except FreezeError as error:
        outstanding.append(str(error))
        artefact = None
    if artefact is not None:
        try:
            assert_freeze_complete(artefact)
        except FreezeError as error:
            outstanding.append(str(error))
    if state_directory is not None:
        try:
            stages.verify_stage_artefact(
                state_directory, stages.PRE_FINAL_AUDIT
            )
        except (stages.ArtefactError, stages.StageOrderError) as error:
            outstanding.append(str(error))
    else:
        outstanding.append(
            "no campaign state directory was given, so the pre-final audit "
            "cannot be shown to have happened"
        )
    raise UnlockRefused(
        "final_test remains locked. The unlock is a separate, explicit action "
        "to be implemented only after independent review, and it is "
        "deliberately not implemented in this batch. Outstanding "
        "preconditions: {}".format(outstanding or ["none; awaiting review"])
    )
