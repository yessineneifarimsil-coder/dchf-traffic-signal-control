"""Tests of the campaign B runner (tools/confirmation/b_runner.py), with fake evaluators (no SUMO), and of the real
readers (robustness_analysis.cell_metrics) on complete synthetic cells finalised with gzip logs.

The campaign A selections are the real sealed files of the uploaded results when B_TEST_A_SELECTIONS points to
their folder; otherwise a sealed stand-in with the same validation J is written (values of A_comparators results,
handoff 2026-11-15). The frozen package adaptive_qmix (statistics module, numpy) is needed by the analysis tests.
"""
import gzip
import hashlib
import io
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
for var, default in (("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"),
                     ("AQ_FROZEN_REPOSITORY", r"C:\Users\LENOVO\QMIX_Traffic_Coordination")):
    src = os.path.join(os.environ.get(var, default), "src")
    if os.path.isdir(os.path.join(src, "adaptive_qmix")):
        os.environ.setdefault("QMIX_PROTECTED_ROOT", os.path.dirname(src))
        sys.path.insert(0, src)
        break
sys.path.insert(0, os.path.join(TOOLS, "confirmation"))
import b_runner as BR  # noqa: E402

HAVE_STATS = os.path.isfile(BR.statistics_path())
try:
    import numpy  # noqa: F401
except ImportError:
    HAVE_STATS = False

R0, R1, R2, R3, R4 = BR.PROFILES
EXPECTED_A = {(R1, "g5"): 1.9399, (R1, "min7"): 2.6677, (R1, "actuated"): 2.5753,
              (R2, "g5"): 1.5722, (R2, "min7"): 2.0438, (R2, "actuated"): 1.3669,
              (R3, "g5"): 3.5806, (R3, "min7"): 3.5806, (R3, "actuated"): 3.82,
              (R3, "tod-g5"): 2.7219, (R3, "tod-min7"): 3.3041}


def sealed(path, payload):
    payload = dict(payload)
    payload["sha256"] = BR.sha_obj(payload)
    with open(path, "w") as f:
        json.dump(payload, f)


def stand_in_spec(profile, kind, k):
    if kind in ("g5", "min7"):
        return BR.fixed_spec((25, 12, 7, 0)) if profile == R3 else BR.fixed_spec((25 + k, 14, 5, 1))
    if kind == "actuated":
        return {"kind": "actuated", "params": {"gap_s": 2, "max_green_H_s": 45, "max_green_V_s": 15, "zone_m": 40}}
    if kind == "actuated_g5":
        return {"kind": "actuated_g5", "params": {"gap_s": 1, "max_green_H_s": 30 + k, "max_green_V_s": 10, "zone_m": 40}}
    return {"kind": "tod", "periods": [kind, k]}


def write_a(root):
    folder = os.path.join(root, "selections")
    os.makedirs(folder)
    real = os.environ.get("B_TEST_A_SELECTIONS")
    if real and os.path.isdir(real):
        for n in os.listdir(real):
            shutil.copyfile(os.path.join(real, n), os.path.join(folder, n))
        return True
    for k, ((profile, kind), j) in enumerate(sorted(EXPECTED_A.items())):
        sealed(os.path.join(folder, "{}__{}.json".format(profile, kind)),
               {"profile": profile, "stage": "x", "order": "x", "candidates": [],
                "selected": {"spec": stand_in_spec(profile, kind, k if kind != "min7" or profile != R3 else 0),
                             "seeds": [1], "valid": True, "mean_J": j, "mean_time_loss": 1.0}})
    return False


def write_aext(root, js):
    folder = os.path.join(root, "selections")
    os.makedirs(folder)
    for k, (profile, j) in enumerate(sorted(js.items())):
        sealed(os.path.join(folder, "{}__actuated_g5.json".format(profile)),
               {"profile": profile, "stage": "aext-validation", "order": "x", "candidates": [],
                "selected": {"spec": stand_in_spec(profile, "actuated_g5", k), "seeds": [1], "valid": True,
                             "mean_J": j, "mean_time_loss": 1.0}})


def write_rob(root):
    os.makedirs(os.path.join(root, "checkpoints"))
    models = []
    plan = BR.conf_plan()
    for method in ("qmix", "vdn", "idqn"):
        # IDQN: stand-in tags for the test only (the real tags are read from the robustness plan, never written here)
        tags = plan["learned_policies"][method] if method != "idqn" else ["idqn_seed{}_tTEST".format(s) for s in range(101, 111)]
        for tag in tags:
            data = ("checkpoint " + tag).encode()
            with open(os.path.join(root, "checkpoints", tag + ".pth"), "wb") as f:
                f.write(data)
            models.append({"method": method, "training_seed": 0, "tag": tag, "source": "x",
                           "sha256": hashlib.sha256(data).hexdigest()})
    with open(os.path.join(root, "plan.json"), "w") as f:
        json.dump({"models": models}, f)


