"""Classical-controller runner: same contract, different timing authority.

Everything that defines a scientific run is reused rather than reimplemented.
The frozen network, the 2800-vehicle manifest generator, the vehicle type, the
SUMO seed derivation, the [0, 3600) generation interval, clearance to empty,
Tmax, the vehicle ledger and its reconciliation, the tripinfo parser,
J_primary, 1 s lane-state logging, the bidirectional WE/EW detectors, the
episode-completeness checks and the provenance manifest all come from the
adaptive package unchanged. A baseline differs from QMIX in exactly one thing:
who decides the signal.

That is achieved by substituting the executor rather than by rewriting the
environment. BaselineEnvironment subclasses AdaptiveTrafficEnvironment and
swaps its executor after reset, so the per-second contract in _after_second is
literally the same code path a QMIX run takes. The adaptive environment itself
is not modified.

The P-5 diagnostic is the exception that proves the rule: it uses the
unmodified AdaptiveTrafficEnvironment with its own SynchronousSignalExecutor,
because matching QMIX's control authority means using QMIX's timing, not an
imitation of it.

No legacy DCHF result is read, reused or carried forward here.
"""

from __future__ import absolute_import

import csv
import json
import os

from ..completeness import STATUS_CLEARED
from ..environment import AdaptiveTrafficEnvironment
from ..logging import LANE_LOG_FULL, RAW_LOG_SCHEMA_VERSION, RunLogger
from ..metrics import parse_tripinfo, scheduled_demand_metrics
from ..provenance import build_run_manifest, sha256_file
from ..signal_executor import EXTEND, SWITCH
from ..traci_access import DEFAULT_MODE
from .integrity import (
    assert_paths_are_the_verified_ones,
    manifest_paths,
    verify_manifest_for_run,
)
from .executors import (
    CanonicalMaxPressureExecutor,
    PretimedScheduleExecutor,
    TIMING_PRESSURE,
    TIMING_PRETIMED,
    TIMING_SYNCHRONOUS,
)
from .plans import MIN_GREEN_S, candidate_is_valid, validate_plan
from .pressure import (
    FROZEN_MOVEMENT_PAIRS,
    LANE_COUNT_ACCESSOR,
    local_pressures,
    preferred_phase,
    validate_against_observation_topology,
    validate_movement_pairs,
)


SIMULTANEOUS_FIXED_TIME = "simultaneous_fixed_time"
OPTIMIZED_FIXED_OFFSET = "optimized_fixed_offset"
OPTIMIZED_FIXED_TIMING = "optimized_fixed_timing"
CANONICAL_MAX_PRESSURE = "canonical_operational_max_pressure"
MATCHED_INTERVAL_PRESSURE_P5 = "matched_interval_pressure_P5"

PRETIMED_CONTROLLERS = (
    SIMULTANEOUS_FIXED_TIME, OPTIMIZED_FIXED_OFFSET, OPTIMIZED_FIXED_TIMING,
)
PRESSURE_CONTROLLERS = (CANONICAL_MAX_PRESSURE, MATCHED_INTERVAL_PRESSURE_P5)
BASELINE_CONTROLLERS = PRETIMED_CONTROLLERS + PRESSURE_CONTROLLERS

# The learned methods, kept separate so no identifier can be read as both.
LEARNED_METHODS = ("qmix", "vdn", "idqn")

TIMING_AUTHORITY = {
    SIMULTANEOUS_FIXED_TIME: TIMING_PRETIMED,
    OPTIMIZED_FIXED_OFFSET: TIMING_PRETIMED,
    OPTIMIZED_FIXED_TIMING: TIMING_PRETIMED,
    CANONICAL_MAX_PRESSURE: TIMING_PRESSURE,
    MATCHED_INTERVAL_PRESSURE_P5: TIMING_SYNCHRONOUS,
}

# P-5 is a control-authority diagnostic, not an official controller.
OFFICIAL_CLASSICAL_CONTROLLERS = (
    SIMULTANEOUS_FIXED_TIME, OPTIMIZED_FIXED_OFFSET, OPTIMIZED_FIXED_TIMING,
    CANONICAL_MAX_PRESSURE,
)
DIAGNOSTIC_CONTROLLERS = (MATCHED_INTERVAL_PRESSURE_P5,)

