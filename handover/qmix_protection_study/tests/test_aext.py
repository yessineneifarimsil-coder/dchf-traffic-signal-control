"""Tests of campaign A-ext (actuated gap-out with a 5 s minimum green): controller, evaluator dispatch, search
chain with a fake evaluator (no SUMO). The frozen package adaptive_qmix is needed; skipped without it."""
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
for var, default in (("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"),
                     ("AQ_FROZEN_REPOSITORY", r"C:\Users\LENOVO\QMIX_Traffic_Coordination")):
    src = os.path.join(os.environ.get(var, default), "src")
    if os.path.isdir(os.path.join(src, "adaptive_qmix")):
        sys.path.insert(0, src)
        break
sys.path.insert(0, os.path.join(HERE, "..", "tools", "comparators_ext"))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "comparators"))
sys.path.insert(0, HERE)
try:
    import adaptive_qmix.baselines.executors  # noqa: F401
    HAVE_FROZEN = True
except ImportError:
    HAVE_FROZEN = False

A_CONTROLLERS_SHA256 = "7ee74f0e228ca3bcf5ceaa3fe0b4600b909684a67e7bcfe6e63e20e44c7741ca"   # campaign A plan


def segments(states):
    out = []
    for s in states:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return out


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class ControllerG5(unittest.TestCase):

    def make(self, vehicles, **params):
        import controllers_g5 as G
        from test_comparators import CONFIG, FakeSource, FakeTraci
        traci = FakeTraci()
        return G.ActuatedGapOutG5Executor(traci, CONFIG, data_source=FakeSource(traci, vehicles), **params), traci

    def run_states(self, ex, seconds):
        from test_comparators import run_executor
        return run_executor(ex, None, seconds)["J1"]

    def test_campaign_A_controller_file_is_unchanged_and_still_refuses_5_s(self):
        with open(os.path.join(HERE, "..", "tools", "comparators", "controllers.py"), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), A_CONTROLLERS_SHA256)
        import controllers as C
        from test_comparators import CONFIG, FakeSource, FakeTraci
        t = FakeTraci()
        with self.assertRaises(ValueError):
            C.ActuatedGapOutExecutor(t, CONFIG, data_source=FakeSource(t, lambda s: {}), minimum_green_s=5)

    def test_gap_out_after_5_s(self):
        ex, _t = self.make(lambda t: {"b_0": [10.0], "d_0": [10.0]}, gap_s=1)
        segs = segments(self.run_states(ex, 40))
        self.assertEqual(segs[0], ["H", 5])
        self.assertEqual(segs[1], ["Y", 3])
        self.assertEqual(ex.minimum_green_s, 5)

    def test_secondary_max_out_at_10_s(self):
        ex, _t = self.make(lambda t: {"a_1": [10.0], "b_0": [195.0], "b_1": [10.0]}, gap_s=3, max_green_H_s=30,
                           max_green_V_s=10)
        segs = segments(self.run_states(ex, 200))
        v = [l for p, l in segs[:-1] if p == "V"]
        self.assertTrue(v and all(l == 10 for l in v))

    def test_minimum_5_maximum_and_yellow_hold_under_random_demand(self):
        pattern = lambda t: {"a_0": [190.0] if t % 17 < 5 else [], "a_1": [10.0], "b_0": [100.0],  # noqa: E731
                             "b_1": [195.0] if t % 13 < 4 else []}
        ex, _t = self.make(pattern, gap_s=1, max_green_H_s=30, max_green_V_s=10)
        segs = segments(self.run_states(ex, 2000))
        greens = [l for p, l in segs[:-1] if p != "Y"]
        self.assertEqual(min(greens), 5)
        self.assertTrue(all(l == 3 for p, l in segs[:-1] if p == "Y"))
        self.assertLessEqual(max(l for p, l in segs[:-1] if p == "V"), 10)

    def test_refusals(self):
        with self.assertRaises(ValueError):
            self.make(lambda t: {}, minimum_green_s=7)
        with self.assertRaises(ValueError):
            self.make(lambda t: {}, max_green_V_s=4)


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class EvaluateExt(unittest.TestCase):

    def test_dispatch_extends_without_changing_campaign_A_kinds(self):
        import evaluate_ext as X
        import evaluate_comparator as ec
        act = {"kind": "actuated", "params": {"gap_s": 2, "max_green_H_s": 45, "max_green_V_s": 15, "zone_m": 40}}
        self.assertEqual(ec.label(act), "actuated:gap2_H45_V15_z40")
        g5 = {"kind": "actuated_g5", "params": {"gap_s": 1, "max_green_H_s": 30, "max_green_V_s": 10, "zone_m": 40}}
        self.assertEqual(ec.label(g5), "actuated_g5:gap1_H30_V10_z40")
        from test_comparators import CONFIG, FakeSource, FakeTraci
        t = FakeTraci()
        env = type("E", (), {"source": FakeSource(t, lambda s: {})})()
        made = ec.executor_factory(g5)(t, CONFIG, env)
        self.assertEqual((type(made).__name__, made.minimum_green_s), ("ActuatedGapOutG5Executor", 5))
        made7 = ec.executor_factory(act)(t, CONFIG, env)
        self.assertEqual((type(made7).__name__, made7.minimum_green_s), ("ActuatedGapOutExecutor", 7))
        self.assertIs(X.evaluate.__module__, "evaluate_ext")


