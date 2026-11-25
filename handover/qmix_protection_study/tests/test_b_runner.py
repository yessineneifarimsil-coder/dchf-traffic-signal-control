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
import stats_reference as SR  # noqa: E402

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
    with open(path, "w", encoding="utf-8") as f:
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
    with open(os.path.join(root, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({"models": models}, f)


def fake_manifest(profile, seed, prefix):
    with open(prefix + ".metadata.json", "w", encoding="utf-8") as f:
        json.dump({"scenario": profile, "seed_value": seed, "scheduled_total": 100}, f)


SUMMARY_OVERRIDES = {}       # directory -> fields forced into the fake summary (technical-contract tests)


def fake_summary(j, work, n):
    m = BR.read_json(os.path.join(work, "evaluation_metrics.json"))
    out = {"status": m["clearance_status"], "J_primary_s": m.get("J"), "open_wait_at_end_s": m.get("open_wait"),
           "vehicles_waiting_ge_300s": 0, "D_bar_s": m.get("D_bar", 1.0), "mean_completed_time_loss_s": 2.0,
           "max_vehicle_waiting_s": 50.0, "N": 100, "tripinfo_rows": 100, "max_counter_s": 40, "max_counter_recomputed_s": 40,
           "shortest_green_s": BR.min_green_contract(j) or 5, "counter_rows_differing": 0, "sumo_mismatch_s": 0 if j["kind"] == "learned" else None,
           "interventions_guarantee_demand": 0 if j["kind"] == "learned" else None,
           "interventions_guarantee_after": 0 if j["kind"] == "learned" else None}
    out.update(SUMMARY_OVERRIDES.get(j.get("directory"), {}))
    for k in [k for k, v in out.items() if v == "<absent>"]:
        del out[k]
    return out, []


class FakeEvaluator(object):
    """Writes the files of a real run; J from a synthetic law (learned: comparator J + effect)."""

    def __init__(self, effect=0.0, fail=(), idqn_effect=0.0, not_cleared=()):
        self.calls, self.effect, self.fail, self.idqn_effect = [], effect, set(fail), idqn_effect
        self.not_cleared = set(not_cleared)

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
            with open(os.path.join(work, name), "w", encoding="utf-8") as f:
                f.write("x" * 200)
        m = dict(ident, scenario=j["profile"], traffic_seed=j["seed"], clearance_status="CLEARED", J=value)
        if j["directory"] in self.not_cleared:                                 # a scientific failure, recorded
            m.update(clearance_status="CLEARANCE_FAILURE", J=None, D_bar=2.5)
        with open(os.path.join(work, "evaluation_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)


class Base(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.a, self.x, self.rob, self.root = (os.path.join(self.base, n) for n in ("a", "aext", "rob", "b"))
        self.real_a = write_a(self.a)
        write_aext(self.x, {R1: 2.10, R2: 1.50, R3: 3.00})          # worse than the A primaries: secondary (B2)
        write_rob(self.rob)
        self.saved = (BR.manifest_writer, BR.summarise_cell, BR.environment)
        # restored by addCleanup, which also runs when a subclass setUp fails after this point (a failed setUp
        # skips tearDown: without this, the stand-ins would leak into the next tests)
        self.addCleanup(self.restore, self.saved)
        self.addCleanup(SUMMARY_OVERRIDES.clear)
        BR.manifest_writer, BR.summarise_cell = fake_manifest, fake_summary
        BR.environment = lambda: {"python": "3.7.16", "sumo": "Eclipse SUMO sumo Version 1.25.0", "platform": "test"}
        self.reports = os.path.join(self.base, "logs")
        os.makedirs(self.reports)
        self.etapes = os.path.join(self.reports, "verify_etapes_B.txt")
        self.tests = os.path.join(self.reports, "tests_B.txt")
        with open(self.etapes, "w", encoding="utf-8") as f:
            f.write("...\nResult: 300 checks passed, 0 failed.\n")
        with open(self.tests, "w", encoding="utf-8") as f:
            f.write("Ran 130 tests in 200.1s\n\nOK (skipped=3)\n")
        SUMMARY_OVERRIDES.clear()

    @staticmethod
    def restore(saved):
        BR.manifest_writer, BR.summarise_cell, BR.environment = saved

    def tearDown(self):
        shutil.rmtree(self.base)

    def roots(self):
        return self.a, self.x, self.rob

    def q(self, fn, *args, **kw):
        with redirect_stdout(io.StringIO()):
            return fn(*args, **kw)

    def run_in(self, **kw):
        return self.q(BR.measure, self.root, *self.roots(), evaluator=FakeEvaluator(), workers=kw.get("workers", 1))

    def resolve_stats(self):
        """Synthetic reference results reproduced with the frozen module, then the B procedure resolution. The
        results report is marked Python 3.7.16 as on the Windows stack (stand-in: these tests run on another Python)."""
        os.makedirs(self.root, exist_ok=True)
        path = os.path.join(self.reports, "stats_reference_check.json")
        payload, diffs = SR.results(None, path)
        self.assertEqual(diffs, [])
        payload["python"] = "3.7.16"
        SR.write_json(path, payload)
        return SR.resolve(self.root, "b-crossed-bootstrap-1", path)

    def freeze(self, **kw):
        if not os.path.exists(os.path.join(self.root, "measure.json")):
            self.run_in()
        if not os.path.exists(os.path.join(self.root, "stats_resolution.json")):
            self.resolve_stats()
        kw.setdefault("free", 10 ** 13)
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
        with open(path, "w", encoding="utf-8") as f:
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
        self.assertEqual(len(idqn), 200)                                           # guarantee + none (descriptive)
        self.assertEqual(set(j["profile"] for j in idqn), {R0})
        self.assertEqual(sorted(set(j["arm"] for j in idqn)), ["guarantee", "none"])
        self.assertEqual(sorted(set(j["seed"] for j in idqn)), list(range(8051, 8061)))
        per_profile = dict((p, len([j for j in comp if j["profile"] == p]) // 10) for p in BR.PROFILES)
        # R0, R4: C19, C25, MP. R1, R2: + oft_g5, oft_min7, actuated_min7, actuated_g5 (7 specs).
        # R3: oft_g5 = oft_min7 = C25 12/7 D0 (one spec), + actuated, actuated_g5, tod_g5, tod_min7 (7 specs).
        self.assertEqual(per_profile, {R0: 3, R1: 7, R2: 7, R3: 7, R4: 3})
        self.assertEqual(len(plan["jobs"]), 2470)
        self.assertEqual(len(set(j["directory"] for j in plan["jobs"])), 2470)
        self.assertEqual((plan["estimate"]["learned"], plan["estimate"]["comparators"]), (2200, 270))
        r3c25 = [j for j in comp if j["profile"] == R3 and "fixed:min7_C25_12_7_D0" in j["labels"]][0]
        self.assertEqual(sorted(r3c25["labels"]), ["fixed:min7_C25_12_7_D0", "oft_g5", "oft_min7"])
        self.assertEqual(sorted(set(j["model"] for j in learned if j["method"] != "idqn")), sorted(
            t for m in ("qmix", "vdn") for t in BR.conf_plan()["learned_policies"][m]))
        self.assertTrue(all(BR.SD.role_of(j["profile"], j["seed"]) == "confirmation" for j in plan["jobs"]))

    def test_shards_partition_the_unique_jobs(self):
        plan = BR.build_plan(self.root, *self.roots())
        jobs = plan["jobs"] + plan["jobs"][:9]
        parts = [set(j["directory"] for j in BR.shard(jobs, "{}/4".format(i))) for i in range(4)]
        self.assertEqual(sum(len(p) for p in parts), 2470)
        self.assertEqual(len(set.union(*parts)), 2470)

    def test_the_10_idqn_checkpoints_are_required(self):
        path = os.path.join(self.rob, "plan.json")
        plan = BR.read_json(path)
        plan["models"] = [m for m in plan["models"] if m["tag"] != "idqn_seed107_tTEST"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        with self.assertRaises(BR.BError):
            BR.build_plan(self.root, *self.roots())

    def test_the_fingerprint_ignores_the_estimate_only(self):
        plan = BR.build_plan(self.root, *self.roots())
        os.makedirs(self.root)
        with open(os.path.join(self.root, "measure.json"), "w", encoding="utf-8") as f:
            json.dump({"seconds_learned": 20.0, "seconds_comparator": 15.0, "seconds_learned_max": 30.0,
                       "seconds_comparator_max": 20.0, "bytes_per_run": 10 ** 6, "parallel_efficiency": 0.8,
                       "workers": 4}, f)
        again = BR.build_plan(self.root, *self.roots())
        self.assertEqual(plan["fingerprint"], again["fingerprint"])
        self.assertNotEqual(plan["estimate"], again["estimate"])
        self.assertTrue(again["estimate"]["source"].startswith("measure.json (parallel run-in, 4 workers)"))
        e = again["estimate"]
        self.assertAlmostEqual(e["wall_h_4_workers"], round((2200 * 20.0 + 270 * 15.0) / 4 / 0.8 / 3600, 2))
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
        types = set(r["type"] for r in payload["results"])
        for t in ("learned:qmix:guarantee", "learned:qmix:none", "learned:vdn:guarantee", "learned:vdn:none",
                  "learned:idqn:guarantee", "learned:idqn:none", "comparator:fixed", "comparator:actuated",
                  "comparator:actuated_g5", "comparator:tod", "comparator:canonical_mp"):
            self.assertIn(t, types)                                               # every path of B is exercised
        self.assertEqual(sorted(payload["by_type"]), sorted(types))
        self.assertIn("finalize_gzip_s_per_run", payload)
        self.assertTrue(all(r["recheck"] == [] for r in payload["results"]))          # re-read from gzip

    def test_measure_with_the_planned_parallelism(self):
        payload = self.run_in(workers=4)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["workers"], 4)
        self.assertTrue(0 < payload["parallel_efficiency"] <= 1.0)
        self.assertGreater(payload["throughput_runs_per_h"], 0)
        self.assertEqual(len(payload["results"]), BR.MEASURE_RUNS)
        self.assertEqual(payload["environment"]["python"], "3.7.16")

    def test_measure_under_spawn_as_on_windows(self):
        # Windows starts the workers by "spawn": they inherit no module state, so the stand-in reader must travel
        # in the task (the defect seen in logs/tests_B.txt of 2026-11-24: IndexError in every worker)
        payload = self.q(BR.measure, self.root, *self.roots(), evaluator=FakeEvaluator(), workers=2,
                         start_method="spawn")
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["results"]), BR.MEASURE_RUNS)
        self.assertTrue(all(r["state"] == "complete" and r["recheck"] == [] for r in payload["results"]))

    def test_measure_is_a_gate(self):
        BR.summarise_cell = lambda j, w, n: (fake_summary(j, w, n)[0], ["J differs from tripinfo"])
        with self.assertRaises(BR.BError):
            self.run_in()
        self.assertFalse(os.path.exists(os.path.join(self.root, "measure.json")))
        with self.assertRaises(BR.BError):
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests, free=10 ** 13)

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
        with open(bad, "w", encoding="utf-8") as f:
            f.write("Result: 299 checks passed, 1 failed.\n")
        with self.assertRaises(BR.BError):
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=bad, tests_report=self.tests)
        with open(bad, "w", encoding="utf-8") as f:
            f.write("Ran 3 tests\n\nFAILED (errors=1)\n")
        with self.assertRaises(BR.BError):
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=bad)
        with self.assertRaises(BR.BError):                                        # statistical reference unresolved
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests, free=10 ** 13)
        self.resolve_stats()
        with self.assertRaises(BR.BError):                                        # not enough disk on the target volume
            self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests, free=BR.SAFETY_BYTES)
        self.assertFalse(os.path.exists(os.path.join(self.root, "freeze.json")))
        fr, _plan = self.q(BR.freeze, self.root, *self.roots(), etapes_report=self.etapes, tests_report=self.tests, free=10 ** 13)
        self.assertEqual(sorted(fr["prerequisites"]), ["etapes_check", "run_in", "unit_tests"])
        self.assertTrue(fr["statistical_procedure"]["label"].startswith("b-crossed-bootstrap-1"))
        self.assertEqual(fr["statistical_procedure"]["procedure"], "b-crossed-bootstrap-1")
        self.assertIn("not labelled statistics-1.2", fr["statistical_procedure"]["label"])

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

    def test_a_resolution_with_another_statistics_module_or_a_changed_report_is_refused(self):
        self.run_in()
        r = self.resolve_stats()
        path = os.path.join(self.root, "stats_resolution.json")
        bad = dict(r, results=dict(r["results"], statistics_module_sha256="0" * 64))
        BR.write_json(path, bad)
        with self.assertRaises(BR.BError):
            self.freeze()
        BR.write_json(path, r)
        with open(r["results"]["path"], "a", encoding="utf-8") as f:
            f.write(" ")
        with self.assertRaises(BR.BError):
            self.freeze()

    def test_a_statistics_1_2_resolution_is_refused(self):
        os.makedirs(self.root)
        path = os.path.join(self.reports, "stats_reference_check.json")
        SR.results(None, path)
        with self.assertRaises(SR.StatsRefError):
            SR.resolve(self.root, "statistics-1.2", path)
        self.assertFalse(os.path.exists(os.path.join(self.root, "stats_resolution.json")))
        # a resolution written by hand with another procedure is refused by the freeze
        self.run_in()
        r = self.resolve_stats()
        BR.write_json(os.path.join(self.root, "stats_resolution.json"), dict(r, procedure="statistics-1.2"))
        with self.assertRaises(BR.BError):
            self.freeze()

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
            with open(os.path.join(copy_tools, "comparators_ext", "controllers_g5.py"), "a", encoding="utf-8") as f:
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
        with open(path, "w", encoding="utf-8") as f:
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
        self.assertEqual(len(ev.calls), 2470)
        self.assertEqual(len(set(ev.calls)), 2470)                                  # no folder twice
        self.assertEqual(BR.classify(self.root, jobs[5])[0], "interrupted")
        self.assertEqual(self.q(BR.progress, self.root), 3)
        ev2 = FakeEvaluator()
        self.assertEqual(self.q(BR.run, self.root, "0/1", evaluator=ev2, free=10 ** 13), 0)
        self.assertEqual(ev2.calls, [crash])                                       # one retry, finished runs kept
        self.assertTrue(os.path.isdir(os.path.join(self.root, crash + ".incomplete1")))
        self.assertEqual(self.q(BR.progress, self.root), 0)
        victim = os.path.join(self.root, jobs[7]["directory"], "cell_summary.json")
        with open(victim, "w", encoding="utf-8") as f:
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
        self.q(BR.run, self.root, "0/2470", evaluator=FakeEvaluator(), free=10 ** 13)
        d = os.path.join(self.root, j["directory"])
        self.assertEqual(BR.classify(self.root, j)[0], "complete")
        for name in ("tripinfo.xml", "service_counters.csv", "signal_phases.csv"):
            self.assertFalse(os.path.exists(os.path.join(d, name)))
            with gzip.open(os.path.join(d, name + ".gz"), "rt", encoding="utf-8") as f:
                self.assertEqual(f.read(), "x" * 200)
        self.assertFalse(os.path.exists(os.path.join(d, "evaluation_metrics.json.pending")))
        self.assertFalse(os.path.isdir(d + ".tmp"))

    def test_cell_metrics_problems_make_a_cell_corrupted(self):
        j = self.plan["jobs"][0]
        BR.summarise_cell = lambda jj, w, n: (fake_summary(jj, w, n)[0], ["tripinfo has 99 rows for N = 100"])
        self.q(BR.run, self.root, "0/2470", evaluator=FakeEvaluator(), free=10 ** 13)
        self.assertEqual(BR.classify(self.root, j)[0], "corrupted")

    def run_one(self, j, **override):
        SUMMARY_OVERRIDES[j["directory"]] = override
        self.q(BR.run, self.root, "{}/2470".format(self.plan["jobs"].index(j)), evaluator=FakeEvaluator(), free=10 ** 13)
        return BR.classify(self.root, j)

    def pick(self, **kw):
        return [j for j in self.plan["jobs"] if all(j.get(k) == v for k, v in kw.items())][0]

    def test_cleared_guarantee_cell_above_the_counter_bound_is_a_technical_failure(self):
        state, why = self.run_one(self.pick(kind="learned", arm="guarantee"), max_counter_s=128, max_counter_recomputed_s=128)
        self.assertEqual(state, "corrupted")
        self.assertTrue(any("above the guarantee bound 127" in w for w in why), why)

    def test_the_counter_bound_is_not_imposed_on_the_none_arm(self):
        state, why = self.run_one(self.pick(kind="learned", arm="none"), max_counter_s=400, max_counter_recomputed_s=400)
        self.assertEqual((state, why), ("complete", []))

    def test_a_sumo_signal_mismatch_fails_every_learned_arm(self):
        for arm in ("guarantee", "none"):
            state, why = self.run_one(self.pick(kind="learned", arm=arm, method="idqn"), sumo_mismatch_s=1)
            self.assertEqual(state, "corrupted", arm)

    def test_a_missing_critical_field_is_a_technical_failure(self):
        state, why = self.run_one(self.pick(kind="learned", arm="guarantee", method="vdn"), shortest_green_s="<absent>")
        self.assertEqual(state, "corrupted")
        self.assertTrue(any("critical field shortest_green_s missing" in w for w in why), why)

    def test_minimum_green_follows_the_evaluated_controller(self):
        self.assertEqual(self.run_one(self.pick(kind="learned", arm="guarantee", method="qmix"), shortest_green_s=2)[0],
                         "complete")                                           # 2 s greens are allowed to learners
        self.assertEqual(self.run_one(self.pick(kind="learned", arm="none", method="qmix"), shortest_green_s=1)[0], "corrupted")
        g5 = [j for j in self.plan["jobs"] if j["kind"] == "comparator" and j["spec"]["kind"] == "actuated_g5"][0]
        self.assertEqual(self.run_one(g5, shortest_green_s=5)[0], "complete")
        g5b = [j for j in self.plan["jobs"] if j["kind"] == "comparator" and j["spec"]["kind"] == "actuated_g5"][1]
        self.assertEqual(self.run_one(g5b, shortest_green_s=4)[0], "corrupted")
        fixed = [j for j in self.plan["jobs"] if j["kind"] == "comparator" and j["spec"]["kind"] == "fixed"][0]
        self.assertEqual(self.run_one(fixed, shortest_green_s=1)[0], "complete")   # pretimed: no realised-minimum contract

    def test_a_scientific_failure_is_finished_and_never_rerun(self):
        j = self.pick(kind="learned", arm="none", method="idqn")
        ev = FakeEvaluator(not_cleared={j["directory"]})
        pos = "{}/2470".format(self.plan["jobs"].index(j))
        self.q(BR.run, self.root, pos, evaluator=ev, free=10 ** 13)
        self.assertEqual(BR.classify(self.root, j)[0], "scientific_failure")
        self.assertEqual(self.q(BR.run, self.root, pos, evaluator=ev, free=10 ** 13), 0)
        self.assertEqual(ev.calls, [j["directory"]])                              # finished: not rerun

    def test_identity_mismatch_is_corrupted(self):
        j = self.plan["jobs"][0]
        self.q(BR.run, self.root, "0/2470", evaluator=FakeEvaluator(), free=10 ** 13)
        path = os.path.join(self.root, j["directory"], "evaluation_metrics.json")
        m = BR.read_json(path)
        m["checkpoint_sha256"] = "0" * 64
        with open(path, "w", encoding="utf-8") as f:
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
            self.assertLessEqual(d["ci"][0], d["ci_95"][0])                      # 1 - 0.05/12 wider than 95 %
            self.assertEqual(d["confidence"], 1 - 0.05 / 12)
        try:
            import matplotlib  # noqa: F401
            self.assertTrue(os.path.getsize(os.path.join(out, "forest.png")) > 1000)
        except ImportError:
            self.assertFalse(os.path.exists(os.path.join(out, "forest.png")))
        for name in ("decisions.csv", "service_counts.csv", "RESULTATS_B.md", "results.json"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        self.assertFalse(os.path.exists(os.path.join(out, "service_rates.csv")))      # no pooled interval any more
        with open(os.path.join(out, "RESULTATS_B.md"), encoding="utf-8") as f:
            text = f.read()
        for words in ("scénario de référence", "scénario 3", "plan fixe optimisé", "règle anti-attente",
                      "temps d'attente moyen par véhicule", "n'établit pas un risque nul", "une seule famille de 12 contrastes",
                      "extension des références", "relue et recalculée", "Effet de la règle anti-attente",
                      "n'est pas une pénalité appariée", "ne prouve pas un effet causal"):
            self.assertIn(words, text)
        # joint learners 0.5 s better than IDQN on R0, decided with the same global correction (family of 12)
        joint = dict((d["method"], d) for d in result["joint_learning"])
        self.assertEqual(sorted(joint), ["qmix", "vdn"])
        for d in joint.values():
            self.assertEqual((d["profile"], d["reference"], d["confidence"]), (R0, "idqn", 1 - 0.05 / 12))
            self.assertEqual(d["category"], "SUPERIOR BEYOND MARGIN")
            self.assertAlmostEqual(d["mean_difference"], -0.5, places=6)
            self.assertEqual(d["conditional_descriptive_cleared_pairs"]["pairs_used"], 100)
        res = BR.read_json(os.path.join(out, "results.json"))
        self.assertEqual(res["mode"], "confirmatory")
        eff = dict(((e["profile"], e["method"]), e) for e in res["guarantee_effects"])
        self.assertEqual(sorted(k for k in eff if k[1] == "idqn"), [(R0, "idqn")])      # IDQN only on R0
        self.assertEqual(eff[(R0, "idqn")]["guarantee"]["expected"], 100)
        self.assertEqual(eff[(R0, "idqn")]["D_bar_guarantee_minus_none_all_valid_pairs"]["pairs"], 100)
        self.assertEqual(len(res["D_bar_contrasts"]), 12)
        import csv as _csv
        with open(os.path.join(out, "service_counts.csv"), encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        g = [r for r in rows if r["profile"] == R0 and r["method"] == "idqn" and r["arm"] == "guarantee"
             and r["event"] == "failure"][0]
        self.assertEqual((g["expected"], g["evaluations"], g["events"], g["models"], g["traffics"]), ("100", "100", "0", "10", "10"))
        self.assertAlmostEqual(float(g["models_upper95_one_sided"]), 1 - 0.05 ** 0.1)
        self.assertEqual(set(r["profile"] for r in rows if r["method"] == "idqn"), {R0})   # no false incompleteness
        cmp_row = [r for r in rows if r["method"] == "canonical_mp" and r["profile"] == R0][0]
        self.assertEqual(cmp_row["models"], "")                                   # one deterministic controller

    def test_the_report_is_written_when_the_default_encoding_is_cp1252(self):
        """Windows retour of 2026-11-25: open() without encoding used cp1252 and "D\u0304" (D-bar) failed in write_report.
        Every text open() of the modules used by the analysis now defaults to cp1252 here, as on Windows, and the
        console is a strict ASCII stream: the report must still be written in UTF-8 and nothing printed may fail."""
        import builtins
        import confirmation_analysis as CA
        import stats_reference as SR2
        real_open = builtins.open

        def windows_open(file, mode="r", buffering=-1, encoding=None, *args, **kw):
            if "b" not in mode and encoding is None:
                encoding = "cp1252"                      # what Python 3.7 uses on a French/English Windows
            return real_open(file, mode, buffering, encoding, *args, **kw)
        for module in (BR, CA, SR2):
            setattr(module, "open", windows_open)
            self.addCleanup(delattr, module, "open")
        self.small()
        self.run_all(-0.5)
        out = os.path.join(self.base, "analysis")
        console = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
        with redirect_stdout(console):
            rc = BR.main(["analyse", "--root", self.root, "--out", out])          # the console lines of b-analyse
            console.flush()
        printed = console.buffer.getvalue().decode("ascii")
        self.assertEqual(rc, 0, printed)
        self.assertIn("missing cells: 0", printed)
        self.assertEqual(printed.count("[family of 12]"), 12)
        with real_open(os.path.join(out, "RESULTATS_B.md"), "rb") as f:
            text = f.read().decode("utf-8")              # strict: the report is UTF-8
        self.assertIn("D\u0304", text)
        self.assertIn("scénario de référence", text)

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
        # a technical failure blocks EVERY confirmatory decision, not only the contrasts of that cell
        self.assertTrue(all(d["category"] == BR.BLOCKED for d in result["primary"] + result["joint_learning"]))

    def test_without_re_read_nothing_is_confirmatory(self):
        self.small()
        self.run_all(-0.5)
        result, _missing = self.q(BR.analyse, self.root, os.path.join(self.base, "diag"), recheck=False)
        self.assertTrue(all(d["category"] == BR.DIAGNOSTIC for d in result["primary"] + result["joint_learning"]))
        with open(os.path.join(self.base, "diag", "RESULTATS_B.md"), encoding="utf-8") as f:
            self.assertIn("MODE DIAGNOSTIC", f.read())

    def test_a_technical_contract_violation_blocks_the_decisions(self):
        self.small()
        victim = [j for j in self.plan["jobs"] if j["kind"] == "learned" and j["arm"] == "guarantee" and j["profile"] == R3][0]
        SUMMARY_OVERRIDES[victim["directory"]] = {"max_counter_s": 200, "max_counter_recomputed_s": 200}
        self.run_all(-0.5)
        self.assertEqual(BR.classify(self.root, victim)[0], "corrupted")
        self.assertEqual(self.q(BR.progress, self.root), 5)
        result, missing = self.q(BR.analyse, self.root, os.path.join(self.base, "analysis"))
        self.assertTrue(all(d["category"] == BR.BLOCKED for d in result["primary"] + result["joint_learning"]))


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
            with open(os.path.join(self.manifests, "{}_{}.metadata.json".format(R0, seed)), "w", encoding="utf-8") as f:
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
        with gzip.open(trip, "rt", encoding="utf-8") as f:
            text = f.read()
        with gzip.open(trip, "wt", encoding="utf-8") as f:
            f.write(text.replace('waitingTime="3.0"', 'waitingTime="4.0"', 1))
        diff = BR.recheck_cell(self.root, j, self.manifests)
        self.assertTrue(diff and any("problems differ" in x or "J_primary_s" in x for x in diff), diff)
        rows, missing = BR.cell_rows(self.root, self.plan)
        self.assertIn((j["directory"], "recheck_mismatch"), [(m["directory"], m["state"]) for m in missing])

    def test_a_changed_counter_in_the_gzip_trace_is_detected(self):
        j = self.jobs()[0]
        d = self.make(j)
        path = os.path.join(d, "service_counters.csv.gz")
        with gzip.open(path, "rt", encoding="utf-8") as f:
            lines = f.read().splitlines()
        head = lines[0].split(",")
        k = head.index("c_V")
        cells = lines[200].split(",")
        cells[k] = str(int(cells[k]) + 150)
        lines[200] = ",".join(cells)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        diff = BR.recheck_cell(self.root, j, self.manifests)
        self.assertTrue(any("counter_rows_differing" in x or "max_counter" in x for x in diff), diff)

    def test_a_scientific_failure_cell_from_the_real_reader_stays_a_finished_observation(self):
        # none arm: a clearance failure with a long red is a scientific observation (no counter contract there)
        j = [x for x in self.plan["jobs"] if x["profile"] == R0 and x["seed"] == 8051 and x["kind"] == "learned"
             and x["method"] == "idqn" and x["arm"] == "none"][0]
        work = os.path.join(self.root, j["directory"]) + ".tmp"
        self.world.model_sha[j["model"]] = j["checkpoint_sha256"]
        os.makedirs(os.path.dirname(work), exist_ok=True)
        self.world.cell({"scenario": R0, "seed": j["seed"], "controller": j["controller"], "model": j["model"],
                         "directory": work}, fail=True)
        BR.finalize_cell(self.root, j, work, os.path.join(self.root, j["directory"]), self.world.n[R0])
        state, why = BR.classify(self.root, j)
        self.assertEqual(state, "scientific_failure", why)
        self.assertEqual(BR.recheck_cell(self.root, j, self.manifests), [])

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

    def test_the_same_failure_in_a_guarantee_arm_is_a_technical_violation(self):
        j = self.jobs()[1]                                            # IDQN with the guarantee
        work = os.path.join(self.root, j["directory"]) + ".tmp"
        self.world.model_sha[j["model"]] = j["checkpoint_sha256"]
        os.makedirs(os.path.dirname(work), exist_ok=True)
        self.world.cell({"scenario": R0, "seed": j["seed"], "controller": j["controller"], "model": j["model"],
                         "directory": work}, fail=True)
        BR.finalize_cell(self.root, j, work, os.path.join(self.root, j["directory"]), self.world.n[R0])
        state, why = BR.classify(self.root, j)
        self.assertEqual(state, "corrupted")                          # not hidden as a scientific failure
        self.assertTrue(any("above the guarantee bound" in w for w in why), why)


if __name__ == "__main__":
    unittest.main()
