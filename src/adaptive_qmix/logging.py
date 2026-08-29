"""Append-only raw run logging with stable CSV schemas."""

from __future__ import absolute_import

import csv
import json
import os

from .provenance import write_run_manifest


# Lane-state logging cadence. "full" logs every simulated second; "decision"
# logs only the last second of each joint-decision block, which is the instant
# the next observation is built. A decision-cadence log is therefore a strict
# timestamp subset of the corresponding full log. Cadence affects stored
# evidence only: no table consumed by scientific evaluation reads lane_states,
# and no control quantity depends on it.
LANE_LOG_FULL = "full"
LANE_LOG_DECISION = "decision"
LANE_LOG_MODES = (LANE_LOG_FULL, LANE_LOG_DECISION)


SCHEMAS = {
    "episode_summary": [
        "episode_index", "status", "start_time", "end_time", "elapsed_s",
        "scheduled", "inserted", "completed", "exceptional_terminal",
        "pending_due", "scheduled_future", "active_sumo", "active_ledger",
        "teleport_started", "teleport_ended", "network_reward",
        "active_stopped_vehicle_seconds", "pending_due_vehicle_seconds",
        "legacy_waiting_state_integral", "legacy_waiting_state_time_average",
        "budget_truncated", "timeout_truncated", "clearance_failure",
        "transport_healed_subscriptions",
    ],
    "signal_actions": [
        "decision_time", "decision_index", "intersection", "observation_json",
        "action", "q_extend", "q_switch", "epsilon", "explore", "reward",
        "elapsed_seconds", "terminated", "budget_truncated", "timeout_truncated",
    ],
    "signal_phases": [
        "time", "intersection", "actual_phase", "logical_green_phase",
        "green_elapsed_s", "yellow", "green_start", "green_end",
        "H_red_elapsed_s", "V_red_elapsed_s",
    ],
    "lane_states": [
        "time", "lane", "queue", "vehicle_count", "occupancy", "mean_speed",
    ],
    "vehicle_crossings": [
        "vehicle_id", "intersection", "approach", "event", "time",
        "lane", "position_m", "signal_state", "speed_m_s",
        "stopped_after_GAD50",
    ],
    "reward_seconds": [
        "time", "active_vehicle_count", "stopped_active_count",
        "pending_due_count", "incremental_delay_vehicle_seconds",
    ],
    "learner_updates": [
        "transition_index", "learner_event", "method", "loss",
        "component_losses_json", "target_mean", "preclip_gradient_norms_json",
        "target_hard_copied",
    ],
}


class RunLogger(object):
    def __init__(self, run_directory, run_manifest):
        self.run_directory = os.path.abspath(run_directory)
        if not os.path.isdir(self.run_directory):
            os.makedirs(self.run_directory)
        write_run_manifest(
            os.path.join(self.run_directory, "run_manifest.json"), run_manifest
        )
        self._handles = {}
        self._writers = {}
        for name, fields in SCHEMAS.items():
            path = os.path.join(self.run_directory, name + ".csv")
            handle = open(path, "w", newline="")
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            self._handles[name] = handle
            self._writers[name] = writer

    def write(self, table, row):
        if table not in self._writers:
            raise KeyError("Unknown raw log table: {}".format(table))
        self._writers[table].writerow(row)

    def write_json_fields(self, table, row, field_names):
        converted = dict(row)
        for name in field_names:
            if name in converted:
                converted[name] = json.dumps(converted[name], sort_keys=True)
        self.write(table, converted)

    def flush(self):
        for handle in self._handles.values():
            handle.flush()

    def write_clearance_failure(self, residual_state):
        path = os.path.join(self.run_directory, "clearance_failures.jsonl")
        with open(path, "a") as handle:
            handle.write(json.dumps(residual_state, sort_keys=True) + "\n")

    def close(self):
        for handle in self._handles.values():
            handle.close()
        self._handles = {}
        self._writers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
