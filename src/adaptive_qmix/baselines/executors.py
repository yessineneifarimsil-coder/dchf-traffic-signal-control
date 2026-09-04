"""One-second signal executors for the classical baselines.

Both executors present the same interface the adaptive SynchronousSignalExecutor
presents to AdaptiveTrafficEnvironment -- initialize(), execute(actions,
after_second), current_phase, green_elapsed -- so the environment's per-second
contract (ledger, teleport bookkeeping, reward sampling, detector sampling,
lane and phase logging, clearance reconciliation) is reused unchanged rather
than reimplemented. Only the timing authority differs, which is the whole point
of a baseline.

They advance exactly one second per call. That is what lets a pretimed plan be
represented exactly at 1 s resolution, and what lets the two intersections of
the pressure controller run on genuinely independent local clocks. The P-5
diagnostic does NOT use these: it uses the adaptive executor itself, because
matching QMIX's control authority means using QMIX's timing.

Block length does not affect any accumulated quantity: reward blocks sum
per-second delays, so a one-second block sums to the same total as a five-second
one.
"""

from __future__ import absolute_import

from .plans import local_second, state_at, validate_plan
from .pressure import local_pressures, preferred_phase


TIMING_PRETIMED = "pretimed_schedule"
TIMING_PRESSURE = "decentralised_pressure_min_green"
TIMING_SYNCHRONOUS = "synchronous_qmix_executor_3plus2"


class _OneSecondExecutor(object):
    """Shared plumbing: set the phases, step once, report what was shown."""

    timing_authority = None

    def __init__(self, traci_module, config):
        self.traci = traci_module
        self.config = config
        self.phase_map = config["network"]["phase_map"]
        self.tl_ids = list(config["network"]["traffic_lights"])
        self.current_phase = dict((tl_id, "H") for tl_id in self.tl_ids)
        self.green_elapsed = dict((tl_id, 0) for tl_id in self.tl_ids)
        self.decision_index = 0
        self.events = []

    def _phase_index(self, actual, logical):
        if actual == "H":
            return self.phase_map["H_GREEN"]
        if actual == "V":
            return self.phase_map["V_GREEN"]
        # A yellow is named by the green it terminates.
        return self.phase_map[
            "H_TO_V_YELLOW" if logical == "H" else "V_TO_H_YELLOW"
        ]

    def _apply(self, states):
        for tl_id in self.tl_ids:
            actual, logical = states[tl_id]
            self.traci.trafficlight.setPhase(
                tl_id, self._phase_index(actual, logical)
            )
            self.traci.trafficlight.setPhaseDuration(tl_id, 1)

    def _plan_second(self, simulation_time):
        """Return {tl: (actual, logical, green_elapsed_after_this_second)}."""
        raise NotImplementedError

    def execute(self, joint_actions=None, after_second=None):
        simulation_time = float(self.traci.simulation.getTime())
        decided = self._plan_second(simulation_time)
        states = dict(
            (tl_id, (decided[tl_id][0], decided[tl_id][1]))
            for tl_id in self.tl_ids
        )
        self._apply(states)
        self.traci.simulationStep()

        actual_states = dict(
            (tl_id, decided[tl_id][0]) for tl_id in self.tl_ids
        )
        actual_green_elapsed = dict(
            (tl_id, decided[tl_id][2]) for tl_id in self.tl_ids
        )
        for tl_id in self.tl_ids:
            self.current_phase[tl_id] = decided[tl_id][1]
            self.green_elapsed[tl_id] = decided[tl_id][2]
        callback_result = None
        if after_second is not None:
            callback_result = after_second(
                0, dict(actual_states), dict(actual_green_elapsed)
            )
        self.decision_index += 1
        return {
            "elapsed_seconds": 1,
            "actions": {},
            "action_names": {},
            "trace": [{
                "second_offset": 0,
                "states": dict(actual_states),
                "actual_green_elapsed": dict(actual_green_elapsed),
                "callback": callback_result,
            }],
            "current_phase": dict(self.current_phase),
            "green_elapsed": dict(self.green_elapsed),
        }


class PretimedScheduleExecutor(_OneSecondExecutor):
    """A fixed cycle per intersection, evaluated at its own offset.

    J1 carries offset 0 and starts its H green at t = 0. J2 carries Delta and
    is read at local time (t - Delta) mod C from t = 0 onward: it is a periodic
    steady-state schedule, so it starts wherever its own phase says, with no
    startup all-red and no warm-up inserted to make it begin at a segment
    boundary.
    """

    timing_authority = TIMING_PRETIMED

    def __init__(self, traci_module, config, plan=None, offsets=None):
        super(PretimedScheduleExecutor, self).__init__(traci_module, config)
        if plan is None:
            raise ValueError("A pretimed executor needs a plan.")
        validate_plan(plan)
        self.plan = dict(plan)
        # J1 defines the reference; only J2 carries the offset.
        self.offsets = dict(offsets) if offsets else {
            "J1": 0, "J2": int(plan["offset_s"]) % int(plan["cycle_s"])
        }
        for tl_id in self.tl_ids:
            self.offsets.setdefault(tl_id, 0)
        self._previous_actual = {}

    def initialize(self):
        states = {}
        for tl_id in self.tl_ids:
            local = local_second(self.plan, 0, self.offsets[tl_id])
            actual, logical, served = state_at(self.plan, local)
            states[tl_id] = (actual, logical)
            self.current_phase[tl_id] = logical
            self.green_elapsed[tl_id] = served
        self._apply(states)
        self.decision_index = 0
        self.events = []
        self._previous_actual = dict(
            (tl_id, states[tl_id][0]) for tl_id in self.tl_ids
        )

    def _plan_second(self, simulation_time):
        decided = {}
        for tl_id in self.tl_ids:
            local = local_second(
                self.plan, simulation_time, self.offsets[tl_id]
            )
            actual, logical, served = state_at(self.plan, local)
            decided[tl_id] = (actual, logical, 0 if actual == "Y" else served + 1)
            previous = self._previous_actual.get(tl_id)
            if previous is not None and actual != previous:
                # A real schedule transition, recorded as itself rather than
                # dressed up as a controller decision.
                self.events.append({
                    "time": float(simulation_time),
                    "intersection": tl_id,
                    "from_actual_phase": previous,
                    "to_actual_phase": actual,
                    "local_schedule_time_s": local,
                    "cycle_index": int(
                        (int(simulation_time) - self.offsets[tl_id])
                        // self.plan["cycle_s"]
                    ),
                    "cycle_s": self.plan["cycle_s"],
                    "offset_s": self.offsets[tl_id],
                })
            self._previous_actual[tl_id] = actual
        return decided


