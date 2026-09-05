"""Configuration loading and fail-fast contract validation."""

from __future__ import absolute_import

import hashlib
import json
import os

from .protocol import semantics as semantics_module


class ContractError(ValueError):
    """Raised when a configuration violates the approved contract."""


class ScientificRunBlocked(RuntimeError):
    """Raised when an official run is attempted with a provisional setting."""


def canonical_json_bytes(data):
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def config_sha256(data):
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


def load_config(path):
    with open(path, "r") as handle:
        data = json.load(handle)
    validate_config(data)
    data["_config_path"] = os.path.abspath(path)
    data["_config_sha256"] = config_sha256(
        {key: value for key, value in data.items() if not key.startswith("_")}
    )
    return data


def validate_config(config):
    if config.get("schema_version") != "1.3a":
        raise ContractError("Expected schema_version '1.3a'.")

    executor = config["executor"]
    if executor["decision_clock"] != "globally_synchronized":
        raise ContractError("Qualification supports globally synchronized decisions only.")

    control = int(executor["control_interval_s"])
    extend = int(executor["extend_duration_s"])
    switch = int(executor["switch_duration_s"])
    yellow = int(executor["yellow_duration_s"])
    new_green = int(executor["switch_new_green_s"])

    if control <= 0 or yellow < 0 or new_green <= 0:
        raise ContractError("Signal durations must be positive and physically valid.")
    if yellow + new_green != switch:
        raise ContractError("switch_duration must equal yellow + new green service.")
    if extend != control or switch != control:
        raise ContractError(
            "Unsupported asynchronous semantics: all actions must reach the same "
            "next joint-decision time. elapsed_seconds only solves discounting."
        )

    semantics = executor["yellow_semantics"]
    if semantics == semantics_module.FROZEN_YELLOW_SEMANTICS:
        # The frozen primary declaration is only meaningful if the numbers
        # behind it are the frozen ones, so it is verified rather than trusted.
        try:
            semantics_module.assert_frozen_timing(executor)
            semantics_module.assert_no_imposed_green_bounds(executor)
        except semantics_module.SemanticsError as error:
            raise ContractError(str(error))
    elif semantics.startswith(semantics_module.PROVISIONAL_PREFIX):
        if (yellow, new_green, control) != (3, 2, 5):
            raise ContractError(
                "{} must be exactly 3+2.".format(semantics)
            )

    observation = config["observation"]
    if len(observation["feature_order"]) != 8:
        raise ContractError("The qualification observation must remain 8-D.")
    if observation["queue_normalizer_H"] != 150.0:
        raise ContractError("Unexpected H queue normalizer.")
    if observation["queue_normalizer_V"] != 100.0:
        raise ContractError("Unexpected V queue normalizer.")

    demand = config["demand"]
    total = sum(int(item["count"]) for item in demand["streams"].values())
    if total != 2800 or total != int(demand["scheduled_total"]):
        raise ContractError("The qualification demand must contain exactly 2800 vehicles.")

    training = config["training"]
    if int(training["interaction_budget"]) != 360000:
        raise ContractError("The matched interaction budget must be 360000.")
    expected_updates = int(training["interaction_budget"]) - int(
        training["replay_warmup"]
    )
    if expected_updates != int(training["learner_events"]):
        raise ContractError("Learner-event budget is inconsistent with replay warm-up.")
    if float(training["huber_beta"]) != 1.0:
        raise ContractError("SmoothL1/Huber beta must be exactly 1.0.")
    if int(training["target_hard_update_events"]) != 500:
        raise ContractError("Target hard-copy frequency must be exactly 500 events.")


def require_scientific_run_allowed(config):
    """DEPRECATED as an authorisation gate. Not consulted by any entry point.

    Official training is authorised by the verified campaign state (see
    adaptive_qmix.protocol.authorization), because starting the campaign must
    not require editing the configuration whose hash the campaign is pinned
    to. This function is retained only to verify the frozen semantics
    declaration, and it is no longer called to decide whether a run may
    proceed.
    """
    try:
        semantics_module.assert_primary_semantics_frozen(config)
    except semantics_module.SemanticsError as error:
        raise ScientificRunBlocked(
            "Official run blocked: {}".format(error)
        )
    if not bool(config.get("scientific_run_allowed", False)):
        raise ScientificRunBlocked(
            "Official run blocked: the primary semantics is frozen, but "
            "scientific_run_allowed is still false. NOTE: this flag is "
            "deprecated and is not what authorises official training; see "
            "adaptive_qmix.protocol.authorization, which requires the "
            "verified campaign state instead."
        )

