"""Batch S2: classical and pressure baselines.

Everything here runs on synthetic state or pure plan arithmetic, so each
assertion is hand-computable and no SUMO run is needed to prove the
controllers, the grids or the selection protocol correct.
"""

from __future__ import absolute_import

import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from .common import REPOSITORY_ROOT, config_copy

from adaptive_qmix.baselines import integrity, plans, pressure, search
from adaptive_qmix.baselines.executors import (
    CanonicalMaxPressureExecutor,
    PretimedScheduleExecutor,
    TIMING_PRESSURE,
    TIMING_PRETIMED,
    TIMING_SYNCHRONOUS,
)
from adaptive_qmix.baselines.runner import (
    BaselineEnvironment,
    BaselineError,
    OPTIMIZED_FIXED_TIMING,
    SIMULTANEOUS_FIXED_TIME,
    _baseline_manifest,
    _log_matched_decisions,
    run_baseline,
    BASELINE_CONTROLLERS,
    CANONICAL_MAX_PRESSURE,
    DIAGNOSTIC_CONTROLLERS,
    LEARNED_METHODS,
    MATCHED_INTERVAL_PRESSURE_P5,
    MatchedIntervalPressurePolicy,
    OFFICIAL_CLASSICAL_CONTROLLERS,
    TIMING_AUTHORITY,
    controller_interpretation,
)
from adaptive_qmix.behavior_analysis import (
    NOT_APPLICABLE,
    WINDOW_FULL_EPISODE,
    derive_behavior_metrics,
)
from adaptive_qmix.config import load_config
from adaptive_qmix.environment import AdaptiveTrafficEnvironment
from adaptive_qmix.ledger import VehicleLedger
from adaptive_qmix.metrics import scheduled_demand_metrics
from adaptive_qmix.traffic import generate_manifest_records, write_manifest
from adaptive_qmix.signal_executor import (
    EXTEND,
    SWITCH,
    SynchronousSignalExecutor,
)

from . import test_scientific_instrumentation as instrumentation

NETWORK_PATH = os.path.join(
    REPOSITORY_ROOT, "sumo_scenarios", "two_intersections", "corridor_2x2",
    "corridor_2x2.net.xml",
)
BASELINE_CONFIG_PATH = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)
QUALIFICATION_CONFIG_PATH = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
)


class FakeSource(object):
    """A lane-count view that records which accessor a controller used."""

    def __init__(self, counts):
        self.counts = dict(counts)
        self.accessors_used = []

    def lane_vehicle_number(self, lane_id):
        self.accessors_used.append(("lane_vehicle_number", lane_id))
        return self.counts.get(lane_id, 0)

    def lane_halting_number(self, lane_id):
        self.accessors_used.append(("lane_halting_number", lane_id))
        raise AssertionError(
            "max pressure must never read the halting queue count"
        )

    def lane_occupancy(self, lane_id):
        self.accessors_used.append(("lane_occupancy", lane_id))
        raise AssertionError("max pressure must never read occupancy")


class FakeTrafficLight(object):
    def __init__(self):
        self.phases = {}
        self.durations = {}
        self.history = []

    def setPhase(self, tl_id, index):
        self.phases[tl_id] = index
        self.history.append((tl_id, index))

    def setPhaseDuration(self, tl_id, duration):
        self.durations[tl_id] = duration


class FakeSimulation(object):
    def __init__(self):
        self.time = 0.0

    def getTime(self):
        return self.time


class FakeTraci(object):
    """Just enough TraCI for an executor: phases and a clock."""

    def __init__(self):
        self.trafficlight = FakeTrafficLight()
        self.simulation = FakeSimulation()
        self.steps = 0

    def simulationStep(self):
        self.steps += 1
        self.simulation.time += 1.0


def drive(executor, traci_module, seconds):
    """Run an executor for a number of seconds, collecting the shown states."""
    shown = []

    def record(second_offset, states, green_elapsed):
        shown.append((traci_module.simulation.time - 1.0, dict(states),
                      dict(green_elapsed)))
        return None

    executor.initialize()
    for _ in range(seconds):
        executor.execute(None, after_second=record)
    return shown


def phase_string(shown, intersection):
    return "".join(states[intersection] for _time, states, _e in shown)


class SimultaneousPlanTests(unittest.TestCase):
    """S2-B: the reference plan is exactly 90 / 42 / 3 / 42 / 3."""

    def setUp(self):
        self.config = config_copy()
        self.plan = plans.simultaneous_plan()

    def test_the_plan_parameters_are_exact(self):
        self.assertEqual(self.plan["cycle_s"], 90)
        self.assertEqual(self.plan["green_H_s"], 42)
        self.assertEqual(self.plan["green_V_s"], 42)
        self.assertEqual(self.plan["yellow_s"], 3)
        self.assertEqual(self.plan["offset_s"], 0)

    def test_every_complete_cycle_has_the_exact_second_counts(self):
        traci_module = FakeTraci()
        executor = PretimedScheduleExecutor(
            traci_module, self.config, plan=self.plan
        )
        shown = drive(executor, traci_module, 270)
        for intersection in ("J1", "J2"):
            sequence = phase_string(shown, intersection)
            for cycle in range(3):
                block = sequence[cycle * 90:(cycle + 1) * 90]
                self.assertEqual(block.count("H"), 42, intersection)
                self.assertEqual(block.count("V"), 42, intersection)
                self.assertEqual(block.count("Y"), 6, intersection)
                # H -> yellow -> V -> yellow, in that order and nowhere else.
                self.assertEqual(
                    block, "H" * 42 + "Y" * 3 + "V" * 42 + "Y" * 3, intersection
                )

    def test_both_intersections_begin_h_green_together_at_zero(self):
        traci_module = FakeTraci()
        executor = PretimedScheduleExecutor(
            traci_module, self.config, plan=self.plan
        )
        shown = drive(executor, traci_module, 90)
        self.assertEqual(phase_string(shown, "J1"), phase_string(shown, "J2"))
        self.assertEqual(shown[0][1], {"J1": "H", "J2": "H"})

    def test_the_two_yellows_use_their_own_phase_indices(self):
        """An H->V yellow is not the same signal state as a V->H yellow."""
        traci_module = FakeTraci()
        executor = PretimedScheduleExecutor(
            traci_module, self.config, plan=self.plan
        )
        drive(executor, traci_module, 90)
        phase_map = self.config["network"]["phase_map"]
        indices = set(
            index for tl_id, index in traci_module.trafficlight.history
            if tl_id == "J1"
        )
        self.assertEqual(indices, {
            phase_map["H_GREEN"], phase_map["H_TO_V_YELLOW"],
            phase_map["V_GREEN"], phase_map["V_TO_H_YELLOW"],
        })

    def test_the_plan_is_not_routed_through_the_five_second_executor(self):
        traci_module = FakeTraci()
        executor = PretimedScheduleExecutor(
            traci_module, self.config, plan=self.plan
        )
        executor.initialize()
        result = executor.execute(None)
        self.assertEqual(result["elapsed_seconds"], 1)
        self.assertEqual(executor.timing_authority, TIMING_PRETIMED)


class FixedOffsetTests(unittest.TestCase):
    """S2-C: Delta = t^H,start_J2 - t^H,start_J1 (mod 90)."""

    def setUp(self):
        self.config = config_copy()

    def _h_start_second(self, shown, intersection):
        """First second at which this signal shows a fresh H green."""
        previous = None
        for index, (_time, states, _elapsed) in enumerate(shown):
            actual = states[intersection]
            if actual == "H" and previous != "H":
                return index
            previous = actual
        raise AssertionError("no H green start found")

    def test_a_positive_offset_makes_j2_follow_j1(self):
        plan = plans.fixed_offset_plan(20)
        traci_module = FakeTraci()
        executor = PretimedScheduleExecutor(traci_module, self.config, plan=plan)
        shown = drive(executor, traci_module, 200)
        j1_start = self._h_start_second(shown, "J1")
        j2_start = self._h_start_second(shown, "J2")
        self.assertEqual(j1_start, 0)
        self.assertEqual(j2_start, 20)
        self.assertEqual((j2_start - j1_start) % 90, 20)

    def test_offset_zero_reproduces_the_simultaneous_timing_exactly(self):
        traci_a = FakeTraci()
        traci_b = FakeTraci()
        simultaneous = PretimedScheduleExecutor(
            traci_a, self.config, plan=plans.simultaneous_plan()
        )
        zero_offset = PretimedScheduleExecutor(
            traci_b, self.config, plan=plans.fixed_offset_plan(0)
        )
        shown_a = drive(simultaneous, traci_a, 180)
        shown_b = drive(zero_offset, traci_b, 180)
        self.assertEqual(
            [states for _t, states, _e in shown_a],
            [states for _t, states, _e in shown_b],
        )

    def test_all_ninety_offset_candidates_exist_and_are_distinct(self):
        candidates = plans.fixed_offset_candidates()
        self.assertEqual(len(candidates), 90)
        self.assertEqual(
            sorted(plan["offset_s"] for plan in candidates), list(range(90))
        )
        for plan in candidates:
            self.assertEqual(plan["cycle_s"], 90)
            self.assertEqual(plan["green_H_s"], 42)
            self.assertEqual(plan["green_V_s"], 42)

    def test_j2_is_a_steady_state_schedule_with_no_startup_all_red(self):
        """At t = 0 J2 sits wherever its own phase says, not in an all-red."""
        plan = plans.fixed_offset_plan(45)
        traci_module = FakeTraci()
        executor = PretimedScheduleExecutor(traci_module, self.config, plan=plan)
        shown = drive(executor, traci_module, 5)
        # local time of J2 at t = 0 is (0 - 45) mod 90 = 45, which is its
        # V green start: 42 H, 3 yellow, then V from local second 45.
        self.assertEqual(shown[0][1]["J2"], "V")
        self.assertEqual(shown[0][1]["J1"], "H")
        self.assertNotIn("R", set(phase_string(shown, "J2")))