DECISION_FIELDS = (
    "time", "intersection", "controller", "timing_authority",
    "controller_decision_index", "current_phase", "green_elapsed_s",
    "pressure_H", "pressure_V", "preferred_phase", "decision",
)
TRANSITION_FIELDS = (
    "time", "intersection", "controller", "timing_authority", "event",
    "from_actual_phase", "to_actual_phase", "local_schedule_time_s",
    "cycle_index", "cycle_s", "offset_s",
)

CONTROLLER_DECISIONS_FILE = "controller_decisions.csv"
SCHEDULE_TRANSITIONS_FILE = "schedule_transitions.csv"


class BaselineError(RuntimeError):
    pass


def controller_interpretation(controller):
    """What a comparison against this controller may and may not claim."""
    if controller == CANONICAL_MAX_PRESSURE:
        return (
            "QMIX versus canonical operational max pressure is a "
            "controller-family competitiveness comparison. This finite, "
            "two-phase, switching-loss implementation with a minimum green "
            "does NOT inherit the idealised theoretical maximum-stability "
            "guarantee; it is a strong empirical operational baseline."
        )
    if controller == MATCHED_INTERVAL_PRESSURE_P5:
        return (
            "QMIX versus matched_interval_pressure_P5 is a matched "
            "control-authority diagnostic, not a controller-family "
            "comparison. P-5 is not an official controller, and canonical "
            "max-pressure stability claims never transfer to it."
        )
    return (
        "A pretimed classical benchmark. Its plan is fixed offline; it takes "
        "no online decisions."
    )


class BaselineEnvironment(AdaptiveTrafficEnvironment):
    """The adaptive environment with the signal executor substituted.

    reset() runs the inherited setup first, so the ledger, data source,
    observation builder, detectors and reward sampler are built exactly as
    they are for a QMIX run, and only then replaces the executor. Both
    initialize() calls happen before any simulation step, so the baseline
    executor's phases are what SUMO actually starts from.
    """

    def __init__(self, *args, **kwargs):
        self.executor_factory = kwargs.pop("executor_factory", None)
        super(BaselineEnvironment, self).__init__(*args, **kwargs)

    def reset(self, episode_index=0):
        local, state, info = super(BaselineEnvironment, self).reset(
            episode_index
        )
        if self.executor_factory is not None:
            self.executor = self.executor_factory(self.traci, self.config, self)
            self.executor.initialize()
        return local, state, info


class MatchedIntervalPressurePolicy(object):
    """Pressure decisions on the adaptive 5 s clock, with QMIX's 3+2 switch.

    The pressure score and the tie rule are identical to the canonical
    controller's; only the execution authority differs. That is exactly what
    makes the pair a control-authority diagnostic rather than two controllers.
    """

    controller = MATCHED_INTERVAL_PRESSURE_P5
    timing_authority = TIMING_SYNCHRONOUS

    def __init__(self, config, data_source, movement_pairs=None):
        self.config = config
        self.source = data_source
        self.movement_pairs = movement_pairs
        self.tl_ids = list(config["network"]["traffic_lights"])
        self.events = []
        self.decision_index = 0

    def decide(self, simulation_time, current_phase, green_elapsed):
        actions = []
        for tl_id in self.tl_ids:
            pressures = local_pressures(
                self.source, tl_id, self.movement_pairs
            )
            current = current_phase[tl_id]
            preferred = preferred_phase(pressures, current)
            action = EXTEND if preferred == current else SWITCH
            self.events.append({
                "time": float(simulation_time),
                "intersection": tl_id,
                "controller_decision_index": self.decision_index,
                "current_phase": current,
                "green_elapsed_s": int(green_elapsed[tl_id]),
                "pressure_H": pressures["H"],
                "pressure_V": pressures["V"],
                "preferred_phase": preferred,
                "decision": "EXTEND" if action == EXTEND else "SWITCH",
            })
            actions.append(action)
        self.decision_index += 1
        return actions


