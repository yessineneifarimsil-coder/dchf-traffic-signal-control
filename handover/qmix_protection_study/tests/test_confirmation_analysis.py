"""Tests of the pre-registered confirmation analysis (plan B) and of the A004 check, on synthetic panels.

statistics-1.2 (A004) is not available in the review environment: the tests stand the frozen statistics-1.1 file
in for it by setting the plan's reference hash to that file's hash, which exercises the hash gate and the
loading-by-path; on Windows the real A004 file is used.
"""
import copy
import hashlib
import importlib
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "confirmation"))
STATS = None
for var, default in (("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"),
                     ("AQ_FROZEN_REPOSITORY", r"C:\Users\LENOVO\QMIX_Traffic_Coordination")):
    src = os.path.join(os.environ.get(var, default), "src")
    if os.path.isdir(os.path.join(src, "adaptive_qmix")):
        sys.path.insert(0, src)
        STATS = os.path.join(src, "adaptive_qmix", "protocol", "statistics.py")
        break
try:
    importlib.import_module("numpy")
    HAVE_FROZEN = STATS is not None
except ImportError:
    HAVE_FROZEN = False

import check_statistics as CS  # noqa: E402
import confirmation_analysis as CA  # noqa: E402

with open(os.path.join(HERE, "..", "tools", "confirmation", "confirmation_plan.json")) as handle:
    PLAN = json.load(handle)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Plan(unittest.TestCase):

    def test_classification_order_and_boundaries(self):
        d = 0.3
        self.assertEqual(CA.classify(-1.0, -0.5, d), "SUPERIOR BEYOND MARGIN")
        self.assertEqual(CA.classify(-0.2, -0.01, d), "SUPERIOR")              # superiority before equivalence
        self.assertEqual(CA.classify(-0.2, 0.2, d), "EQUIVALENT")
        self.assertEqual(CA.classify(0.4, 0.9, d), "INFERIOR BEYOND MARGIN")
        self.assertEqual(CA.classify(0.05, 0.4, d), "INFERIOR")
        self.assertEqual(CA.classify(-0.5, 0.5, d), "INCONCLUSIVE")
        self.assertEqual(CA.classify(-1, -0.5, d, service_failure=True), "SERVICE FAILURE")
        self.assertEqual(CA.classify(-1, -0.5, d, not_estimable=True), "NOT ESTIMABLE")

    def test_margin_rule_of_2026_11_07(self):
        self.assertAlmostEqual(CA.margin(PLAN, 3.0), 0.15)
        self.assertAlmostEqual(CA.margin(PLAN, 1.0), 0.10)                    # floor 0.10 s
        self.assertAlmostEqual(CA.margin(PLAN, PLAN["statistics"]["equivalence_margin"]["c19_validation_J_s"]),
                               0.05 * 2.765071428571429)

    def test_the_plan_fingerprint_and_its_fields(self):
        self.assertTrue(CA.check_plan(PLAN))
        tampered = dict(PLAN, statistics=dict(PLAN["statistics"], decision_confidence=0.99))
        with self.assertRaises(CA.PlanError):
            CA.check_plan(tampered)
        seeds = [s for v in PLAN["traffic_seeds"].values() for s in v]
        self.assertEqual(len(set(seeds)), 50)
        self.assertFalse(set(seeds) & (set(range(3001, 3011)) | set(range(3101, 3121))))
        self.assertTrue(all(s % 100 >= 51 for s in seeds))
        self.assertEqual(PLAN["statistics"]["decision_confidence"], 0.995)
        self.assertEqual(PLAN["statistics"]["descriptive_confidence"], 0.95)
        self.assertEqual(PLAN["statistics"]["replicates"], 10000)
        self.assertEqual(PLAN["statistics"]["reference"]["sha256"], CS.REFERENCE_SHA256)
        self.assertEqual(set(PLAN["comparators"]["primary_controller_label"]), set(PLAN["profiles"]))
        self.assertEqual(sorted(PLAN["learned_policies"]), ["qmix", "vdn"])
        self.assertEqual(len(PLAN["idqn_exclusion"]["reasons"]), 3)
        self.assertEqual(PLAN["costs"]["total"], 2260)


