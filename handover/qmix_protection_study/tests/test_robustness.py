"""Robustness tooling tests (no SUMO): scenario generator, N-adapter, plan constants.

    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "robustness"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")
HAVE_PROTECTED = os.path.isdir(os.path.join(PROTECTED, "src"))
if HAVE_PROTECTED:
    sys.path.insert(0, os.path.join(PROTECTED, "src"))

import scenario_traffic as st  # noqa: E402


class Generator(unittest.TestCase):
    def setUp(self):
        self.spec = st.load_spec()

    def test_exact_counts_determinism_and_ids(self):
        for sc, s in self.spec["scenarios"].items():
            seed = s["seeds"][0]
            a, b = st.generate(self.spec, sc, seed), st.generate(self.spec, sc, seed)
            self.assertEqual(a, b)
            self.assertEqual(len(a), sum(x["count"] for x in s["streams"].values()))
            for name, x in s["streams"].items():
                self.assertEqual(sum(r["stream"] == name for r in a), x["count"])
            self.assertTrue(all(0 <= r["depart"] < 3600 for r in a))
            self.assertNotEqual(a, st.generate(self.spec, sc, s["seeds"][1]))

    def test_profiles_respected(self):
        tail = st.generate(self.spec, "R4_isolated_tail", 8401)
        self.assertFalse([r for r in tail if r["stream"] in ("WE", "EW") and r["depart"] >= 3000])
        late = sum(1 for r in tail if r["stream"] not in ("WE", "EW") and r["depart"] >= 3000)
        self.assertTrue(20 <= late <= 100, late)          # expectation 4 x 300 x 150/3150 = 57
        tv = st.generate(self.spec, "R3_time_varying", 8301)
        mid = sum(1 for r in tv if r["stream"] == "WE" and 900 <= r["depart"] < 2700)
        self.assertTrue(abs(mid - 900 * 1.4 * 1800 / (1.4 * 1800 + 0.6 * 1800)) < 60, mid)

    def test_seed_guards_and_constants(self):
        with self.assertRaises(ValueError):
            st.generate(self.spec, "R0_reference", 3001)
        with self.assertRaises(ValueError):
            st.generate(self.spec, "R0_reference", 9305)
        all_seeds = [x for s in self.spec["scenarios"].values() for x in s["seeds"]]
        self.assertEqual(len(all_seeds), len(set(all_seeds)))
        if HAVE_PROTECTED:
            from adaptive_qmix import rng
            self.assertEqual((rng.MASTER_ENTROPY, rng.EXPERIMENT_NAMESPACE), (st.MASTER_ENTROPY, st.EXPERIMENT_NAMESPACE))
            self.assertEqual(rng.NAMESPACE_CODES["traffic_manifest"], st.TRAFFIC_NAMESPACE)
            self.assertEqual(rng.NAMESPACE_CODES["sumo_episode"], st.SUMO_NAMESPACE)
            from adaptive_qmix.traffic import FAMILY_CODES
            self.assertNotIn(st.FAMILY_CODE, FAMILY_CODES.values())

    def test_writer_refuses_existing_and_records_N(self):
        recs = st.generate(self.spec, "R2_single_secondary_trickle", 8201)
        vt = {"id": "car", "length": 5.0, "minGap": 2.5, "accel": 2.6, "decel": 4.5, "sigma": 0.5, "maxSpeed": 13.89,
              "departLane": "free", "departPos": "base", "departSpeed": "max"}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m")
            meta = st.write(self.spec, "R2_single_secondary_trickle", 8201, recs, p, vt)
            self.assertEqual(meta["scheduled_total"], 1860)
            with self.assertRaises(FileExistsError):
                st.write(self.spec, "R2_single_secondary_trickle", 8201, recs, p, vt)


@unittest.skipUnless(HAVE_PROTECTED, "QMIX_PROTECTED not available")
class Adapter(unittest.TestCase):
    def _ledger_and_trips(self, n):
        recs = [{"vehicle_id": "v{}".format(i), "depart": i % 3600} for i in range(n)]
        trips = dict(("v{}".format(i), {"waitingTime": str(i % 7), "departDelay": "0.5", "timeLoss": "1",
                                       "duration": "60", "waitingCount": "1"}) for i in range(n))
        return recs, trips

    def test_equivalence_at_2800_and_denominator_otherwise(self):
        import adaptive_qmix.ledger as L
        import adaptive_qmix.metrics as M
        import n_adapter
        original_metrics = M.scheduled_demand_metrics
        recs, trips = self._ledger_and_trips(2800)
        ref = L.VehicleLedger(recs)
        for v in ref.scheduled:
            ref.inserted_at[v] = 0.0
            ref.completed_at[v] = 1.0
        expected = original_metrics(ref, trips, "CLEARED")
        n_adapter.install()
        try:
            led = L.VehicleLedger(recs)
            fresh = n_adapter._INSTALLED["ledger_init"]
            orig_obj = L.VehicleLedger.__new__(L.VehicleLedger)
            fresh(orig_obj, recs)
            self.assertEqual(vars(L.VehicleLedger(recs)), vars(orig_obj))
            for v in led.scheduled:
                led.inserted_at[v] = 0.0
                led.completed_at[v] = 1.0
            self.assertEqual(M.scheduled_demand_metrics(led, trips, "CLEARED"), expected)
            import adaptive_qmix_protected.evaluation as PE
            import adaptive_qmix.baselines.runner as BR
            self.assertIs(PE.scheduled_demand_metrics, M.scheduled_demand_metrics)
            self.assertIs(BR.scheduled_demand_metrics, M.scheduled_demand_metrics)
            recs2, trips2 = self._ledger_and_trips(1500)
            led2 = L.VehicleLedger(recs2)
            for v in led2.scheduled:
                led2.inserted_at[v] = 0.0
                led2.completed_at[v] = 1.0
            out = M.scheduled_demand_metrics(led2, trips2, "CLEARED")
            total = sum(i % 7 + 0.5 for i in range(1500))
            self.assertAlmostEqual(out["J_primary_mean_scheduled_waiting_burden_s"], total / 1500.0)
            self.assertEqual(out["J_denominator_scheduled_total"], 1500)
        finally:
            n_adapter.uninstall()
        with self.assertRaises(Exception):
            L.VehicleLedger(self._ledger_and_trips(1500)[0])

    def test_fixed_plans_equal_frozen_make_plan(self):
        import evaluate_any as ea
        from adaptive_qmix.baselines.plans import make_plan, validate_plan
        self.assertEqual(ea.PLANS["old_C19_8_5_D9"], make_plan(19, 577, 9))
        self.assertEqual(ea.PLANS["min7_C25_12_7_D0"], make_plan(25, 606, 0))
        for p in ea.PLANS.values():
            validate_plan(p)


if __name__ == "__main__":
    unittest.main()
