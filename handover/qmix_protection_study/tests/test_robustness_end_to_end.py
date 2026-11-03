"""Synthetic end-to-end pass of the robustness chain: plan -> run (4 shards) -> progress -> analysis.

    python -m unittest tests.test_robustness_end_to_end -v

No SUMO: a fake evaluate_any module writes, for each planned cell, the files of the synthetic World of
test_robustness_analysis.py (same layout and identity stamp as the real evaluator). It injects one complete
scientific failure and one technical interruption (first attempt only). This checks the chaining of the
runner, its cell states, its exit codes and the analysis; it does not check the SUMO evaluator itself.
"""
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools", "robustness"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import robustness_analysis as ra  # noqa: E402
import robustness_runner as rr  # noqa: E402
from test_robustness_analysis import World  # noqa: E402

J_WAIT = {"fixed": 2.0, "canonical_mp": 4.0, "p5": 3.5, "learned": 3.0}


class EndToEnd(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.world = World(self.base)
        cells = self.world.plan["cells"]
        self.failure = [c for c in cells if c["controller"] == "learned:none"][-1]
        self.interrupted = [c for c in cells if c["controller"] == "learned:both"][0]
        self.calls = []
        self.saved = rr.build_plan, sys.modules.get("evaluate_any")
        rr.build_plan = lambda root: (json.loads(json.dumps(self.world.plan)), [], [])
        sys.modules["evaluate_any"] = types.SimpleNamespace(evaluate=self.fake_evaluate)

    def tearDown(self):
        rr.build_plan = self.saved[0]
        if self.saved[1] is None:
            sys.modules.pop("evaluate_any", None)
        else:
            sys.modules["evaluate_any"] = self.saved[1]
        shutil.rmtree(self.base)

    def fake_evaluate(self, controller, prefix, out_dir, checkpoint=None):
        cell = [c for c in self.world.plan["cells"] if os.path.join(self.world.root, c["directory"]) == out_dir][0]
        self.calls.append(cell["directory"])
        if cell is self.interrupted and self.calls.count(cell["directory"]) == 1:
            os.makedirs(out_dir)
            raise RuntimeError("TraCI connection closed")
        self.world.cell(cell, j_wait=J_WAIT[controller.split(":")[0]], fail=cell is self.failure)
        return {}

    def quiet(self, function, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = function(*args)
        return code, out.getvalue()

    def test_plan_run_progress_analysis(self):
        n = len(self.world.plan["cells"])
        codes = [self.quiet(rr.run, self.world.root, "{}/4".format(i))[0] for i in range(4)]
        self.assertEqual(sorted(codes), [0, 0, 0, 3])                      # the interrupted cell's shard
        code, text = self.quiet(rr.progress, self.world.root)
        self.assertEqual(code, 3)
        self.assertIn("finished {}/{}".format(n - 1, n), text)
        self.assertEqual(ra.main(["--root", self.world.root, "--out", os.path.join(self.base, "early")]), 1)
        codes = [self.quiet(rr.run, self.world.root, "{}/4".format(i))[0] for i in range(4)]   # resume
        self.assertEqual(codes, [0, 0, 0, 0])
        self.assertEqual(self.calls.count(self.interrupted["directory"]), 2)
        self.assertEqual(self.calls.count(self.failure["directory"]), 1)          # never rerun
        self.assertEqual(len(self.calls), n + 1)
        code, text = self.quiet(rr.progress, self.world.root)
        self.assertEqual(code, 0)
        self.assertIn("finished {0}/{0} (complete {1}, scientific failures 1)".format(n, n - 1), text)
        out = os.path.join(self.base, "analysis")
        code, _ = self.quiet(ra.main, ["--root", self.world.root, "--out", out])
        self.assertEqual(code, 0)
        with open(os.path.join(out, "summary.json")) as handle:
            summary = json.load(handle)
        self.assertEqual((summary["cells_analysed"], summary["complete"], summary["all_ok"]), (n, True, True))
        with open(os.path.join(out, "REPORT.md")) as handle:
            report = handle.read()
        self.assertNotIn("INCOMPLETE", report)
        self.assertIn("no indefinite denial of service", report)

    def test_a_result_corrupted_after_the_run_blocks_progress_and_analysis(self):
        for i in range(4):
            self.quiet(rr.run, self.world.root, "{}/4".format(i))
        for i in range(4):
            self.quiet(rr.run, self.world.root, "{}/4".format(i))
        victim = [c for c in self.world.plan["cells"] if c["controller"] == "p5:both"][0]
        path = os.path.join(self.world.root, victim["directory"], "protection_record.json")
        os.remove(path)
        self.assertEqual(self.quiet(rr.progress, self.world.root)[0], 5)
        before = len(self.calls)
        self.assertEqual(self.quiet(rr.run, self.world.root, "0/1")[0], 5)
        self.assertEqual(len(self.calls), before)                                 # nothing rerun
        code, text = self.quiet(ra.main, ["--root", self.world.root, "--out", os.path.join(self.base, "a")])
        self.assertEqual(code, 1)
        self.assertIn("corrupted", text)


if __name__ == "__main__":
    unittest.main()