class TimingGridTests(unittest.TestCase):
    """S2-D: the grids, the rounding rule and the split identity."""

    def test_round_half_up_is_not_bankers_rounding(self):
        self.assertEqual(
            [plans.round_half_up(v) for v in (0.5, 1.5, 2.5, 3.5, 4.5)],
            [1, 2, 3, 4, 5],
        )
        # Python's own round() disagrees on exactly these boundaries.
        self.assertEqual([round(v) for v in (0.5, 2.5, 4.5)], [0, 2, 4])

    def test_the_coarse_grid_has_exactly_1980_candidates(self):
        self.assertEqual(
            len(plans.coarse_timing_candidates(include_invalid=True)), 1980
        )
        cycles = sorted(set(
            plan["cycle_s"]
            for plan in plans.coarse_timing_candidates(include_invalid=True)
        ))
        self.assertEqual(cycles, list(range(40, 141, 10)))
        splits = sorted(set(
            plan["split_thousandths"]
            for plan in plans.coarse_timing_candidates(include_invalid=True)
        ))
        self.assertEqual(splits, list(range(300, 751, 50)))

    def test_every_candidate_satisfies_the_split_identity(self):
        for plan in plans.coarse_timing_candidates(include_invalid=True):
            self.assertEqual(
                plan["green_H_s"] + plan["green_V_s"] + 6, plan["cycle_s"],
                plan,
            )
            self.assertTrue(plans.validate_plan(plan))

    def test_offsets_step_by_five_within_each_cycle(self):
        by_cycle = {}
        for plan in plans.coarse_timing_candidates(include_invalid=True):
            by_cycle.setdefault(plan["cycle_s"], set()).add(plan["offset_s"])
        for cycle_s, offsets in by_cycle.items():
            self.assertEqual(sorted(offsets), list(range(0, cycle_s, 5)))

    def test_invalid_green_candidates_are_rejected(self):
        too_short = plans.make_plan(40, 900, 0)
        self.assertEqual(too_short["green_V_s"], 3)
        self.assertFalse(plans.candidate_is_valid(too_short))
        healthy = plans.make_plan(90, 500, 0)
        self.assertTrue(plans.candidate_is_valid(healthy))

    def test_the_five_second_rule_is_enforced_by_the_generator(self):
        """A grid containing a short green must drop it."""
        generated = plans.fine_timing_candidates(
            [plans.make_plan(40, 800, 0)], include_invalid=False
        )
        for plan in generated:
            self.assertGreaterEqual(plan["green_H_s"], plans.MIN_GREEN_S)
            self.assertGreaterEqual(plan["green_V_s"], plans.MIN_GREEN_S)

    def test_the_benchmark_minimum_green_is_not_a_qmix_constraint(self):
        config = load_config(BASELINE_CONFIG_PATH)
        note = config["baselines"]["optimized_fixed_timing"][
            "benchmark_minimum_green_note"
        ]
        self.assertIn("not a minimum green imposed on QMIX", note)
        self.assertNotIn("minimum_green_s", config["executor"])


class FineGridTests(unittest.TestCase):
    """S2-D: neighbourhood bounds, steps, modulo and deduplication."""

    def test_bounds_and_steps_are_exact(self):
        centre = plans.make_plan(90, 500, 30)
        generated = plans.fine_timing_candidates([centre])
        cycles = sorted(set(plan["cycle_s"] for plan in generated))
        self.assertEqual(cycles, [80, 85, 90, 95, 100])
        splits = sorted(set(plan["split_thousandths"] for plan in generated))
        self.assertEqual(splits, [450, 475, 500, 525, 550])
        offsets = sorted(set(
            plan["offset_s"] for plan in generated if plan["cycle_s"] == 90
        ))
        self.assertEqual(offsets, list(range(20, 41)))

    def test_cycles_and_splits_are_clipped_to_their_bounds(self):
        low = plans.fine_timing_candidates([plans.make_plan(40, 300, 0)])
        self.assertEqual(
            sorted(set(plan["cycle_s"] for plan in low)), [40, 45, 50]
        )
        self.assertEqual(
            sorted(set(plan["split_thousandths"] for plan in low)),
            [250, 275, 300, 325, 350],
        )
        high = plans.fine_timing_candidates([plans.make_plan(140, 750, 0)])
        self.assertEqual(
            sorted(set(plan["cycle_s"] for plan in high)), [130, 135, 140]
        )
        self.assertEqual(
            sorted(set(plan["split_thousandths"] for plan in high)),
            [700, 725, 750, 775, 800],
        )

    def test_offsets_are_reduced_modulo_the_candidate_cycle(self):
        """A negative or over-long offset wraps into its own cycle."""
        centre = plans.make_plan(45, 500, 2)
        generated = plans.fine_timing_candidates([centre])
        for plan in generated:
            self.assertTrue(0 <= plan["offset_s"] < plan["cycle_s"], plan)
        offsets = sorted(set(
            plan["offset_s"] for plan in generated if plan["cycle_s"] == 40
        ))
        # centre 2, +/-10 gives -8..12, reduced mod 40 -> 32..39 and 0..12.
        self.assertEqual(offsets, list(range(0, 13)) + list(range(32, 40)))

    def test_duplicate_fine_candidates_are_removed(self):
        centre = plans.make_plan(90, 500, 30)
        once = plans.fine_timing_candidates([centre])
        twice = plans.fine_timing_candidates([centre, dict(centre)])
        self.assertEqual(len(once), len(twice))
        keys = [plans.candidate_key(plan) for plan in twice]
        self.assertEqual(len(keys), len(set(keys)))

    def test_overlapping_neighbourhoods_are_merged_not_repeated(self):
        first = plans.make_plan(90, 500, 30)
        second = plans.make_plan(95, 500, 32)
        merged = plans.fine_timing_candidates([first, second])
        keys = [plans.candidate_key(plan) for plan in merged]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertLess(
            len(merged),
            len(plans.fine_timing_candidates([first]))
            + len(plans.fine_timing_candidates([second])),
            "overlapping neighbourhoods must share their common candidates",
        )


class PressureTests(unittest.TestCase):
    """S2-E: the pressure score, its inputs and its movement mapping."""

    def setUp(self):
        self.config = config_copy()

    def test_pressure_reproduces_a_hand_computed_example(self):
        # J1 H serves E0_0->E1_0, E0_1->E1_1, -E1_0->-E0_0, -E1_1->-E0_1.
        counts = {
            "E0_0": 10, "E1_0": 4,
            "E0_1": 7, "E1_1": 1,
            "-E1_0": 3, "-E0_0": 5,
            "-E1_1": 2, "-E0_1": 0,
        }
        source = FakeSource(counts)
        # (10-4) + (7-1) + (3-5) + (2-0) = 6 + 6 - 2 + 2 = 12
        self.assertEqual(pressure.phase_pressure(source, "J1", "H"), 12)

    def test_pressure_can_be_negative_when_the_exit_is_fuller(self):
        counts = {"E4_0": 0, "-E5_0": 6, "E4_1": 1, "-E5_1": 2,
                  "E5_0": 0, "-E4_0": 0, "E5_1": 0, "-E4_1": 3}
        source = FakeSource(counts)
        # (0-6) + (1-2) + (0-0) + (0-3) = -10
        self.assertEqual(pressure.phase_pressure(source, "J1", "V"), -10)

    def test_pressure_uses_lane_vehicle_counts_not_halting_queues(self):
        source = FakeSource({"E0_0": 3})
        pressure.local_pressures(source, "J1")
        used = set(name for name, _lane in source.accessors_used)
        self.assertEqual(used, {"lane_vehicle_number"})
        self.assertEqual(pressure.LANE_COUNT_ACCESSOR, "lane_vehicle_number")
        for forbidden in pressure.FORBIDDEN_ACCESSORS:
            self.assertNotIn(forbidden, used)

    def test_every_frozen_movement_is_physically_connected(self):
        self.assertTrue(pressure.validate_movement_pairs(NETWORK_PATH))

    def test_a_movement_the_network_lacks_is_a_hard_failure(self):
        broken = {
            "J1": {
                "H": (("E0_0", "E7_1"),),
                "V": (("E4_0", "-E5_0"),),
            },
        }
        with self.assertRaises(pressure.MovementMappingError):
            pressure.validate_movement_pairs(NETWORK_PATH, broken)

    def test_movements_agree_with_the_frozen_observation_topology(self):
        self.assertTrue(
            pressure.validate_against_observation_topology(self.config)
        )

    def test_each_phase_has_all_four_straight_through_movements(self):
        for intersection in ("J1", "J2"):
            for movement in ("H", "V"):
                pairs = pressure.FROZEN_MOVEMENT_PAIRS[intersection][movement]
                self.assertEqual(len(pairs), 4)
                incoming = set(lane for lane, _out in pairs)
                self.assertEqual(
                    incoming,
                    set(self.config["observation"]["lanes"][intersection][
                        "{}_in".format(movement)
                    ]),
                )

    def test_an_exact_tie_retains_the_current_phase(self):
        self.assertEqual(
            pressure.preferred_phase({"H": 7, "V": 7}, "H"), "H"
        )
        self.assertEqual(
            pressure.preferred_phase({"H": 7, "V": 7}, "V"), "V"
        )

    def test_a_strictly_greater_pressure_wins(self):
        self.assertEqual(pressure.preferred_phase({"H": 7, "V": 8}, "H"), "V")
        self.assertEqual(pressure.preferred_phase({"H": 8, "V": 7}, "V"), "H")