def fake_manifest(profile, seed, prefix):
    with open(prefix + ".metadata.json", "w") as f:
        json.dump({"scenario": profile, "seed_value": seed, "scheduled_total": 100}, f)


def fake_summary(j, work, n):
    m = BR.read_json(os.path.join(work, "evaluation_metrics.json"))
    return ({"status": m["clearance_status"], "J_primary_s": m.get("J"), "open_wait_at_end_s": 0,
             "vehicles_waiting_ge_300s": 0, "D_bar_s": 1.0, "mean_completed_time_loss_s": 2.0,
             "max_vehicle_waiting_s": 50.0}, [])


class FakeEvaluator(object):
    """Writes the files of a real run; J from a synthetic law (learned: comparator J + effect)."""

    def __init__(self, effect=0.0, fail=(), idqn_effect=0.0):
        self.calls, self.effect, self.fail, self.idqn_effect = [], effect, set(fail), idqn_effect

    def __call__(self, root, j, prefix, work):
        self.calls.append(j["directory"])
        if j["directory"] in self.fail:
            os.makedirs(work, exist_ok=True)
            raise RuntimeError("simulated crash")
        os.makedirs(work)
        rnd = random.Random("{}{}".format(j["profile"], j["seed"]))
        base = 3.0 + rnd.uniform(-0.3, 0.3)
        names = list(BR.REQUIRED[2:]) + [n[:-3] for n in BR.REQUIRED if n.endswith(".gz")]
        if j["kind"] == "learned":
            names += list(BR.REQUIRED_LEARNED)
            seed_of_model = int(j["model"].split("_seed")[1][:3])
            effect = self.idqn_effect if j["method"] == "idqn" else self.effect
            value = base + effect + (seed_of_model - 105) * 0.01 + (0.02 if j["arm"] == "none" else 0)
            ident = {"controller": j["controller"], "checkpoint_sha256": j["checkpoint_sha256"]}
        else:
            value = base
            ident = {"controller": "cmp", "comparator_spec_sha256": j["spec_sha256"]}
        for name in set(n for n in names if not n.endswith(".gz") and n not in ("cell_summary.json",)):
            with open(os.path.join(work, name), "w") as f:
                f.write("x" * 200)
        m = dict(ident, scenario=j["profile"], traffic_seed=j["seed"], clearance_status="CLEARED", J=value)
        with open(os.path.join(work, "evaluation_metrics.json"), "w") as f:
            json.dump(m, f)


class Base(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.a, self.x, self.rob, self.root = (os.path.join(self.base, n) for n in ("a", "aext", "rob", "b"))
        self.real_a = write_a(self.a)
        write_aext(self.x, {R1: 2.10, R2: 1.50, R3: 3.00})          # worse than the A primaries: secondary (B2)
        write_rob(self.rob)
        self.saved = (BR.manifest_writer, BR.summarise_cell, BR.environment)
        BR.manifest_writer, BR.summarise_cell = fake_manifest, fake_summary
        BR.environment = lambda: {"python": "3.7.16", "sumo": "Eclipse SUMO sumo Version 1.25.0", "platform": "test"}
        self.reports = os.path.join(self.base, "logs")
        os.makedirs(self.reports)
        self.etapes = os.path.join(self.reports, "verify_etapes_B.txt")
        self.tests = os.path.join(self.reports, "tests_B.txt")
        with open(self.etapes, "w") as f:
            f.write("...\nResult: 300 checks passed, 0 failed.\n")
        with open(self.tests, "w") as f:
            f.write("Ran 130 tests in 200.1s\n\nOK (skipped=3)\n")

    def tearDown(self):
        BR.manifest_writer, BR.summarise_cell, BR.environment = self.saved
        shutil.rmtree(self.base)

    def roots(self):
        return self.a, self.x, self.rob

    def q(self, fn, *args, **kw):
        with redirect_stdout(io.StringIO()):
            return fn(*args, **kw)

    def run_in(self, **kw):
        return self.q(BR.measure, self.root, *self.roots(), evaluator=FakeEvaluator(), workers=kw.get("workers", 1))

    def freeze(self, **kw):
        if not os.path.exists(os.path.join(self.root, "measure.json")):
            self.run_in()
        return self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests, **kw)

    def frozen_and_prepared(self):
        _fr, plan = self.freeze()
        self.q(BR.prepare, self.root, plan["fingerprint"], *self.roots())
        return plan


