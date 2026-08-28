"""Matched-transition training loop for QMIX, VDN and Independent DQN."""

from __future__ import absolute_import

import json
import os

from .config import require_scientific_run_allowed
from .environment import AdaptiveTrafficEnvironment
from .feasibility import FeasibilityMeter, write_feasibility_report
from .learner import MultiAgentLearner, epsilon_at_transition
from .logging import RunLogger
from .provenance import build_run_manifest
from .replay import JointReplayBuffer
from .rng import (
    IndependentEpsilonStreams,
    configure_python_and_torch,
    namespace_manifest,
    numpy_rng,
)
from .traffic import generate_manifest_records, write_manifest


RUN_KINDS = ("development", "compute_feasibility", "official_training")


def _manifest_for_episode(config, output_directory, training_seed, episode_index):
    records = generate_manifest_records(
        config, "training", training_seed, manifest_index=episode_index
    )
    prefix = os.path.join(
        output_directory, "manifests", "train_{:03d}_episode_{:05d}".format(
            int(training_seed), int(episode_index)
        )
    )
    metadata = write_manifest(
        records, config, prefix, "training", training_seed, episode_index
    )
    return prefix + ".csv", prefix + ".rou.xml", metadata


def train_learned_controller(
    traci_module,
    config,
    repository_root,
    method,
    training_seed,
    output_directory,
    run_kind="development",
    transition_limit=None,
    device="cpu",
):
    if run_kind not in RUN_KINDS:
        raise ValueError("Unknown run kind: {}".format(run_kind))
    if run_kind == "official_training":
        require_scientific_run_allowed(config)
    deterministic_seed = configure_python_and_torch(training_seed, deterministic=True)
    budget = int(config["training"]["interaction_budget"])
    if transition_limit is not None:
        budget = min(budget, int(transition_limit))
    if run_kind == "compute_feasibility":
        expected = int(config["training"]["compute_feasibility_transitions"])
        if budget != expected:
            raise ValueError(
                "Compute feasibility must use exactly {} transitions.".format(expected)
            )

    output_directory = os.path.abspath(output_directory)
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    manifest_csv, route_xml, traffic_metadata = _manifest_for_episode(
        config, output_directory, training_seed, 0
    )
    initial_sumo_seed = int(traffic_metadata["sumo_seed"])
    run_manifest = build_run_manifest(
        repository_root,
        config,
        manifest_csv,
        None,
        method,
        training_seed,
        training_seed,
        device,
        run_kind,
    )
    run_manifest["initial_sumo_seed"] = initial_sumo_seed
    run_manifest["traffic_manifest_metadata"] = traffic_metadata
    run_manifest["deterministic_python_torch_seed"] = deterministic_seed
    run_manifest["interaction_budget_this_run"] = budget
    run_manifest["official_scientific_result"] = run_kind == "official_training"

    learner = MultiAgentLearner(method, training_seed, config["training"], device)
    replay = JointReplayBuffer(
        config["training"]["replay_capacity"], 2, 8, 16
    )
    replay_rng = numpy_rng(training_seed, "replay_sampling")
    epsilon_streams = IndependentEpsilonStreams(training_seed, action_dim=2)
    rng_log = namespace_manifest(training_seed)
    transition_index = 0
    episode_index = 0
    feasibility = (
        FeasibilityMeter(method, budget)
        if run_kind == "compute_feasibility" else None
    )
    if feasibility is not None:
        feasibility.start()

    with RunLogger(output_directory, run_manifest) as logger:
        environment = None
        try:
            while transition_index < budget:
                if episode_index > 0:
                    manifest_csv, route_xml, traffic_metadata = _manifest_for_episode(
                        config, output_directory, training_seed, episode_index
                    )
                tripinfo_path = os.path.join(
                    output_directory, "tripinfo_episode_{:05d}.xml".format(episode_index)
                )
                sumo_seed = int(traffic_metadata["sumo_seed"])
                environment = AdaptiveTrafficEnvironment(
                    traci_module,
                    config,
                    repository_root,
                    manifest_csv,
                    route_xml,
                    tripinfo_path,
                    sumo_seed,
                    logger=logger,
                )
                observations, state, _reset_info = environment.reset(episode_index)
                episode_finished = False
                last_info = None

                while not episode_finished and transition_index < budget:
                    epsilon = epsilon_at_transition(
                        transition_index,
                        config["training"]["epsilon_start"],
                        config["training"]["epsilon_end"],
                        config["training"]["epsilon_decay_transitions"],
                    )
                    q_values = learner.local_q_values(observations)
                    greedy = [int(values.argmax()) for values in q_values]
                    actions, exploration = epsilon_streams.select(greedy, epsilon)
                    final_budget_action = transition_index + 1 == budget
                    next_observations, next_state, reward, terminated, info = (
                        environment.step(actions, budget_truncated=final_budget_action)
                    )
                    transition_index += 1
                    replay.push(
                        state,
                        observations,
                        actions,
                        reward,
                        next_state,
                        next_observations,
                        terminated,
                        info["elapsed_seconds"],
                        budget_truncated=info["budget_truncated"],
                        timeout_truncated=info["timeout_truncated"],
                    )

                    for agent_index, intersection in enumerate(("J1", "J2")):
                        logger.write_json_fields(
                            "signal_actions",
                            {
                                "decision_time": info["start_time"],
                                "decision_index": transition_index - 1,
                                "intersection": intersection,
                                "observation_json": observations[agent_index].tolist(),
                                "action": "EXTEND" if actions[agent_index] == 0 else "SWITCH",
                                "q_extend": float(q_values[agent_index][0]),
                                "q_switch": float(q_values[agent_index][1]),
                                "epsilon": epsilon,
                                "explore": exploration[agent_index]["explore"],
                                "reward": reward,
                                "elapsed_seconds": info["elapsed_seconds"],
                                "terminated": terminated,
                                "budget_truncated": info["budget_truncated"],
                                "timeout_truncated": info["timeout_truncated"],
                            },
                            ("observation_json",),
                        )

                    warmup = int(config["training"]["replay_warmup"])
                    if transition_index > warmup:
                        batch = replay.sample(
                            config["training"]["batch_size"], replay_rng
                        )
                        update = learner.update(batch)
                        update["transition_index"] = transition_index
                        update["component_losses_json"] = update.pop(
                            "component_losses"
                        )
                        update["preclip_gradient_norms_json"] = update.pop(
                            "preclip_gradient_norms"
                        )
                        logger.write_json_fields(
                            "learner_updates",
                            update,
                            ("component_losses_json", "preclip_gradient_norms_json"),
                        )

                    checkpoint_indices = set(
                        int(value)
                        for value in config["training"]["checkpoint_transitions"]
                    )
                    if transition_index in checkpoint_indices:
                        learner.save_checkpoint(
                            os.path.join(
                                output_directory,
                                "{}_seed{}_t{:06d}.pth".format(
                                    method, training_seed, transition_index
                                ),
                            ),
                            transition_index,
                            config["_config_sha256"],
                            rng_log,
                        )

                    if feasibility is not None:
                        feasibility.record_transition(
                            replay.estimated_bytes(), output_directory
                        )
                    observations, state = next_observations, next_state
                    last_info = info
                    episode_finished = bool(
                        terminated
                        or info["timeout_truncated"]
                        or info["budget_truncated"]
                    )

                if last_info is None:
                    raise RuntimeError("Episode ended without any joint transition.")
                if last_info["terminated"]:
                    status = "CLEARED"
                elif last_info["timeout_truncated"]:
                    status = "CLEARANCE_FAILURE"
                else:
                    status = "BUDGET_TRUNCATED"
                summary = environment.episode_summary(
                    status,
                    budget_truncated=last_info["budget_truncated"],
                    timeout_truncated=last_info["timeout_truncated"],
                )
                logger.write("episode_summary", summary)
                if status == "CLEARANCE_FAILURE":
                    logger.write_clearance_failure(
                        environment.complete_residual_state()
                    )
                logger.flush()
                environment.close()
                environment = None
                episode_index += 1
        finally:
            if environment is not None:
                environment.close()

    result = {
        "method": method,
        "training_seed": int(training_seed),
        "transitions": transition_index,
        "learner_events": learner.learner_events,
        "episodes": episode_index,
        "output_directory": output_directory,
    }
    if budget == int(config["training"]["interaction_budget"]):
        expected_updates = int(config["training"]["learner_events"])
        if learner.learner_events != expected_updates:
            raise RuntimeError(
                "Matched learner-event budget violated: {} != {}".format(
                    learner.learner_events, expected_updates
                )
            )
    if feasibility is not None:
        report = feasibility.finish()
        write_feasibility_report(
            os.path.join(output_directory, "compute_feasibility.json"), report
        )
        result["compute_feasibility"] = report
    with open(os.path.join(output_directory, "training_result.json"), "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
    return result
