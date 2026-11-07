"""Tests of tools/comparators: OFT grids, seed registry and the two new executors (no SUMO, stdlib only).

The frozen package adaptive_qmix is needed (QMIX_PROTECTED_ROOT/src or AQ_FROZEN_REPOSITORY/src); the tests
are skipped without it. Expected counts are those published by Amendment 002 and the min-7 protocol.
"""
import collections
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN_SRC = [os.path.join(os.environ.get(v, d), "src") for v, d in
              (("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"),
               ("AQ_FROZEN_REPOSITORY", r"C:\Users\LENOVO\QMIX_Traffic_Coordination"))]
for path in FROZEN_SRC:
    if os.path.isdir(os.path.join(path, "adaptive_qmix")):
        sys.path.insert(0, path)
        break
sys.path.insert(0, os.path.join(HERE, "..", "tools", "comparators"))
try:
    from adaptive_qmix.baselines import plans as P
    HAVE_FROZEN = True
except ImportError:
    HAVE_FROZEN = False

import seeds as SD  # noqa: E402

PHASE_MAP = {"V_GREEN": 0, "V_TO_H_YELLOW": 1, "H_GREEN": 2, "H_TO_V_YELLOW": 3}
LANES = {"J1": {"H_in": ["a_0", "a_1"], "V_in": ["b_0", "b_1"]}, "J2": {"H_in": ["c_0", "c_1"], "V_in": ["d_0", "d_1"]}}
CONFIG = {"network": {"phase_map": PHASE_MAP, "traffic_lights": ["J1", "J2"]},
          "observation": {"lanes": LANES, "expected_lane_lengths_m": dict((l, 200.0) for tl in LANES.values()
                                                                          for ls in tl.values() for l in ls)}}


class FakeTraci(object):
    def __init__(self):
        self.t = 0
        self.trafficlight = self
        self.simulation = self

    def setPhase(self, tl, index):
        pass

    def setPhaseDuration(self, tl, duration):
        pass

    def simulationStep(self):
        self.t += 1

    def getTime(self):
        return float(self.t)


class FakeSource(object):
    """vehicles(t) -> {lane: [position, ...]}"""
    def __init__(self, traci, vehicles):
        self.traci, self.vehicles = traci, vehicles

    def _now(self):
        return self.vehicles(self.traci.t)

    def lane_vehicle_ids(self, lane):
        return ["{}#{}".format(lane, k) for k, _p in enumerate(self._now().get(lane, []))]

    def vehicle_lane_position(self, vehicle):
        lane, k = vehicle.split("#")
        return self._now()[lane][int(k)]

    def lane_vehicle_number(self, lane):
        return len(self._now().get(lane, []))


def run_executor(executor, traci, seconds):
    shown = collections.defaultdict(list)
    executor.initialize()
    for _ in range(seconds):
        result = executor.execute()
        for tl, state in result["trace"][0]["states"].items():
            shown[tl].append(state)
    return shown


def segments(states):
    out = []
    for s in states:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return out