class CanonicalMaxPressureTests(unittest.TestCase):
    """S2-E: minimum green, yellow length, no cycle, independent clocks."""

    def setUp(self):
        self.config = config_copy()

    def _executor(self, counts, **kwargs):
        traci_module = FakeTraci()
        source = FakeSource(counts)
        executor = CanonicalMaxPressureExecutor(
            traci_module, self.config, data_source=source, **kwargs
        )
        return traci_module, source, executor

    @staticmethod
    def _pressing_v_counts():
        """Counts under which V pressure strictly exceeds H at both signals."""
        counts = {}
        for intersection in ("J1", "J2"):
            for lane, _out in pressure.FROZEN_MOVEMENT_PAIRS[
                intersection
            ]["V"]:
                counts[lane] = 20
            for _in, lane in pressure.FROZEN_MOVEMENT_PAIRS[
                intersection
            ]["H"]:
                counts[lane] = 20
        return counts

    def test_the_minimum_green_is_enforced_before_any_switch(self):
        traci_module, _source, executor = self._executor(
            self._pressing_v_counts()
        )
        shown = drive(executor, traci_module, 20)
        sequence = phase_string(shown, "J1")
        # Ten seconds of H are served before the first decision can end it.
        self.assertEqual(sequence[:10], "H" * 10)
        self.assertEqual(sequence[10], "Y")

    def test_a_switch_executes_exactly_three_yellow_seconds(self):
        traci_module, _source, executor = self._executor(
            self._pressing_v_counts()
        )
        shown = drive(executor, traci_module, 20)
        sequence = phase_string(shown, "J1")
        self.assertEqual(sequence[10:13], "YYY")
        self.assertEqual(sequence[13], "V")
        self.assertNotEqual(sequence[9], "Y")

    def test_the_new_green_gets_its_own_minimum_green(self):
        counts = self._pressing_v_counts()
        traci_module, source, executor = self._executor(counts)
        shown = drive(executor, traci_module, 13)
        # Flip the demand so H is now the pressing phase.
        source.counts = dict(
            (lane, 0) for lane in source.counts
        )
        for lane, _out in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["H"]:
            source.counts[lane] = 30
        for _in, lane in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["V"]:
            source.counts[lane] = 30
        more = []

        def record(second_offset, states, elapsed):
            more.append(dict(states))

        for _ in range(12):
            executor.execute(None, after_second=record)
        sequence = "".join(row["J1"] for row in more)
        self.assertEqual(sequence[:10], "V" * 10,
                         "the new green must be protected for 10 s too")
        self.assertEqual(sequence[10], "Y")

    def test_a_tie_never_switches(self):
        # All counts equal makes every pressure zero at both phases.
        traci_module, _source, executor = self._executor({})
        shown = drive(executor, traci_module, 40)
        self.assertEqual(phase_string(shown, "J1"), "H" * 40)
        self.assertEqual(phase_string(shown, "J2"), "H" * 40)

    def test_there_is_no_fixed_cycle(self):
        """Green durations follow demand, not a repeating period."""
        counts = self._pressing_v_counts()
        traci_module, source, executor = self._executor(counts)
        executor.initialize()
        states = []

        def record(second_offset, shown_states, elapsed):
            states.append(shown_states["J1"])

        for second in range(60):
            if second == 25:
                # Demand flips back to H part-way through the V green.
                source.counts = dict((lane, 0) for lane in source.counts)
                for lane, _out in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["H"]:
                    source.counts[lane] = 40
                for _in, lane in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["V"]:
                    source.counts[lane] = 40
            executor.execute(None, after_second=record)
        sequence = "".join(states)
        greens = [
            len(run) for run in sequence.replace("Y", " ").split()
        ]
        self.assertGreater(len(greens), 2)
        self.assertGreater(
            len(set(greens)), 1,
            "a demand-driven controller must not produce one repeating period",
        )

    def test_the_two_intersections_keep_independent_clocks(self):
        counts = {}
        # Only J1 sees pressure to switch; J2 sees none.
        for lane, _out in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["V"]:
            counts[lane] = 25
        for _in, lane in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["H"]:
            counts[lane] = 25
        traci_module, _source, executor = self._executor(counts)
        shown = drive(executor, traci_module, 30)
        j1 = phase_string(shown, "J1")
        j2 = phase_string(shown, "J2")
        self.assertNotEqual(j1, j2)
        self.assertEqual(j2, "H" * 30, "J2 had no reason to switch")
        self.assertIn("Y", j1, "J1 did")

    def test_decisions_are_recorded_with_both_pressures(self):
        traci_module, _source, executor = self._executor(
            self._pressing_v_counts()
        )
        drive(executor, traci_module, 20)
        self.assertTrue(executor.events)
        event = executor.events[0]
        for field in ("time", "intersection", "current_phase",
                      "green_elapsed_s", "pressure_H", "pressure_V",
                      "preferred_phase", "decision", "timing_authority"):
            self.assertIn(field, event)
        self.assertEqual(event["timing_authority"], TIMING_PRESSURE)

    def test_no_decision_is_recorded_inside_the_minimum_green(self):
        traci_module, _source, executor = self._executor(
            self._pressing_v_counts()
        )
        drive(executor, traci_module, 9)
        self.assertEqual(
            executor.events, [],
            "a decision inside the protected green would be fictitious",
        )


class MatchedIntervalPressureTests(unittest.TestCase):
    """S2-F: P-5 is max-pressure choice on the adaptive control authority."""

    def setUp(self):
        self.config = config_copy()

    def test_p5_uses_the_adaptive_executor_semantics(self):
        executor_config = self.config["executor"]
        self.assertEqual(int(executor_config["control_interval_s"]), 5)
        self.assertEqual(int(executor_config["yellow_duration_s"]), 3)
        self.assertEqual(int(executor_config["switch_new_green_s"]), 2)
        self.assertEqual(
            TIMING_AUTHORITY[MATCHED_INTERVAL_PRESSURE_P5], TIMING_SYNCHRONOUS
        )

    def test_a_p5_switch_is_executed_as_three_yellow_plus_two_new_green(self):
        """Checked on the real executor, not merely asserted from the config."""
        traci_module = FakeTraci()
        executor = SynchronousSignalExecutor(traci_module, self.config)
        executor.initialize()
        shown = []

        def record(second_offset, states, elapsed):
            shown.append(states["J1"])

        executor.execute([SWITCH, SWITCH], after_second=record)
        self.assertEqual("".join(shown), "YYYVV")
        self.assertEqual(executor.current_phase["J1"], "V")
        self.assertEqual(executor.green_elapsed["J1"], 2)

    def test_a_p5_extend_is_five_seconds_of_the_same_green(self):
        traci_module = FakeTraci()
        executor = SynchronousSignalExecutor(traci_module, self.config)
        executor.initialize()
        shown = []

        def record(second_offset, states, elapsed):
            shown.append(states["J1"])

        executor.execute([EXTEND, EXTEND], after_second=record)
        self.assertEqual("".join(shown), "HHHHH")
        self.assertEqual(executor.green_elapsed["J1"], 5)

    def test_p5_decisions_occur_exactly_every_five_seconds(self):
        source = FakeSource({})
        policy = MatchedIntervalPressurePolicy(self.config, source)
        for index in range(6):
            policy.decide(
                float(index * 5), {"J1": "H", "J2": "H"}, {"J1": 0, "J2": 0}
            )
        times = sorted(set(event["time"] for event in policy.events))
        self.assertEqual(times, [0.0, 5.0, 10.0, 15.0, 20.0, 25.0])
        self.assertEqual(
            [t - s for s, t in zip(times, times[1:])], [5.0] * 5
        )

    def test_p5_makes_the_same_choice_as_canonical_on_one_snapshot(self):
        """Same pressure score, same tie rule; only the authority differs."""
        counts = {}
        for lane, _out in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["V"]:
            counts[lane] = 17
        for _in, lane in pressure.FROZEN_MOVEMENT_PAIRS["J1"]["H"]:
            counts[lane] = 9
        source = FakeSource(counts)
        for current in ("H", "V"):
            canonical = pressure.preferred_phase(
                pressure.local_pressures(source, "J1"), current
            )
            policy = MatchedIntervalPressurePolicy(self.config, source)
            actions = policy.decide(
                0.0, {"J1": current, "J2": current}, {"J1": 0, "J2": 0}
            )
            expected = EXTEND if canonical == current else SWITCH
            self.assertEqual(actions[0], expected, current)
            self.assertEqual(policy.events[0]["preferred_phase"], canonical)

    def test_p5_extends_on_a_tie(self):
        policy = MatchedIntervalPressurePolicy(self.config, FakeSource({}))
        actions = policy.decide(
            0.0, {"J1": "H", "J2": "V"}, {"J1": 3, "J2": 8}
        )
        self.assertEqual(actions, [EXTEND, EXTEND])

    def test_p5_has_no_minimum_green_of_its_own(self):
        """A switch is available at the very first decision."""
        counts = {}
        for intersection in ("J1", "J2"):
            for lane, _out in pressure.FROZEN_MOVEMENT_PAIRS[
                intersection
            ]["V"]:
                counts[lane] = 30
            for _in, lane in pressure.FROZEN_MOVEMENT_PAIRS[
                intersection
            ]["H"]:
                counts[lane] = 30
        policy = MatchedIntervalPressurePolicy(self.config, FakeSource(counts))
        actions = policy.decide(
            0.0, {"J1": "H", "J2": "H"}, {"J1": 0, "J2": 0}
        )
        self.assertEqual(actions, [SWITCH, SWITCH])

    def test_p5_never_reads_the_reward_or_a_learner(self):
        policy = MatchedIntervalPressurePolicy(self.config, FakeSource({}))
        self.assertFalse(hasattr(policy, "learner"))
        self.assertFalse(hasattr(policy, "reward"))
        config = load_config(BASELINE_CONFIG_PATH)
        p5 = config["baselines"]["matched_interval_pressure_P5"]
        self.assertFalse(p5["reward_used_for_control"])
        self.assertEqual(p5["learning"], "none")
        self.assertFalse(p5["is_official_controller"])