class Primary(Base):

    def test_B1_primary_from_the_A_selections(self):
        sel = BR.load_selections(self.a)
        got = dict((p, BR.choose_primary(sel, p)) for p in BR.PROFILES)
        self.assertEqual(got[R1]["label"], "oft_g5")
        self.assertAlmostEqual(got[R1]["validation_J"], 1.9399, places=4)
        self.assertEqual(got[R2]["label"], "actuated_min7")
        self.assertAlmostEqual(got[R2]["validation_J"], 1.3669, places=4)
        self.assertEqual(got[R3]["label"], "tod_g5")
        self.assertAlmostEqual(got[R3]["validation_J"], 2.7219, places=4)
        for p in (R0, R4):
            self.assertEqual((got[p]["label"], got[p]["validation_J"]), (BR.C19_LABEL, 2.765071428571429))

    def test_margins(self):
        plan = BR.build_plan(self.root, *self.roots())
        d = dict((p, plan["margins"][p]["delta_s"]) for p in BR.PROFILES)
        self.assertAlmostEqual(d[R0], 0.13825357, places=6)
        self.assertAlmostEqual(d[R4], d[R0])
        self.assertAlmostEqual(d[R1], 0.10)                  # 0.05 x 1.94 = 0.097 < floor
        self.assertAlmostEqual(d[R2], 0.10)
        self.assertAlmostEqual(d[R3], 0.05 * plan["margins"][R3]["validation_J"])

    def test_B2_actuated_g5_is_primary_when_best_and_secondary_otherwise(self):
        plan = BR.build_plan(self.root, *self.roots())
        self.assertEqual(plan["primary"][R2]["label"], "actuated_min7")
        self.assertIn("actuated_g5", plan["comparators"][R2])                     # evaluated as secondary
        shutil.rmtree(self.x)
        write_aext(self.x, {R1: 2.10, R2: 1.20, R3: 3.00})
        plan = BR.build_plan(self.root, *self.roots())
        self.assertEqual(plan["primary"][R2]["label"], "actuated_g5")
        self.assertAlmostEqual(plan["margins"][R2]["validation_J"], 1.20)

    def test_no_plan_without_the_A_ext_selections(self):
        shutil.rmtree(self.x)
        with self.assertRaises(BR.BError):
            BR.build_plan(self.root, *self.roots())
        os.makedirs(os.path.join(self.x, "selections"))
        with self.assertRaises(BR.BError):
            BR.build_plan(self.root, *self.roots())

    def test_ties_follow_the_declared_order(self):
        sel = [{"profile": R1, "label": "actuated_g5", "validation_J": 1.0},
               {"profile": R1, "label": "oft_min7", "validation_J": 1.0}]
        self.assertEqual(BR.choose_primary(sel, R1)["label"], "oft_min7")

    def test_a_broken_seal_is_refused(self):
        path = os.path.join(self.x, "selections", "{}__actuated_g5.json".format(R1))
        payload = BR.read_json(path)
        payload["selected"]["mean_J"] = 0.5
        with open(path, "w") as f:
            json.dump(payload, f)
        with self.assertRaises(BR.BError):
            BR.load_selections(self.a, self.x)


