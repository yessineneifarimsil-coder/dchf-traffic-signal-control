"""Tests of tools/robustness/robustness_analysis.py on synthetic runner outputs (no SUMO, stdlib only).

    python -m unittest discover -s tests -v

The synthetic root has the layout robustness_runner.py writes: plan.json, manifests/<scenario>_<seed>.*,
manifests_sha256.json, checkpoints/, cells/<scenario>/<seed>/<controller or model/arm>/ with the files the
evaluator writes. The two scenarios schedule different numbers of vehicles (28 and 18) so that any use of a
constant denominator would show.
"""
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "robustness"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import robustness_analysis as ra  # noqa: E402

SCENARIOS = {"R0_reference": (28, (8001, 8002)), "R2_single_secondary_trickle": (18, (8201, 8202))}
CLASSICAL = ["fixed:old_C19_8_5_D9", "fixed:min7_C25_12_7_D0", "canonical_mp", "p5:none", "p5:both"]
MODELS = ["qmix_seed101_t350000", "idqn_seed102_t300000"]
ARMS = ["none", "guarantee", "both"]
END = 3700
# Cycle: H 10 s, Y 3 s, V 7 s, Y 3 s.
PATTERN = ["H"] * 10 + ["Y"] * 3 + ["V"] * 7 + ["Y"] * 3


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def write_csv(path, fields, records):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def counters(phases, queues):
    """The protected rule: 0 on green, +1 while a vehicle halts on red, else 0."""
    c = {"H": 0, "V": 0}
    out = []
    for phase, q in zip(phases, queues):
        for d in ("H", "V"):
            c[d] = 0 if phase == d else (c[d] + 1 if q[d] >= 1 else 0)
        out.append(dict(c))
    return out


