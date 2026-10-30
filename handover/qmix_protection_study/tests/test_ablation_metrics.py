"""Unit tests (stdlib unittest; synthetic data, no SUMO) for the ablation indicators and runner guards.

    python -m unittest discover -s tests -v
"""
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")

import ablation_metrics as am  # noqa: E402


class DemandCost(unittest.TestCase):
    def rows(self, end, f):
        return [{"time": float(t), "stopped_active_count": f(t), "pending_due_count": 1 if t == 5 else 0}
                for t in range(1, end + 1)]

    def test_window_split(self):
        d, p = am.demand_and_post_cost(self.rows(3700, lambda t: 2), 3700)
        self.assertEqual(d, 2 * 3600 + 1)
        self.assertEqual(p, 2 * 100)

    def test_rejects_gaps_duplicates_and_early_end(self):
        r = self.rows(3700, lambda t: 1)
        with self.assertRaises(ValueError):
            am.demand_and_post_cost(r[:-1] + [dict(r[-2])], 3700)
        with self.assertRaises(ValueError):
            am.demand_and_post_cost(r[:100] + r[101:], 3700)
        with self.assertRaises(ValueError):
            am.demand_and_post_cost(self.rows(3500, lambda t: 1), 3500)


class FakeSource(object):
    def __init__(self):
        self.h = {}

    def lane_halting_number(self, lane):
        return self.h.get(lane, 0)


@unittest.skipUnless(os.path.isdir(os.path.join(PROTECTED, "src")), "QMIX_PROTECTED not available")
class CounterReconstruction(unittest.TestCase):
    """The reconstruction from logs must equal the protected ServiceCounters on identical inputs."""

    def test_equals_protected_service_counters(self):
        sys.path.insert(0, os.path.join(PROTECTED, "src"))
        from adaptive_qmix_protected.protection import ServiceCounters
        config = {"observation": {"lanes": dict((tl, {"H_in": am.H_IN[tl], "V_in": am.V_IN[tl]}) for tl in ("J1", "J2"))},
                  "network": {"traffic_lights": ["J1", "J2"]}}
        rng = random.Random(7)
        for trial in range(20):
            src = FakeSource()
            sc = ServiceCounters(config, src)
            lane_rows, phase_rows, ref = [], [], {}
            ph = {"J1": "H", "J2": "V"}
            for t in range(1, 400):
                for tl in ("J1", "J2"):
                    if rng.random() < 0.08:
                        ph[tl] = {"H": "Y", "Y": rng.choice("HV"), "V": "Y"}[ph[tl]]
                src.h = dict((l, rng.choice([0, 0, 0, 1, 2])) for tl in ("J1", "J2") for l in am.H_IN[tl] + am.V_IN[tl])
                for l, v in src.h.items():
                    lane_rows.append({"time": float(t), "lane": l, "queue": v})
                for tl in ("J1", "J2"):
                    phase_rows.append({"time": float(t), "intersection": tl, "actual_phase": ph[tl]})
                sc.update(dict(ph), t)
                ref[t] = dict((tl, (sc.counter[tl]["H"], sc.counter[tl]["V"])) for tl in ("J1", "J2"))
            series, summ = am.counters_from_logs(lane_rows, phase_rows)
            for t in ref:
                for tl in ("J1", "J2"):
                    self.assertEqual((series[t][tl]["c_H"], series[t][tl]["c_V"]), ref[t][tl])
            for tl in ("J1", "J2"):
                for d in ("H", "V"):
                    self.assertEqual(summ[tl][d]["max_counter"], sc.max_counter[tl][d])
                    self.assertEqual(summ[tl][d]["max_wait_to_first_green"], sc.max_wait_to_green[tl][d])
                    self.assertEqual(summ[tl][d]["open_wait_at_end"], sc.open_waits()[tl][d])


class GreenSpells(unittest.TestCase):
    def test_censored_final_spell_excluded(self):
        seq = list("HHHHHYYYVVYYYHHHHHHH")
        rows = [{"time": float(i + 1), "intersection": "J1", "actual_phase": p} for i, p in enumerate(seq)]
        sp = am.green_spells(rows, tls=("J1",))
        self.assertEqual([(d, n) for d, n, _ in sp["J1"]], [("H", 5), ("V", 2)])
        st = am.spell_stats(sp)
        self.assertEqual(st["shortest_green_s"], 2)
        self.assertEqual(st["greens_below_7s"], 2)
        self.assertAlmostEqual(st["share_2s_greens"], 0.5)


class RunnerGuards(unittest.TestCase):
    def test_prepare_refuses_existing_root(self):
        import ablation_runner as ar
        with tempfile.TemporaryDirectory() as d:
            fake = {"root": d, "fingerprint": "f", "n_cells": 0, "n_new": 0, "n_reused": 0, "models": []}
            orig = ar.build_plan
            ar.build_plan = lambda root: (fake, [], [])
            try:
                self.assertEqual(ar.cmd_prepare(d, "f"), 2)
                self.assertEqual(ar.cmd_prepare(d, "wrong"), 2)
            finally:
                ar.build_plan = orig


if __name__ == "__main__":
    unittest.main()