class PlanCount(Base):

    def test_exact_count_and_no_duplicate_folder(self):
        plan = BR.build_plan(self.root, *self.roots())
        learned = [j for j in plan["jobs"] if j["kind"] == "learned"]
        comp = [j for j in plan["jobs"] if j["kind"] == "comparator"]
        self.assertEqual(len([j for j in learned if j["method"] != "idqn"]), 2 * 10 * 2 * 5 * 10)
        idqn = [j for j in learned if j["method"] == "idqn"]
        self.assertEqual(len(idqn), 100)                                           # rectificatif point 1
        self.assertEqual(set(j["profile"] for j in idqn), {R0})
        self.assertEqual(set(j["arm"] for j in idqn), {"guarantee"})
        self.assertEqual(sorted(set(j["seed"] for j in idqn)), list(range(8051, 8061)))
        per_profile = dict((p, len([j for j in comp if j["profile"] == p]) // 10) for p in BR.PROFILES)
        # R0, R4: C19, C25, MP. R1, R2: + oft_g5, oft_min7, actuated_min7, actuated_g5 (7 specs).
        # R3: oft_g5 = oft_min7 = C25 12/7 D0 (one spec), + actuated, actuated_g5, tod_g5, tod_min7 (7 specs).
        self.assertEqual(per_profile, {R0: 3, R1: 7, R2: 7, R3: 7, R4: 3})
        self.assertEqual(len(plan["jobs"]), 2370)
        self.assertEqual(len(set(j["directory"] for j in plan["jobs"])), 2370)
        self.assertEqual((plan["estimate"]["learned"], plan["estimate"]["comparators"]), (2100, 270))
        r3c25 = [j for j in comp if j["profile"] == R3 and "fixed:min7_C25_12_7_D0" in j["labels"]][0]
        self.assertEqual(sorted(r3c25["labels"]), ["fixed:min7_C25_12_7_D0", "oft_g5", "oft_min7"])
        self.assertEqual(sorted(set(j["model"] for j in learned if j["method"] != "idqn")), sorted(
            t for m in ("qmix", "vdn") for t in BR.conf_plan()["learned_policies"][m]))
        self.assertTrue(all(BR.SD.role_of(j["profile"], j["seed"]) == "confirmation" for j in plan["jobs"]))

    def test_shards_partition_the_unique_jobs(self):
        plan = BR.build_plan(self.root, *self.roots())
        jobs = plan["jobs"] + plan["jobs"][:9]
        parts = [set(j["directory"] for j in BR.shard(jobs, "{}/4".format(i))) for i in range(4)]
        self.assertEqual(sum(len(p) for p in parts), 2370)
        self.assertEqual(len(set.union(*parts)), 2370)

    def test_the_10_idqn_checkpoints_are_required(self):
        path = os.path.join(self.rob, "plan.json")
        plan = BR.read_json(path)
        plan["models"] = [m for m in plan["models"] if m["tag"] != "idqn_seed107_tTEST"]
        with open(path, "w") as f:
            json.dump(plan, f)
        with self.assertRaises(BR.BError):
            BR.build_plan(self.root, *self.roots())

    def test_the_fingerprint_ignores_the_estimate_only(self):
        plan = BR.build_plan(self.root, *self.roots())
        os.makedirs(self.root)
        with open(os.path.join(self.root, "measure.json"), "w") as f:
            json.dump({"seconds_learned": 20.0, "seconds_comparator": 15.0, "seconds_learned_max": 30.0,
                       "seconds_comparator_max": 20.0, "bytes_per_run": 10 ** 6, "parallel_efficiency": 0.8,
                       "workers": 4}, f)
        again = BR.build_plan(self.root, *self.roots())
        self.assertEqual(plan["fingerprint"], again["fingerprint"])
        self.assertNotEqual(plan["estimate"], again["estimate"])
        self.assertTrue(again["estimate"]["source"].startswith("measure.json (parallel run-in, 4 workers)"))
        e = again["estimate"]
        self.assertAlmostEqual(e["wall_h_4_workers"], round((2100 * 20.0 + 270 * 15.0) / 4 / 0.8 / 3600, 2))
        self.assertGreater(e["wall_h_4_workers_pessimistic"], e["wall_h_4_workers"])
        self.assertIn("not a guarantee", e["note"])


class Freeze(Base):

    def test_seed_guard_refuses_confirmation_traffic_before_the_freeze(self):
        plan = BR.build_plan(self.root, *self.roots())
        with self.assertRaises(BR.BError):
            BR.confirmation_seeds_allowed(self.root)
        with self.assertRaises(BR.BError):
            BR.write_confirmation_manifests(self.root, plan)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "manifests")))
        with self.assertRaises(BR.BError):
            self.q(BR.prepare, self.root, plan["fingerprint"], *self.roots())
        self.assertFalse(os.path.isdir(os.path.join(self.root, "manifests")))

    def test_measure_uses_design_seeds_only(self):
        made = []
        BR.manifest_writer = lambda p, s, prefix: (made.append((p, s)), fake_manifest(p, s, prefix))
        payload = self.run_in()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["runs"], BR.MEASURE_RUNS)
        self.assertTrue(made and all(BR.SD.role_of(p, s) == "comparator_design" for p, s in made))
        self.assertFalse(os.path.isdir(os.path.join(self.root, "manifests")))
        self.assertEqual(set(r["method"] for r in payload["results"] if r["kind"] == "learned"), {"qmix", "vdn", "idqn"})
        self.assertTrue(all(r["recheck"] == [] for r in payload["results"]))          # re-read from gzip

    def test_measure_with_the_planned_parallelism(self):
        payload = self.run_in(workers=4)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["workers"], 4)
        self.assertTrue(0 < payload["parallel_efficiency"] <= 1.0)
        self.assertGreater(payload["throughput_runs_per_h"], 0)
        self.assertEqual(len(payload["results"]), BR.MEASURE_RUNS)
        self.assertEqual(payload["environment"]["python"], "3.7.16")

    def test_measure_is_a_gate(self):
        BR.summarise_cell = lambda j, w, n: (fake_summary(j, w, n)[0], ["J differs from tripinfo"])
        with self.assertRaises(BR.BError):
            self.run_in()
        self.assertFalse(os.path.exists(os.path.join(self.root, "measure.json")))
        with self.assertRaises(BR.BError):
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests)

    def test_freeze_needs_the_run_in_the_stack_the_tested_code_and_clean_reports(self):
        with self.assertRaises(BR.BError):                                        # no run-in
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests)
        BR.environment = lambda: {"python": "3.11.17", "sumo": "Eclipse SUMO sumo 1.28.0", "platform": "x"}
        self.run_in()
        with self.assertRaises(BR.BError):                                        # not Python 3.7 / SUMO 1.25
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests)
        path = os.path.join(self.root, "measure.json")
        mj = BR.read_json(path)
        mj["environment"] = {"python": "3.7.16", "sumo": "Eclipse SUMO sumo Version 1.25.0"}
        mj["code_sha256"] = dict(mj["code_sha256"], **{"confirmation/b_runner.py": "0" * 64})
        BR.write_json(path, mj)
        with self.assertRaises(BR.BError):                                        # code changed since the run-in
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests)
        mj["code_sha256"] = BR.code_hashes()
        BR.write_json(path, mj)
        bad = os.path.join(self.reports, "bad.txt")
        with open(bad, "w") as f:
            f.write("Result: 299 checks passed, 1 failed.\n")
        with self.assertRaises(BR.BError):
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=bad, tests_report=self.tests)
        with open(bad, "w") as f:
            f.write("Ran 3 tests\n\nFAILED (errors=1)\n")
        with self.assertRaises(BR.BError):
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=bad)
        self.assertFalse(os.path.exists(os.path.join(self.root, "freeze.json")))
        fr, _plan = self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests)
        self.assertEqual(sorted(fr["prerequisites"]), ["etapes_check", "run_in", "unit_tests"])

    def test_nothing_runs_before_the_freeze(self):
        os.makedirs(self.root)
        with self.assertRaises(BR.BError):
            BR.run(self.root, "0/1", evaluator=FakeEvaluator())
        self.assertEqual(self.q(BR.main, ["run", "--root", self.root]), 1)

    def test_freeze_once_then_prepare_with_the_frozen_fingerprint(self):
        fr, plan = self.freeze()
        self.assertEqual(fr["plan_fingerprint"], plan["fingerprint"])
        self.assertEqual(BR.read_json(os.path.join(self.root, "margins.json"))[R2]["primary"], "actuated_min7")
        with self.assertRaises(BR.BError):
            self.freeze()
        with self.assertRaises(BR.BError):
            self.q(BR.prepare, self.root, "0" * 64, *self.roots())
        self.q(BR.prepare, self.root, plan["fingerprint"], *self.roots())
        self.assertEqual(len([n for n in os.listdir(os.path.join(self.root, "manifests"))]), 50)
        self.assertEqual(len(os.listdir(os.path.join(self.root, "checkpoints"))), 30)      # 10 QMIX, 10 VDN, 10 IDQN

    def test_the_A003_check_is_recorded_and_writes_nothing_there(self):
        a003 = os.path.join(self.base, "a003")
        os.makedirs(a003)
        with open(os.path.join(a003, "amendment003.py"), "w") as f:
            f.write("def protocol_hashes():\n    return {'statistics_1_2': '%s'}\n" % BR.conf_plan()["statistics"]["reference"]["protocol_hash"])
        before = sorted(os.listdir(a003))
        fr, _plan = self.freeze(a003_root=a003)
        sys.modules.pop("amendment003", None)
        self.assertEqual(sorted(os.listdir(a003)), before)                        # no __pycache__
        self.assertTrue(fr["statistics_1_2"]["checked"] and fr["statistics_1_2"]["equal"])
        self.assertNotIn(a003, sys.path)
        self.assertEqual(fr["statistics_module_path"], os.path.abspath(BR.statistics_path()))

    def test_a_new_selection_after_the_freeze_is_refused(self):
        _fr, plan = self.freeze()
        shutil.rmtree(self.x)
        write_aext(self.x, {R1: 2.10, R2: 1.20, R3: 3.00})
        with self.assertRaises(BR.BError):
            self.q(BR.prepare, self.root, plan["fingerprint"], *self.roots())

    def test_a_code_change_after_the_freeze_is_refused(self):
        copy_tools = os.path.join(self.base, "tools")
        for rel in BR.CODE_FILES:
            dst = os.path.join(copy_tools, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(BR.TOOLS, rel), dst)
        saved = BR.TOOLS
        BR.TOOLS = copy_tools
        try:
            plan = self.frozen_and_prepared()
            self.assertEqual(BR.load_plan(self.root)["fingerprint"], plan["fingerprint"])
            with open(os.path.join(copy_tools, "comparators_ext", "controllers_g5.py"), "a") as f:
                f.write("\n# changed\n")
            with self.assertRaises(BR.BError):
                BR.load_plan(self.root)
            self.assertEqual(self.q(BR.main, ["progress", "--root", self.root]), 1)
        finally:
            BR.TOOLS = saved

    def test_a_tampered_plan_or_margins_is_refused(self):
        self.frozen_and_prepared()
        path = os.path.join(self.root, "plan.json")
        plan = BR.read_json(path)
        plan["margins"][R1]["delta_s"] = 1.0
        with open(path, "w") as f:
            json.dump(plan, f)
        with self.assertRaises(BR.BError):
            BR.load_plan(self.root)


