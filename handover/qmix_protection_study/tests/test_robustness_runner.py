"""Tests of the cell states of tools/robustness/robustness_runner.py (review point 3; no SUMO, stdlib only).

    python -m unittest tests.test_robustness_runner -v

A synthetic plan replaces build_plan and a fake evaluate_any module replaces the SUMO evaluator: it writes the
files the real evaluator writes, with the identity stamp, and records every call so that a rerun shows.
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "robustness"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import cell_state as cs  # noqa: E402
import robustness_runner as rr  # noqa: E402

MODEL = "qmix_seed101_t350000"


def write_result(directory, cell, status="CLEARED", checkpoint_sha256=None, skip=()):
    """The files evaluate_any.py writes for this cell (all of them unless listed in skip)."""
    os.makedirs(directory)
    for name in cs.required_files(cell["controller"]):
        if name in skip or name == cs.METRICS:
            continue
        with open(os.path.join(directory, name), "w") as handle:
            handle.write("{}" if name.endswith(".json") else "x\n")
    if cs.METRICS in skip:
        return
    metrics = {"clearance_status": status, "scenario": cell["scenario"], "controller": cell["controller"],
               "traffic_seed": cell["seed"]}
    if cell.get("model"):
        metrics["checkpoint_sha256"] = checkpoint_sha256
    with open(os.path.join(directory, cs.METRICS), "w") as handle:
        json.dump(metrics, handle)


class Runner(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.root = os.path.join(self.base, "root")
        os.makedirs(os.path.join(self.root, "checkpoints"))
        path = os.path.join(self.root, "checkpoints", MODEL + ".pth")
        with open(path, "wb") as handle:
            handle.write(b"weights")
        with open(path, "rb") as handle:
            self.sha = hashlib.sha256(handle.read()).hexdigest()
        cells = []
        for seed in (8001, 8002):
            cells.append({"scenario": "R0_reference", "seed": seed, "controller": "fixed:old_C19_8_5_D9",
                          "directory": os.path.join("cells", "R0_reference", str(seed), "fixed__old_C19_8_5_D9")})
            for arm in ("none", "both"):
                cells.append({"scenario": "R0_reference", "seed": seed, "controller": "learned:" + arm,
                              "model": MODEL, "directory": os.path.join("cells", "R0_reference", str(seed), MODEL,
                                                                        arm)})
        self.plan = {"fingerprint": "f" * 64, "cells": cells, "n_cells": len(cells), "root": self.root,
                     "models": [{"tag": MODEL, "sha256": self.sha}]}
        with open(os.path.join(self.root, "plan.json"), "w") as handle:
            json.dump(self.plan, handle)
        self.calls = []
        self.fail_next = []          # directories whose next evaluation raises before writing any result
        self.saved = rr.build_plan, sys.modules.get("evaluate_any")
        rr.build_plan = lambda root: (json.loads(json.dumps(self.plan)), [], [])
        sys.modules["evaluate_any"] = types.SimpleNamespace(evaluate=self.fake_evaluate)

    def tearDown(self):
        rr.build_plan = self.saved[0]
        if self.saved[1] is None:
            sys.modules.pop("evaluate_any", None)
        else:
            sys.modules["evaluate_any"] = self.saved[1]
        shutil.rmtree(self.base)

    def fake_evaluate(self, controller, prefix, out_dir, checkpoint=None):
        cell = [c for c in self.plan["cells"] if os.path.join(self.root, c["directory"]) == out_dir][0]
        self.calls.append(cell["directory"])
        if cell["directory"] in self.fail_next:
            self.fail_next.remove(cell["directory"])
            os.makedirs(out_dir)
            raise RuntimeError("SUMO connection lost")
        if checkpoint is not None:
            with open(checkpoint, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        else:
            digest = None
        write_result(out_dir, cell, checkpoint_sha256=digest)
        return {}

    def cell(self, i):
        c = self.plan["cells"][i]
        return c, os.path.join(self.root, c["directory"])

    def progress(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = rr.progress(self.root)
        return code, out.getvalue()

    def run_shard(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = rr.run(self.root, "0/1")
        return code, out.getvalue()

    def test_a_clean_run_finishes_every_cell_and_progress_returns_0(self):
        code, _ = self.run_shard()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls), len(self.plan["cells"]))
        code, text = self.progress()
        self.assertEqual(code, 0)
        self.assertIn("finished {0}/{0}".format(len(self.plan["cells"])), text)
        self.assertEqual(self.run_shard()[0], 0)
        self.assertEqual(len(self.calls), len(self.plan["cells"]))         # nothing rerun

    def test_truncated_metrics_are_corrupted_preserved_reported_and_never_rerun(self):
        targets = [self.cell(0), self.cell(3)]
        for c, d in targets:
            write_result(d, c, checkpoint_sha256=self.sha)
            with open(os.path.join(d, cs.METRICS), "w") as handle:
                handle.write('{"clearance_status": "CLEA')
        code, text = self.progress()
        self.assertEqual(code, 5)
        self.assertIn("finished 0/{}".format(len(self.plan["cells"])), text)
        self.assertIn("corrupted 2", text)
        code, text = self.run_shard()
        self.assertEqual(code, 5)
        for c, d in targets:
            self.assertNotIn(c["directory"], self.calls)
            with open(os.path.join(d, cs.METRICS)) as handle:
                self.assertEqual(handle.read(), '{"clearance_status": "CLEA')      # preserved as found
            self.assertIn("CORRUPTED, preserved, NOT rerun: " + c["directory"], text)
        self.assertEqual(len(self.calls), len(self.plan["cells"]) - 2)

    def test_missing_required_files_are_corrupted(self):
        c, d = self.cell(2)                       # learned:both needs the protection files
        write_result(d, c, checkpoint_sha256=self.sha, skip=("protection_decisions.csv",))
        state, why = cs.classify_planned(self.root, c, cs.model_hashes(self.plan))
        self.assertEqual(state, cs.CORRUPTED)
        self.assertIn("protection_decisions.csv", why[0])
        f, fd = self.cell(0)                      # a fixed plan does not need them...
        write_result(fd, f, skip=("service_counters.csv",))     # ...but needs the per-second counters
        self.assertEqual(cs.classify_planned(self.root, f)[0], cs.CORRUPTED)
        self.assertEqual(self.progress()[0], 5)
        self.run_shard()
        self.assertNotIn(c["directory"], self.calls)
        self.assertNotIn(f["directory"], self.calls)

    def test_an_inconsistent_identity_is_corrupted(self):
        hashes = cs.model_hashes(self.plan)
        cases = []
        c, d = self.cell(1)                       # seed 8001, learned:none
        write_result(d, c, checkpoint_sha256="0" * 64)                     # another checkpoint
        cases.append(c)
        c, d = self.cell(4)                       # seed 8002, learned:none
        other = dict(c, seed=8001)
        write_result(d, other, checkpoint_sha256=self.sha)                 # another traffic
        cases.append(c)
        c, d = self.cell(5)                       # seed 8002, learned:both
        write_result(d, dict(c, controller="learned:none"), checkpoint_sha256=self.sha)   # another arm
        cases.append(c)
        for c in cases:
            state, why = cs.classify_planned(self.root, c, hashes)
            self.assertEqual(state, cs.CORRUPTED, c)
            self.assertTrue(why)
        self.assertEqual(self.run_shard()[0], 5)
        for c in cases:
            self.assertNotIn(c["directory"], self.calls)

    def test_a_complete_scientific_failure_is_finished_and_never_rerun(self):
        c, d = self.cell(2)
        write_result(d, c, status="CLEARANCE_FAILURE", checkpoint_sha256=self.sha)
        self.assertEqual(cs.classify_planned(self.root, c, cs.model_hashes(self.plan))[0], cs.SCIENTIFIC_FAILURE)
        code, _ = self.run_shard()
        self.assertEqual(code, 0)
        self.assertNotIn(c["directory"], self.calls)
        code, text = self.progress()
        self.assertEqual(code, 0)
        self.assertIn("scientific failures 1", text)

    def test_an_unknown_status_is_corrupted_not_finished(self):
        c, d = self.cell(0)
        write_result(d, c, status="RUNNING")
        self.assertEqual(cs.classify_planned(self.root, c)[0], cs.CORRUPTED)

    def test_an_interruption_without_result_is_retried_once_then_left_for_diagnosis(self):
        c, d = self.cell(1)
        os.makedirs(d)                            # an interrupted earlier attempt: directory, no metrics
        with open(os.path.join(d, "tripinfo.xml"), "w") as handle:
            handle.write("partial")
        self.fail_next.append(c["directory"])
        code, text = self.run_shard()
        self.assertEqual(code, 3)
        self.assertEqual(self.calls.count(c["directory"]), 1)
        self.assertTrue(os.path.isfile(os.path.join(d + ".incomplete1", "tripinfo.xml")))   # preserved
        self.assertIn("INTERRUPTED: " + c["directory"], text)
        code, text = self.run_shard()             # second interruption: never retried again
        self.assertEqual(code, 3)
        self.assertEqual(self.calls.count(c["directory"]), 1)
        self.assertIn("INTERRUPTED TWICE, preserved, NOT rerun: " + c["directory"], text)
        code, text = self.progress()
        self.assertEqual(code, 3)
        self.assertIn("interrupted 1", text)

    def test_a_first_interruption_is_resumed_and_then_complete(self):
        c, d = self.cell(1)
        os.makedirs(d)
        code, _ = self.run_shard()
        self.assertEqual(code, 0)
        self.assertEqual(self.calls.count(c["directory"]), 1)
        self.assertTrue(os.path.isdir(d + ".incomplete1"))
        self.assertEqual(cs.classify_planned(self.root, c, cs.model_hashes(self.plan))[0], cs.COMPLETE)


class SmokeCheck(unittest.TestCase):
    """cell_state.py check-smoke on the smoke layout (runs/<scenario>/<controller>)."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "manifests"))
        with open(os.path.join(self.base, "manifests", "R2_single_secondary_trickle_8201.metadata.json"), "w") as h:
            json.dump({"scenario": "R2_single_secondary_trickle", "seed_value": 8201}, h)

    def tearDown(self):
        shutil.rmtree(self.base)

    def test_check_smoke(self):
        cell = {"scenario": "R2_single_secondary_trickle", "seed": 8201, "controller": "learned:both"}
        d = os.path.join(self.base, "runs", cell["scenario"], "learned__both")
        write_result(d, cell, checkpoint_sha256=None)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cs.main(["check-smoke", "--root", self.base]), 0)
            self.assertEqual(cs.main(["check-smoke", "--root", self.base, "--stamped"]), 1)   # no checkpoint stamp
        os.remove(os.path.join(d, "service_counters.csv"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cs.main(["check-smoke", "--root", self.base]), 1)


if __name__ == "__main__":
    unittest.main()
