"""Tests of tools/confirmation/stats_reference.py: reference results, read-only A003 inspection, guarded extraction,
resolution. The frozen statistics module (and numpy) are needed for the results tests."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "confirmation"))
import stats_reference as SR  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE = os.path.isfile(SR.default_statistics())
except ImportError:
    HAVE = False

HASH = SR.DECLARED_HASH


class A003(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.a003 = os.path.join(self.base, "a003")
        os.makedirs(self.a003)
        spec = {"name": "statistics-1.2", "replicates": 10000}
        self.spec = spec
        canon = __import__("hashlib").sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        self.canon = canon
        with open(os.path.join(self.a003, "amendment003.py"), "w") as f:
            f.write('"""A003 stand-in."""\nimport hashlib\nimport json\nSTATISTICS_1_2 = %r\n\n\n'
                    'def protocol_hashes():\n    return {"statistics_1_2": hashlib.sha256(json.dumps(STATISTICS_1_2, '
                    'sort_keys=True).encode()).hexdigest()}\n' % (spec,))
        with open(os.path.join(self.a003, "data.txt"), "w") as f:
            f.write("x")
        lines = ["{}  {}".format(SR.sha256_file(os.path.join(self.a003, n)), n) for n in ("amendment003.py", "data.txt")]
        with open(os.path.join(self.a003, "SHA256SUMS.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")

    def tearDown(self):
        shutil.rmtree(self.base)

    def q(self, argv):
        with redirect_stdout(io.StringIO()) as out:
            code = SR.main(argv)
        return code, out.getvalue()

    def test_inspection_imports_nothing_and_reports_a_pycache_without_touching_it(self):
        os.makedirs(os.path.join(self.a003, "__pycache__"))
        with open(os.path.join(self.a003, "__pycache__", "amendment003.cpython-37.pyc"), "wb") as f:
            f.write(b"\0" * 16)
        before = SR.snapshot(self.a003)
        out = os.path.join(self.base, "inspection.json")
        code, text = self.q(["inspect-a003", "--a003", self.a003, "--out", out])
        self.assertEqual(code, 0)
        self.assertEqual(SR.snapshot(self.a003), before)                     # nothing written, nothing deleted
        rep = SR.read_json(out)
        self.assertTrue(rep["pycache"]["exists"])
        self.assertEqual(rep["pycache"]["files"], ["__pycache__/amendment003.cpython-37.pyc"])
        self.assertIn("does not establish when", rep["pycache"]["note"])
        self.assertEqual(rep["amendment003_py"]["top_level_code"], [])
        m = rep["manifests"][0]
        self.assertEqual(m["file"], "SHA256SUMS.txt")
        self.assertEqual(m["present_not_listed"], ["__pycache__/amendment003.cpython-37.pyc"])
        self.assertNotIn("amendment003", sys.modules)

    def test_extraction_is_guarded_and_leaves_the_folder_unchanged(self):
        ins = os.path.join(self.base, "inspection.json")
        self.q(["inspect-a003", "--a003", self.a003, "--out", ins])
        out = os.path.join(self.base, "extract.json")
        code, text = self.q(["extract-a003", "--a003", self.a003, "--inspection", ins, "--out", out])
        ex = SR.read_json(out)
        self.assertEqual(ex["folder_changed"], [])
        self.assertFalse(os.path.isdir(os.path.join(self.a003, "__pycache__")))   # -B: no bytecode written
        self.assertEqual(ex["statistics_1_2"], self.canon)
        self.assertEqual([m["name"] for m in ex["matches"]], ["STATISTICS_1_2"])
        self.assertEqual(ex["equal_to_declared"], self.canon == HASH)            # stand-in: not the real hash
        self.assertEqual(code, 0 if ex["valid"] else 1)
        self.assertFalse(ex["valid"])

    def test_top_level_code_blocks_the_extraction(self):
        with open(os.path.join(self.a003, "amendment003.py"), "a") as f:
            f.write("open('side_effect.txt', 'w').write('x')\n")
        ins = os.path.join(self.base, "inspection.json")
        self.q(["inspect-a003", "--a003", self.a003, "--out", ins])
        self.assertTrue(SR.read_json(ins)["amendment003_py"]["top_level_code"])
        code, text = self.q(["extract-a003", "--a003", self.a003, "--inspection", ins, "--out", os.path.join(self.base, "x.json")])
        self.assertEqual(code, 1)
        self.assertIn("top-level code", text)

    def test_a_folder_changed_since_the_inspection_is_refused(self):
        ins = os.path.join(self.base, "inspection.json")
        self.q(["inspect-a003", "--a003", self.a003, "--out", ins])
        with open(os.path.join(self.a003, "data.txt"), "w") as f:
            f.write("y")
        code, text = self.q(["extract-a003", "--a003", self.a003, "--inspection", ins, "--out", os.path.join(self.base, "x.json")])
        self.assertEqual(code, 1)
        self.assertIn("changed since the inspection", text)


@unittest.skipUnless(HAVE, "frozen statistics module not available")
class Results(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base)

    def test_reference_results_are_reproduced_and_a_changed_module_is_detected(self):
        out = os.path.join(self.base, "r.json")
        payload, diffs = SR.results(None, out)
        self.assertEqual((payload["status"], diffs), ("REPRODUCED", []))
        self.assertEqual(payload["results"]["non_finite_refused"], "StatisticsError")
        changed = os.path.join(self.base, "statistics.py")
        with open(SR.default_statistics()) as f:
            src = f.read()
        with open(changed, "w") as f:
            f.write(src.replace("rows = generator.integers(0, row_count, size=row_count)",
                                "rows = generator.integers(0, row_count, size=row_count)[::-1].copy()"))
        payload, diffs = SR.results(changed, os.path.join(self.base, "r2.json"))
        self.assertEqual(payload["status"], "DIFFERENT")
        self.assertTrue(diffs)

    def test_resolution_requires_reproduced_results(self):
        out = os.path.join(self.base, "r.json")
        SR.results(None, out)
        bad = SR.read_json(out)
        bad["status"] = "DIFFERENT"
        SR.write_json(os.path.join(self.base, "bad.json"), bad)
        with self.assertRaises(SR.StatsRefError):
            SR.resolve(self.base, "b-crossed-bootstrap-1", os.path.join(self.base, "bad.json"))
        r = SR.resolve(self.base, "b-crossed-bootstrap-1", out)
        self.assertIn("not labelled statistics-1.2", r["label"])


if __name__ == "__main__":
    unittest.main()
