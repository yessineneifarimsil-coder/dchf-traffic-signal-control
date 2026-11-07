"""Tests of tools/article_analyses (Clopper-Pearson, J(cycle), guarantee diagnostic), stdlib only, no SUMO."""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "article_analyses"))

import clopper_pearson as CP  # noqa: E402
import guarantee_diagnostic as GD  # noqa: E402
import j_cycle_curve as JC  # noqa: E402


def comb(n, k):
    out = 1
    for i in range(1, k + 1):
        out = out * (n - k + i) // i
    return out


def binom_cdf(k, n, p):
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))


class ClopperPearson(unittest.TestCase):

    def test_bounds_satisfy_their_defining_equalities(self):
        for k, n in ((1, 50), (4, 50), (5, 10), (6, 300), (35, 750), (49, 50)):
            lo, hi = CP.clopper_pearson(k, n)
            self.assertAlmostEqual(1 - binom_cdf(k - 1, n, lo), 0.025, places=9)     # P(X >= k | lo)
            self.assertAlmostEqual(binom_cdf(k, n, hi), 0.025, places=9)             # P(X <= k | hi)

    def test_closed_forms_at_the_edges(self):
        for n in (10, 50, 300, 750):
            lo, hi = CP.clopper_pearson(0, n)
            self.assertEqual(lo, 0.0)
            self.assertAlmostEqual(hi, 1 - 0.025 ** (1.0 / n), places=10)
            lo, hi = CP.clopper_pearson(n, n)
            self.assertAlmostEqual(lo, 0.025 ** (1.0 / n), places=10)
            self.assertEqual(hi, 1.0)
            self.assertAlmostEqual(CP.one_sided_upper_zero(n), 1 - 0.05 ** (1.0 / n), places=12)
        self.assertAlmostEqual(CP.clopper_pearson(5, 10)[0], 0.187086, places=5)

    def test_event_definitions(self):
        row = {"status": "CLEARANCE_FAILURE", "open_wait_at_end_s": "412", "vehicles_waiting_ge_300s": "1"}
        self.assertEqual(CP.events_of(row, "robustness"), {"failure": True, "open_wait": True, "wait_ge_300s": True})
        row = {"status": "CLEARED", "open_wait_at_end_s": "", "max_vehicle_waiting_s": "299.9"}
        self.assertEqual(CP.events_of(row, "ablation"), {"failure": False, "open_wait": False, "wait_ge_300s": False})

    def test_on_the_ablation_table_when_present(self):
        path = os.path.join(HERE, "..", "analysis", "ablation", "cells.csv")
        if not os.path.isfile(path):
            self.skipTest("ablation table absent")
        with open(path) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 600)
        pooled = dict((r["event"], r) for r in CP.pooled(rows, "ablation", lambda r: r["arm"] in ("guarantee", "both"), "g"))
        self.assertEqual((pooled["failure"]["k"], pooled["failure"]["n"]), (0, 300))


class JCycle(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base)

    def run_dir(self, root, name, plan, seed, j, status="CLEARED", family="benchmark_design"):
        d = os.path.join(self.base, root, name, str(seed))
        os.makedirs(d)
        c, gh, gv, off = plan
        m = {"controller": "optimized_fixed_timing", "traffic_family": family, "traffic_seed": seed,
             "phase_parameters": {"cycle_s": c, "green_H_s": gh, "green_V_s": gv, "offset_s": off, "yellow_s": 3},
             "clearance_status": status, "J_primary_valid": status == "CLEARED",
             "J_primary_mean_scheduled_waiting_burden_s": j if status == "CLEARED" else float("nan")}
        with open(os.path.join(d, "evaluation_metrics.json"), "w") as f:
            json.dump(m, f)

    def test_curve_validity_conflicts_and_minimum_green(self):
        plans = {(19, 8, 5, 9): 2.7, (20, 7, 7, 10): 2.9, (40, 22, 12, 23): 3.4, (40, 20, 14, 0): 3.6,
                 (60, 30, 24, 5): 5.0}
        for plan, j in plans.items():
            for seed in JC.DESIGN_SEEDS:
                self.run_dir("orig", "p{}".format(plan), plan, seed, j + seed / 1e4)
        for seed in JC.DESIGN_SEEDS:                       # a failing plan: invalid, never ranked
            self.run_dir("orig", "fail", (16, 5, 5, 0), seed, 1.0, status="CLEARANCE_FAILURE" if seed == 2003 else "CLEARED")
        self.run_dir("audit", "dup", (19, 8, 5, 9), 2001, 2.7 + 2001 / 1e4)            # agreeing duplicate
        self.run_dir("orig", "val", (19, 8, 5, 9), 2101, 9.9, family="benchmark_validation")
        runs, conflicts, _files = JC.collect([os.path.join(self.base, "orig"), os.path.join(self.base, "audit")])
        self.assertEqual(conflicts, [])
        scores = JC.plan_scores(runs)
        self.assertFalse(scores[(16, 5, 5, 0)]["valid"])
        g5 = dict((r["cycle_s"], r) for r in JC.curve(scores, 5))
        self.assertEqual(g5[40]["best_plan"], [40, 22, 12, 23])
        self.assertEqual(g5[16]["valid"], 0)
        m7 = dict((r["cycle_s"], r) for r in JC.curve(scores, 7))
        self.assertNotIn(19, m7)                           # 8/5 is not admissible under 7 s
        self.assertEqual(JC.best(scores)["plan"], [19, 8, 5, 9])
        self.assertEqual(JC.best(scores, 40, 140)["plan"], [40, 22, 12, 23])
        self.assertEqual(JC.best(scores, min_green=7)["plan"], [20, 7, 7, 10])
        self.run_dir("audit", "conflict", (20, 7, 7, 10), 2002, 7.7)
        _runs, conflicts, _files = JC.collect([os.path.join(self.base, "orig"), os.path.join(self.base, "audit")])
        self.assertEqual(len(conflicts), 1)