class ControllerIdentityTests(unittest.TestCase):
    """Identifiers must not be confusable, and roles must not be swapped."""

    def test_every_identifier_is_distinct(self):
        self.assertEqual(len(BASELINE_CONTROLLERS), len(set(BASELINE_CONTROLLERS)))
        self.assertEqual(len(BASELINE_CONTROLLERS), 5)

    def test_baseline_and_learned_identifiers_never_overlap(self):
        self.assertFalse(set(BASELINE_CONTROLLERS) & set(LEARNED_METHODS))

    def test_p5_is_a_diagnostic_and_canonical_mp_is_official(self):
        self.assertIn(CANONICAL_MAX_PRESSURE, OFFICIAL_CLASSICAL_CONTROLLERS)
        self.assertNotIn(
            MATCHED_INTERVAL_PRESSURE_P5, OFFICIAL_CLASSICAL_CONTROLLERS
        )
        self.assertEqual(
            DIAGNOSTIC_CONTROLLERS, (MATCHED_INTERVAL_PRESSURE_P5,)
        )

    def test_the_official_set_is_exactly_seven_controllers(self):
        config = load_config(BASELINE_CONFIG_PATH)
        official = config["baselines"]["official_controllers"]
        self.assertEqual(len(official), 7)
        self.assertEqual(sorted(official), sorted([
            "simultaneous_fixed_time", "optimized_fixed_offset",
            "optimized_fixed_timing", "idqn", "vdn", "qmix",
            "canonical_operational_max_pressure",
        ]))
        self.assertNotIn(
            "matched_interval_pressure_P5", official
        )

    def test_stability_claims_never_attach_to_p5(self):
        canonical = controller_interpretation(CANONICAL_MAX_PRESSURE)
        diagnostic = controller_interpretation(MATCHED_INTERVAL_PRESSURE_P5)
        self.assertIn("does NOT inherit", canonical)
        self.assertIn("empirical operational baseline", canonical)
        self.assertIn("matched", diagnostic)
        self.assertIn("never transfer", diagnostic)
        self.assertNotIn("stability guarantee", diagnostic)

    def test_the_timing_authorities_are_the_expected_three(self):
        self.assertEqual(
            set(TIMING_AUTHORITY.values()),
            {TIMING_PRETIMED, TIMING_PRESSURE, TIMING_SYNCHRONOUS},
        )
        self.assertEqual(
            TIMING_AUTHORITY[CANONICAL_MAX_PRESSURE], TIMING_PRESSURE
        )
        self.assertNotEqual(
            TIMING_AUTHORITY[CANONICAL_MAX_PRESSURE],
            TIMING_AUTHORITY[MATCHED_INTERVAL_PRESSURE_P5],
            "the two pressure controllers differ precisely in authority",
        )


class SelectionProtocolTests(unittest.TestCase):
    """S2-C/D: design ranks, validation selects, final is never touched."""

    @staticmethod
    def _record(plan, family, mean_j, mean_loss, valid=True, failed=0):
        seeds = list(search.required_seeds(family))
        return {
            "plan": dict(plan), "key": plans.candidate_key(plan),
            "family": family, "valid": valid, "failed_seed_count": failed,
            "failed_seeds": [], "mean_J_primary_s": mean_j,
            "mean_time_loss_s": mean_loss, "seeds": seeds,
            "required_seeds": seeds, "run_count": len(seeds),
            "clearance_statuses": [],
        }

    def test_the_optimiser_refuses_the_final_family(self):
        with self.assertRaises(search.LeakageError):
            search.assert_family_allowed(search.FINAL_FAMILY)
        with self.assertRaises(search.LeakageError):
            search.seeds_for(search.FINAL_FAMILY)

    def test_the_optimiser_refuses_final_seeds_in_any_family(self):
        with self.assertRaises(search.LeakageError):
            search.assert_family_allowed(
                search.DESIGN_FAMILY, [2001, 3001]
            )
        self.assertTrue(
            search.assert_family_allowed(search.DESIGN_FAMILY, [2001, 2002])
        )

    def test_the_search_families_and_seeds_are_the_specified_ones(self):
        self.assertEqual(search.DESIGN_SEEDS, (2001, 2002, 2003, 2004, 2005))
        self.assertEqual(
            search.VALIDATION_SEEDS, (2101, 2102, 2103, 2104, 2105)
        )
        self.assertEqual(search.FINAL_SEEDS, tuple(range(3001, 3011)))
        self.assertFalse(
            set(search.DESIGN_SEEDS) & set(search.VALIDATION_SEEDS)
        )
        self.assertFalse(
            set(search.DESIGN_SEEDS + search.VALIDATION_SEEDS)
            & set(search.FINAL_SEEDS)
        )

    def test_selection_must_use_validation_records_not_design_ones(self):
        plan = plans.simultaneous_plan()
        design_only = [
            self._record(plan, search.DESIGN_FAMILY, 10.0, 5.0)
        ]
        with self.assertRaises(search.SelectionError):
            search.select_offset_plan(design_only)

    def test_design_ranks_before_validation_selects(self):
        candidates = [plans.fixed_offset_plan(offset) for offset in (0, 10, 20)]
        design = [
            self._record(candidates[0], search.DESIGN_FAMILY, 30.0, 9.0),
            self._record(candidates[1], search.DESIGN_FAMILY, 10.0, 8.0),
            self._record(candidates[2], search.DESIGN_FAMILY, 20.0, 7.0),
        ]
        seen = {}

        def evaluator(retained):
            seen["retained"] = [plan["offset_s"] for plan in retained]
            return [
                self._record(retained[0], search.VALIDATION_FAMILY, 12.0, 6.0),
                self._record(retained[1], search.VALIDATION_FAMILY, 11.0, 6.5),
            ]

        result = search.run_selection_protocol(
            design, evaluator, 2, search.select_offset_plan
        )
        # Design order is by mean J_primary: offsets 10 then 20.
        self.assertEqual(seen["retained"], [10, 20])
        self.assertEqual(result["selected_plan"]["offset_s"], 20)

    def test_offset_tie_break_order_is_exact(self):
        a = plans.fixed_offset_plan(40)
        b = plans.fixed_offset_plan(5)
        c = plans.fixed_offset_plan(70)
        # Equal J_primary and equal time loss: smallest Delta wins.
        records = [
            self._record(a, search.VALIDATION_FAMILY, 10.0, 4.0),
            self._record(b, search.VALIDATION_FAMILY, 10.0, 4.0),
            self._record(c, search.VALIDATION_FAMILY, 10.0, 3.0),
        ]
        # c has the lower time loss, so it wins on the second key.
        self.assertEqual(
            search.select_offset_plan(records)["plan"]["offset_s"], 70
        )
        records = records[:2]
        self.assertEqual(
            search.select_offset_plan(records)["plan"]["offset_s"], 5
        )

    def test_timing_tie_break_order_is_exact(self):
        long_cycle = plans.make_plan(120, 500, 0)
        short_cycle = plans.make_plan(60, 500, 0)
        other_short = plans.make_plan(60, 450, 5)
        records = [
            self._record(long_cycle, search.VALIDATION_FAMILY, 9.0, 3.0),
            self._record(short_cycle, search.VALIDATION_FAMILY, 9.0, 3.0),
        ]
        # Equal J_primary and time loss: the shorter cycle wins.
        self.assertEqual(
            search.select_timing_plan(records)["plan"]["cycle_s"], 60
        )
        records = [
            self._record(other_short, search.VALIDATION_FAMILY, 9.0, 3.0),
            self._record(short_cycle, search.VALIDATION_FAMILY, 9.0, 3.0),
        ]
        # Same cycle: lexicographic (C, f_H, Delta) decides.
        selected = search.select_timing_plan(records)["plan"]
        self.assertEqual(
            (selected["cycle_s"], selected["split_thousandths"],
             selected["offset_s"]),
            (60, 450, 5),
        )

    def test_j_primary_wins_before_time_loss(self):
        better_j = plans.make_plan(90, 500, 0)
        better_loss = plans.make_plan(90, 500, 10)
        records = [
            self._record(better_loss, search.VALIDATION_FAMILY, 9.5, 1.0),
            self._record(better_j, search.VALIDATION_FAMILY, 9.0, 8.0),
        ]
        self.assertEqual(
            search.select_timing_plan(records)["plan"]["offset_s"], 0
        )


class ClearanceFailureRankingTests(unittest.TestCase):
    """S2-G: an uncleared candidate is never given a favourable score."""

    @staticmethod
    def _runs(statuses, j_value=5.0, family=None):
        """One run per preregistered seed; statuses is padded with CLEARED."""
        seeds = search.required_seeds(family or search.DESIGN_FAMILY)
        statuses = list(statuses) + ["CLEARED"] * (len(seeds) - len(statuses))
        return [
            {
                "traffic_seed": seed,
                "clearance_status": status,
                "J_primary_valid": status == "CLEARED",
                search.PRIMARY_FIELD: j_value if status == "CLEARED"
                else float("nan"),
                search.TIME_LOSS_FIELD: 1.0,
            }
            for seed, status in zip(seeds, statuses)
        ]

    def test_a_failing_candidate_is_marked_invalid_with_no_finite_score(self):
        record = search.summarise_candidate(
            plans.simultaneous_plan(),
            self._runs(["CLEARED", "CLEARANCE_FAILURE", "CLEARED"]),
            search.DESIGN_FAMILY,
        )
        self.assertFalse(record["valid"])
        self.assertEqual(record["failed_seed_count"], 1)
        self.assertNotEqual(
            record["mean_J_primary_s"], record["mean_J_primary_s"],
            "a failing candidate must not carry a finite J_primary",
        )

    def test_a_failing_candidate_is_excluded_from_the_shortlist(self):
        good = search.summarise_candidate(
            plans.fixed_offset_plan(10),
            self._runs(["CLEARED"], j_value=999.0),
            search.DESIGN_FAMILY,
        )
        bad = search.summarise_candidate(
            plans.fixed_offset_plan(20),
            self._runs(["CLEARANCE_FAILURE"] * 5),
            search.DESIGN_FAMILY,
        )
        ranked = search.rank_by_design([bad, good], 1)
        self.assertEqual(len(ranked), 1)
        self.assertTrue(ranked[0]["valid"])
        self.assertEqual(ranked[0]["plan"]["offset_s"], 10)

    def test_the_shortlist_is_never_padded_with_invalid_candidates(self):
        """Too few valid candidates is an error, not a shorter-quality list."""
        good = search.summarise_candidate(
            plans.fixed_offset_plan(10), self._runs([]), search.DESIGN_FAMILY
        )
        bad = search.summarise_candidate(
            plans.fixed_offset_plan(20),
            self._runs(["CLEARANCE_FAILURE"] * 5),
            search.DESIGN_FAMILY,
        )
        with self.assertRaises(search.SelectionError) as caught:
            search.rank_by_design([good, bad], 2)
        self.assertIn("never padded", str(caught.exception))

    def test_a_single_failing_seed_invalidates_the_whole_candidate(self):
        record = search.summarise_candidate(
            plans.fixed_offset_plan(30),
            self._runs(["CLEARED", "CLEARANCE_FAILURE"]),
            search.DESIGN_FAMILY,
        )
        self.assertFalse(record["valid"])
        self.assertEqual(record["failed_seeds"], [2002])
        with self.assertRaises(search.SelectionError):
            search.rank_by_design([record], 1)

    def test_no_plan_is_selected_when_every_candidate_failed(self):
        records = [
            search.summarise_candidate(
                plans.fixed_offset_plan(offset),
                self._runs(
                    ["CLEARANCE_FAILURE"] * 5,
                    family=search.VALIDATION_FAMILY,
                ),
                search.VALIDATION_FAMILY,
            )
            for offset in (0, 10)
        ]
        with self.assertRaises(search.SelectionError):
            search.select_offset_plan(records)

    def test_a_budget_truncated_run_also_invalidates_a_candidate(self):
        record = search.summarise_candidate(
            plans.simultaneous_plan(),
            self._runs(["BUDGET_TRUNCATED"]),
            search.DESIGN_FAMILY,
        )
        self.assertFalse(record["valid"])
        self.assertEqual(record["failed_seeds"], [2001])


