"""New classical comparators on the frozen one-second executor plumbing (nothing frozen is modified).

Both classes subclass the frozen adaptive_qmix.baselines.executors._OneSecondExecutor, so the frozen
environment's per-second contract (ledger, logging, clearance) is reused unchanged, exactly as for the frozen
pretimed and max-pressure executors. Same phase model: two greens H and V, a 3 s yellow named by the green it
terminates, 1 s clock, each intersection on its own state.

ActuatedGapOutExecutor (comparator A2), per intersection:
  * minimum green MIN_GREEN_S = 7 s on both phases (never shortened);
  * detection: a virtual presence detector covering the last `zone_m` metres before the stop line of every
    incoming lane of the green phase (vehicle lane position >= lane length - zone_m). A second with a vehicle
    in the zone resets the gap timer; a second without one adds 1 s;
  * a conflicting call exists when any incoming lane of the red phase holds a vehicle (whole lane, i.e.
    locking memory of a vehicle that arrived on red);
  * once the minimum green is served, the green ends (3 s yellow, then the other green) when a conflicting
    call exists AND (the gap timer reached `gap_s` (gap-out) OR the green reached its maximum (max-out));
  * no conflicting call: the green rests (no recall, no forced cycle);
  * no pedestrian phase, no coordination between J1 and J2.
  Parameters (tuned by a small grid on design seeds, comparator_search.py): gap_s, max_green_H_s,
  max_green_V_s, zone_m.

TimeOfDayScheduleExecutor (comparator A3, profile R3): a sequence of pretimed plans, plan k from
period_start[k]. Transition ("dwell" method, fixed here before any run):
  * a new period never interrupts a cycle: each intersection finishes its current cycle of the old plan
    (which ends with the V->H yellow);
  * J1 then starts the new plan at local time 0 (H green) at that instant t1;
  * J2, after finishing its own old cycle, holds H green (dwell) until its new local time
    (t - t1 - offset_new) mod C_new is 0, then follows the new plan. The dwell lasts at most C_new - 1 s and
    only extends the main-axis green;
  * if the old cycle of an intersection ends after a later period has already started, it goes directly to
    the latest plan due.
"""
from __future__ import absolute_import

from adaptive_qmix.baselines.executors import _OneSecondExecutor
from adaptive_qmix.baselines.plans import state_at, validate_plan

MIN_GREEN_S = 7
YELLOW_S = 3
TIMING_ACTUATED = "actuated_gap_out_min_green_7"
TIMING_TIME_OF_DAY = "time_of_day_pretimed_dwell_transition"
OTHER = {"H": "V", "V": "H"}


class ActuatedGapOutExecutor(_OneSecondExecutor):
    timing_authority = TIMING_ACTUATED

    def __init__(self, traci_module, config, data_source=None, gap_s=3, max_green_H_s=45, max_green_V_s=25,
                 zone_m=40.0, minimum_green_s=MIN_GREEN_S, yellow_s=YELLOW_S):
        super(ActuatedGapOutExecutor, self).__init__(traci_module, config)
        if data_source is None:
            raise ValueError("The actuated controller needs a data source.")
        if int(minimum_green_s) < MIN_GREEN_S:
            raise ValueError("The actuated comparator keeps a 7 s minimum green.")
        self.source = data_source
        self.gap_s = int(gap_s)
        self.max_green = {"H": int(max_green_H_s), "V": int(max_green_V_s)}
        if min(self.max_green.values()) < int(minimum_green_s) or self.gap_s < 1:
            raise ValueError("Maximum greens must be >= the minimum green and the gap >= 1 s.")
        self.zone_m = float(zone_m)
        self.minimum_green_s = int(minimum_green_s)
        self.yellow_s = int(yellow_s)
        lanes = config["observation"]["lanes"]
        self.lanes_in = dict((tl, {"H": list(lanes[tl]["H_in"]), "V": list(lanes[tl]["V_in"])}) for tl in self.tl_ids)
        self.lane_length = dict((k, float(v)) for k, v in config["observation"]["expected_lane_lengths_m"].items())
        self.yellow_remaining = dict((tl, 0) for tl in self.tl_ids)
        self.pending_phase = dict((tl, None) for tl in self.tl_ids)
        self.gap_timer = dict((tl, 0) for tl in self.tl_ids)

    def parameters(self):
        return {"gap_s": self.gap_s, "max_green_H_s": self.max_green["H"], "max_green_V_s": self.max_green["V"],
                "zone_m": self.zone_m, "minimum_green_s": self.minimum_green_s, "yellow_s": self.yellow_s}

    def initialize(self):
        states = {}
        for tl in self.tl_ids:
            self.current_phase[tl] = "H"
            self.green_elapsed[tl] = 0
            self.yellow_remaining[tl] = 0
            self.pending_phase[tl] = None
            self.gap_timer[tl] = 0
            states[tl] = ("H", "H")
        self._apply(states)
        self.decision_index = 0
        self.events = []

    def _occupied_zone(self, tl, phase):
        for lane in self.lanes_in[tl][phase]:
            limit = self.lane_length[lane] - self.zone_m
            for vehicle in self.source.lane_vehicle_ids(lane):
                if float(self.source.vehicle_lane_position(vehicle)) >= limit:
                    return True
        return False

    def _call(self, tl, phase):
        return any(int(self.source.lane_vehicle_number(lane)) > 0 for lane in self.lanes_in[tl][phase])

    def _plan_second(self, simulation_time):
        decided = {}
        for tl in self.tl_ids:
            current = self.current_phase[tl]
            if self.yellow_remaining[tl] > 0:
                self.yellow_remaining[tl] -= 1
                decided[tl] = ("Y", current, 0)
                continue
            served = self.green_elapsed[tl]
            self.gap_timer[tl] = 0 if self._occupied_zone(tl, current) else self.gap_timer[tl] + 1
            if served < self.minimum_green_s:
                decided[tl] = (current, current, served + 1)
                continue
            call = self._call(tl, OTHER[current])
            reason = None
            if call and served >= self.max_green[current]:
                reason = "max_out"
            elif call and self.gap_timer[tl] >= self.gap_s:
                reason = "gap_out"
            if reason is None:
                decided[tl] = (current, current, served + 1)
                continue
            self.events.append({"time": float(simulation_time), "intersection": tl, "current_phase": current,
                                "green_elapsed_s": served, "decision": "SWITCH", "reason": reason,
                                "gap_timer_s": self.gap_timer[tl], "timing_authority": self.timing_authority})
            self.yellow_remaining[tl] = self.yellow_s - 1
            self.pending_phase[tl] = OTHER[current]
            decided[tl] = ("Y", current, 0)
        return decided

    def execute(self, joint_actions=None, after_second=None):
        result = super(ActuatedGapOutExecutor, self).execute(joint_actions, after_second)
        for tl in self.tl_ids:
            if self.pending_phase[tl] is not None and self.yellow_remaining[tl] == 0:
                self.current_phase[tl] = self.pending_phase[tl]
                self.green_elapsed[tl] = 0
                self.gap_timer[tl] = 0
                self.pending_phase[tl] = None
        result["current_phase"] = dict(self.current_phase)
        result["green_elapsed"] = dict(self.green_elapsed)
        return result