@unittest.skipUnless(HAVE_FROZEN, "frozen statistics module not available")
class Analysis(unittest.TestCase):

    def setUp(self):
        self.plan = copy.deepcopy(PLAN)
        self.plan["profiles"] = ["R0_reference", "R1_sparse_secondary_heavy_main"]
        self.plan["statistics"]["replicates"] = 2000
        self.plan["statistics"]["reference"]["sha256"] = sha(STATS)       # stand-in for A004 in this environment
        self.plan["fingerprint"] = CA.plan_fingerprint(self.plan)
        self.ST = CA.load_statistics(STATS, self.plan)
        rnd = random.Random(7)
        self.cells = []
        comparator = {}
        labels = self.plan["comparators"]["primary_controller_label"]
        for profile in self.plan["profiles"]:
            for seed in self.plan["traffic_seeds"][profile]:
                comparator[(profile, seed)] = 3.0 + rnd.uniform(-0.3, 0.3)
                self.cells.append(self.row(profile, seed, labels[profile], "", "", comparator[(profile, seed)]))
                self.cells.append(self.row(profile, seed, "canonical_mp", "", "", 9.0))
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
        result = CA.analyse(self.plan, self.cells, self.margins, self.ST)
        r0q = self.primary(result, "R0_reference", "qmix")
        self.assertEqual(r0q["comparator"], "fixed:old_C19_8_5_D9")
        self.assertEqual(r0q["category"], "SUPERIOR BEYOND MARGIN")
        self.assertEqual(self.primary(result, "R0_reference", "vdn")["category"], "EQUIVALENT")    # +0.1, delta 0.15
        r1 = self.primary(result, "R1_sparse_secondary_heavy_main", "qmix")
        self.assertEqual((r1["comparator"], r1["category"]), ("oft_g5", "INFERIOR BEYOND MARGIN"))
        self.assertAlmostEqual(r0q["delta"], 0.15)
        self.assertEqual(r0q["confidence"], 0.995)
        gmn = [s for s in result["secondary_descriptive"] if s.get("contrast", "").startswith("guarantee - none")]
        self.assertEqual(len(gmn), 4)
        self.assertAlmostEqual(gmn[0]["mean_difference"], 0.1, places=2)
        self.assertTrue(all(s["service_claim_allowed"] is False for s in result["service"]))   # 2 profiles only

    def test_an_open_wait_failure_is_a_service_failure_with_a_descriptive_sensitivity(self):
        cells = list(self.cells)
        victim = [i for i, c in enumerate(cells) if c["scenario"] == "R1_sparse_secondary_heavy_main"
                  and c["method"] == "vdn" and c["controller"] == "learned:guarantee"][3]
        cells[victim] = dict(cells[victim], status="CLEARANCE_FAILURE", J_primary_s="", open_wait_at_end_s="512")
        result = CA.analyse(self.plan, cells, self.margins, self.ST)
        r = self.primary(result, "R1_sparse_secondary_heavy_main", "vdn")
        self.assertEqual(r["category"], "SERVICE FAILURE")
        self.assertNotIn("ci", r)
        self.assertEqual(len(r["sensitivity_descriptive_only"]["models_kept"]), 9)

    def test_a_missing_cell_gives_no_decision(self):
        cells = [c for c in self.cells if not (c["scenario"] == "R0_reference" and c["method"] == "qmix"
                                               and c["controller"] == "learned:guarantee" and c["seed"] == "8051")]
        r = self.primary(CA.analyse(self.plan, cells, self.margins, self.ST), "R0_reference", "qmix")
        self.assertTrue(r["category"].startswith("INCOMPLETE"))

    def test_only_the_reference_statistics_module_is_accepted(self):
        plan = copy.deepcopy(self.plan)
        plan["statistics"]["reference"]["sha256"] = CS.REFERENCE_SHA256
        with self.assertRaises(CA.PlanError):
            CA.load_statistics(STATS, plan)                  # statistics-1.1 is not statistics-1.2


@unittest.skipUnless(HAVE_FROZEN, "frozen statistics module not available")
class StatisticsCheck(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base)

    def run_check(self, candidate):
        out = os.path.join(self.base, "out.json")
        code = CS.main(["--a004", candidate, "--frozen", STATS, "--reference-sha256", sha(candidate), "--out", out])
        with open(out) as f:
            return code, json.load(f)

    def test_wrong_file_is_refused(self):
        out = os.path.join(self.base, "o.json")
        self.assertEqual(CS.main(["--a004", STATS, "--frozen", STATS, "--out", out]), 2)

    def test_identical_and_different_bootstraps_are_told_apart(self):
        code, result = self.run_check(STATS)
        self.assertEqual((code, result["verdict"]), (0, "IDENTICAL_BOOTSTRAP"))
        modified = os.path.join(self.base, "statistics_modified.py")
        with open(STATS) as f:
            text = f.read()
        text = text.replace("alpha = (1.0 - float(confidence)) / 2.0", "alpha = (1.0 - float(confidence)) / 2.5")
        with open(modified, "w") as f:
            f.write(text)
        code, result = self.run_check(modified)
        self.assertEqual((code, result["verdict"]), (0, "DIFFERENT_BOOTSTRAP"))
        self.assertFalse(result["functions"]["paired_crossed_bootstrap"]["identical"])
        self.assertFalse(result["numerical"]["deterministic 0.95"]["identical"])


if __name__ == "__main__":
    unittest.main()
