"""End-to-end test of tools/comparators/comparator_search.py with a fake evaluator (no SUMO, stdlib only).

Two profiles (R0, R3), a reduced coarse grid and a reduced fine union (patched), every stage chained:
coarse -> fine (g5, min7) -> validation -> selection; actuated design -> validation -> selection; R3 plans by
period -> time-of-day design -> validation -> selection; then the robustness-eval order. The fake evaluator
writes the files of the compact (or full) mode with the identity stamp; its J is a known function of the plan,
so the expected selections are computed here independently.
"""
import csv
import gzip
import io
import importlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN_SRC = [os.path.join(os.environ.get(v, d), "src") for v, d in
              (("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"),
               ("AQ_FROZEN_REPOSITORY", r"C:\Users\LENOVO\QMIX_Traffic_Coordination"))]
for path in FROZEN_SRC:
    if os.path.isdir(os.path.join(path, "adaptive_qmix")):
        sys.path.insert(0, path)
        break
sys.path.insert(0, os.path.join(HERE, "..", "tools", "comparators"))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "robustness"))
try:
    importlib.import_module("adaptive_qmix.baselines.plans")
    HAVE_FROZEN = True
except ImportError:
    HAVE_FROZEN = False

PROFILES = ["R0_reference", "R3_time_varying"]
TARGET = {0: 20, 1: 40, 2: 20}          # fake: best cycle per R3 period


def plan_j(plan, period=None):
    c, gh = plan["cycle_s"], plan["green_H_s"]
    target = 30 if period is None else TARGET[period]
    return abs(c - target) / 10.0 + abs(gh / float(c - 6) - 0.6) + plan["offset_s"] / 100.0