def starts(states, phase):
    return [t for t in range(1, len(states)) if states[t] == phase and states[t - 1] != phase]


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class Grids(unittest.TestCase):

    def test_counts_reproduce_amendment_002_and_min7(self):
        import grids as G
        g5, m7 = G.report(5), G.report(7)
        self.assertEqual(g5["labels"], {"original": 1980, "short": 208, "floor": 68})
        self.assertEqual(g5["realized_plans"], {"original": 1980, "short": 195, "floor": 40})
        self.assertEqual(g5["floor_cycles_s"], [16, 17, 18, 19])
        self.assertEqual((m7["combined_labels"], m7["combined_realized_plans"]), (2143, 2138))
        self.assertEqual(m7["labels"]["short"], 163)
        self.assertEqual(m7["floor_cycles_s"], [])
        self.assertTrue(set(G.groups(G.coarse_labels(7))) <= set(G.groups(G.coarse_labels(5))))
        self.assertEqual(G.fine_bound(7)["upper_bound_new_plans"], 2475)

    def test_reduced_coarse_grid_declared_on_2026_11_07(self):
        import grids as G
        g5, m7 = G.report(5, 10), G.report(7, 10)
        self.assertEqual((g5["labels"], g5["realized_plans"]), ({"original": 990, "short": 114, "floor": 34},
                                                                 {"original": 990, "short": 107, "floor": 20}))
        self.assertEqual((g5["combined_realized_plans"], m7["combined_realized_plans"]), (1117, 1077))
        self.assertTrue(set(G.groups(G.coarse_labels(7, 10))) <= set(G.groups(G.coarse_labels(5, 10))))
        self.assertTrue(all(p["offset_s"] % 10 == 0 for p in G.coarse_labels(5, 10)))
        # the fine rule is unchanged: offsets every 1 s around a winner
        winner = G.groups(G.coarse_labels(5, 10))[(30, 13, 11, 10)]
        offsets = set(p["offset_s"] for p in G.fine_candidates(winner, 5) if p["cycle_s"] == 30)
        self.assertEqual(offsets, set(range(0, 21)))

    def test_fine_rule_equals_the_frozen_generator_on_the_original_bounds(self):
        import grids as G
        winner = P.make_plan(60, 550, 25)
        frozen = set(P.candidate_key(p) for p in P.fine_timing_candidates([winner]))
        mine = set(P.candidate_key(p) for p in G.fine_candidates([winner], 5) if p["cycle_s"] >= 40)
        self.assertEqual(frozen, mine)

    def test_canonical_split_names_the_realized_plan(self):
        import comparator_search as CS
        for cycle in (16, 19, 25, 40, 140):
            for g_h in range(5, cycle - 6 - 4):
                spec = CS.fixed_spec((cycle, g_h, cycle - 6 - g_h, 3))
                plan = P.make_plan(cycle, spec["plan"]["split_thousandths"], 3)
                self.assertEqual((plan["green_H_s"], plan["green_V_s"]), (g_h, cycle - 6 - g_h))


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class R0Demand(unittest.TestCase):
    """Condition for reusing C19 and C25 on R0 (decision of 2026-11-07)."""

    def config(self):
        import adaptive_qmix
        from adaptive_qmix.config import load_config
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(adaptive_qmix.__file__))))
        return load_config(os.path.join(root, "config", "adaptive_qmix", "qualification_300m_medium.json"))

    def test_r0_is_the_qualification_demand_and_a_change_is_reported(self):
        sys.path.insert(0, os.path.join(HERE, "..", "tools", "robustness"))
        import check_r0_demand as R
        import scenario_traffic as st
        result = R.check(self.config())
        self.assertEqual((result["verdict"], result["problems"]), ("IDENTICAL_LAW", []))
        self.assertTrue(all(v["ks_distance"] < 0.06 for v in result["empirical_informative"].values()))
        original = st.load_spec

        def altered(*args, **kwargs):
            spec = original(*args, **kwargs)
            spec["scenarios"]["R0_reference"]["streams"]["WE"] = {"count": 900, "profile": [[0, 1800, 2.0], [1800, 3600, 1.0]]}
            return spec
        st.load_spec = altered
        try:
            changed = R.check(self.config())
        finally:
            st.load_spec = original
        self.assertEqual(changed["verdict"], "DIFFERS")
        self.assertTrue(any("profile" in p for p in changed["problems"]))