class Run(Base):

    def setUp(self):
        Base.setUp(self)
        self.plan = self.frozen_and_prepared()

    def test_disk_threshold(self):
        self.assertEqual(BR.check_disk(self.root, 10, 10 ** 6, free=10 ** 7 + BR.SAFETY_BYTES), 10 ** 7 + BR.SAFETY_BYTES)
        with self.assertRaises(BR.BError):
            BR.check_disk(self.root, 10, 10 ** 6, free=10 ** 7 + BR.SAFETY_BYTES - 1)
        ev = FakeEvaluator()
        with self.assertRaises(BR.BError):
            BR.run(self.root, "0/1", evaluator=ev, free=BR.SAFETY_BYTES)
        self.assertEqual(ev.calls, [])
        with self.assertRaises(BR.BError):
            BR.preflight(self.root, free=BR.SAFETY_BYTES)
        self.assertEqual(self.q(BR.preflight, self.root, free=10 ** 13), 0)

    def test_resume_one_retry_and_corrupted_never_rerun(self):
        jobs = self.plan["jobs"]
        crash = jobs[5]["directory"]
        ev = FakeEvaluator(fail={crash})
        codes = [self.q(BR.run, self.root, "{}/4".format(i), evaluator=ev, free=10 ** 13) for i in range(4)]
        self.assertEqual(sorted(codes), [0, 0, 0, 3])
        self.assertEqual(len(ev.calls), 2370)
        self.assertEqual(len(set(ev.calls)), 2370)                                  # no folder twice
        self.assertEqual(BR.classify(self.root, jobs[5])[0], "interrupted")
        self.assertEqual(self.q(BR.progress, self.root), 3)
        ev2 = FakeEvaluator()
        self.assertEqual(self.q(BR.run, self.root, "0/1", evaluator=ev2, free=10 ** 13), 0)
        self.assertEqual(ev2.calls, [crash])                                       # one retry, finished runs kept
        self.assertTrue(os.path.isdir(os.path.join(self.root, crash + ".incomplete1")))
        self.assertEqual(self.q(BR.progress, self.root), 0)
        victim = os.path.join(self.root, jobs[7]["directory"], "cell_summary.json")
        with open(victim, "w") as f:
            f.write("{")
        ev3 = FakeEvaluator()
        self.assertEqual(self.q(BR.run, self.root, "0/1", evaluator=ev3, free=10 ** 13), 5)
        self.assertEqual(ev3.calls, [])
        self.assertEqual(self.q(BR.progress, self.root), 5)

    def test_a_second_interruption_is_left_for_diagnosis(self):
        j = self.plan["jobs"][0]
        ev = FakeEvaluator(fail={j["directory"]})
        self.q(BR.run, self.root, "0/2", evaluator=ev, free=10 ** 13)
        self.assertEqual(self.q(BR.run, self.root, "0/2", evaluator=ev, free=10 ** 13), 3)
        calls = len(ev.calls)
        self.assertEqual(self.q(BR.run, self.root, "0/2", evaluator=ev, free=10 ** 13), 3)
        self.assertEqual(len(ev.calls), calls)

    def test_finished_cells_have_gzipped_readable_logs_and_metrics_last(self):
        j = self.plan["jobs"][0]
        self.q(BR.run, self.root, "0/2370", evaluator=FakeEvaluator(), free=10 ** 13)
        d = os.path.join(self.root, j["directory"])
        self.assertEqual(BR.classify(self.root, j)[0], "complete")
        for name in ("tripinfo.xml", "service_counters.csv", "signal_phases.csv"):
            self.assertFalse(os.path.exists(os.path.join(d, name)))
            with gzip.open(os.path.join(d, name + ".gz"), "rt") as f:
                self.assertEqual(f.read(), "x" * 200)
        self.assertFalse(os.path.exists(os.path.join(d, "evaluation_metrics.json.pending")))
        self.assertFalse(os.path.isdir(d + ".tmp"))

    def test_cell_metrics_problems_make_a_cell_corrupted(self):
        j = self.plan["jobs"][0]
        BR.summarise_cell = lambda jj, w, n: (fake_summary(jj, w, n)[0], ["tripinfo has 99 rows for N = 100"])
        self.q(BR.run, self.root, "0/2370", evaluator=FakeEvaluator(), free=10 ** 13)
        self.assertEqual(BR.classify(self.root, j)[0], "corrupted")

    def test_identity_mismatch_is_corrupted(self):
        j = self.plan["jobs"][0]
        self.q(BR.run, self.root, "0/2370", evaluator=FakeEvaluator(), free=10 ** 13)
        path = os.path.join(self.root, j["directory"], "evaluation_metrics.json")
        m = BR.read_json(path)
        m["checkpoint_sha256"] = "0" * 64
        with open(path, "w") as f:
            json.dump(m, f)
        self.assertEqual(BR.classify(self.root, j)[0], "corrupted")