class BaselineConfigTests(unittest.TestCase):
    """The baseline specification must not disturb the adaptive contract."""

    def setUp(self):
        self.baseline = load_config(BASELINE_CONFIG_PATH)
        self.qualification = load_config(QUALIFICATION_CONFIG_PATH)

    def test_the_adaptive_qualification_hash_is_untouched(self):
        self.assertEqual(
            self.qualification["_config_sha256"],
            "fa31ffc2b83f17dd49b9525cebea60de8b3b52b9c2312cb16f9626a7a8e8882c",
        )

    def test_the_baseline_config_is_a_separate_file_with_its_own_hash(self):
        self.assertNotEqual(
            self.baseline["_config_sha256"],
            self.qualification["_config_sha256"],
        )
        self.assertNotEqual(
            self.baseline["_config_path"], self.qualification["_config_path"]
        )

    def test_every_shared_block_is_identical_to_the_qualification_config(self):
        """A baseline setting may never drift the frozen scientific contract."""
        shared = [
            key for key in self.qualification
            if not key.startswith("_") and key != "experiment_name"
        ]
        for key in shared:
            self.assertEqual(
                self.baseline[key], self.qualification[key],
                "block {!r} differs between the two configurations".format(key),
            )
        self.assertEqual(
            sorted(set(self.baseline) - set(self.qualification)), ["baselines"]
        )

    def test_the_baseline_config_declares_the_frozen_movement_pairs(self):
        declared = self.baseline["baselines"][
            "canonical_operational_max_pressure"
        ]["movement_pairs"]
        for intersection in ("J1", "J2"):
            for movement in ("H", "V"):
                self.assertEqual(
                    [tuple(pair) for pair in declared[intersection][movement]],
                    list(pressure.FROZEN_MOVEMENT_PAIRS[intersection][movement]),
                )

    def test_the_declared_grid_counts_match_the_generators(self):
        coarse = self.baseline["baselines"]["optimized_fixed_timing"][
            "coarse_grid"
        ]
        self.assertEqual(coarse["candidate_count_before_rejection"], 1980)
        self.assertEqual(
            len(plans.coarse_timing_candidates(include_invalid=True)),
            coarse["candidate_count_before_rejection"],
        )
        offsets = self.baseline["baselines"]["optimized_fixed_offset"][
            "offset_grid_s"
        ]
        self.assertEqual(offsets["count"], len(plans.fixed_offset_candidates()))

    def test_forbidden_pressure_inputs_are_named_in_the_specification(self):
        forbidden = self.baseline["baselines"][
            "canonical_operational_max_pressure"
        ]["forbidden_pressure_inputs"]
        for name in ("lane_halting_number", "reward"):
            self.assertIn(name, forbidden)


class ActionMetricApplicabilityTests(unittest.TestCase):
    """S2-H: no fabricated zero, and no cross-family switch-rate comparison.

    A pretimed plan takes no online decisions, and canonical max pressure
    takes them per intersection on its own clock rather than as a synchronous
    joint action, so neither produces the quantity signal_actions describes.
    P-5 does: it decides on exactly the adaptive clock with exactly the
    adaptive EXTEND/SWITCH meaning, which is what makes it the matched
    diagnostic, so its decisions belong in that log and are comparable there.
    """

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = config_copy()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write(self, action_rows):
        phases = []
        for intersection in ("J1", "J2"):
            phases.extend(instrumentation.phase_rows(
                instrumentation.HAND_TRACE, intersection
            ))
        instrumentation.write_table(self.directory, "signal_phases", phases)
        instrumentation.write_table(
            self.directory, "signal_actions", action_rows
        )
        lane_rows = []
        for time_value in range(1, len(instrumentation.HAND_TRACE) + 1):
            for intersection in ("J1", "J2"):
                for movement in ("H", "V"):
                    for lane in self.config["observation"]["lanes"][
                        intersection
                    ]["{}_in".format(movement)]:
                        lane_rows.append({
                            "episode_index": 0, "time": float(time_value),
                            "lane": lane, "queue": 1, "vehicle_count": 1,
                            "occupancy": 0.0, "mean_speed": 0.0,
                        })
        instrumentation.write_table(self.directory, "lane_states", lane_rows)

    def test_a_controller_with_no_decisions_reports_not_applicable(self):
        self._write([])
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertFalse(summary["action_metrics_applicable"])
        stats = summary["by_intersection"][WINDOW_FULL_EPISODE]["J1"]
        for field in ("switch_count", "decision_count", "switches_per_hour",
                      "switch_fraction_of_decisions"):
            self.assertEqual(stats[field], NOT_APPLICABLE, field)

    def test_a_zero_is_never_fabricated_for_a_pretimed_plan(self):
        self._write([])
        summary = derive_behavior_metrics(self.directory, self.config)
        stats = summary["by_intersection"][WINDOW_FULL_EPISODE]["J1"]
        self.assertNotEqual(stats["switches_per_hour"], 0)
        self.assertNotEqual(stats["switches_per_hour"], 0.0)
        self.assertIn("rather than as zero", summary["action_metrics_note"])

    def test_phase_derived_quantities_stay_defined_without_any_decisions(self):
        """Green spells and deprivation remain comparable across families."""
        self._write([])
        summary = derive_behavior_metrics(self.directory, self.config)
        stats = summary["by_intersection"][WINDOW_FULL_EPISODE]["J1"]
        self.assertAlmostEqual(stats["emergent_cycle_mean_s"], 23.0)
        self.assertAlmostEqual(stats["yellow_fraction_of_elapsed"], 6.0 / 28.0)
        self.assertNotEqual(stats["emergent_cycle_count"], NOT_APPLICABLE)

    def test_a_controller_with_real_decisions_still_reports_numbers(self):
        actions = []
        for index in range(5):
            for intersection in ("J1", "J2"):
                actions.append({
                    "episode_index": 0, "decision_time": float(index * 5),
                    "decision_index": index, "intersection": intersection,
                    "action": "SWITCH" if index % 2 else "EXTEND",
                })
        self._write(actions)
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertTrue(summary["action_metrics_applicable"])
        stats = summary["by_intersection"][WINDOW_FULL_EPISODE]["J1"]
        self.assertEqual(stats["decision_count"], 5)
        self.assertEqual(stats["switch_count"], 2)
        self.assertAlmostEqual(
            stats["switch_fraction_of_decisions"], 2.0 / 5.0
        )


class MatchedDecisionLoggingTests(unittest.TestCase):
    """P-5's joint decisions are logged as themselves, with no fake Q-values."""

    class _Logger(object):
        def __init__(self):
            self.rows = []

        def write(self, table, row):
            self.rows.append((table, dict(row)))

    def test_decisions_land_in_signal_actions_without_q_values(self):
        logger = self._Logger()
        info = {"start_time": 15.0, "elapsed_seconds": 5.0,
                "timeout_truncated": False}
        _log_matched_decisions(logger, info, [EXTEND, SWITCH], 3, False)
        self.assertEqual([table for table, _row in logger.rows],
                         ["signal_actions", "signal_actions"])
        first = logger.rows[0][1]
        self.assertEqual(first["decision_time"], 15.0)
        self.assertEqual(first["decision_index"], 3)
        self.assertEqual(first["action"], "EXTEND")
        self.assertEqual(logger.rows[1][1]["action"], "SWITCH")
        # No Q-value is invented; the columns are simply absent.
        for _table, row in logger.rows:
            self.assertNotIn("q_extend", row)
            self.assertNotIn("q_switch", row)
            self.assertFalse(row["explore"])
            self.assertEqual(row["epsilon"], 0.0)


class BaselineRunnerContractTests(unittest.TestCase):
    """The runner reuses the adaptive contract rather than restating it."""

    def test_a_pretimed_controller_requires_an_explicit_plan(self):
        with self.assertRaises(BaselineError):
            run_baseline(
                None, config_copy(), REPOSITORY_ROOT, SIMULTANEOUS_FIXED_TIME,
                "manifest.csv", "routes.rou.xml", "development", 101, 1, "/tmp",
                plan=None,
            )

    def test_an_unknown_controller_is_refused(self):
        with self.assertRaises(BaselineError):
            run_baseline(
                None, config_copy(), REPOSITORY_ROOT, "webster_1958",
                "manifest.csv", "routes.rou.xml", "development", 101, 1, "/tmp",
            )

    def test_the_baseline_environment_substitutes_only_the_executor(self):
        """Every per-second contract method is inherited, not overridden."""
        inherited = (
            "_after_second", "_lane_rows", "_lane_log_due", "step",
            "episode_summary", "complete_residual_state", "close",
        )
        for name in inherited:
            self.assertIs(
                getattr(BaselineEnvironment, name),
                getattr(AdaptiveTrafficEnvironment, name),
                "{} must come from the adaptive environment unchanged".format(
                    name
                ),
            )
        overridden = set(BaselineEnvironment.__dict__) - set(
            ("__module__", "__qualname__", "__doc__")
        )
        self.assertEqual(overridden, {"__init__", "reset"})

    def test_the_p5_diagnostic_uses_the_unmodified_adaptive_environment(self):
        """It is not a subclass at all: matched authority means the real thing."""
        source = inspect.getsource(run_baseline)
        self.assertIn("AdaptiveTrafficEnvironment(", source)
        self.assertIn("MATCHED_INTERVAL_PRESSURE_P5", source)