class World(object):
    """A complete synthetic robustness root; defects are injected per cell."""

    def __init__(self, base):
        self.root = os.path.join(base, "robustness_root")
        os.makedirs(os.path.join(self.root, "manifests"))
        os.makedirs(os.path.join(self.root, "checkpoints"))
        models = []
        for tag in MODELS:
            path = os.path.join(self.root, "checkpoints", tag + ".pth")
            with open(path, "wb") as handle:
                handle.write(tag.encode())
            models.append({"tag": tag, "sha256": sha(path)})
        cells = []
        for scenario, (n, seeds) in sorted(SCENARIOS.items()):
            for seed in seeds:
                prefix = os.path.join(self.root, "manifests", "{}_{}".format(scenario, seed))
                with open(prefix + ".csv", "w") as handle:
                    handle.write("vehicle_id\n" + "\n".join("v{}".format(i) for i in range(n)) + "\n")
                with open(prefix + ".metadata.json", "w") as handle:
                    json.dump({"scenario": scenario, "seed_value": seed, "scheduled_total": n}, handle)
                for c in CLASSICAL:
                    cells.append({"scenario": scenario, "seed": seed, "controller": c,
                                  "directory": os.path.join("cells", scenario, str(seed), c.replace(":", "__"))})
                for m in MODELS:
                    for arm in ARMS:
                        cells.append({"scenario": scenario, "seed": seed, "controller": "learned:" + arm,
                                      "model": m, "directory": os.path.join("cells", scenario, str(seed), m, arm)})
        hashes = dict((name, sha(os.path.join(self.root, "manifests", name)))
                      for name in sorted(os.listdir(os.path.join(self.root, "manifests"))))
        with open(os.path.join(self.root, "manifests_sha256.json"), "w") as handle:
            json.dump(hashes, handle)
        self.plan = {"fingerprint": "f" * 64, "cells": cells, "models": models,
                     "analysis_sha256": sha(ra.__file__)}
        with open(os.path.join(self.root, "plan.json"), "w") as handle:
            json.dump(self.plan, handle)
        self.n = dict((s, v[0]) for s, v in SCENARIOS.items())

    def cell(self, cell, j_wait=2.0, fail=False, j_declared=None, interventions=(), extra_red_tail=0,
             logged_counter_offset=0, short_green=False, sumo_mismatch=0):
        """Write one cell. j_wait: waitingTime of every vehicle (J = j_wait when cleared)."""
        d = os.path.join(self.root, cell["directory"])
        os.makedirs(d)
        n = self.n[cell["scenario"]]
        end = 7200 if fail else END
        pattern = list(PATTERN)
        if short_green:
            pattern = ["H"] * 10 + ["Y"] * 3 + ["V"] * 2 + ["Y"] * 3
        phases = [pattern[(t - 1) % len(pattern)] for t in range(1, end + 1)]
        queues = [{"H": 0, "V": 1} for _ in range(end)]
        if fail or extra_red_tail:
            tail = (end - 3600) if fail else extra_red_tail
            for i in range(end - tail, end):
                phases[i] = "H"
        series = counters(phases, queues)
        tls = ("J1", "J2")
        write_csv(os.path.join(d, "signal_phases.csv"), ["time", "intersection", "actual_phase"],
                  [{"time": t, "intersection": tl, "actual_phase": phases[t - 1]}
                   for t in range(1, end + 1) for tl in tls])
        write_csv(os.path.join(d, "service_counters.csv"),
                  ["episode_index", "time", "intersection", "executor_state", "q_H", "q_V", "c_H", "c_V",
                   "wait_start_H", "wait_start_V"],
                  [{"episode_index": 0, "time": t, "intersection": tl, "executor_state": phases[t - 1],
                    "q_H": 0, "q_V": 1, "c_H": series[t - 1]["H"],
                    "c_V": series[t - 1]["V"] + (logged_counter_offset if t == 100 else 0),
                    "wait_start_H": "", "wait_start_V": ""} for t in range(1, end + 1) for tl in tls])
        write_csv(os.path.join(d, "reward_seconds.csv"), ["time", "stopped_active_count", "pending_due_count"],
                  [{"time": t, "stopped_active_count": 1 if t <= 3600 else 0, "pending_due_count": 0}
                   for t in range(1, end + 1)])
        write_csv(os.path.join(d, "episode_summary.csv"), ["end_time"], [{"end_time": end}])
        with open(os.path.join(d, "tripinfo.xml"), "w") as handle:
            handle.write("<tripinfos>\n")
            for i in range(n):
                arrival = "-1.00" if (fail and i == n - 1) else "100.00"
                handle.write('<tripinfo id="v{}" depart="0" departDelay="0.00" arrival="{}" waitingTime="{}" '
                             'timeLoss="{}"/>\n'.format(i, arrival, j_wait, j_wait + 1))
            handle.write("</tripinfos>\n")
        valid = not fail
        metrics = {"clearance_status": "CLEARANCE_FAILURE" if fail else "CLEARED", "J_primary_valid": valid,
                   "J_primary_mean_scheduled_waiting_burden_s": (j_declared if j_declared is not None else j_wait)
                   if valid else float("nan"),
                   "mean_completed_time_loss_s": j_wait + 1, "completed_count": n - 1 if fail else n,
                   "scheduled_count": n, "N_scheduled": n}
        with open(os.path.join(d, "evaluation_metrics.json"), "w") as handle:
            json.dump(metrics, handle)
        kind = cell["controller"].split(":")[0]
        if kind in ("learned", "p5"):
            write_csv(os.path.join(d, "protection_decisions.csv"), ["decision_time", "intervention"],
                      [{"decision_time": t, "intervention": k} for t, k in interventions])
            with open(os.path.join(d, "protection_record.json"), "w") as handle:
                json.dump({"sumo_index_mismatch_s": sumo_mismatch, "sumo_state_mismatch_s": 0}, handle)
        return d

    def fill(self, special=None):
        special = special or {}
        for cell in self.plan["cells"]:
            key = (cell["scenario"], cell["seed"], cell["controller"], cell.get("model", ""))
            if special.get(key) == "skip":
                continue
            kwargs = dict(special.get(key, {}))
            if "j_wait" not in kwargs:
                kind = cell["controller"].split(":")[0]
                kwargs["j_wait"] = {"fixed": 2.0, "canonical_mp": 4.0, "p5": 3.5, "learned": 3.0}[kind]
            self.cell(cell, **kwargs)