class Seeds(unittest.TestCase):

    def test_registry_is_disjoint_and_guards_the_confirmation_seeds(self):
        self.assertTrue(SD.check_disjoint())
        self.assertEqual(SD.seeds("R0_reference", "robustness_evaluation"), (8001, 8002, 8003, 8004, 8005))
        self.assertEqual(SD.seeds("R4_isolated_tail", "comparator_design")[0], 8411)
        for profile in SD.PROFILES:
            for role in ("robustness_evaluation", "confirmation"):
                for seed in SD.seeds(profile, role):
                    with self.assertRaises(SD.SeedError):
                        SD.assert_search_seed(profile, seed)
        with self.assertRaises(SD.SeedError):
            SD.assert_search_seed("R0_reference", 8111)          # an R1 design seed is not an R0 seed


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class Actuated(unittest.TestCase):

    def make(self, vehicles, **params):
        import controllers as C
        traci = FakeTraci()
        source = FakeSource(traci, vehicles)
        return C.ActuatedGapOutExecutor(traci, CONFIG, data_source=source, **params), traci

    def test_rests_in_green_without_a_conflicting_call(self):
        ex, traci = self.make(lambda t: {})
        shown = run_executor(ex, traci, 300)
        self.assertEqual(set(shown["J1"]), {"H"})

    def test_gap_out_after_the_7_s_minimum_green(self):
        ex, traci = self.make(lambda t: {"b_0": [10.0], "d_0": [10.0]}, gap_s=3)
        segs = segments(run_executor(ex, traci, 40)["J1"])
        self.assertEqual(segs[0], ["H", 7])                  # empty H zone: gap-out as soon as 7 s are served
        self.assertEqual(segs[1], ["Y", 3])
        self.assertEqual(segs[2][0], "V")

    def test_max_out_with_continuous_detection(self):
        ex, traci = self.make(lambda t: {"a_0": [195.0], "b_0": [10.0], "c_0": [195.0], "d_0": [10.0]},
                              gap_s=2, max_green_H_s=30)
        segs = segments(run_executor(ex, traci, 60)["J1"])
        self.assertEqual(segs[0], ["H", 30])
        self.assertEqual(segs[1], ["Y", 3])

    def test_minimum_green_holds_on_both_phases_and_yellow_is_3_s(self):
        # Permanent calls far upstream on both phases (a_1, b_0 outside the 40 m zone), intermittent detection
        # in the zones: the maximum greens bound every green because a conflicting call always exists.
        pattern = lambda t: {"a_0": [190.0] if t % 17 < 5 else [], "a_1": [10.0], "b_0": [100.0],  # noqa: E731
                             "b_1": [195.0] if t % 13 < 4 else []}
        ex, traci = self.make(pattern, gap_s=2, max_green_H_s=30, max_green_V_s=15)
        segs = segments(run_executor(ex, traci, 2000)["J1"])
        self.assertTrue(len(segs) > 20)
        for (phase, length), nxt in zip(segs[:-1], segs[1:]):
            if phase == "Y":
                self.assertEqual(length, 3)
            else:
                self.assertGreaterEqual(length, 7)
                self.assertEqual(nxt[0], "Y")
        self.assertLessEqual(max(l for p, l in segs if p == "H"), 30)
        self.assertLessEqual(max(l for p, l in segs if p == "V"), 15)

    def test_refuses_a_minimum_green_below_7_s(self):
        with self.assertRaises(ValueError):
            self.make(lambda t: {}, minimum_green_s=5)


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class TimeOfDay(unittest.TestCase):

    def test_dwell_transition_keeps_cycles_whole_and_restores_the_offset(self):
        import controllers as C
        p1, p2 = P.make_plan(30, 550, 10), P.make_plan(40, 650, 23)
        traci = FakeTraci()
        ex = C.TimeOfDayScheduleExecutor(traci, CONFIG, periods=[(0, p1), (900, p2), (2700, p1)])
        shown = run_executor(ex, traci, 3600)
        for tl in ("J1", "J2"):
            segs = segments(shown[tl])
            for (phase, length), nxt in zip(segs[:-1], segs[1:]):
                if phase == "Y":
                    self.assertEqual(length, 3)
                else:
                    self.assertEqual(nxt[0], "Y")               # never green to green
        j1, j2 = starts(shown["J1"], "H"), starts(shown["J2"], "H")
        # Period 1 (from 0 s): J1 H starts at multiples of 30, J2 offset 10.
        self.assertTrue(all(t % 30 == 0 for t in j1 if t < 900))
        self.assertTrue(all((t - 10) % 30 == 0 for t in j2 if t < 890))
        # Period 2: J1 switches at its first cycle end >= 900, i.e. 900; J2 offset 23 restored by dwell.
        t1 = min(t for t in j1 if t >= 900)
        self.assertEqual(t1, 900)
        self.assertTrue(all((t - t1) % 40 == 0 for t in j1 if 900 <= t < 2700))
        self.assertTrue(all((t - t1 - 23) % 40 == 0 for t in j2 if 960 <= t < 2700))
        # Period 3: J1 at its first C40 cycle end >= 2700; J2 back to offset 10.
        t3 = min(t for t in j1 if t >= 2700)
        self.assertEqual((t3 - t1) % 40, 0)
        self.assertTrue(all((t - t3) % 30 == 0 for t in j1 if t >= t3))
        self.assertTrue(all((t - t3 - 10) % 30 == 0 for t in j2 if t >= t3 + 60))
        self.assertEqual(len(ex.events), 4)

    def test_refuses_periods_that_do_not_start_at_zero(self):
        import controllers as C
        with self.assertRaises(ValueError):
            C.TimeOfDayScheduleExecutor(FakeTraci(), CONFIG, periods=[(10, P.make_plan(30, 550, 0))])


if __name__ == "__main__":
    unittest.main()
