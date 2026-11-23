"""Tests of the pre-registered confirmation analysis (plan B; procedure b-crossed-bootstrap-1) and of the withdrawn,
historical A004 file check, on synthetic panels.

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
        self.assertEqual(PLAN["statistics"]["decision_confidence"], 1 - 0.05 / 12)          # one family of 12
        self.assertEqual(PLAN["statistics"]["confirmatory_family"]["size"], 12)
        self.assertAlmostEqual(CA.check_family(PLAN), 0.9958333333333333)
        self.assertEqual(PLAN["statistics"]["descriptive_confidence"], 0.95)
        self.assertEqual(PLAN["statistics"]["replicates"], 10000)
        ref = PLAN["statistics"]["reference"]
        self.assertEqual(ref["retained_procedure"], "b-crossed-bootstrap-1")
        self.assertIn("statistics-1.1", ref["name"])
        self.assertNotIn("1.2", ref["name"])
        self.assertTrue(PLAN["statistics"]["procedure"].startswith("b-crossed-bootstrap-1"))
        hist = ref["historical_statistics_1_2"]                                 # kept only as historical, not claimed
        self.assertEqual(hist["protocol_hash"], CS.REFERENCE_SHA256)
        self.assertIn("NOT CLAIMED", hist["status"])
        self.assertNotIn("sha256", PLAN["statistics"]["reference"])
        self.assertEqual(set(PLAN["comparators"]["primary_controller_label"]), set(PLAN["profiles"]))
        self.assertEqual(sorted(PLAN["learned_policies"]), ["qmix", "vdn"])
        self.assertEqual(len(PLAN["idqn_exclusion"]["reasons"]), 3)
        lc = PLAN["learned_contrasts"]                                            # rectificatif 2026-11-23
        self.assertEqual((lc["profiles"], lc["methods"], lc["reference"], lc["arm"]),
                         (["R0_reference"], ["qmix", "vdn"], "idqn", "guarantee"))
        self.assertEqual((lc["decision_confidence"], lc["evaluations_added"]), (1 - 0.05 / 12, 100))
        self.assertNotIn("sensitivity_confidence", lc)
        self.assertIn("2,470", PLAN["costs"])
        self.assertEqual(PLAN["arms"]["per_method"]["idqn"], ["guarantee", "none"])
        self.assertIn("b_runner.py plan", PLAN["costs"])                       # counted by code (amendment B)
        self.assertEqual(sorted(PLAN["amendment_B"]["deviations"]), ["B1", "B2", "B3"])


@unittest.skipUnless(HAVE_FROZEN, "frozen statistics module not available")
class Analysis(unittest.TestCase):

    def setUp(self):
        self.plan = copy.deepcopy(PLAN)
        self.plan["profiles"] = ["R0_reference", "R1_sparse_secondary_heavy_main"]
        self.plan["statistics"]["replicates"] = 2000
        self.plan["statistics"]["reference"]["module_file_sha256"] = sha(STATS)   # as freeze.json records it
        self.plan["comparators"]["primary_controller_label"]["R1_sparse_secondary_heavy_main"] = "oft_g5"  # as B1 resolves
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
        self.assertEqual(r0q["confidence"], 1 - 0.05 / 12)
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

    def test_joint_learning_contrast_without_idqn_tags_is_incomplete_not_a_crash(self):
        result = CA.analyse(self.plan, self.cells, self.margins, self.ST)
        self.assertEqual([d["method"] for d in result["joint_learning"]], ["qmix", "vdn"])
        self.assertTrue(all(d["category"].startswith("INCOMPLETE") for d in result["joint_learning"]))

    def test_service_counts_by_unit_and_no_pooled_interval(self):
        rows = [{"scenario": "R0_reference", "seed": str(s), "model": "qmix_seed{}_t1".format(m), "status": "CLEARED",
                 "open_wait_at_end_s": "", "vehicles_waiting_ge_300s": "0"} for m in range(101, 111) for s in range(8051, 8061)]
        rows[0] = dict(rows[0], status="CLEARANCE_FAILURE", open_wait_at_end_s="400")
        rows[1] = dict(rows[1], status="CLEARANCE_FAILURE", open_wait_at_end_s="400")     # same model, 2 traffics
        u = CA.unit_counts(rows, CA.open_wait)
        self.assertEqual((u["evaluations"], u["events"]), (100, 2))
        self.assertEqual((u["models"]["units"], u["models"]["units_with_event"]), (10, 1))
        self.assertEqual((u["traffics"]["units"], u["traffics"]["units_with_event"]), (10, 2))
        self.assertNotIn("cp95_two_sided", u)                                      # nothing on pooled evaluations
        lo, hi = u["models"]["cp95_two_sided"]
        self.assertTrue(lo < 0.1 < hi and u["models"]["upper95_one_sided"] < hi)   # one-sided bound is distinct
        zero = CA.unit_counts(rows[2:], CA.open_wait)
        self.assertEqual(zero["events"], 0)
        self.assertAlmostEqual(zero["models"]["upper95_one_sided"], 1 - 0.05 ** 0.1)   # 25.9 %, not 0
        self.assertGreater(zero["models"]["cp95_two_sided"][1], 0.25)
        pooled = CA.unit_counts(rows, CA.open_wait, intervals=False)
        self.assertNotIn("cp95_two_sided", pooled["models"])
        self.assertIn("zero risk", CA.UNIT_ASSUMPTIONS)

    def test_a_level_other_than_the_family_level_is_refused(self):
        plan = copy.deepcopy(self.plan)
        plan["learned_contrasts"]["decision_confidence"] = 0.975                    # the withdrawn separate family
        plan["fingerprint"] = CA.plan_fingerprint(plan)
        with self.assertRaises(CA.PlanError):
            CA.analyse(plan, self.cells, self.margins, self.ST)

    def test_a_failure_in_the_descriptive_none_arm_does_not_touch_the_guarantee_contrast(self):
        cells = [dict(c) for c in self.cells]
        victim = [i for i, c in enumerate(cells) if c["scenario"] == "R0_reference" and c["method"] == "qmix"
                  and c["controller"] == "learned:none"][0]
        cells[victim] = dict(cells[victim], status="CLEARANCE_FAILURE", J_primary_s="", open_wait_at_end_s="500")
        r = self.primary(CA.analyse(self.plan, cells, self.margins, self.ST), "R0_reference", "qmix")
        self.assertEqual(r["category"], "SUPERIOR BEYOND MARGIN")

    def test_joint_contrast_rules_and_conditional_descriptive(self):
        plan = copy.deepcopy(self.plan)
        plan["learned_policies"]["idqn"] = ["idqn_seed{}_tX".format(s) for s in range(101, 111)]
        plan["fingerprint"] = CA.plan_fingerprint(plan)
        cells = [dict(c) for c in self.cells]
        q = dict(((int(c["model"].split("_seed")[1][:3]), c["seed"]), float(c["J_primary_s"])) for c in cells
                 if c["scenario"] == "R0_reference" and c["method"] == "qmix" and c["controller"] == "learned:guarantee")
        for (seed, traffic), j in sorted(q.items()):
            for arm in ("guarantee", "none"):
                cells.append(self.row("R0_reference", traffic, "learned:" + arm, "idqn_seed{}_tX".format(seed), "idqn", j + 0.5))
        r = [d for d in CA.analyse(plan, cells, self.margins, self.ST)["joint_learning"] if d["method"] == "qmix"][0]
        self.assertEqual(r["category"], "SUPERIOR BEYOND MARGIN")               # QMIX 0.5 s below IDQN, delta 0.15
        self.assertEqual(r["conditional_descriptive_cleared_pairs"]["pairs_used"], 100)
        # an IDQN failure without open wait in the guarantee arm: NOT ESTIMABLE, conditional descriptive on 99 pairs
        i = [k for k, c in enumerate(cells) if c["method"] == "idqn" and c["controller"] == "learned:guarantee"][0]
        original = dict(cells[i])
        cells[i] = dict(cells[i], status="CLEARANCE_FAILURE", J_primary_s="")
        r = [d for d in CA.analyse(plan, cells, self.margins, self.ST)["joint_learning"] if d["method"] == "qmix"][0]
        self.assertEqual(r["category"], "NOT ESTIMABLE")
        self.assertEqual(r["conditional_descriptive_cleared_pairs"]["pairs_used"], 99)
        # with an open wait: SERVICE FAILURE comes first
        cells[i] = dict(cells[i], open_wait_at_end_s="400")
        r = [d for d in CA.analyse(plan, cells, self.margins, self.ST)["joint_learning"] if d["method"] == "qmix"][0]
        self.assertEqual(r["category"], "SERVICE FAILURE")
        # an IDQN failure in the descriptive none arm only: the guarantee contrast is decided
        cells[i] = original
        k = [n for n, c in enumerate(cells) if c["method"] == "idqn" and c["controller"] == "learned:none"][0]
        cells[k] = dict(cells[k], status="CLEARANCE_FAILURE", J_primary_s="", open_wait_at_end_s="400")
        r = [d for d in CA.analyse(plan, cells, self.margins, self.ST)["joint_learning"] if d["method"] == "qmix"][0]
        self.assertNotIn(r["category"], ("SERVICE FAILURE", "NOT ESTIMABLE"))

    def idqn_rows(self, plan):
        return [self.row("R0_reference", seed, "learned:guarantee", tag, "idqn", 3.0)
                for tag in plan["learned_policies"]["idqn"] for seed in plan["traffic_seeds"]["R0_reference"]]

    def idqn_plan(self):
        plan = copy.deepcopy(self.plan)
        plan["learned_policies"]["idqn"] = ["idqn_seed{}_tX".format(s) for s in range(101, 111)]
        plan["fingerprint"] = CA.plan_fingerprint(plan)
        return plan

    def idqn_service(self, plan, rows):
        return [s for s in CA.service(rows, plan) if s["method"] == "idqn" and s["arm"] == "guarantee"][0]

    def test_idqn_service_statement_on_its_R0_scope_only(self):
        plan = self.idqn_plan()
        rows = self.idqn_rows(plan)
        self.assertEqual(len(rows), 100)
        s = self.idqn_service(plan, rows)
        self.assertEqual((s["coverage"]["expected"], s["coverage"]["present"]), (100, 100))
        self.assertTrue(s["service_claim_allowed"])                      # 100 complete cells, no failure
        self.assertEqual(s["service_claim_scope"], ["R0_reference"])     # never generalised to R1-R4
        self.assertNotIn("cp95_two_sided", s["failure"]["models"])       # no pooled interval

    def test_idqn_missing_cell_forbids_the_statement(self):
        plan = self.idqn_plan()
        s = self.idqn_service(plan, self.idqn_rows(plan)[1:])
        self.assertEqual(len(s["coverage"]["missing"]), 1)
        self.assertFalse(s["service_claim_allowed"])

    def test_a_duplicate_never_replaces_a_missing_cell(self):
        plan = self.idqn_plan()
        rows = self.idqn_rows(plan)
        rows[0] = dict(rows[1])                                          # 100 rows, one identity twice
        s = self.idqn_service(plan, rows)
        self.assertEqual(s["n"], 100)
        self.assertEqual((len(s["coverage"]["missing"]), len(s["coverage"]["duplicates"])), (1, 1))
        self.assertFalse(s["coverage"]["complete"])
        self.assertFalse(s["service_claim_allowed"])

    def test_an_idqn_cell_outside_R0_is_unexpected(self):
        plan = self.idqn_plan()
        rows = self.idqn_rows(plan) + [self.row("R1_sparse_secondary_heavy_main", 8151, "learned:guarantee",
                                                "idqn_seed101_tX", "idqn", 3.0)]
        s = self.idqn_service(plan, rows)
        self.assertEqual(len(s["coverage"]["unexpected"]), 1)
        self.assertFalse(s["service_claim_allowed"])

    def test_qmix_vdn_coverage_rule_unchanged(self):
        plan = copy.deepcopy(PLAN)
        tags = plan["learned_policies"]["qmix"]
        rows = [self.row(p, seed, "learned:guarantee", t, "qmix", 3.0) for t in tags
                for p in plan["traffic_seeds"] for seed in plan["traffic_seeds"][p]]
        self.assertEqual(len(rows), 500)
        s = [x for x in CA.service(rows, plan) if x["method"] == "qmix"][0]
        self.assertEqual(s["coverage"]["expected"], 500)
        self.assertTrue(s["service_claim_allowed"])
        s = [x for x in CA.service(rows[:-1], plan) if x["method"] == "qmix"][0]
        self.assertFalse(s["service_claim_allowed"])

    def test_an_unresolved_primary_is_refused(self):
        plan = copy.deepcopy(self.plan)
        plan["comparators"]["primary_controller_label"]["R1_sparse_secondary_heavy_main"] = "auto (B1)"
        plan["fingerprint"] = CA.plan_fingerprint(plan)
        with self.assertRaises(CA.PlanError):
            CA.analyse(plan, self.cells, self.margins, self.ST)

    def test_only_the_reference_statistics_module_is_accepted(self):
        plan = copy.deepcopy(self.plan)
        plan["statistics"]["reference"]["module_file_sha256"] = CS.REFERENCE_SHA256
        with self.assertRaises(CA.PlanError):
            CA.load_statistics(STATS, plan)                  # another file hash is refused
        plan["statistics"]["reference"]["module_file_sha256"] = "recorded in freeze.json"
        with self.assertRaises(CA.PlanError):
            CA.load_statistics(STATS, plan)                  # no digest, no load
        self.assertTrue(CA.load_statistics(STATS, plan, sha(STATS)))


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