class Fake(object):
    def __init__(self, sha_obj):
        self.calls, self.sha_obj = [], sha_obj

    def evaluate(self, spec, prefix, out_dir, counters=False, compact=True):
        name = os.path.basename(prefix)
        profile, seed = name.rsplit("_", 1)
        self.calls.append(out_dir)
        with open(prefix + ".csv") as f:
            vehicles = list(csv.DictReader(f))
        fail = spec["kind"] == "fixed" and spec["plan"]["cycle_s"] == 16
        trips = []
        for v in vehicles:
            d = int(v["depart"])
            k = 0 if d < 900 else (1 if d < 2700 else 2)
            if spec["kind"] == "fixed":
                w = plan_j(spec["plan"], k if profile == "R3_time_varying" else None)
            elif spec["kind"] == "tod":
                w = plan_j(spec["periods"][k][1], k)
            else:
                w = 1.0 + spec["params"]["gap_s"] / 10.0 + spec["params"]["max_green_V_s"] / 100.0
            trips.append((v["vehicle_id"], w + int(seed) % 10 / 1000.0))
        j = sum(w for _v, w in trips) / len(trips)
        os.makedirs(out_dir)
        metrics = {"clearance_status": "CLEARANCE_FAILURE" if fail else "CLEARED", "J_primary_valid": not fail,
                   "J_primary_mean_scheduled_waiting_burden_s": None if fail else j,
                   "mean_completed_time_loss_s": j + 1, "scenario": profile, "traffic_seed": int(seed),
                   "comparator_spec_sha256": self.sha_obj(spec)}
        for n in ("run_manifest.json", "episode_summary.csv"):
            with open(os.path.join(out_dir, n), "w") as f:
                f.write("{}")
        xml = "<tripinfos>" + "".join('<tripinfo id="{}" waitingTime="{}" departDelay="0"/>'.format(v, w)
                                      for v, w in trips) + "</tripinfos>"
        if compact:
            with gzip.open(os.path.join(out_dir, "tripinfo.xml.gz"), "wt") as f:
                f.write(xml)
        else:
            for n in ("tripinfo.xml", "signal_phases.csv", "reward_seconds.csv", "service_counters.csv"):
                with open(os.path.join(out_dir, n), "w") as f:
                    f.write(xml if n == "tripinfo.xml" else "x")
        with open(os.path.join(out_dir, "evaluation_metrics.json"), "w") as f:
            json.dump(metrics, f)
        return metrics


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class Pipeline(unittest.TestCase):

    def setUp(self):
        import comparator_search as CS
        import grids as G
        import seeds as SD
        self.CS, self.G, self.SD = CS, G, SD
        self.base = tempfile.mkdtemp()
        self.root = os.path.join(self.base, "root")
        os.makedirs(os.path.join(self.root, "manifests"))
        for profile in PROFILES:
            for role in ("comparator_design", "comparator_validation", "robustness_evaluation"):
                for seed in SD.seeds(profile, role):
                    with open(os.path.join(self.root, "manifests", "{}_{}.csv".format(profile, seed)), "w") as f:
                        f.write("vehicle_id,depart\n" + "".join("v{},{}\n".format(k, k * 120) for k in range(30)))
        keys = sorted(G.groups(G.coarse_labels(5)))
        chosen = [k for k in keys if k[0] in (16, 20, 25, 30, 40, 60) and k[3] in (0, 5) and (k[1] % 3 == 0 or k[0] == 16)]
        self.coarse_keys = chosen
        self.saved = (CS.coarse_specs, G.fine_union, sys.modules.get("evaluate_comparator"))
        CS.coarse_specs = lambda: [CS.fixed_spec(k) for k in chosen]
        real_union = G.fine_union
        G.fine_union = lambda winners, g: real_union(winners, g)[:12]
        self.fake = Fake(CS.sha_obj)
        sys.modules["evaluate_comparator"] = types.SimpleNamespace(evaluate=self.fake.evaluate)
        plan = CS.build_plan(self.root)
        plan["profiles"] = PROFILES
        with open(os.path.join(self.root, "plan.json"), "w") as f:
            json.dump(plan, f)
        with redirect_stdout(io.StringIO()):
            CS.initial_orders(self.root, plan)

    def tearDown(self):
        self.CS.coarse_specs, self.G.fine_union = self.saved[0], self.saved[1]
        if self.saved[2] is None:
            sys.modules.pop("evaluate_comparator", None)
        else:
            sys.modules["evaluate_comparator"] = self.saved[2]
        shutil.rmtree(self.base)

    def q(self, fn, *args):
        with redirect_stdout(io.StringIO()):
            return fn(*args)

    def stage(self, name, finalise=True):
        codes = [self.q(self.CS.run, self.root, name, "{}/2".format(i)) for i in range(2)]
        self.assertEqual(codes, [0, 0], name)
        if finalise:
            self.q(self.CS.finalise, self.root, name)

    def order(self, name):
        return self.CS.read_order(self.root, name)

    def selection(self, name):
        with open(os.path.join(self.root, "selections", name + ".json")) as f:
            return json.load(f)

    def test_every_stage_chains_and_selects_by_the_frozen_rules(self):
        CS, SD = self.CS, self.SD
        self.stage("coarse")
        coarse_runs = len(self.fake.calls)
        self.assertEqual(coarse_runs, len(self.coarse_keys) * 5 * len(PROFILES))
        for version, g in CS.VERSIONS:
            fine = self.order("fine-" + version)
            self.assertTrue(all(self.G.admissible(j["spec"]["plan"], g) for j in fine["jobs"]))
            self.assertTrue(all(CS.realized(j["spec"]) not in set(self.coarse_keys) for j in fine["jobs"]))
        self.stage("fine-g5")
        self.stage("fine-min7")
        for version, g in CS.VERSIONS:
            self.stage("validation-" + version)
        for profile in PROFILES:
            g5, m7 = self.selection(profile + "__g5"), self.selection(profile + "__min7")
            self.assertGreaterEqual(min(m7["selected"]["spec"]["plan"]["green_H_s"],
                                        m7["selected"]["spec"]["plan"]["green_V_s"]), 7)
            for sel in (g5, m7):
                valid = [c for c in sel["candidates"] if c["valid"]]
                best = min(valid, key=lambda c: (c["mean_J"], c["mean_time_loss"], c["spec"]["plan"]["cycle_s"]))
                self.assertEqual(sel["selected"]["spec"], best["spec"])
                self.assertTrue(all(SD.role_of(profile, s) == "comparator_validation" for s in sel["selected"]["seeds"]))
        self.stage("actuated-design")
        self.stage("actuated-validation")
        act = self.selection("R0_reference__actuated")["selected"]["spec"]["params"]
        self.assertEqual((act["gap_s"], act["max_green_V_s"]), (2, 15))       # fake J favours both
        for version, _g in CS.VERSIONS:
            tod = self.order("tod-design-" + version)
            self.assertEqual(len(tod["jobs"]), 27 * 5)
            top = tod["inputs"]["per_period_top"]
            self.assertLess(top[0][0][0], top[1][0][0])                       # period 1 prefers a shorter cycle
            self.stage("tod-design-" + version)
            self.stage("tod-validation-" + version)
            sel = self.selection("R3_time_varying__tod-" + version)["selected"]["spec"]
            self.assertEqual(sel["kind"], "tod")
        robust = self.order("robustness-eval")
        self.assertEqual(len(robust["jobs"]), (len(PROFILES) * 3 + 2) * 5)
        self.assertTrue(all(j["full"] and SD.role_of(j["profile"], j["seed"]) == "robustness_evaluation"
                            for j in robust["jobs"]))
        self.stage("robustness-eval", finalise=False)
        for name in CS.STAGES:
            for j in self.order(name)["jobs"]:
                self.assertNotEqual(SD.role_of(j["profile"], j["seed"]), "confirmation")
        self.assertEqual(self.q(CS.progress, self.root), 0)

    def test_a_scientific_failure_is_kept_excluded_and_never_rerun(self):
        self.stage("coarse", finalise=False)
        calls = len(self.fake.calls)
        failed = [j for j in self.order("coarse")["jobs"] if j["spec"]["plan"]["cycle_s"] == 16]
        self.assertTrue(failed)
        self.assertEqual(self.CS.classify(self.root, failed[0])[0], "scientific_failure")
        self.stage("coarse", finalise=False)
        self.assertEqual(len(self.fake.calls), calls)
        self.q(self.CS.finalise, self.root, "coarse")
        winners = self.order("fine-g5")["inputs"]["report"]["R0_reference/g5"]["winners"]
        self.assertTrue(all(w[0] != 16 for w in winners))

    def test_a_corrupted_result_blocks_finalise_and_is_never_rerun(self):
        self.stage("coarse", finalise=False)
        j = self.order("coarse")["jobs"][7]
        with open(os.path.join(self.root, j["directory"], "evaluation_metrics.json"), "w") as f:
            f.write('{"clearance')
        self.assertEqual(self.q(self.CS.progress, self.root, "coarse"), 5)
        calls = len(self.fake.calls)
        self.assertEqual(self.q(self.CS.run, self.root, "coarse", "0/1"), 5)
        self.assertEqual(len(self.fake.calls), calls)
        with self.assertRaises(self.CS.SearchError):
            self.q(self.CS.finalise, self.root, "coarse")

    def test_orders_are_written_once_and_checked_against_their_seal(self):
        self.stage("coarse")
        with self.assertRaises(self.CS.SearchError):
            self.q(self.CS.finalise, self.root, "coarse")
        path = self.CS.order_path(self.root, "fine-g5")
        with open(path) as f:
            payload = json.load(f)
        payload["jobs"] = payload["jobs"][1:]
        with open(path, "w") as f:
            json.dump(payload, f)
        with self.assertRaises(self.CS.SearchError):
            self.CS.read_order(self.root, "fine-g5")

    def test_code_changed_after_the_plan_is_refused(self):
        with open(os.path.join(self.root, "plan.json")) as f:
            plan = json.load(f)
        plan["code_sha256"]["grids.py"] = "0" * 64
        with open(os.path.join(self.root, "plan.json"), "w") as f:
            json.dump(plan, f)
        with self.assertRaises(self.CS.SearchError):
            self.CS.load_plan(self.root)


if __name__ == "__main__":
    unittest.main()