class CanonicalMaxPressureExecutor(_OneSecondExecutor):
    """Decentralised max pressure with a minimum green and a 3 s yellow.

    Each intersection keeps its own clock. Once a green has been served for at
    least g_min seconds, the local pressures are recomputed every second: a
    strictly greater opposing pressure starts a 3 s yellow, an equal one
    retains the current phase. After the yellow the new green must itself be
    served for g_min seconds before it can be replaced. There is no cycle and
    no shared decision instant, so J1 and J2 drift apart freely.
    """

    timing_authority = TIMING_PRESSURE

    def __init__(self, traci_module, config, data_source=None,
                 minimum_green_s=None, yellow_s=None, movement_pairs=None):
        super(CanonicalMaxPressureExecutor, self).__init__(
            traci_module, config
        )
        if data_source is None:
            raise ValueError("Max pressure needs a data source for lane counts.")
        self.source = data_source
        settings = config.get("baselines", {}).get(
            "canonical_operational_max_pressure", {}
        )
        self.minimum_green_s = int(
            settings.get("minimum_green_s", 10)
            if minimum_green_s is None else minimum_green_s
        )
        self.yellow_s = int(
            settings.get("yellow_duration_s", 3)
            if yellow_s is None else yellow_s
        )
        self.movement_pairs = movement_pairs
        self.yellow_remaining = dict((tl_id, 0) for tl_id in self.tl_ids)
        self.pending_phase = dict((tl_id, None) for tl_id in self.tl_ids)

    def initialize(self):
        states = {}
        for tl_id in self.tl_ids:
            self.current_phase[tl_id] = "H"
            self.green_elapsed[tl_id] = 0
            self.yellow_remaining[tl_id] = 0
            self.pending_phase[tl_id] = None
            states[tl_id] = ("H", "H")
        self._apply(states)
        self.decision_index = 0
        self.events = []

    def _plan_second(self, simulation_time):
        decided = {}
        for tl_id in self.tl_ids:
            if self.yellow_remaining[tl_id] > 0:
                decided[tl_id] = self._continue_yellow(tl_id)
                continue
            served = self.green_elapsed[tl_id]
            if served < self.minimum_green_s:
                # Still inside the minimum green: no decision is taken at all.
                decided[tl_id] = (
                    self.current_phase[tl_id], self.current_phase[tl_id],
                    served + 1,
                )
                continue
            decided[tl_id] = self._decide(tl_id, simulation_time, served)
        return decided

    def _continue_yellow(self, tl_id):
        self.yellow_remaining[tl_id] -= 1
        if self.yellow_remaining[tl_id] > 0:
            return ("Y", self.current_phase[tl_id], 0)
        # Last yellow second; the pending green takes over from the next one.
        return ("Y", self.current_phase[tl_id], 0)

    def _decide(self, tl_id, simulation_time, served):
        current = self.current_phase[tl_id]
        pressures = local_pressures(self.source, tl_id, self.movement_pairs)
        preferred = preferred_phase(pressures, current)
        switching = preferred != current
        self.events.append({
            "time": float(simulation_time),
            "intersection": tl_id,
            "controller_decision_index": self.decision_index,
            "current_phase": current,
            "green_elapsed_s": served,
            "pressure_H": pressures["H"],
            "pressure_V": pressures["V"],
            "preferred_phase": preferred,
            "decision": "SWITCH" if switching else "EXTEND",
            "timing_authority": self.timing_authority,
        })
        if not switching:
            return (current, current, served + 1)
        self.yellow_remaining[tl_id] = self.yellow_s
        self.pending_phase[tl_id] = preferred
        return self._continue_yellow(tl_id)

    def execute(self, joint_actions=None, after_second=None):
        result = super(CanonicalMaxPressureExecutor, self).execute(
            joint_actions, after_second
        )
        # Promote a completed yellow to its new green, after the second that
        # showed the last yellow has been simulated and logged.
        for tl_id in self.tl_ids:
            if self.pending_phase[tl_id] is not None and (
                self.yellow_remaining[tl_id] == 0
            ):
                self.current_phase[tl_id] = self.pending_phase[tl_id]
                self.green_elapsed[tl_id] = 0
                self.pending_phase[tl_id] = None
        result["current_phase"] = dict(self.current_phase)
        result["green_elapsed"] = dict(self.green_elapsed)
        return result