class LedgerReconciliationTests(unittest.TestCase):
    """S2-J: a complete baseline reconciles all 2800 scheduled vehicles."""

    @staticmethod
    def _ledger(count=2800, completed=None):
        ledger = VehicleLedger([
            {"vehicle_id": "veh_{:04d}".format(index), "depart": 0}
            for index in range(count)
        ])
        for index, vehicle_id in enumerate(sorted(ledger.scheduled)):
            if completed is not None and index >= completed:
                break
            ledger.inserted_at[vehicle_id] = 0.0
            ledger.completed_at[vehicle_id] = 10.0
        return ledger

    @staticmethod
    def _tripinfo(ledger):
        return dict(
            (vehicle_id, {
                "waitingTime": 4.0, "departDelay": 1.0, "timeLoss": 2.0,
                "duration": 60.0, "waitingCount": 1.0,
            })
            for vehicle_id in ledger.completed_at
        )

    def test_a_cleared_baseline_yields_a_finite_j_primary_over_2800(self):
        ledger = self._ledger()
        metrics = scheduled_demand_metrics(
            ledger, self._tripinfo(ledger), "CLEARED"
        )
        self.assertTrue(metrics["J_primary_valid"])
        self.assertEqual(metrics["scheduled_count"], 2800)
        self.assertEqual(metrics["completed_count"], 2800)
        # mean(waitingTime + departDelay) over exactly 2800 vehicles.
        self.assertAlmostEqual(
            metrics["J_primary_mean_scheduled_waiting_burden_s"], 5.0
        )

    def test_a_clearance_failure_carries_no_finite_j_primary(self):
        ledger = self._ledger(completed=2000)
        metrics = scheduled_demand_metrics(
            ledger, self._tripinfo(ledger), "CLEARANCE_FAILURE"
        )
        self.assertFalse(metrics["J_primary_valid"])
        self.assertNotEqual(
            metrics["J_primary_mean_scheduled_waiting_burden_s"],
            metrics["J_primary_mean_scheduled_waiting_burden_s"],
        )

    def test_an_uncleared_run_is_never_given_a_favourable_value(self):
        """Averaging only the vehicles that finished would flatter the plan."""
        ledger = self._ledger(completed=2000)
        metrics = scheduled_demand_metrics(
            ledger, self._tripinfo(ledger), "CLEARANCE_FAILURE"
        )
        # The completed-only means are still reported as diagnostics ...
        self.assertAlmostEqual(metrics["mean_completed_waiting_time_s"], 4.0)
        # ... but they are never promoted into the ranked objective.
        self.assertNotEqual(
            metrics["mean_completed_waiting_time_s"],
            metrics["J_primary_mean_scheduled_waiting_burden_s"],
        )


class FinalSeedProtectionTests(unittest.TestCase):
    """S2-I: development and search code cannot reach the final family."""

    def test_search_entry_points_all_guard_the_family(self):
        for family in (search.FINAL_FAMILY, "training", "learner_validation"):
            with self.assertRaises(search.LeakageError):
                search.assert_family_allowed(family)

    def test_summarising_a_candidate_rejects_a_final_seed(self):
        runs = [{
            "traffic_seed": seed, "clearance_status": "CLEARED",
            "J_primary_valid": True, search.PRIMARY_FIELD: 5.0,
            search.TIME_LOSS_FIELD: 1.0,
        } for seed in (2001, 2002, 2003, 2004, 3001)]
        with self.assertRaises(search.LeakageError):
            search.summarise_candidate(
                plans.simultaneous_plan(), runs, search.DESIGN_FAMILY
            )

    def test_no_final_test_manifest_exists_in_the_repository(self):
        """S2 development must not have generated or opened one."""
        found = []
        for root, _dirs, files in os.walk(
            os.path.join(REPOSITORY_ROOT, "results")
        ):
            for name in files:
                if "final_test" in name:
                    found.append(os.path.join(root, name))
        self.assertEqual(found, [])


SCRIPT_PATH = os.path.join(
    REPOSITORY_ROOT, "scripts", "adaptive_qmix", "run_baseline.py"
)