@unittest.skipUnless(HAVE_STATS, "frozen statistics module not available")
class Analyse(Base):

    def setUp(self):
        Base.setUp(self)
        self.plan = self.frozen_and_prepared()

    def run_all(self, effect, idqn_effect=0.0):
        self.q(BR.run, self.root, "0/1", evaluator=FakeEvaluator(effect=effect, idqn_effect=idqn_effect), free=10 ** 13)

    def small(self):
        saved = BR.conf_plan

        def fast():
            p = saved()
            p["statistics"]["replicates"] = 1000
            return p
        BR.conf_plan = fast
        self.addCleanup(setattr, BR, "conf_plan", saved)

    def test_decisions_on_synthetic_effects(self):
        self.small()
        self.run_all(-0.5)                       # learned 0.5 s better than every comparator, traffic by traffic
        out = os.path.join(self.base, "analysis")
        result, missing = self.q(BR.analyse, self.root, out)
        self.assertEqual(missing, [])
        cats = dict(((d["profile"], d["method"]), d["category"]) for d in result["primary"])
        self.assertEqual(len(cats), 10)
        self.assertTrue(all(c == "SUPERIOR BEYOND MARGIN" for c in cats.values()), cats)
        comps = dict((d["profile"], d["comparator"]) for d in result["primary"])
        self.assertEqual((comps[R1], comps[R2], comps[R3], comps[R0]), ("oft_g5", "actuated_min7", "tod_g5", BR.C19_LABEL))
        for d in result["primary"]:
            self.assertLessEqual(d["ci"][0], d["ci_95"][0])                      # 99.5 % wider than 95 %
        try:
            import matplotlib  # noqa: F401
            self.assertTrue(os.path.getsize(os.path.join(out, "forest.png")) > 1000)
        except ImportError:
            self.assertFalse(os.path.exists(os.path.join(out, "forest.png")))
        for name in ("decisions.csv", "service_counts.csv", "RESULTATS_B.md", "results.json"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        self.assertFalse(os.path.exists(os.path.join(out, "service_rates.csv")))      # no pooled interval any more
        with open(os.path.join(out, "RESULTATS_B.md")) as f:
            text = f.read()
        for words in ("scénario de référence", "scénario 3", "plan fixe optimisé", "règle anti-attente",
                      "temps d'attente moyen par véhicule", "n'établit pas un risque nul", "Famille 2",
                      "extension des références", "relue et recalculée"):
            self.assertIn(words, text)
        # F2: joint learners 0.5 s better than IDQN on R0, decided at 97.5 % within its own family
        joint = dict((d["method"], d) for d in result["joint_learning"])
        self.assertEqual(sorted(joint), ["qmix", "vdn"])
        for d in joint.values():
            self.assertEqual((d["profile"], d["reference"], d["confidence"]), (R0, "idqn", 0.975))
            self.assertEqual(d["category"], "SUPERIOR BEYOND MARGIN")
            self.assertAlmostEqual(d["mean_difference"], -0.5, places=6)
            sens = d["sensitivity_all_12_bonferroni"]
            self.assertAlmostEqual(sens["confidence"], 1 - 0.05 / 12)
            self.assertLessEqual(sens["ci"][0], d["ci"][0])
        import csv as _csv
        with open(os.path.join(out, "service_counts.csv")) as f:
            rows = list(_csv.DictReader(f))
        g = [r for r in rows if r["profile"] == R0 and r["method"] == "idqn" and r["event"] == "failure"][0]
        self.assertEqual((g["evaluations"], g["events"], g["models"], g["traffics"]), ("100", "0", "10", "10"))
        self.assertAlmostEqual(float(g["model_upper95_if_zero"]), 1 - 0.05 ** 0.1)
        cmp_row = [r for r in rows if r["method"] == "canonical_mp" and r["profile"] == R0][0]
        self.assertEqual(cmp_row["models"], "")                                   # one deterministic controller

    def test_equivalence_and_missing_cells_are_not_imputed(self):
        self.small()
        self.run_all(0.0)
        gone = [j for j in self.plan["jobs"] if j["kind"] == "learned" and j["profile"] == R0
                and j["arm"] == "guarantee" and j["method"] == "qmix"][0]
        shutil.rmtree(os.path.join(self.root, gone["directory"]))
        result, missing = self.q(BR.analyse, self.root, os.path.join(self.base, "analysis"))
        self.assertEqual([m["directory"] for m in missing], [gone["directory"]])
        cats = dict(((d["profile"], d["method"]), d["category"]) for d in result["primary"])
        self.assertTrue(cats[(R0, "qmix")].startswith("INCOMPLETE"))
        self.assertEqual(cats[(R0, "vdn")], "EQUIVALENT")
        joint = dict((d["method"], d["category"]) for d in result["joint_learning"])
        self.assertTrue(joint["qmix"].startswith("INCOMPLETE"))                      # the missing QMIX cell
        self.assertEqual(joint["vdn"], "EQUIVALENT")

    def test_a_cell_that_differs_when_re_read_is_excluded(self):
        self.small()
        self.run_all(0.0)
        victim = [j for j in self.plan["jobs"] if j["kind"] == "learned" and j["method"] == "idqn"][0]
        saved = BR.summarise_cell
        BR.summarise_cell = lambda jj, w, n: (dict(saved(jj, w, n)[0], J_primary_s=99.0) if jj["directory"] == victim["directory"]
                                              else saved(jj, w, n)[0], [])
        result, missing = self.q(BR.analyse, self.root, os.path.join(self.base, "analysis"))
        self.assertEqual([(m["directory"], m["state"]) for m in missing], [(victim["directory"], "recheck_mismatch")])
        joint = dict((d["method"], d["category"]) for d in result["joint_learning"])
        self.assertTrue(joint["qmix"].startswith("INCOMPLETE") and joint["vdn"].startswith("INCOMPLETE"))


class RealReaders(Base):
    """The real reader (robustness_analysis.cell_metrics) on complete synthetic cells (the files the evaluators
    write, built by tests/test_robustness_analysis.World), finalised with gzip logs, then re-read from the gzip."""

    def setUp(self):
        Base.setUp(self)
        sys.path.insert(0, HERE)
        import test_robustness_analysis as TRA
        self.TRA = TRA
        BR.summarise_cell = self.saved[1]                                          # the real reader
        self.world = TRA.World(os.path.join(self.base, "world"))
        self.plan = BR.build_plan(self.root, *self.roots())
        self.manifests = os.path.join(self.root, "manifests")
        os.makedirs(self.manifests)
        n = self.world.n[R0]
        for seed in range(8051, 8061):
            with open(os.path.join(self.manifests, "{}_{}.metadata.json".format(R0, seed)), "w") as f:
                json.dump({"scenario": R0, "seed_value": seed, "scheduled_total": n}, f)

    def make(self, j, j_wait=3.0):
        work = os.path.join(self.root, j["directory"]) + ".tmp"
        if j["kind"] == "learned":
            cell = {"scenario": j["profile"], "seed": j["seed"], "controller": j["controller"], "model": j["model"],
                    "directory": work}
            self.world.model_sha[j["model"]] = j["checkpoint_sha256"]
        else:
            cell = {"scenario": j["profile"], "seed": j["seed"], "controller": "fixed:C19", "directory": work}
        os.makedirs(os.path.dirname(work), exist_ok=True)
        self.world.cell(cell, j_wait=j_wait)
        path = os.path.join(work, "evaluation_metrics.json")
        m = BR.read_json(path)
        if j["kind"] == "comparator":
            m["comparator_spec_sha256"] = j["spec_sha256"]
        BR.write_json(path, m)
        BR.finalize_cell(self.root, j, work, os.path.join(self.root, j["directory"]), self.world.n[R0])
        return os.path.join(self.root, j["directory"])

    def jobs(self):
        r0 = [j for j in self.plan["jobs"] if j["profile"] == R0 and j["seed"] == 8051]
        pick = [[j for j in r0 if j["kind"] == "learned" and j["method"] == "qmix" and j["arm"] == "guarantee"][0],
                [j for j in r0 if j["kind"] == "learned" and j["method"] == "idqn"][0],
                [j for j in r0 if j["kind"] == "comparator" and BR.C19_LABEL in j["labels"]][0]]
        return pick

    def test_real_summary_gzip_logs_and_re_read(self):
        for j in self.jobs():
            d = self.make(j)
            self.assertEqual(BR.classify(self.root, j), ("complete", []), j["directory"])
            summary = BR.read_json(os.path.join(d, "cell_summary.json"))
            self.assertAlmostEqual(summary["J_primary_s"], 3.0)
            self.assertEqual(summary["N"], self.world.n[R0])
            for name in ("tripinfo.xml", "service_counters.csv", "signal_phases.csv"):
                self.assertFalse(os.path.exists(os.path.join(d, name)))
                self.assertTrue(os.path.getsize(os.path.join(d, name + ".gz")) > 0)
            self.assertEqual(BR.recheck_cell(self.root, j, self.manifests), [])
        rows, missing = BR.cell_rows(self.root, self.plan)
        self.assertEqual(len(rows), 1 + 1 + len(self.jobs()[2]["labels"]))
        self.assertEqual(set(r["J_primary_s"] for r in rows), {repr(3.0)})

    def test_a_changed_gzip_log_is_detected_on_re_read(self):
        j = self.jobs()[0]
        d = self.make(j)
        trip = os.path.join(d, "tripinfo.xml.gz")
        with gzip.open(trip, "rt") as f:
            text = f.read()
        with gzip.open(trip, "wt") as f:
            f.write(text.replace('waitingTime="3.0"', 'waitingTime="4.0"', 1))
        diff = BR.recheck_cell(self.root, j, self.manifests)
        self.assertTrue(diff and any("problems differ" in x or "J_primary_s" in x for x in diff), diff)
        rows, missing = BR.cell_rows(self.root, self.plan)
        self.assertIn((j["directory"], "recheck_mismatch"), [(m["directory"], m["state"]) for m in missing])

    def test_a_truncated_gzip_log_is_reported_not_crashing(self):
        j = self.jobs()[1]
        d = self.make(j)
        path = os.path.join(d, "signal_phases.csv.gz")
        with open(path, "rb") as f:
            data = f.read()
        with open(path, "wb") as f:
            f.write(data[: len(data) // 2])
        diff = BR.recheck_cell(self.root, j, self.manifests)
        self.assertTrue(diff and diff[0].startswith("re-read from gzip failed"), diff)


if __name__ == "__main__":
    unittest.main()
