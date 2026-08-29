"""SUMO environment implementing the synchronous qualification contract."""

from __future__ import absolute_import

import os

import numpy as np

from .coordination import VirtualDetectorTracker
from .ledger import VehicleLedger, reconcile_scheduled_outcomes
from .logging import LANE_LOG_DECISION, LANE_LOG_FULL, LANE_LOG_MODES
from .observation import SymmetricObservationBuilder
from .reward import NetworkDelayReward, legacy_waiting_state
from .signal_executor import SynchronousSignalExecutor
from .traci_access import DEFAULT_MODE, MODES, create_data_source
from .traffic import read_manifest_csv


class EnvironmentFailure(RuntimeError):
    pass


def build_sumo_command(config, repository_root, route_xml_path, tripinfo_path,
                       sumo_seed, gui=False):
    binary = "sumo-gui" if gui else "sumo"
    network_path = os.path.join(repository_root, config["network"]["path"])
    return [
        binary,
        "-n", network_path,
        "-r", os.path.abspath(route_xml_path),
        "--begin", "0",
        "--end", str(config["demand"]["maximum_simulation_s"]),
        "--step-length", "1",
        "--seed", str(int(sumo_seed)),
        "--route-steps", "0",
        "--time-to-teleport", "-1",
        "--tripinfo-output", os.path.abspath(tripinfo_path),
        "--tripinfo-output.write-unfinished", "true",
        "--no-step-log", "true",
        "--duration-log.statistics", "true",
    ]


