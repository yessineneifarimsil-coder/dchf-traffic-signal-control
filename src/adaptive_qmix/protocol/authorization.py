"""Authorising official training, without mutating the scientific config.

Official training is campaign stage 4. Gating it on a boolean inside the
qualification configuration was wrong twice over: flipping the flag changes
the frozen config hash, so starting the campaign would alter the very artefact
the campaign is supposed to be pinned to; and a mutable field in a file says
nothing about whether the baselines were actually frozen first.

Authorisation is therefore external and evidential. Official training requires
the campaign state to show freeze_baseline_plans complete and hash-verified,
which is the real precondition: the classical plans must already be settled,
or a learner could be trained against baselines still in motion.

scientific_run_allowed is deprecated as an authorisation signal. It is left in
the configuration so old artefacts still parse and so its removal is a
separate, reviewed change, but nothing here consults it.

Final-test unlock is stage 7 and remains entirely separate. Authorising stage
4 grants no access to the held-out data.
"""

from __future__ import absolute_import

import hashlib
import json
import os

from . import stages
from .statistics import (
    TRAINING_BUDGET_TRANSITIONS,
    TRAINING_SEEDS,
)


AUTHORIZATION_VERSION = "official-training-authorization-1.0"

REQUIRED_STAGE = stages.FREEZE_BASELINE_PLANS
AUTHORISED_RUN_KIND = "official_training"
UNGATED_RUN_KINDS = ("development", "compute_feasibility")

DEPRECATED_FLAG = "scientific_run_allowed"
DEPRECATION_NOTE = (
    "scientific_run_allowed is NOT authoritative for official training. "
    "Authorisation comes from the verified campaign state showing "
    "{} complete. The flag is retained only so existing artefacts parse, and "
    "is deliberately not consulted here; changing it would alter the frozen "
    "configuration hash without establishing anything.".format(REQUIRED_STAGE)
)


class TrainingAuthorizationError(RuntimeError):
    pass


def authorization_evidence(state_directory):
    """The artefact that authorises official training, and its hash.

    The hash is over the artefact as written, so the run manifest can record
    exactly which freeze authorised it and a later reader can check that the
    artefact has not changed since.
    """
    if not state_directory:
        raise TrainingAuthorizationError(
            "Official training requires a campaign-state directory. "
            "Authorisation is evidence that {} completed, not a flag.".format(
                REQUIRED_STAGE
            )
        )
    state_directory = os.path.abspath(state_directory)
    try:
        stages.assert_stage_allowed(state_directory, stages.TRAIN_LEARNERS)
        artefact = stages.verify_stage_artefact(
            state_directory, REQUIRED_STAGE
        )
        # Verified semantically, not merely hash-consistently: the payload
        # must record both selected classical plans with their provenance and
        # the identity they were selected under.
        stages.validate_stage_payload(REQUIRED_STAGE, artefact.get("payload"))
    except (stages.StageOrderError, stages.ArtefactError) as error:
        raise TrainingAuthorizationError(
            "Official training is not authorised: {}".format(error)
        )
    payload = artefact.get("payload") or {}
    path = stages.artefact_path(state_directory, REQUIRED_STAGE)
    with open(path, "rb") as handle:
        file_digest = hashlib.sha256(handle.read()).hexdigest()
    return {
        "authorization_version": AUTHORIZATION_VERSION,
        "stage_protocol_version": stages.PROTOCOL_VERSION,
        "authorising_stage": REQUIRED_STAGE,
        "authorising_artefact_path": path,
        "authorising_artefact_sha256": file_digest,
        "authorising_payload_sha256": artefact["payload_sha256"],
        "campaign_state_directory": state_directory,
        "frozen_baseline_plans": dict(
            (track, payload[track]["selected_key"])
            for track in ("optimized_fixed_offset", "optimized_fixed_timing")
            if isinstance(payload.get(track), dict)
        ),
        "adaptive_config_sha256": payload.get("adaptive_config_sha256"),
        "baseline_config_sha256": payload.get("baseline_config_sha256"),
        "network_sha256": payload.get("network_sha256"),
        "completed_stages": stages.completed_stages(state_directory),
        "final_test_unlocked": False,
        "final_test_note": (
            "Authorising stage 4 grants no access to final_test, which is "
            "unlocked separately at stage {}.".format(
                stages.STAGE_INDEX[stages.UNLOCK_FINAL_TEST] + 1
            )
        ),
        "deprecated_flag_note": DEPRECATION_NOTE,
    }


def assert_official_training_parameters(training_seed, transition_limit,
                                        interaction_budget):
    """Official training is the frozen campaign, not a variation on it.

    Only the ten preregistered training seeds exist as inferential units, and
    the matched interaction budget is the whole basis of the comparison
    against IDQN and VDN. A shortened official run would be a different
    experiment reported under the same name.
    """
    seed = int(training_seed)
    if seed not in TRAINING_SEEDS:
        raise TrainingAuthorizationError(
            "Official training seed must be one of {}; got {}. The training "
            "seed is the inferential unit, and a seed outside the "
            "preregistered set has no place in the panel.".format(
                list(TRAINING_SEEDS), seed
            )
        )
    budget = int(interaction_budget)
    if transition_limit is not None and int(transition_limit) != budget:
        raise TrainingAuthorizationError(
            "Official training must execute exactly {} transitions; "
            "--transition-limit {} would shorten it. The matched interaction "
            "budget is what makes the comparison between methods "
            "fair.".format(budget, transition_limit)
        )
    return True


def assert_adaptive_config_frozen(evidence, adaptive_config_sha256):
    """Official training runs the configuration the baselines were frozen for.

    A copy of the qualification config with one hyper-parameter changed is a
    different specification, however scientifically reasonable it looks. Its
    hash is not the frozen one, and that is the whole check.
    """
    frozen = evidence.get("adaptive_config_sha256")
    if not frozen:
        raise TrainingAuthorizationError(
            "The baseline freeze records no adaptive_config_sha256, so the "
            "configuration this training would use cannot be shown to be the "
            "frozen one."
        )
    if adaptive_config_sha256 != frozen:
        raise TrainingAuthorizationError(
            "Official training must use the frozen adaptive configuration.\n"
            "  frozen  : {}\n  supplied: {}\n"
            "A configuration that differs in any field is a different "
            "specification, not a variant of the frozen one.".format(
                frozen, adaptive_config_sha256
            )
        )
    return True


def authorize_run(run_kind, state_directory=None, training_seed=None,
                  transition_limit=None, interaction_budget=None,
                  adaptive_config_sha256=None):
    """Returns the evidence for an official run, or None when none is needed."""
    if run_kind in UNGATED_RUN_KINDS:
        return None
    if run_kind != AUTHORISED_RUN_KIND:
        raise TrainingAuthorizationError(
            "Unknown run kind {!r}.".format(run_kind)
        )
    if training_seed is not None:
        assert_official_training_parameters(
            training_seed, transition_limit,
            TRAINING_BUDGET_TRANSITIONS if interaction_budget is None
            else interaction_budget,
        )
    evidence = authorization_evidence(state_directory)
    if adaptive_config_sha256 is not None:
        assert_adaptive_config_frozen(evidence, adaptive_config_sha256)
    evidence["adaptive_config_verified"] = adaptive_config_sha256 is not None
    return evidence
