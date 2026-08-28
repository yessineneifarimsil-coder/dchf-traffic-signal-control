"""Globally synchronized EXTEND/SWITCH signal executor."""

from __future__ import absolute_import


EXTEND = 0
SWITCH = 1
ACTION_NAMES = {EXTEND: "EXTEND", SWITCH: "SWITCH"}


class UnsupportedAsynchronousSemantics(ValueError):
    pass


def validate_synchronous_executor_config(executor_config):
    extend = int(executor_config["extend_duration_s"])
    switch = int(executor_config["switch_duration_s"])
    interval = int(executor_config["control_interval_s"])
    if executor_config.get("decision_clock") != "globally_synchronized":
        raise UnsupportedAsynchronousSemantics(
            "Only globally synchronized joint-decision semantics is implemented."
        )
    if extend != interval or switch != interval:
        raise UnsupportedAsynchronousSemantics(
            "Action durations differ (EXTEND={}, SWITCH={}); an explicit "
            "synchronization rule or event-driven MARL formulation is required.".format(
                extend, switch
            )
        )
    if int(executor_config["yellow_duration_s"]) + int(
        executor_config["switch_new_green_s"]
    ) != switch:
        raise ValueError("Yellow and new-green segments do not sum to SWITCH duration.")


class SynchronousSignalExecutor(object):
    def __init__(self, traci_module, config):
        self.traci = traci_module
        self.config = config
        self.executor_config = config["executor"]
        validate_synchronous_executor_config(self.executor_config)
        self.phase_map = config["network"]["phase_map"]
        self.tl_ids = list(config["network"]["traffic_lights"])
        self.current_phase = {tl_id: "H" for tl_id in self.tl_ids}
        self.green_elapsed = {tl_id: 0 for tl_id in self.tl_ids}
        self.decision_index = 0

    def initialize(self):
        for tl_id in self.tl_ids:
            self.traci.trafficlight.setPhase(tl_id, self.phase_map["H_GREEN"])
            self.traci.trafficlight.setPhaseDuration(
                tl_id, int(self.executor_config["control_interval_s"])
            )
            self.current_phase[tl_id] = "H"
            self.green_elapsed[tl_id] = 0
        self.decision_index = 0

    def _yellow_phase(self, old_phase):
        return self.phase_map[
            "H_TO_V_YELLOW" if old_phase == "H" else "V_TO_H_YELLOW"
        ]

    def _green_phase(self, logical_phase):
        return self.phase_map["H_GREEN" if logical_phase == "H" else "V_GREEN"]

    @staticmethod
    def _opposite(logical_phase):
        return "V" if logical_phase == "H" else "H"

    def execute(self, joint_actions, after_second=None):
        if len(joint_actions) != len(self.tl_ids):
            raise ValueError("Expected one action per traffic light.")
        actions = {tl_id: int(joint_actions[index]) for index, tl_id in enumerate(self.tl_ids)}
        if any(action not in ACTION_NAMES for action in actions.values()):
            raise ValueError("Actions must be EXTEND=0 or SWITCH=1.")

        yellow_s = int(self.executor_config["yellow_duration_s"])
        interval_s = int(self.executor_config["control_interval_s"])
        elapsed_at_decision = dict(self.green_elapsed)
        trace = []

        for second_offset in range(interval_s):
            states = {}
            for tl_id in self.tl_ids:
                action = actions[tl_id]
                if action == EXTEND:
                    states[tl_id] = self.current_phase[tl_id]
                    if second_offset == 0:
                        self.traci.trafficlight.setPhase(
                            tl_id, self._green_phase(self.current_phase[tl_id])
                        )
                        self.traci.trafficlight.setPhaseDuration(tl_id, interval_s)
                elif second_offset < yellow_s:
                    states[tl_id] = "Y"
                    if second_offset == 0:
                        self.traci.trafficlight.setPhase(
                            tl_id, self._yellow_phase(self.current_phase[tl_id])
                        )
                        self.traci.trafficlight.setPhaseDuration(tl_id, yellow_s)
                else:
                    new_phase = self._opposite(self.current_phase[tl_id])
                    states[tl_id] = new_phase
                    if second_offset == yellow_s:
                        self.traci.trafficlight.setPhase(
                            tl_id, self._green_phase(new_phase)
                        )
                        self.traci.trafficlight.setPhaseDuration(
                            tl_id, interval_s - yellow_s
                        )

            self.traci.simulationStep()
            actual_green_elapsed = {}
            for tl_id in self.tl_ids:
                if actions[tl_id] == EXTEND:
                    actual_green_elapsed[tl_id] = (
                        elapsed_at_decision[tl_id] + second_offset + 1
                    )
                elif second_offset < yellow_s:
                    actual_green_elapsed[tl_id] = 0
                else:
                    actual_green_elapsed[tl_id] = second_offset - yellow_s + 1
            callback_result = None
            if after_second is not None:
                callback_result = after_second(
                    second_offset, dict(states), actual_green_elapsed
                )
            trace.append(
                {
                    "second_offset": second_offset,
                    "states": states,
                    "actual_green_elapsed": actual_green_elapsed,
                    "callback": callback_result,
                }
            )

        for tl_id in self.tl_ids:
            if actions[tl_id] == EXTEND:
                self.green_elapsed[tl_id] += interval_s
            else:
                self.current_phase[tl_id] = self._opposite(self.current_phase[tl_id])
                self.green_elapsed[tl_id] = interval_s - yellow_s
        self.decision_index += 1
        return {
            "elapsed_seconds": interval_s,
            "actions": dict(actions),
            "action_names": {tl: ACTION_NAMES[action] for tl, action in actions.items()},
            "trace": trace,
            "current_phase": dict(self.current_phase),
            "green_elapsed": dict(self.green_elapsed),
        }