def _log_matched_decisions(logger, info, actions, decision_index, terminated):
    """Write P-5's joint decisions into the adaptive signal_actions log."""
    for agent_index, intersection in enumerate(("J1", "J2")):
        logger.write("signal_actions", {
            "episode_index": 0,
            "decision_time": info["start_time"],
            "decision_index": decision_index,
            "intersection": intersection,
            "action": "EXTEND" if actions[agent_index] == EXTEND else "SWITCH",
            "epsilon": 0.0,
            "explore": False,
            "elapsed_seconds": info["elapsed_seconds"],
            "terminated": terminated,
            "budget_truncated": False,
            "timeout_truncated": info["timeout_truncated"],
        })


def _write_rows(path, fieldnames, rows, controller, timing_authority,
                event=None):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fieldnames), extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            enriched = dict(row)
            enriched["controller"] = controller
            enriched["timing_authority"] = timing_authority
            if event is not None:
                enriched.setdefault("event", event)
            writer.writerow(enriched)


def _baseline_manifest(repository_root, config, manifest_csv_path, controller,
                       plan, traffic_family, traffic_seed, sumo_seed, run_kind,
                       traci_access_mode, lane_state_logging,
                       qualification_config_path, verified_hashes=None,
                       manifest_index=0):
    manifest = build_run_manifest(
        repository_root,
        config,
        manifest_csv_path,
        None,
        controller,
        None,
        traffic_seed,
        "cpu",
        run_kind,
        traci_access_mode,
        lane_state_logging,
    )
    manifest["raw_log_schema_version"] = RAW_LOG_SCHEMA_VERSION
    manifest["controller"] = controller
    manifest["controller_is_official"] = (
        controller in OFFICIAL_CLASSICAL_CONTROLLERS
    )
    manifest["controller_interpretation"] = controller_interpretation(controller)
    manifest["timing_authority"] = TIMING_AUTHORITY[controller]
    manifest["phase_parameters"] = None if plan is None else dict(plan)
    manifest["traffic_family"] = str(traffic_family)
    manifest["traffic_seed"] = int(traffic_seed)
    manifest["sumo_seed"] = int(sumo_seed)
    manifest["manifest_sha256"] = sha256_file(manifest_csv_path)
    manifest["manifest_index"] = int(manifest_index)
    if verified_hashes is not None:
        manifest["manifest_csv_sha256"] = verified_hashes["csv_sha256"]
        # SUMO executes the route XML; the CSV is provenance for it. Both are
        # recorded so a run can be tied to the file that actually ran.
        manifest["route_xml_sha256"] = verified_hashes["route_xml_sha256"]
        manifest["manifest_metadata_verified"] = True
        if "sumo_seed" in verified_hashes:
            # Recorded as verified, not merely reported: this value was proved
            # equal to both the manifest's and the derivation's.
            manifest["sumo_seed_verified"] = True
            manifest["sumo_seed_derivation"] = (
                "derive_sumo_seed({!r}, {}, {})".format(
                    traffic_family, int(traffic_seed), int(manifest_index)
                )
            )
    manifest["baseline_config_sha256"] = config["_config_sha256"]
    manifest["baseline_config_path"] = config.get("_config_path")
    if qualification_config_path and os.path.isfile(qualification_config_path):
        manifest["adaptive_qualification_config_sha256"] = sha256_file(
            qualification_config_path
        )
    if controller in PRESSURE_CONTROLLERS:
        manifest["pressure_movement_pairs"] = dict(
            (name, dict((m, [list(p) for p in pairs])
                        for m, pairs in movements.items()))
            for name, movements in FROZEN_MOVEMENT_PAIRS.items()
        )
        manifest["pressure_lane_count_accessor"] = LANE_COUNT_ACCESSOR
    return manifest