class Analysis(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.world = World(self.base)
        self.out = os.path.join(self.base, "analysis")

    def tearDown(self):
        shutil.rmtree(self.base)

    def read(self, name):
        with open(os.path.join(self.out, name)) as handle:
            return json.load(handle)

    def test_a_clean_world_passes_and_uses_the_manifest_n(self):
        self.world.fill()
        summary = ra.analyse(self.world.root, self.out)
        self.assertTrue(summary["technical_all_ok"], self.read("technical_checks.json"))
        self.assertEqual(summary["cells_analysed"], len(self.world.plan["cells"]))
        with open(os.path.join(self.out, "cells.csv")) as handle:
            cells = list(csv.DictReader(handle))
        for c in cells:
            n = SCENARIOS[c["scenario"]][0]
            self.assertEqual(int(c["N"]), n)
            self.assertAlmostEqual(float(c["D_bar_s"]), 3600.0 / n, places=9)   # D = 3600 veh-s
            self.assertAlmostEqual(float(c["J_from_tripinfo_s"]), float(c["J_primary_s"]), places=12)
        with open(os.path.join(self.out, "REPORT.md")) as handle:
            report = handle.read()
        self.assertIn("NOT EVALUATED", report)                 # no guarantee intervention at all
        self.assertNotIn("FAILED", report)

    def test_a_constant_denominator_is_detected(self):
        """A run whose J was divided by 2800 instead of N = 18 fails the consistency check."""
        cell = [c for c in self.world.plan["cells"] if c["scenario"] == "R2_single_secondary_trickle"
                and c["controller"] == "fixed:min7_C25_12_7_D0"][0]
        key = (cell["scenario"], cell["seed"], cell["controller"], "")
        self.world.fill({key: {"j_wait": 2.0, "j_declared": 2.0 * 18 / 2800.0}})
        summary = ra.analyse(self.world.root, self.out)
        self.assertFalse(summary["technical_all_ok"])
        checks = self.read("technical_checks.json")
        self.assertFalse(checks["T5_consistency"]["ok"])
        with open(os.path.join(self.out, "REPORT.md")) as handle:
            self.assertIn("no scientific statement is made", handle.read())

    def test_failures_are_kept_never_given_a_j_and_excluded_from_pairs(self):
        key = ("R0_reference", 8001, "learned:none", "idqn_seed102_t300000")
        self.world.fill({key: {"fail": True}})
        ra.analyse(self.world.root, self.out)
        with open(os.path.join(self.out, "cells.csv")) as handle:
            failed = [c for c in csv.DictReader(handle) if c["status"] != "CLEARED"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["J_primary_s"], "")
        self.assertEqual(json.loads(failed[0]["unfinished_ids"]), ["v27"])
        self.assertTrue(float(failed[0]["D_bar_s"]) > 0)                     # defined for a failure
        s2 = [r for r in self.read("s2_latent.json") if r["scenario"] == "R0_reference" and r["method"] == "idqn"]
        self.assertEqual(s2[0]["failures"], 1)
        s3 = [r for r in self.read("s3_costs.json") if r["scenario"] == "R0_reference" and r["method"] == "idqn"]
        for r in s3:
            self.assertEqual((r["pairs"], r["J_comparable_pairs"]), (2, 1))
        s4 = [r for r in self.read("s4_fixed_plans.json") if r["scenario"] == "R0_reference"
              and r["method"] == "idqn" and r["arm"] == "none"]
        for r in s4:
            self.assertEqual((r["pairs"], r["pairs_excluded_not_both_cleared"]), (1, 1))
            self.assertEqual((r["models_with_a_pair"], r["models_all_traffics"]), (1, 0))

    def test_guarantee_cost_is_evaluated_only_with_an_intervention_during_the_demand(self):
        during = ("R0_reference", 8001, "learned:guarantee", "qmix_seed101_t350000")
        after = ("R2_single_secondary_trickle", 8201, "learned:guarantee", "qmix_seed101_t350000")
        self.world.fill({during: {"interventions": [(1200, "guarantee")]},
                         after: {"interventions": [(3700, "guarantee")]}})
        ra.analyse(self.world.root, self.out)
        s3 = dict(((r["scenario"], r["method"], r["arm"]), r) for r in self.read("s3_costs.json"))
        self.assertEqual(s3[("R0_reference", "qmix", "guarantee")]["guarantee_cost_during_demand"], "EVALUATED")
        self.assertTrue(s3[("R2_single_secondary_trickle", "qmix", "guarantee")]
                        ["guarantee_cost_during_demand"].startswith("NOT EVALUATED"))

    def test_a_failure_under_the_guarantee_forbids_the_service_statement(self):
        key = ("R2_single_secondary_trickle", 8202, "learned:both", "qmix_seed101_t350000")
        self.world.fill({key: {"fail": True}})
        ra.analyse(self.world.root, self.out)
        s1 = self.read("s1_service.json")
        self.assertFalse(s1["R2_single_secondary_trickle"]["S1_statement_allowed"])
        self.assertTrue(s1["R0_reference"]["S1_statement_allowed"])
        failures = s1["R2_single_secondary_trickle"]["learned:both"]["failures"]
        self.assertEqual(len(failures), 1)
        self.assertIsNotNone(failures[0]["open_wait_at_end_s"])
        checks = self.read("technical_checks.json")
        self.assertFalse(checks["T3_protection_contracts"]["ok"])        # its counter exceeded 127 s

    def test_contract_and_signal_violations_fail_the_technical_criteria(self):
        g = ("R0_reference", 8002, "learned:guarantee", "idqn_seed102_t300000")
        b = ("R0_reference", 8002, "p5:both", "")
        m = ("R0_reference", 8001, "learned:both", "idqn_seed102_t300000")
        self.world.fill({g: {"extra_red_tail": 200}, b: {"short_green": True}, m: {"sumo_mismatch": 3}})
        ra.analyse(self.world.root, self.out)
        checks = self.read("technical_checks.json")
        self.assertEqual(len(checks["T3_protection_contracts"]["counter_above_127"]), 1)
        self.assertEqual(len(checks["T3_protection_contracts"]["green_below_7_in_both"]), 1)
        self.assertEqual(len(checks["T2_sumo_signals"]["runs_with_mismatch"]), 1)
        self.assertFalse(checks["all_ok"])

    def test_a_logged_counter_that_does_not_recompute_is_reported(self):
        key = ("R0_reference", 8001, "canonical_mp", "")
        self.world.fill({key: {"logged_counter_offset": 5}})
        ra.analyse(self.world.root, self.out)
        problems = self.read("technical_checks.json")["T5_consistency"]["cells_with_problems"]
        self.assertTrue(any("differ from their recomputation" in p for c in problems for p in c["problems"]))

    def test_missing_cells_stop_the_analysis_unless_declared(self):
        key = ("R0_reference", 8001, "learned:both", "qmix_seed101_t350000")
        self.world.fill({key: "skip"})
        with self.assertRaises(ra.AnalysisError):
            ra.analyse(self.world.root, self.out)
        directory = os.path.join("cells", "R0_reference", "8001", "qmix_seed101_t350000", "both")
        summary = ra.analyse(self.world.root, self.out, declared_missing=[directory])
        self.assertEqual(summary["cells_missing_declared"], [directory])
        self.assertEqual(summary["cells_analysed"], len(self.world.plan["cells"]) - 1)

    def test_applied_once_and_bound_to_the_plan(self):
        self.world.fill()
        ra.analyse(self.world.root, self.out)
        with self.assertRaises(ra.AnalysisError):
            ra.analyse(self.world.root, self.out)
        self.world.plan["analysis_sha256"] = "0" * 64
        with open(os.path.join(self.world.root, "plan.json"), "w") as handle:
            json.dump(self.world.plan, handle)
        with self.assertRaises(ra.AnalysisError):
            ra.analyse(self.world.root, os.path.join(self.base, "other"))

    def test_a_manifest_changed_after_preparation_fails_t4(self):
        self.world.fill()
        path = os.path.join(self.world.root, "manifests", "R0_reference_8001.csv")
        with open(path, "a") as handle:
            handle.write("tampered\n")
        ra.analyse(self.world.root, self.out)
        checks = self.read("technical_checks.json")
        self.assertFalse(checks["T4_hashes"]["ok"])


if __name__ == "__main__":
    unittest.main()