class Fake(object):
    def __init__(self, sha):
        self.calls, self.sha = [], sha

    def __call__(self, spec, prefix, out_dir, counters=False, compact=True):
        profile, seed = os.path.basename(prefix).rsplit("_", 1)
        self.calls.append(out_dir)
        q = spec["params"]
        j = 1.0 + q["gap_s"] / 10.0 + q["max_green_V_s"] / 100.0 + q["max_green_H_s"] / 1000.0 + int(seed) % 10 / 1e4
        os.makedirs(out_dir)
        for name in ("run_manifest.json", "episode_summary.csv"):
            with open(os.path.join(out_dir, name), "w") as f:
                f.write("{}")
        with gzip.open(os.path.join(out_dir, "tripinfo.xml.gz"), "wt") as f:
            f.write("<tripinfos/>")
        with open(os.path.join(out_dir, "evaluation_metrics.json"), "w") as f:
            json.dump({"clearance_status": "CLEARED", "J_primary_valid": True,
                       "J_primary_mean_scheduled_waiting_burden_s": j, "mean_completed_time_loss_s": j + 5,
                       "scenario": profile, "traffic_seed": int(seed), "comparator_spec_sha256": self.sha(spec)}, f)


@unittest.skipUnless(HAVE_FROZEN, "frozen adaptive_qmix not available")
class Chain(unittest.TestCase):

    def setUp(self):
        import aext_search as AX
        import comparator_search as CS
        self.AX, self.CS = AX, CS
        self.base = tempfile.mkdtemp()
        self.root = os.path.join(self.base, "aext")
        os.makedirs(self.root)
        plan = AX.build_plan(self.root)
        with open(os.path.join(self.root, "plan.json"), "w") as f:
            json.dump(plan, f)
        jobs = []
        for profile in AX.PROFILES:
            jobs += CS.search_jobs(profile, "comparator_design", [AX.spec(p) for p in AX.GRID])
        with redirect_stdout(io.StringIO()):
            CS.write_order(self.root, "aext-design", jobs + jobs[:7], {"settings": 27})    # duplicates injected
        self.fake = Fake(CS.sha_obj)

    def tearDown(self):
        shutil.rmtree(self.base)

    def q(self, fn, *args, **kw):
        with redirect_stdout(io.StringIO()):
            return fn(*args, **kw)

    def test_plan_counts_grid_and_bound(self):
        plan = self.AX.build_plan(self.root)
        self.assertEqual(len(self.AX.GRID), 27)
        self.assertEqual(set(p["gap_s"] for p in self.AX.GRID), {1, 2, 3})
        self.assertEqual(set(p["max_green_V_s"] for p in self.AX.GRID), {10, 15, 25})
        self.assertEqual(plan["runs_by_stage"], {"aext-design": 405, "aext-validation": 75})
        self.assertEqual(plan["runs_upper_bound"], 480)
        self.assertEqual(plan["estimate_upper_bound"]["runs"], 480)                  # (c) every stage

    def test_shards_never_share_a_folder(self):
        jobs = self.CS.read_order(self.root, "aext-design")["jobs"]
        self.assertEqual(len(jobs), 412)
        shards = [set(j["directory"] for j in self.AX.shard_jobs(jobs, "{}/4".format(i))) for i in range(4)]
        self.assertEqual(sum(len(s) for s in shards), 405)
        self.assertEqual(len(set.union(*shards)), 405)

    def test_chain_selects_by_the_frozen_rule_and_never_reruns(self):
        codes = [self.q(self.AX.run, self.root, "aext-design", "{}/4".format(i), evaluator=self.fake, free=10 ** 13) for i in range(4)]
        self.assertEqual(codes, [0, 0, 0, 0])
        self.assertEqual(len(self.fake.calls), 405)
        self.assertEqual(self.q(self.AX.progress, self.root, "aext-design"), 0)
        self.q(self.AX.finalise, self.root, "aext-design")
        val = self.CS.read_order(self.root, "aext-validation")
        self.assertEqual(len(val["jobs"]), 75)
        self.assertTrue(all(self.CS.SD.role_of(j["profile"], j["seed"]) == "comparator_validation" for j in val["jobs"]))
        top = val["inputs"]["top5"]["R1_sparse_secondary_heavy_main"]
        self.assertEqual(top[0], {"gap_s": 1, "max_green_H_s": 30, "max_green_V_s": 10, "zone_m": 40})
        self.q(self.AX.run, self.root, "aext-validation", "0/1", evaluator=self.fake, free=10 ** 13)
        self.q(self.AX.finalise, self.root, "aext-validation")
        with open(os.path.join(self.root, "selections", "R2_single_secondary_trickle__actuated_g5.json")) as f:
            sel = json.load(f)
        self.assertEqual(sel["selected"]["spec"]["params"], top[0])
        calls = len(self.fake.calls)
        self.q(self.AX.run, self.root, "aext-design", "0/1", evaluator=self.fake, free=10 ** 13)
        self.assertEqual(len(self.fake.calls), calls)
        with self.assertRaises(self.CS.SearchError):
            self.q(self.AX.finalise, self.root, "aext-validation")                     # selections written once

    def test_corrupted_result_code_5_and_not_rerun(self):
        self.q(self.AX.run, self.root, "aext-design", "0/1", evaluator=self.fake, free=10 ** 13)
        j = self.CS.read_order(self.root, "aext-design")["jobs"][3]
        with open(os.path.join(self.root, j["directory"], "evaluation_metrics.json"), "w") as f:
            f.write("{")
        calls = len(self.fake.calls)
        self.assertEqual(self.q(self.AX.run, self.root, "aext-design", "0/1", evaluator=self.fake, free=10 ** 13), 5)
        self.assertEqual(len(self.fake.calls), calls)
        self.assertEqual(self.q(self.AX.progress, self.root, "aext-design"), 5)

    def test_a_run_refuses_to_start_without_the_disk_space(self):
        with self.assertRaises(self.AX.AextError):
            self.AX.run(self.root, "aext-design", "0/1", evaluator=self.fake, free=self.AX.SAFETY_BYTES)
        self.assertEqual(self.fake.calls, [])

    def test_confirmation_seeds_are_refused(self):
        with self.assertRaises(self.CS.SD.SeedError):
            self.CS.search_jobs("R1_sparse_secondary_heavy_main", "confirmation", [self.AX.spec(self.AX.GRID[0])])

    def test_code_change_is_refused(self):
        with open(os.path.join(self.root, "plan.json")) as f:
            plan = json.load(f)
        plan["code_sha256"]["controllers_g5.py"] = "0" * 64
        with open(os.path.join(self.root, "plan.json"), "w") as f:
            json.dump(plan, f)
        with self.assertRaises(self.AX.AextError):
            self.AX.load_plan(self.root)


if __name__ == "__main__":
    unittest.main()