class GuaranteeDiagnostic(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.root = os.path.join(self.base, "rob")
        self.analysis = os.path.join(self.base, "analysis")
        os.makedirs(os.path.join(self.root, "manifests"))
        os.makedirs(self.analysis)
        with open(os.path.join(self.root, "manifests", "R2_single_secondary_trickle_8203.csv"), "w") as f:
            f.write("vehicle_id,depart,stream\nv1,0,WE\nv2,5,N1S1\nv3,9,N1S1\n")
        self.cell("idqn_seed107_t300000", "guarantee", waits={"v1": 3, "v2": 400, "v3": 10},
                  interventions=[{"decision_time": "100", "intervention": "guarantee"}])
        self.cell("idqn_seed107_t300000", "none", waits={"v1": 2, "v2": 30, "v3": 5}, interventions=[])
        self.write("pairs.csv", [
            {"scenario": "R2_single_secondary_trickle", "seed": "8203", "model": "idqn_seed107_t300000",
             "method": "idqn", "arm": "guarantee", "status_none": "CLEARED", "status_arm": "CLEARED",
             "dJ_whole_episode_s": "0.8", "dD_bar_demand_window_s": "-0.1"},
            {"scenario": "R2_single_secondary_trickle", "seed": "8204", "model": "idqn_seed107_t300000",
             "method": "idqn", "arm": "guarantee", "status_none": "CLEARED", "status_arm": "CLEARED",
             "dJ_whole_episode_s": "-0.2", "dD_bar_demand_window_s": "0.3"}])
        self.write("cells.csv", [
            {"scenario": "R2_single_secondary_trickle", "seed": "8203", "model": "qmix_seed101_t350000",
             "method": "qmix", "arm": "both", "interventions_guarantee_demand": "0",
             "interventions_guarantee_after": "2"},
            {"scenario": "R2_single_secondary_trickle", "seed": "8203", "model": "qmix_seed102_t350000",
             "method": "qmix", "arm": "guarantee", "interventions_guarantee_demand": "0",
             "interventions_guarantee_after": "0"}])

    def tearDown(self):
        shutil.rmtree(self.base)

    def write(self, name, records):
        with open(os.path.join(self.analysis, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0]))
            w.writeheader()
            w.writerows(records)

    def cell(self, model, arm, waits, interventions):
        d = os.path.join(self.root, "cells", "R2_single_secondary_trickle", "8203", model, arm)
        os.makedirs(d)
        # J1: H until 100, yellow 101-103 (guarantee), V 104-113, yellow 114-116, H 117-196 (80 s), Y, V ...
        seq = ["H"] * 100 + ["Y"] * 3 + ["V"] * 10 + ["Y"] * 3 + ["H"] * 80 + ["Y"] * 3 + ["V"] * 5 + ["Y"] * 3 + ["H"] * 20
        j2 = ["H"] * len(seq)
        with open(os.path.join(d, "signal_phases.csv"), "w") as f:
            f.write("time,intersection,actual_phase\n")
            for t, (a, b) in enumerate(zip(seq, j2), start=1):
                f.write("{},J1,{}\n{},J2,{}\n".format(t, a, t, b))
        with open(os.path.join(d, "protection_decisions.csv"), "w") as f:
            f.write("decision_time,intervention\n" + "".join("{},{}\n".format(r["decision_time"], r["intervention"])
                                                             for r in interventions))
        with open(os.path.join(d, "tripinfo.xml"), "w") as f:
            f.write("<tripinfos>" + "".join('<tripinfo id="{}" waitingTime="{}"/>'.format(v, w)
                                            for v, w in waits.items()) + "</tripinfos>")

    def test_selection_definitions_and_long_opposite_green(self):
        sel = GD.select(self.analysis)
        g = sel["idqn"]["guarantee"]
        self.assertEqual((len(g["D1"]), len(g["D2"]), len(g["D3"])), (1, 1, 2))
        self.assertEqual(len(sel["qmix_acting"]), 1)
        events, streams = GD.diagnose(self.root, "R2_single_secondary_trickle", "8203", "idqn_seed107_t300000",
                                      "guarantee", "t")
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual((e["intersection"], e["located_by"]), ("J1", "yellow_start"))
        self.assertEqual((e["served_phase"], e["served_green_s"], e["opposite_green_s"]), ("V", 10, 80))
        self.assertTrue(e["opposite_green_gt_60s"])
        self.assertEqual(e["served_phase_red_after_s"], 86)
        by = dict((s["stream"], s) for s in streams)
        self.assertEqual(by["N1S1"]["n_ge_300s"], 1)
        self.assertEqual(by["N1S1"]["d_max_wait_s"], 370)
        out = os.path.join(self.base, "out")
        self.assertEqual(GD.main(["--root", self.root, "--analysis", self.analysis, "--out", out]), 1)
        with open(os.path.join(out, "summary.json")) as f:
            summary = json.load(f)
        self.assertEqual(summary["idqn_degraded_D1"]["opposite_green_gt_60s"], 1)
        self.assertEqual(len(summary["cells_not_readable"]), 1)         # the QMIX cell has no outputs here


if __name__ == "__main__":
    unittest.main()