def invoke_cli(arguments):
    """Actually run the baseline script and return (code, stdout+stderr)."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.path.join(REPOSITORY_ROOT, "src")
    completed = subprocess.run(
        [sys.executable, SCRIPT_PATH] + list(arguments),
        cwd=REPOSITORY_ROOT, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return completed.returncode, completed.stdout.decode("utf-8", "replace")


class HeldOutGuardTests(unittest.TestCase):
    """A: the guard is one place, and it runs before anything is created."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_the_final_family_is_refused(self):
        with self.assertRaises(integrity.HeldOutDataError):
            integrity.assert_traffic_selection_allowed("final_test", 2001, 0)

    def test_every_final_seed_is_refused_under_any_family(self):
        for family in integrity.ALLOWED_FAMILIES:
            for seed in range(3001, 3011):
                with self.assertRaises(integrity.HeldOutDataError):
                    integrity.assert_traffic_selection_allowed(family, seed, 0)

    def test_benchmark_design_with_seed_3001_is_refused(self):
        """The exact relabelling the review asked about."""
        with self.assertRaises(integrity.HeldOutDataError) as caught:
            integrity.assert_traffic_selection_allowed(
                "benchmark_design", 3001, 0
            )
        self.assertIn("held-out final test", str(caught.exception))
        self.assertIn(
            "relabelling the family does not release", str(caught.exception)
        )

    def test_seeds_just_outside_the_held_out_block_are_allowed(self):
        for seed in (3000, 3011, 2005, 2105, 101):
            self.assertTrue(
                integrity.assert_traffic_selection_allowed(
                    "benchmark_design", seed, 0
                )
            )

    def test_non_baseline_families_are_refused(self):
        for family in ("training", "learner_validation",
                       "legacy_deterministic_sanity", "made_up"):
            with self.assertRaises(integrity.HeldOutDataError):
                integrity.assert_traffic_selection_allowed(family, 101, 0)

    def test_the_cli_refuses_benchmark_design_with_a_final_seed(self):
        output = os.path.join(self.directory, "must_not_exist")
        code, text = invoke_cli([
            "--controller", "simultaneous_fixed_time",
            "--traffic-family", "benchmark_design", "--traffic-seed", "3001",
            "--output-directory", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("held-out final test", text)
        self.assertFalse(
            os.path.exists(output),
            "a refused run must not create its output directory",
        )

    def test_the_cli_refuses_the_final_family_outright(self):
        output = os.path.join(self.directory, "also_must_not_exist")
        code, text = invoke_cli([
            "--controller", "simultaneous_fixed_time",
            "--traffic-family", "final_test", "--traffic-seed", "2001",
            "--output-directory", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("held out", text)
        self.assertFalse(os.path.exists(output))

    def test_nothing_is_written_anywhere_by_a_refused_run(self):
        before = sorted(os.listdir(self.directory))
        code, _text = invoke_cli([
            "--controller", "canonical_operational_max_pressure",
            "--traffic-family", "benchmark_validation",
            "--traffic-seed", "3010",
            "--output-directory", os.path.join(self.directory, "nope"),
        ])
        self.assertNotEqual(code, 0)
        self.assertEqual(sorted(os.listdir(self.directory)), before)


class ManifestIntegrityTests(unittest.TestCase):
    """A and B: the manifest, not the label, says what the traffic is."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = load_config(BASELINE_CONFIG_PATH)
        self.prefix = os.path.join(self.directory, "manifest")
        records = generate_manifest_records(
            self.config, "development", 101, 0
        )
        self.metadata = write_manifest(
            records, self.config, self.prefix, "development", 101, 0
        )

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_a_matching_manifest_verifies(self):
        metadata, hashes = integrity.verify_manifest_for_run(
            self.prefix, "development", 101, 0
        )
        self.assertEqual(metadata["family"], "development")
        self.assertEqual(hashes["csv_sha256"], self.metadata["csv_sha256"])
        self.assertEqual(
            hashes["route_xml_sha256"], self.metadata["route_xml_sha256"]
        )

    def test_a_mismatched_family_is_refused(self):
        with self.assertRaises(integrity.ManifestIntegrityError) as caught:
            integrity.verify_manifest_for_run(
                self.prefix, "benchmark_design", 101, 0
            )
        self.assertIn("family", str(caught.exception))
        self.assertIn("never overrides", str(caught.exception))

    def test_a_mismatched_seed_is_refused(self):
        with self.assertRaises(integrity.ManifestIntegrityError):
            integrity.verify_manifest_for_run(self.prefix, "development", 102, 0)

    def test_a_mismatched_manifest_index_is_refused(self):
        with self.assertRaises(integrity.ManifestIntegrityError):
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 1)

    def test_a_manifest_with_the_wrong_vehicle_count_is_refused(self):
        path = integrity.metadata_path_for(self.prefix)
        with open(path) as handle:
            metadata = json.load(handle)
        metadata["scheduled_total"] = 2799
        with open(path, "w") as handle:
            json.dump(metadata, handle)
        with self.assertRaises(integrity.ManifestIntegrityError) as caught:
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 0)
        self.assertIn("2799", str(caught.exception))

    def test_a_final_test_manifest_is_refused_even_if_labelled_otherwise(self):
        """The metadata is authoritative, so a disguised manifest still fails."""
        path = integrity.metadata_path_for(self.prefix)
        with open(path) as handle:
            metadata = json.load(handle)
        metadata["family"] = "final_test"
        with open(path, "w") as handle:
            json.dump(metadata, handle)
        with self.assertRaises(integrity.HeldOutDataError):
            integrity.verify_manifest_for_run(self.prefix, "final_test", 101, 0)
        with self.assertRaises(integrity.HeldOutDataError):
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 0)

    def test_a_manifest_whose_metadata_carries_a_final_seed_is_refused(self):
        path = integrity.metadata_path_for(self.prefix)
        with open(path) as handle:
            metadata = json.load(handle)
        metadata["seed_value"] = 3005
        with open(path, "w") as handle:
            json.dump(metadata, handle)
        with self.assertRaises(integrity.HeldOutDataError):
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 0)

    def test_a_missing_metadata_file_is_refused(self):
        os.remove(integrity.metadata_path_for(self.prefix))
        with self.assertRaises(integrity.ManifestIntegrityError):
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 0)

    def test_a_tampered_csv_is_refused(self):
        with open(self.prefix + ".csv", "a") as handle:
            handle.write("extra,row,that,was,not,hashed,here\n")
        with self.assertRaises(integrity.ManifestIntegrityError) as caught:
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 0)
        self.assertIn("route manifest CSV", str(caught.exception))

    def test_a_tampered_route_xml_is_refused_with_an_intact_csv(self):
        """SUMO executes the route XML, so its hash is the one that matters."""
        csv_before = integrity.sha256_file(self.prefix + ".csv")
        with open(self.prefix + ".rou.xml", "r") as handle:
            body = handle.read()
        # Move one vehicle's departure: a change SUMO would act on and the
        # CSV hash would never notice.
        tampered = body.replace('depart="0"', 'depart="7"', 1)
        self.assertNotEqual(tampered, body)
        with open(self.prefix + ".rou.xml", "w") as handle:
            handle.write(tampered)
        self.assertEqual(
            integrity.sha256_file(self.prefix + ".csv"), csv_before,
            "the CSV is untouched, which is exactly the dangerous case",
        )
        with self.assertRaises(integrity.ManifestIntegrityError) as caught:
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 0)
        message = str(caught.exception)
        self.assertIn("route XML executed by SUMO", message)
        self.assertIn("SUMO executes the route XML", message)

    def test_a_missing_route_xml_is_refused(self):
        os.remove(self.prefix + ".rou.xml")
        with self.assertRaises(integrity.ManifestIntegrityError):
            integrity.verify_manifest_for_run(self.prefix, "development", 101, 0)

    def test_the_runner_refuses_a_tampered_route_before_starting_sumo(self):
        """traci is never touched, because the guard fails first."""
        with open(self.prefix + ".rou.xml", "a") as handle:
            handle.write("<!-- appended after hashing -->\n")
        output = os.path.join(self.directory, "run")
        with self.assertRaises(integrity.ManifestIntegrityError):
            run_baseline(
                None, self.config, REPOSITORY_ROOT, SIMULTANEOUS_FIXED_TIME,
                self.prefix + ".csv", self.prefix + ".rou.xml",
                "development", 101, 1, output,
                plan=plans.simultaneous_plan(),
            )
        self.assertFalse(os.path.exists(output))

    def test_the_cli_refuses_a_manifest_prefix_that_does_not_match(self):
        output = os.path.join(self.directory, "cli_run")
        code, text = invoke_cli([
            "--controller", "simultaneous_fixed_time",
            "--traffic-family", "benchmark_design", "--traffic-seed", "2001",
            "--manifest-prefix", self.prefix,
            "--output-directory", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("not what this run declared", text)
        self.assertFalse(os.path.exists(output))

    def test_the_cli_refuses_a_tampered_route_xml(self):
        with open(self.prefix + ".rou.xml", "a") as handle:
            handle.write("<!-- tampered -->\n")
        output = os.path.join(self.directory, "cli_tampered")
        code, text = invoke_cli([
            "--controller", "simultaneous_fixed_time",
            "--traffic-family", "development", "--traffic-seed", "101",
            "--manifest-prefix", self.prefix,
            "--output-directory", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("route XML executed by SUMO", text)
        self.assertFalse(os.path.exists(output))


class RecordedHashTests(unittest.TestCase):
    """B: both verified hashes are written into the run manifest."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = load_config(BASELINE_CONFIG_PATH)
        self.prefix = os.path.join(self.directory, "manifest")
        self.metadata = write_manifest(
            generate_manifest_records(self.config, "development", 101, 0),
            self.config, self.prefix, "development", 101, 0,
        )

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_the_run_manifest_records_both_verified_hashes(self):
        _metadata, hashes = integrity.verify_manifest_for_run(
            self.prefix, "development", 101, 0
        )
        manifest = _baseline_manifest(
            REPOSITORY_ROOT, self.config, self.prefix + ".csv",
            SIMULTANEOUS_FIXED_TIME, plans.simultaneous_plan(), "development",
            101, 1234, "development_baseline", "subscription", "full", None,
            verified_hashes=hashes, manifest_index=0,
        )
        self.assertEqual(
            manifest["manifest_csv_sha256"], self.metadata["csv_sha256"]
        )
        self.assertEqual(
            manifest["route_xml_sha256"], self.metadata["route_xml_sha256"]
        )
        self.assertNotEqual(
            manifest["manifest_csv_sha256"], manifest["route_xml_sha256"],
            "the CSV and the route XML are different files",
        )
        self.assertTrue(manifest["manifest_metadata_verified"])
        self.assertEqual(manifest["manifest_index"], 0)

    def test_the_recorded_route_hash_is_the_file_sumo_would_read(self):
        _metadata, hashes = integrity.verify_manifest_for_run(
            self.prefix, "development", 101, 0
        )
        self.assertEqual(
            hashes["route_xml_sha256"],
            integrity.sha256_file(self.prefix + ".rou.xml"),
        )


class ExactSeedSetTests(unittest.TestCase):
    """C: a mean over the wrong seed set is not the preregistered quantity."""

    @staticmethod
    def _run(seed, status="CLEARED"):
        return {
            "traffic_seed": seed, "clearance_status": status,
            "J_primary_valid": status == "CLEARED",
            search.PRIMARY_FIELD: 5.0, search.TIME_LOSS_FIELD: 1.0,
        }

    def test_the_exact_design_seed_set_is_accepted(self):
        runs = [self._run(seed) for seed in (2001, 2002, 2003, 2004, 2005)]
        record = search.summarise_candidate(
            plans.simultaneous_plan(), runs, search.DESIGN_FAMILY
        )
        self.assertEqual(record["seeds"], [2001, 2002, 2003, 2004, 2005])
        self.assertEqual(record["required_seeds"], record["seeds"])
        self.assertTrue(record["valid"])

    def test_four_of_five_design_seeds_are_refused(self):
        runs = [self._run(seed) for seed in (2001, 2002, 2003, 2004)]
        with self.assertRaises(search.SelectionError) as caught:
            search.summarise_candidate(
                plans.simultaneous_plan(), runs, search.DESIGN_FAMILY
            )
        message = str(caught.exception)
        self.assertIn("missing [2005]", message)
        self.assertIn("Got 4 runs", message)

    def test_a_duplicated_seed_is_refused(self):
        runs = [self._run(seed) for seed in (2001, 2002, 2003, 2004, 2004)]
        with self.assertRaises(search.SelectionError) as caught:
            search.summarise_candidate(
                plans.simultaneous_plan(), runs, search.DESIGN_FAMILY
            )
        message = str(caught.exception)
        self.assertIn("duplicated [2004]", message)
        self.assertIn("missing [2005]", message)

    def test_a_duplicated_seed_with_the_right_count_is_still_refused(self):
        """Five runs, but not the five seeds."""
        runs = [self._run(seed) for seed in (2001, 2001, 2002, 2003, 2004)]
        with self.assertRaises(search.SelectionError):
            search.summarise_candidate(
                plans.simultaneous_plan(), runs, search.DESIGN_FAMILY
            )

    def test_an_extra_seed_is_refused(self):
        runs = [
            self._run(seed) for seed in (2001, 2002, 2003, 2004, 2005, 2006)
        ]
        with self.assertRaises(search.SelectionError) as caught:
            search.summarise_candidate(
                plans.simultaneous_plan(), runs, search.DESIGN_FAMILY
            )
        self.assertIn("unexpected [2006]", str(caught.exception))

    def test_validation_seeds_are_refused_in_the_design_stage(self):
        runs = [self._run(seed) for seed in (2101, 2102, 2103, 2104, 2105)]
        with self.assertRaises(search.SelectionError):
            search.summarise_candidate(
                plans.simultaneous_plan(), runs, search.DESIGN_FAMILY
            )

    def test_design_seeds_are_refused_in_the_validation_stage(self):
        runs = [self._run(seed) for seed in (2001, 2002, 2003, 2004, 2005)]
        with self.assertRaises(search.SelectionError):
            search.summarise_candidate(
                plans.simultaneous_plan(), runs, search.VALIDATION_FAMILY
            )

    def test_an_empty_run_list_is_refused(self):
        with self.assertRaises(search.SelectionError):
            search.summarise_candidate(
                plans.simultaneous_plan(), [], search.DESIGN_FAMILY
            )

    def test_the_required_seed_sets_are_the_preregistered_ones(self):
        self.assertEqual(
            search.required_seeds(search.DESIGN_FAMILY),
            (2001, 2002, 2003, 2004, 2005),
        )
        self.assertEqual(
            search.required_seeds(search.VALIDATION_FAMILY),
            (2101, 2102, 2103, 2104, 2105),
        )


class ExecutionAdmissibilityTests(unittest.TestCase):
    """D: a short green is refused where a plan is executed, not only generated."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = load_config(BASELINE_CONFIG_PATH)
        self.prefix = os.path.join(self.directory, "manifest")
        write_manifest(
            generate_manifest_records(self.config, "development", 101, 0),
            self.config, self.prefix, "development", 101, 0,
        )

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _run(self, controller, plan):
        return run_baseline(
            None, self.config, REPOSITORY_ROOT, controller,
            self.prefix + ".csv", self.prefix + ".rou.xml",
            "development", 101, 1,
            os.path.join(self.directory, "out"), plan=plan,
        )

    def test_a_short_green_timing_plan_is_refused_at_execution(self):
        short = plans.make_plan(40, 900, 0)
        self.assertEqual(short["green_V_s"], 3)
        with self.assertRaises(BaselineError) as caught:
            self._run(OPTIMIZED_FIXED_TIMING, short)
        message = str(caught.exception)
        self.assertIn("below 5 s", message)
        self.assertIn("g_V = 3", message)

    def test_the_refusal_says_the_rule_is_classical_only(self):
        with self.assertRaises(BaselineError) as caught:
            self._run(OPTIMIZED_FIXED_TIMING, plans.make_plan(40, 900, 0))
        self.assertIn("never applied to QMIX or P-5", str(caught.exception))

    def test_an_admissible_timing_plan_passes_the_check(self):
        """It gets past admissibility and fails later, on the absent traci."""
        good = plans.make_plan(90, 500, 10)
        self.assertTrue(plans.candidate_is_valid(good))
        with self.assertRaises(Exception) as caught:
            self._run(OPTIMIZED_FIXED_TIMING, good)
        self.assertNotIsInstance(caught.exception, BaselineError)

    def test_the_cli_refuses_a_short_green_before_writing_anything(self):
        output = os.path.join(self.directory, "cli_short")
        code, text = invoke_cli([
            "--controller", "optimized_fixed_timing",
            "--traffic-family", "development", "--traffic-seed", "101",
            "--manifest-prefix", self.prefix,
            "--cycle", "40", "--split", "900", "--offset", "0",
            "--output-directory", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("below 5 s", text)
        self.assertFalse(os.path.exists(output))

    def test_the_constraint_does_not_bind_on_the_preregistered_grid(self):
        """Documented, not widened: the rule simply never fires here."""
        coarse = plans.coarse_timing_candidates(include_invalid=True)
        self.assertEqual(len(coarse), 1980)
        self.assertTrue(all(plans.candidate_is_valid(p) for p in coarse))
        self.assertEqual(
            min(min(p["green_H_s"], p["green_V_s"]) for p in coarse), 8
        )
        fine = plans.fine_timing_candidates(coarse, include_invalid=True)
        self.assertEqual(
            min(min(p["green_H_s"], p["green_V_s"]) for p in fine), 7
        )
        self.assertTrue(all(plans.candidate_is_valid(p) for p in fine))


class StructuralProtocolTests(unittest.TestCase):
    """E: the stage order is enforced by the code, not by a convention."""

    def setUp(self):
        self.calls = []

    def _evaluator(self, scores=None, failing_keys=()):
        """A mock campaign: records what it was asked, returns synthetic runs."""
        def evaluate(candidate_plans, family, seeds):
            self.calls.append({
                "family": family, "seeds": list(seeds),
                "count": len(candidate_plans),
                "keys": [plans.candidate_key(p) for p in candidate_plans],
            })
            out = []
            for plan in candidate_plans:
                key = plans.candidate_key(plan)
                failed = key in failing_keys
                score = 100.0 if scores is None else scores(plan)
                out.append([
                    {
                        "traffic_seed": seed,
                        "clearance_status": (
                            "CLEARANCE_FAILURE" if failed else "CLEARED"
                        ),
                        "J_primary_valid": not failed,
                        search.PRIMARY_FIELD: (
                            float("nan") if failed else score
                        ),
                        search.TIME_LOSS_FIELD: score / 2.0,
                    }
                    for seed in seeds
                ])
            return out
        return evaluate

    def test_the_offset_protocol_runs_ninety_then_ten_then_selects(self):
        design = self._evaluator(scores=lambda p: float(p["offset_s"]))
        validation = self._evaluator(scores=lambda p: float(p["offset_s"]))
        result = search.run_fixed_offset_protocol(design, validation)
        self.assertEqual(self.calls[0]["count"], 90)
        self.assertEqual(self.calls[0]["family"], search.DESIGN_FAMILY)
        self.assertEqual(self.calls[0]["seeds"], [2001, 2002, 2003, 2004, 2005])
        self.assertEqual(self.calls[1]["count"], 10)
        self.assertEqual(self.calls[1]["family"], search.VALIDATION_FAMILY)
        self.assertEqual(self.calls[1]["seeds"], [2101, 2102, 2103, 2104, 2105])
        # Scores rise with the offset, so offsets 0..9 are retained and 0 wins.
        self.assertEqual(
            [key[2] for key in self.calls[1]["keys"]], list(range(10))
        )
        self.assertEqual(result["selected_plan"]["offset_s"], 0)
        self.assertTrue(result["frozen"])
        self.assertFalse(result["final_seeds_touched"])

    def test_the_timing_protocol_runs_coarse_then_fine_then_validation(self):
        def score(plan):
            # Smallest cycle and smallest offset score best, deterministically.
            return float(plan["cycle_s"] * 1000 + plan["offset_s"])

        design = self._evaluator(scores=score)
        validation = self._evaluator(scores=score)
        result = search.run_fixed_timing_protocol(design, validation)

        self.assertEqual(
            [call["family"] for call in self.calls],
            [search.DESIGN_FAMILY, search.DESIGN_FAMILY,
             search.VALIDATION_FAMILY],
        )
        stages = [stage["stage"] for stage in result["stages"]]
        self.assertEqual(
            stages, ["coarse_design", "fine_design", "validation"]
        )
        self.assertEqual(self.calls[0]["count"], 1980)
        self.assertEqual(result["coarse_candidate_count"], 1980)
        # Exactly five coarse winners seed the fine neighbourhood ...
        self.assertEqual(
            len(result["stages"][0]["retained_keys"]), 5
        )
        # ... and exactly ten fine winners reach validation.
        self.assertEqual(len(result["stages"][1]["retained_keys"]), 10)
        self.assertEqual(self.calls[2]["count"], 10)
        self.assertEqual(
            self.calls[2]["keys"], result["stages"][1]["retained_keys"]
        )
        self.assertEqual(result["selected_plan"]["cycle_s"], 40)
        self.assertEqual(result["selected_plan"]["offset_s"], 0)

    def test_the_fine_stage_sees_exactly_the_winners_neighbourhood(self):
        def score(plan):
            return float(plan["cycle_s"] * 1000 + plan["offset_s"])

        result = search.run_fixed_timing_protocol(
            self._evaluator(scores=score), self._evaluator(scores=score)
        )
        winner_keys = result["stages"][0]["retained_keys"]
        self.assertEqual(len(winner_keys), 5)
        expected = [
            plans.candidate_key(plan)
            for plan in plans.fine_timing_candidates(
                [plans.make_plan(*key) for key in winner_keys]
            )
        ]
        self.assertEqual(self.calls[1]["keys"], expected)
        self.assertEqual(len(expected), len(set(expected)))
        self.assertEqual(result["fine_candidate_count"], len(expected))

    def test_no_stage_ever_names_the_final_family_or_its_seeds(self):
        def score(plan):
            return float(plan["cycle_s"] * 1000 + plan["offset_s"])

        result = search.run_fixed_timing_protocol(
            self._evaluator(scores=score), self._evaluator(scores=score)
        )
        for call in self.calls:
            self.assertNotEqual(call["family"], search.FINAL_FAMILY)
            self.assertFalse(
                set(call["seeds"]) & set(search.FINAL_SEEDS)
            )
        self.assertFalse(result["final_seeds_touched"])
        self.assertIn("frozen", result["freeze_note"])

    def test_the_protocol_preserves_identities_seeds_and_scores(self):
        design = self._evaluator(scores=lambda p: float(p["offset_s"]))
        validation = self._evaluator(scores=lambda p: float(p["offset_s"]))
        result = search.run_fixed_offset_protocol(design, validation)
        stage = result["stages"][0]
        self.assertEqual(stage["candidate_count"], 90)
        self.assertEqual(stage["valid_count"], 90)
        self.assertEqual(stage["seeds"], [2001, 2002, 2003, 2004, 2005])
        first = stage["scores"][0]
        self.assertEqual(first["key"], (90, 500, 0))
        self.assertEqual(first["seeds"], [2001, 2002, 2003, 2004, 2005])
        self.assertEqual(first["mean_J_primary_s"], 0.0)
        self.assertEqual(result["selected_key"], (90, 500, 0))
        self.assertEqual(result["selected_validation_seeds"],
                         [2101, 2102, 2103, 2104, 2105])

    def test_a_stage_that_evaluates_the_wrong_seeds_fails_closed(self):
        def bad(candidate_plans, family, seeds):
            return [
                [
                    {
                        "traffic_seed": seed, "clearance_status": "CLEARED",
                        "J_primary_valid": True, search.PRIMARY_FIELD: 1.0,
                        search.TIME_LOSS_FIELD: 1.0,
                    }
                    for seed in list(seeds)[:4]
                ]
                for _plan in candidate_plans
            ]

        with self.assertRaises(search.SelectionError) as caught:
            search.run_fixed_offset_protocol(bad, bad)
        self.assertIn("exactly one run for each", str(caught.exception))

    def test_a_stage_that_returns_the_wrong_number_of_results_fails(self):
        def short(candidate_plans, family, seeds):
            return []

        with self.assertRaises(search.SelectionError) as caught:
            search.run_fixed_offset_protocol(short, short)
        self.assertIn("were submitted", str(caught.exception))

    def test_too_few_valid_candidates_stops_the_protocol(self):
        """Rather than shortlisting plans that could not clear."""
        all_keys = set(
            plans.candidate_key(plan)
            for plan in plans.fixed_offset_candidates()
        )
        # Leave only nine valid candidates where ten are required.
        keep = set(list(sorted(all_keys))[:9])
        failing = all_keys - keep
        design = self._evaluator(
            scores=lambda p: float(p["offset_s"]), failing_keys=failing
        )
        with self.assertRaises(search.SelectionError) as caught:
            search.run_fixed_offset_protocol(design, design)
        self.assertIn("never padded", str(caught.exception))

    def test_the_protocol_does_not_run_a_campaign_itself(self):
        """Without evaluators there is nothing to execute: it is orchestration."""
        with self.assertRaises(TypeError):
            search.run_fixed_offset_protocol()


if __name__ == "__main__":
    unittest.main()