def run_baseline(traci_module, config, repository_root, controller,
                 manifest_csv_path, route_xml_path, traffic_family,
                 traffic_seed, sumo_seed, output_directory, plan=None,
                 run_kind="development_baseline",
                 traci_access_mode=DEFAULT_MODE,
                 lane_state_logging=LANE_LOG_FULL,
                 qualification_config_path=None,
                 movement_pairs=None, manifest_index=0,
                 manifest_prefix=None):
    """One full-clearance baseline episode, logged exactly like an adaptive run.

    Every held-out and manifest-integrity check runs before an output
    directory is created or a manifest is opened, so a refused run leaves no
    trace on disk to be mistaken for a real one later.
    """
    if controller not in BASELINE_CONTROLLERS:
        raise BaselineError(
            "Unknown baseline controller {!r}; expected one of {}.".format(
                controller, BASELINE_CONTROLLERS
            )
        )
    # Argument validity first: it touches nothing, so a malformed call is
    # rejected before the guard even needs to look at a manifest.
    if controller in PRETIMED_CONTROLLERS:
        if plan is None:
            raise BaselineError(
                "{} is pretimed and needs an explicit plan.".format(controller)
            )
        validate_plan(plan)
    if controller == OPTIMIZED_FIXED_TIMING and not candidate_is_valid(plan):
        # The classical benchmark's plan-admissibility rule, enforced where a
        # plan is executed and not only where one is generated. It is a rule
        # about pretimed plans; QMIX and P-5 have no minimum green and are
        # deliberately untouched by it.
        raise BaselineError(
            "optimized_fixed_timing refuses a plan with a green below {} s: "
            "g_H = {}, g_V = {}, C = {}. This admissibility rule is classical "
            "only and is never applied to QMIX or P-5.".format(
                MIN_GREEN_S, plan["green_H_s"], plan["green_V_s"],
                plan["cycle_s"],
            )
        )
    # Held-out and manifest-integrity checks, before any directory exists and
    # before SUMO is given a route file to execute.
    if manifest_prefix is None:
        if not str(manifest_csv_path).endswith(".csv"):
            raise BaselineError(
                "Cannot locate the manifest metadata for {!r}; pass "
                "manifest_prefix explicitly.".format(manifest_csv_path)
            )
        manifest_prefix = str(manifest_csv_path)[: -len(".csv")]
    _metadata, verified_hashes = verify_manifest_for_run(
        manifest_prefix, traffic_family, traffic_seed, manifest_index,
        sumo_seed=sumo_seed,
    )
    # What was verified must be what SUMO is handed. The executed paths are
    # required to be the verified prefix's own files, and the run then uses
    # those derived paths rather than whatever was passed in, so a verified
    # prefix can never authorise a different route file.
    assert_paths_are_the_verified_ones(
        manifest_prefix, manifest_csv_path, route_xml_path
    )
    executed = manifest_paths(manifest_prefix)
    manifest_csv_path = executed["csv"]
    route_xml_path = executed["route_xml"]
    sumo_seed = int(verified_hashes["sumo_seed"])

    network_path = os.path.join(repository_root, config["network"]["path"])
    if controller in PRESSURE_CONTROLLERS:
        validate_movement_pairs(network_path, movement_pairs)
        validate_against_observation_topology(config, movement_pairs)

    output_directory = os.path.abspath(output_directory)
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    tripinfo_path = os.path.join(output_directory, "tripinfo.xml")
    manifest = _baseline_manifest(
        repository_root, config, manifest_csv_path, controller, plan,
        traffic_family, traffic_seed, sumo_seed, run_kind, traci_access_mode,
        lane_state_logging, qualification_config_path,
        verified_hashes=verified_hashes, manifest_index=manifest_index,
    )

    policy = None
    executor_factory = None
    if controller in PRETIMED_CONTROLLERS:
        def executor_factory(traci_ref, config_ref, environment):
            return PretimedScheduleExecutor(traci_ref, config_ref, plan=plan)
    elif controller == CANONICAL_MAX_PRESSURE:
        def executor_factory(traci_ref, config_ref, environment):
            return CanonicalMaxPressureExecutor(
                traci_ref, config_ref, data_source=environment.source,
                movement_pairs=movement_pairs,
            )

    with RunLogger(output_directory, manifest) as logger:
        if controller == MATCHED_INTERVAL_PRESSURE_P5:
            environment = AdaptiveTrafficEnvironment(
                traci_module, config, repository_root, manifest_csv_path,
                route_xml_path, tripinfo_path, sumo_seed, logger=logger,
                traci_access_mode=traci_access_mode,
                lane_state_logging=lane_state_logging,
            )
        else:
            environment = BaselineEnvironment(
                traci_module, config, repository_root, manifest_csv_path,
                route_xml_path, tripinfo_path, sumo_seed, logger=logger,
                traci_access_mode=traci_access_mode,
                lane_state_logging=lane_state_logging,
                executor_factory=executor_factory,
            )
        try:
            environment.reset(episode_index=0)
            if controller == MATCHED_INTERVAL_PRESSURE_P5:
                policy = MatchedIntervalPressurePolicy(
                    config, environment.source, movement_pairs
                )
            status = None
            last_info = None
            decision_index = 0
            while status is None:
                if policy is not None:
                    actions = policy.decide(
                        environment.time,
                        environment.executor.current_phase,
                        environment.executor.green_elapsed,
                    )
                else:
                    actions = None
                _local, _state, _reward, terminated, info = environment.step(
                    actions
                )
                if actions is not None:
                    # P-5 alone takes decisions with QMIX's own semantics --
                    # the same 5 s clock, the same EXTEND/SWITCH meaning -- so
                    # they belong in signal_actions, where they are directly
                    # comparable with a learned run's. Nothing is invented:
                    # there are no Q-values, so those columns stay empty
                    # rather than being written as zero, and no pretimed
                    # controller reaches this branch at all.
                    _log_matched_decisions(
                        logger, info, actions, decision_index, terminated
                    )
                decision_index += 1
                last_info = info
                if terminated:
                    status = STATUS_CLEARED
                elif info["timeout_truncated"]:
                    status = "CLEARANCE_FAILURE"
            summary = environment.episode_summary(
                status, timeout_truncated=last_info["timeout_truncated"]
            )
            logger.write("episode_summary", summary)
            if status == "CLEARANCE_FAILURE":
                logger.write_clearance_failure(
                    environment.complete_residual_state()
                )
            logger.flush()
            ledger = environment.ledger
            executor = environment.executor
        finally:
            environment.close()

    timing_authority = TIMING_AUTHORITY[controller]
    if controller in PRETIMED_CONTROLLERS:
        events = list(getattr(executor, "events", []))
        _write_rows(
            os.path.join(output_directory, SCHEDULE_TRANSITIONS_FILE),
            TRANSITION_FIELDS, events, controller, timing_authority,
            event="SCHEDULE_TRANSITION",
        )
        decision_count = 0
    else:
        events = list(
            policy.events if policy is not None
            else getattr(executor, "events", [])
        )
        _write_rows(
            os.path.join(output_directory, CONTROLLER_DECISIONS_FILE),
            DECISION_FIELDS, events, controller, timing_authority,
        )
        decision_count = len(events)

    tripinfo_rows = parse_tripinfo(tripinfo_path)
    metrics = scheduled_demand_metrics(ledger, tripinfo_rows, status)
    metrics["J_legacy_time_averaged_aggregate_waiting_state"] = summary[
        "legacy_waiting_state_time_average"
    ]
    metrics["clearance_status"] = status
    metrics["controller"] = controller
    metrics["controller_is_official"] = (
        controller in OFFICIAL_CLASSICAL_CONTROLLERS
    )
    metrics["controller_interpretation"] = controller_interpretation(controller)
    metrics["timing_authority"] = timing_authority
    metrics["phase_parameters"] = None if plan is None else dict(plan)
    metrics["traffic_family"] = str(traffic_family)
    metrics["traffic_seed"] = int(traffic_seed)
    metrics["sumo_seed"] = int(sumo_seed)
    metrics["manifest_sha256"] = manifest["manifest_sha256"]
    metrics["manifest_csv_sha256"] = manifest["manifest_csv_sha256"]
    # The route XML is what SUMO actually executed; the CSV is provenance.
    metrics["route_xml_sha256"] = manifest["route_xml_sha256"]
    metrics["manifest_index"] = int(manifest_index)
    metrics["sumo_seed_verified"] = bool(
        manifest.get("sumo_seed_verified", False)
    )
    metrics["executed_route_xml_path"] = route_xml_path
    metrics["executed_manifest_csv_path"] = manifest_csv_path
    metrics["network_sha256"] = manifest["network_sha256"]
    metrics["network_git_blob"] = manifest["network_git_blob"]
    metrics["baseline_config_sha256"] = manifest["baseline_config_sha256"]
    metrics["controller_decision_count"] = decision_count
    metrics["elapsed_s"] = summary["elapsed_s"]
    metrics["method"] = controller
    with open(
        os.path.join(output_directory, "evaluation_metrics.json"), "w"
    ) as handle:
        json.dump(metrics, handle, indent=2, sort_keys=True)
    return metrics
