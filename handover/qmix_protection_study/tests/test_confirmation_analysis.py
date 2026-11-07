"""Tests of the pre-registered confirmation analysis (plan B) on synthetic panels (no simulation)."""
import copy
import importlib
import json
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "confirmation"))
for var, default in (("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"),
                     ("AQ_FROZEN_REPOSITORY", r"C:\Users\LENOVO\QMIX_Traffic_Coordination")):
    src = os.path.join(os.environ.get(var, default), "src")
    if os.path.isdir(os.path.join(src, "adaptive_qmix")):
        sys.path.insert(0, src)
        break
try:
    importlib.import_module("adaptive_qmix.protocol.statistics")
    HAVE_FROZEN = True
except ImportError:
    HAVE_FROZEN = False

import confirmation_analysis as CA  # noqa: E402

with open(os.path.join(HERE, "..", "tools", "confirmation", "confirmation_plan.json")) as handle:
    PLAN = json.load(handle)


class Classification(unittest.TestCase):

    def test_order_and_boundaries(self):
        d = 0.3
        self.assertEqual(CA.classify(-1.0, -0.5, d), "SUPERIOR BEYOND MARGIN")
        self.assertEqual(CA.classify(-0.2, -0.01, d), "SUPERIOR")              # superiority before equivalence
        self.assertEqual(CA.classify(-0.2, 0.2, d), "EQUIVALENT")
        self.assertEqual(CA.classify(0.4, 0.9, d), "INFERIOR BEYOND MARGIN")
        self.assertEqual(CA.classify(0.05, 0.4, d), "INFERIOR")
        self.assertEqual(CA.classify(-0.5, 0.5, d), "INCONCLUSIVE")
        self.assertEqual(CA.classify(-1, -0.5, d, service_failure=True), "SERVICE FAILURE")
        self.assertEqual(CA.classify(-1, -0.5, d, not_estimable=True), "NOT ESTIMABLE")

    def test_the_plan_reserves_new_seeds_and_never_the_final_ones(self):
        seeds = [s for v in PLAN["traffic_seeds"].values() for s in v]
        self.assertEqual(len(seeds), 50)
        self.assertEqual(len(set(seeds)), 50)
        self.assertFalse(set(seeds) & set(range(3001, 3011)) | set(seeds) & set(range(3101, 3121)))
        self.assertTrue(all(s % 100 >= 51 for s in seeds))
        self.assertEqual(PLAN["statistics"]["decision_confidence"], 0.995)
        self.assertEqual([len(PLAN["learned_policies"][m]) for m in ("qmix", "vdn")], [10, 10])


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class Analysis(unittest.TestCase):

    def setUp(self):
        self.plan = copy.deepcopy(PLAN)
        self.plan["profiles"] = ["R0_reference", "R1_sparse_secondary_heavy_main"]
        self.plan["statistics"]["replicates"] = 2000
        rnd = random.Random(7)
        self.cells = []
        comparator = {}
        for profile in self.plan["profiles"]:
            for seed in self.plan["traffic_seeds"][profile]:
                comparator[(profile, seed)] = 3.0 + rnd.uniform(-0.3, 0.3)
                self.cells.append(self.row(profile, seed, "oft_g5", "", "", comparator[(profile, seed)]))
                self.cells.append(self.row(profile, seed, "actuated_min7", "", "", 4.0))
        effects = {("R0_reference", "qmix"): -1.0, ("R0_reference", "vdn"): 0.0,
                   ("R1_sparse_secondary_heavy_main", "qmix"): 1.0, ("R1_sparse_secondary_heavy_main", "vdn"): -1.0}
        for (profile, method), effect in effects.items():
            for tag in self.plan["learned_policies"][method]:
                for seed in self.plan["traffic_seeds"][profile]:
                    for arm in ("guarantee", "none"):
                        j = comparator[(profile, seed)] + effect + rnd.uniform(-0.05, 0.05) + (0.1 if arm == "guarantee" else 0)
                        self.cells.append(self.row(profile, seed, "learned:" + arm, tag, method, j))
        self.margins = {"R0_reference": 3.0, "R1_sparse_secondary_heavy_main": 3.0}

    @staticmethod
    def row(profile, seed, controller, model, method, j, status="CLEARED", open_wait=""):
        return {"scenario": profile, "seed": str(seed), "controller": controller, "model": model, "method": method,
                "status": status, "J_primary_s": str(j) if status == "CLEARED" else "", "open_wait_at_end_s": open_wait}

    def primary(self, result, profile, method):
        return [r for r in result["primary"] if r["profile"] == profile and r["method"] == method][0]

    def test_decisions_follow_the_preregistered_rules(self):
        result = CA.analyse(self.plan, self.cells, self.margins)
        self.assertEqual(self.primary(result, "R0_reference", "qmix")["category"], "SUPERIOR BEYOND MARGIN")
        self.assertEqual(self.primary(result, "R0_reference", "vdn")["category"], "EQUIVALENT")   # +0.1, delta 0.3
        self.assertEqual(self.primary(result, "R1_sparse_secondary_heavy_main", "qmix")["category"], "INFERIOR BEYOND MARGIN")
        r = self.primary(result, "R0_reference", "qmix")
        self.assertAlmostEqual(r["delta"], 0.3)
        self.assertEqual(r["confidence"], 0.995)
        self.assertTrue(all(s.get("category") is None or s["contrast"] for s in result["secondary_descriptive"]
                            if "contrast" in s))
        gmn = [s for s in result["secondary_descriptive"] if s.get("contrast", "").startswith("guarantee - none")]
        self.assertEqual(len(gmn), 4)
        self.assertAlmostEqual(gmn[0]["mean_difference"], 0.1, places=2)
        self.assertTrue(all(s["service_claim_allowed"] is False for s in result["service"]))   # 2 profiles only

    def test_an_open_wait_failure_is_a_service_failure_with_a_descriptive_sensitivity(self):
        cells = [c for c in self.cells]
        victim = [i for i, c in enumerate(cells) if c["scenario"] == "R1_sparse_secondary_heavy_main"
                  and c["method"] == "vdn" and c["controller"] == "learned:guarantee"][3]
        cells[victim] = dict(cells[victim], status="CLEARANCE_FAILURE", J_primary_s="", open_wait_at_end_s="512")
        result = CA.analyse(self.plan, cells, self.margins)
        r = self.primary(result, "R1_sparse_secondary_heavy_main", "vdn")
        self.assertEqual(r["category"], "SERVICE FAILURE")
        self.assertNotIn("ci", r)
        self.assertEqual(len(r["sensitivity_descriptive_only"]["models_kept"]), 9)
        svc = [s for s in result["service"] if s["method"] == "vdn" and s["arm"] == "guarantee"][0]
        self.assertEqual(svc["open_wait_failures"], 1)

    def test_a_missing_cell_gives_no_decision(self):
        cells = [c for c in self.cells if not (c["scenario"] == "R0_reference" and c["method"] == "qmix"
                                               and c["controller"] == "learned:guarantee" and c["seed"] == "8051")]
        r = self.primary(CA.analyse(self.plan, cells, self.margins), "R0_reference", "qmix")
        self.assertTrue(r["category"].startswith("INCOMPLETE"))


if __name__ == "__main__":
    unittest.main()