class AdaptiveTrafficEnvironment(object):
    """One environment transition is one synchronized joint-decision interval."""

    def __init__(
        self,
        traci_module,
        config,
        repository_root,
        manifest_csv_path,
        route_xml_path,
        tripinfo_path,
        sumo_seed,
        gui=False,
        logger=None,
        traci_access_mode=DEFAULT_MODE,
        lane_state_logging=LANE_LOG_FULL,
    ):
        if traci_access_mode not in MODES:
            raise ValueError(
                "Unknown TraCI access mode {!r}; expected one of {}.".format(
                    traci_access_mode, MODES
                )
            )
        if lane_state_logging not in LANE_LOG_MODES:
            raise ValueError(
                "Unknown lane-state logging mode {!r}; expected one of {}.".format(
                    lane_state_logging, LANE_LOG_MODES
                )
            )
        self.traci_access_mode = traci_access_mode
        self.lane_state_logging = lane_state_logging
        self.traci = traci_module
        self.config = config
        self.repository_root = os.path.abspath(repository_root)
        self.manifest_csv_path = manifest_csv_path
        self.route_xml_path = route_xml_path
        self.tripinfo_path = tripinfo_path
        self.sumo_seed = int(sumo_seed)
        self.gui = bool(gui)
        self.logger = logger
        self.connection_open = False
        self.episode_index = None
        self.network_reward_total = 0.0
        self.active_stopped_total = 0
        self.pending_due_total = 0
        self.legacy_waiting_integral = 0.0
        self.legacy_waiting_samples = 0

    def reset(self, episode_index=0):
        if self.connection_open:
            self.close()
        command = build_sumo_command(
            self.config,
            self.repository_root,
            self.route_xml_path,
            self.tripinfo_path,
            self.sumo_seed,
            self.gui,
        )
        self.traci.start(command)
        self.connection_open = True
        self.episode_index = int(episode_index)

        # A new episode is a new SUMO process and a new TraCI connection, so the
        # data source is rebuilt and its subscriptions re-established here; no
        # subscription state can survive from the previous episode.
        self.lane_log_ids = sorted(
            self.config["observation"]["expected_lane_lengths_m"]
        )
        self.source = create_data_source(self.traci, self.traci_access_mode)
        self.source.begin_episode(self.lane_log_ids)

        records = read_manifest_csv(self.manifest_csv_path)
        self.ledger = VehicleLedger(records)
        self.executor = SynchronousSignalExecutor(self.traci, self.config)
        self.observations = SymmetricObservationBuilder(
            self.traci, self.config, self.source
        )
        self.reward = NetworkDelayReward(self.source, self.ledger)
        self.executor.initialize()
        self.observations.validate_runtime_schema()
        self.observations.reset_history()

        detector_position = float(
            self.config["coordination"]["detector_position_m"]
        )
        # E1 lanes are the eastbound J1 -> J2 central approach.
        self.detector = VirtualDetectorTracker(
            self.source, ["E1_0", "E1_1"], detector_position
        )
        self.previous_actual_phase = {"J1": "H", "J2": "H"}
        # Last actually-served green state, used to attribute red time during
        # the yellow seconds, when previous_actual_phase is itself "Y".
        self.last_green_phase = {"J1": "H", "J2": "H"}
        self.red_elapsed = {
            "J1": {"H": 0, "V": 0},
            "J2": {"H": 0, "V": 0},
        }
        self.network_reward_total = 0.0
        self.active_stopped_total = 0
        self.pending_due_total = 0
        self.legacy_waiting_integral = 0.0
        self.legacy_waiting_samples = 0

        local, state, raw = self.observations.build(
            self.executor.current_phase, self.executor.green_elapsed
        )
        return local, state, {"raw_observations": raw, "time": self.time}

    @property
    def time(self):
        return float(self.traci.simulation.getTime())

    def _teleport_ids(self, method_name):
        simulation = self.traci.simulation
        method = getattr(simulation, method_name, None)
        return [] if method is None else list(method())

    def _lane_log_due(self, second_offset):
        """True on the seconds whose lane state is written to the log.

        Decision cadence writes the last second of each joint-decision block,
        which is exactly the instant the next observation is built, so the
        reduced log is a strict timestamp subset of the full one.
        """
        if self.lane_state_logging == LANE_LOG_FULL:
            return True
        interval = int(self.config["executor"]["control_interval_s"])
        return int(second_offset) == interval - 1

    def _lane_rows(self, simulation_time):
        rows = []
        for lane_id in self.lane_log_ids:
            rows.append(
                {
                    "time": float(simulation_time),
                    "lane": lane_id,
                    "queue": int(self.source.lane_halting_number(lane_id)),
                    "vehicle_count": int(
                        self.source.lane_vehicle_number(lane_id)
                    ),
                    "occupancy": float(
                        self.source.lane_occupancy(lane_id)
                    ) / 100.0,
                    "mean_speed": float(
                        self.source.lane_mean_speed(lane_id)
                    ),
                }
            )
        return rows

    def _after_second(self, second_offset, phase_states, actual_green_elapsed):
        simulation_time = self.time
        departed = list(self.traci.simulation.getDepartedIDList())
        # Subscribe newly inserted vehicles before refreshing the per-second
        # view, so a vehicle inserted this second contributes its first second
        # of reward, waiting, arrival and detector state exactly as the getter
        # path does.
        self.source.note_departures(departed)
        self.source.refresh()
        arrived = list(self.traci.simulation.getArrivedIDList())
        self.ledger.mark_departed(departed, simulation_time)
        self.ledger.mark_arrived(arrived, simulation_time)
        self.ledger.mark_teleport_start(
            self._teleport_ids("getStartingTeleportIDList")
        )
        self.ledger.mark_teleport_end(
            self._teleport_ids("getEndingTeleportIDList")
        )
        active_ids = list(self.source.vehicle_ids())
        self.ledger.assert_active_consistency(active_ids)

        arrival_events = self.observations.update_arrivals_one_second()
        reward_row = self.reward.sample_second(simulation_time)
        if simulation_time <= float(self.config["demand"]["generation_end_s"]):
            self.legacy_waiting_integral += float(legacy_waiting_state(self.source))
            self.legacy_waiting_samples += 1

        detector_events = self.detector.sample(
            simulation_time, phase_states["J2"], phase_states["J1"]
        )
        lane_rows = (
            self._lane_rows(simulation_time)
            if self.logger is not None and self._lane_log_due(second_offset)
            else []
        )
        if self.logger is not None:
            self.logger.write("reward_seconds", reward_row)
            for lane_row in lane_rows:
                self.logger.write("lane_states", lane_row)
            for event in detector_events:
                crossing = dict(event)
                crossing["intersection"] = (
                    "J1" if event["event"] == "UPSTREAM_RELEASE" else "J2"
                )
                crossing["approach"] = "H_WESTBOUND_TO_EASTBOUND"
                self.logger.write("vehicle_crossings", crossing)
        # Phase and red-duration bookkeeping is state, not logging: it must
        # advance on every simulated second whether or not a logger is
        # attached, otherwise the starvation counters depend on log settings.
        for intersection, actual in sorted(phase_states.items()):
            previous = self.previous_actual_phase[intersection]
            green_start = actual in ("H", "V") and actual != previous
            green_end = previous in ("H", "V") and actual != previous
            if actual == "H":
                self.red_elapsed[intersection]["H"] = 0
                self.red_elapsed[intersection]["V"] += 1
                self.last_green_phase[intersection] = "H"
            elif actual == "V":
                self.red_elapsed[intersection]["V"] = 0
                self.red_elapsed[intersection]["H"] += 1
                self.last_green_phase[intersection] = "V"
            elif self.last_green_phase[intersection] == "H":
                # Amber terminating H: the opposite approach is still red.
                # Keyed on the last green rather than on previous_actual_phase,
                # which is already "Y" from the second yellow second onward and
                # previously left both counters frozen for those seconds.
                self.red_elapsed[intersection]["V"] += 1
            else:
                self.red_elapsed[intersection]["H"] += 1
            if self.logger is not None:
                self.logger.write(
                    "signal_phases",
                    {
                        "time": simulation_time,
                        "intersection": intersection,
                        "actual_phase": actual,
                        "logical_green_phase": self.executor.current_phase[intersection],
                        "green_elapsed_s": actual_green_elapsed[intersection],
                        "yellow": actual == "Y",
                        "green_start": green_start,
                        "green_end": green_end,
                        "H_red_elapsed_s": self.red_elapsed[intersection]["H"],
                        "V_red_elapsed_s": self.red_elapsed[intersection]["V"],
                    },
                )
            self.previous_actual_phase[intersection] = actual
        return {
            "time": simulation_time,
            "departed": departed,
            "arrived": arrived,
            "active_ids": active_ids,
            "arrival_events": arrival_events,
            "detector_events": detector_events,
            "reward": reward_row,
        }

    def step(self, joint_actions, budget_truncated=False):
        if not self.connection_open:
            raise EnvironmentFailure("reset() must be called before step().")
        self.reward.reset_block()
        start_time = self.time
        execution = self.executor.execute(
            joint_actions, after_second=self._after_second
        )
        block_reward = self.reward.finish_block()
        self.network_reward_total += block_reward["reward"]
        self.active_stopped_total += block_reward["active_stopped_vehicle_seconds"]
        self.pending_due_total += block_reward["pending_due_vehicle_seconds"]

        active_ids = list(self.traci.vehicle.getIDList())
        min_expected = int(self.traci.simulation.getMinExpectedNumber())
        terminated = self.ledger.is_reconciled_clear(
            self.time, active_ids, min_expected
        )
        timeout_truncated = (
            not terminated
            and self.time >= float(self.config["demand"]["maximum_simulation_s"])
        )
        local, state, raw = self.observations.build(
            self.executor.current_phase, self.executor.green_elapsed
        )
        info = {
            "start_time": start_time,
            "end_time": self.time,
            "elapsed_seconds": float(execution["elapsed_seconds"]),
            "terminated": bool(terminated),
            "budget_truncated": bool(budget_truncated),
            "timeout_truncated": bool(timeout_truncated),
            "failure_truncated": False,
            "reward_components": block_reward,
            "execution": execution,
            "raw_observations": raw,
            "ledger": self.ledger.snapshot(self.time, active_ids, min_expected),
        }
        return local, state, block_reward["reward"], terminated, info

    def episode_summary(self, status, budget_truncated=False,
                        timeout_truncated=False):
        active_ids = list(self.traci.vehicle.getIDList())
        min_expected = int(self.traci.simulation.getMinExpectedNumber())
        ledger_snapshot = self.ledger.snapshot(self.time, active_ids, min_expected)
        reconciliation = reconcile_scheduled_outcomes(self.ledger)
        if status == "CLEARED" and not reconciliation["valid"]:
            raise EnvironmentFailure("A cleared episode has unreconciled vehicle IDs.")
        legacy_average = (
            self.legacy_waiting_integral / float(self.legacy_waiting_samples)
            if self.legacy_waiting_samples else float("nan")
        )
        summary = dict(ledger_snapshot)
        summary.update(
            {
                "episode_index": self.episode_index,
                "status": str(status),
                "start_time": 0.0,
                "end_time": self.time,
                "elapsed_s": self.time,
                "network_reward": self.network_reward_total,
                "active_stopped_vehicle_seconds": self.active_stopped_total,
                "pending_due_vehicle_seconds": self.pending_due_total,
                "legacy_waiting_state_integral": self.legacy_waiting_integral,
                "legacy_waiting_state_time_average": legacy_average,
                "budget_truncated": bool(budget_truncated),
                "timeout_truncated": bool(timeout_truncated),
                "clearance_failure": status == "CLEARANCE_FAILURE",
                # Engineering transport diagnostic, normally zero. It records
                # how many active vehicles needed their TraCI subscription
                # re-established (see traci_access). It is not a scientific
                # quantity and never influences control, reward or metrics.
                "transport_healed_subscriptions": int(
                    getattr(self.source, "healed_subscriptions", 0)
                ),
                "missing_vehicle_ids": reconciliation["missing_ids"],
                "overlapping_vehicle_ids": reconciliation["overlap_ids"],
            }
        )
        return summary

    def complete_residual_state(self):
        active_ids = sorted(self.traci.vehicle.getIDList())
        min_expected = int(self.traci.simulation.getMinExpectedNumber())
        return {
            "episode_index": self.episode_index,
            "time": self.time,
            "ledger_snapshot": self.ledger.snapshot(
                self.time, active_ids, min_expected
            ),
            "active_ids": active_ids,
            "active_ledger_ids": sorted(self.ledger.active_ids_from_ledger()),
            "pending_due_ids": sorted(self.ledger.pending_due_ids(self.time)),
            "scheduled_future_ids": sorted(
                self.ledger.scheduled_future_ids(self.time)
            ),
            "completed_ids": sorted(self.ledger.completed_at),
            "exceptional_outcomes": dict(self.ledger.exceptional),
            "teleport_started_ids": sorted(self.ledger.teleport_started),
            "teleport_ended_ids": sorted(self.ledger.teleport_ended),
            "min_expected_number": min_expected,
        }

    def close(self):
        if self.connection_open:
            self.traci.close()
            self.connection_open = False