class TimeOfDayScheduleExecutor(_OneSecondExecutor):
    timing_authority = TIMING_TIME_OF_DAY

    def __init__(self, traci_module, config, periods=None):
        super(TimeOfDayScheduleExecutor, self).__init__(traci_module, config)
        if not periods:
            raise ValueError("A time-of-day executor needs periods [(start_s, plan), ...].")
        periods = sorted((int(start), dict(plan)) for start, plan in periods)
        if periods[0][0] != 0:
            raise ValueError("The first period must start at 0 s.")
        for _start, plan in periods:
            validate_plan(plan)
        self.periods = periods
        self.tl_index = dict((tl, i) for i, tl in enumerate(self.tl_ids))
        self.active = dict((tl, 0) for tl in self.tl_ids)        # index of the plan each intersection runs
        self.origin = dict((tl, 0) for tl in self.tl_ids)        # time of local 0 of the active plan
        self.dwell = dict((tl, False) for tl in self.tl_ids)
        self.j1_switch = {}                                      # plan index -> t1 (J1 start of that plan)
        self.served = dict((tl, 0) for tl in self.tl_ids)
        self.shown = {}

    def due_index(self, t):
        index = 0
        for k, (start, _plan) in enumerate(self.periods):
            if t >= start:
                index = k
        return index

    def _offset(self, tl, plan):
        return 0 if self.tl_index[tl] == 0 else int(plan["offset_s"]) % int(plan["cycle_s"])

    def initialize(self):
        plan = self.periods[0][1]
        states = {}
        for tl in self.tl_ids:
            self.active[tl] = 0
            self.origin[tl] = self._offset(tl, plan)
            self.dwell[tl] = False
            local = (0 - self.origin[tl]) % plan["cycle_s"]
            actual, logical, served = state_at(plan, local)
            states[tl] = (actual, logical)
            self.current_phase[tl] = logical
            self.green_elapsed[tl] = served
            self.served[tl] = served
            self.shown[tl] = actual
        self.j1_switch = {0: 0}
        self._apply(states)
        self.decision_index = 0
        self.events = []

    def _elapsed(self, tl, actual):
        """Seconds of the current green including this one (0 during a yellow), from the shown states."""
        if actual == "Y":
            self.served[tl] = 0
        elif self.shown.get(tl) == actual:
            self.served[tl] += 1
        else:
            self.served[tl] = 1
        self.shown[tl] = actual
        return self.served[tl]

    def _plan_second(self, simulation_time):
        t = int(simulation_time)
        decided = {}
        for tl in self.tl_ids:
            plan = self.periods[self.active[tl]][1]
            due = self.due_index(t)
            local = (t - self.origin[tl]) % plan["cycle_s"]
            if not self.dwell[tl] and due != self.active[tl] and local == 0:
                # The old cycle has just ended (the next second would be its H green): change plan.
                self.events.append({"time": float(t), "intersection": tl, "from_plan": self.active[tl],
                                    "to_plan": due, "timing_authority": self.timing_authority})
                self.active[tl] = due
                plan = self.periods[due][1]
                if self.tl_index[tl] == 0:
                    self.origin[tl] = t
                    self.j1_switch[due] = t
                else:
                    self.dwell[tl] = True
            if self.dwell[tl]:
                t1 = self.j1_switch.get(self.active[tl])
                if t1 is not None and (t - t1 - int(plan["offset_s"])) % plan["cycle_s"] == 0:
                    self.dwell[tl] = False
                    self.origin[tl] = t
                else:
                    decided[tl] = ("H", "H", self._elapsed(tl, "H"))
                    continue
            local = (t - self.origin[tl]) % plan["cycle_s"]
            actual, logical, _served = state_at(plan, local)
            decided[tl] = (actual, logical, self._elapsed(tl, actual))
        return decided
