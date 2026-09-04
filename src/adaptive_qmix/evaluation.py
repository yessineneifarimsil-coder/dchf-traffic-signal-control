"""Frozen-policy full-clearance evaluation on an explicit traffic manifest."""

from __future__ import absolute_import

import json
import os

import torch

from .config import require_scientific_run_allowed
from .environment import AdaptiveTrafficEnvironment
from .learner import MultiAgentLearner
from .logging import LANE_LOG_FULL, RAW_LOG_SCHEMA_VERSION, RunLogger
from .metrics import parse_tripinfo, scheduled_demand_metrics
from .provenance import build_run_manifest
from .traci_access import DEFAULT_MODE


def load_frozen_policy(checkpoint_path, config, device="cpu"):
    payload = torch.load(checkpoint_path, map_location=device)
    method = payload["method"]
    training_seed = int(
        payload["rng_namespaces"]["local_init_J1"]["training_seed"]
    )
    if payload["config_sha256"] != config["_config_sha256"]:
        raise RuntimeError("Checkpoint and evaluation configuration hashes differ.")
    learner = MultiAgentLearner(method, training_seed, config["training"], device)
    learner.online_locals.load_state_dict(payload["online_locals"])
    if method == "qmix":
        learner.online_mixer.load_state_dict(payload["online_mixer"])
        learner.online_mixer.eval()
    learner.online_locals.eval()
    return learner, payload, training_seed


def evaluate_checkpoint(
    traci_module,
    config,
    repository_root,
    checkpoint_path,
    manifest_csv_path,
    route_xml_path,
    traffic_seed,
    sumo_seed,
    output_directory,
    run_kind="development_evaluation",
    device="cpu",
    traci_access_mode=DEFAULT_MODE,
    lane_state_logging=LANE_LOG_FULL,
):
    if run_kind == "official_evaluation":
        require_scientific_run_allowed(config)
    learner, payload, training_seed = load_frozen_policy(
        checkpoint_path, config, device
    )
    if run_kind == "official_evaluation" and int(payload["transition_index"]) != int(
        config["training"]["interaction_budget"]
    ):
        raise RuntimeError("Official evaluation requires the final 360000-transition checkpoint.")

    output_directory = os.path.abspath(output_directory)
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    tripinfo_path = os.path.join(output_directory, "tripinfo.xml")
    manifest = build_run_manifest(
        repository_root,
        config,
        manifest_csv_path,
        checkpoint_path,
        payload["method"],
        training_seed,
        traffic_seed,
        device,
        run_kind,
        traci_access_mode,
        lane_state_logging,
    )
    manifest["raw_log_schema_version"] = RAW_LOG_SCHEMA_VERSION
    manifest["sumo_seed"] = int(sumo_seed)
    manifest["checkpoint_transition_index"] = int(payload["transition_index"])

    with RunLogger(output_directory, manifest) as logger:
        environment = AdaptiveTrafficEnvironment(
            traci_module,
            config,
            repository_root,
            manifest_csv_path,
            route_xml_path,
            tripinfo_path,
            sumo_seed,
            logger=logger,
            traci_access_mode=traci_access_mode,
            lane_state_logging=lane_state_logging,
        )
        try:
            observations, state, _info = environment.reset(episode_index=0)
            decision_index = 0
            status = None
            last_info = None
            while status is None:
                q_values = learner.local_q_values(observations)
                actions = [int(values.argmax()) for values in q_values]
                next_observations, next_state, reward, terminated, info = (
                    environment.step(actions)
                )
                for agent_index, intersection in enumerate(("J1", "J2")):
                    logger.write_json_fields(
                        "signal_actions",
                        {
                            "episode_index": 0,
                            "decision_time": info["start_time"],
                            "decision_index": decision_index,
                            "intersection": intersection,
                            "observation_json": observations[agent_index].tolist(),
                            "action": "EXTEND" if actions[agent_index] == 0 else "SWITCH",
                            "q_extend": float(q_values[agent_index][0]),
                            "q_switch": float(q_values[agent_index][1]),
                            "epsilon": 0.0,
                            "explore": False,
                            "reward": reward,
                            "elapsed_seconds": info["elapsed_seconds"],
                            "terminated": terminated,
                            "budget_truncated": False,
                            "timeout_truncated": info["timeout_truncated"],
                        },
                        ("observation_json",),
                    )
                decision_index += 1
                observations, state = next_observations, next_state
                last_info = info
                if terminated:
                    status = "CLEARED"
                elif info["timeout_truncated"]:
                    status = "CLEARANCE_FAILURE"

            summary = environment.episode_summary(
                status, timeout_truncated=last_info["timeout_truncated"]
            )
            logger.write("episode_summary", summary)
            if status == "CLEARANCE_FAILURE":
                logger.write_clearance_failure(environment.complete_residual_state())
            logger.flush()
            ledger = environment.ledger
        finally:
            environment.close()

    tripinfo_rows = parse_tripinfo(tripinfo_path)
    metrics = scheduled_demand_metrics(ledger, tripinfo_rows, status)
    metrics["J_legacy_time_averaged_aggregate_waiting_state"] = summary[
        "legacy_waiting_state_time_average"
    ]
    metrics["clearance_status"] = status
    metrics["traffic_seed"] = int(traffic_seed)
    metrics["training_seed"] = int(training_seed)
    metrics["method"] = payload["method"]
    with open(os.path.join(output_directory, "evaluation_metrics.json"), "w") as handle:
        json.dump(metrics, handle, indent=2, sort_keys=True)
    return metrics

