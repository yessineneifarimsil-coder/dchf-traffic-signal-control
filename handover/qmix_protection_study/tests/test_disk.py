"""Tests of tools/disk (storage audit, archive of campaign A design runs) on a synthetic A root (stdlib only)."""
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "disk"))

import archive_campaign_A as AR  # noqa: E402
import audit_storage as AU  # noqa: E402


def make_root(base):
    root = os.path.join(base, "A")
    os.makedirs(os.path.join(root, "orders"))
    os.makedirs(os.path.join(root, "selections"))
    os.makedirs(os.path.join(root, "manifests"))
    with open(os.path.join(root, "plan.json"), "w") as f:
        f.write("{}")
    with open(os.path.join(root, "run_log_coarse_shard0of4.jsonl"), "w") as f:
        f.write("{}\n")
    layout = {"coarse": [("8111", "fixed_a"), ("8111", "fixed_b")], "fine-g5": [("8112", "fixed_c")],
              "fine-min7": [("8112", "fixed_c"), ("8113", "fixed_d")], "actuated-design": [("8111", "actuated_e")],
              "tod-design-g5": [("8311", "tod_f")], "tod-design-min7": [],
              "validation-g5": [("8121", "fixed_g")], "actuated-validation": [("8121", "actuated_h")],
              "robustness-eval": [("8101", "fixed_i_full"), ("8111", "fixed_b")]}      # fixed_b is protected
    for stage, items in layout.items():
        jobs = []
        for seed, name in items:
            rel = os.path.join("runs", "R1", seed, name)
            jobs.append({"directory": rel})
            d = os.path.join(root, rel)
            if not os.path.isdir(d):
                os.makedirs(d)
                with open(os.path.join(d, "evaluation_metrics.json"), "w") as f:
                    json.dump({"name": name}, f)
                with gzip.open(os.path.join(d, "tripinfo.xml.gz"), "wt") as f:
                    f.write("<tripinfos>" + name * 50 + "</tripinfos>")
        with open(os.path.join(root, "orders", stage + ".json"), "w") as f:
            json.dump({"stage": stage, "jobs": jobs}, f)
    return root


class Archive(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.root = make_root(self.base)
        self.zip = os.path.join(self.base, "out", "a.zip")
        self.cwd = os.getcwd()
        os.chdir(self.base)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.base)

    def q(self, argv):
        with redirect_stdout(io.StringIO()) as out:
            code = AR.main(argv)
        return code, out.getvalue()

    def test_selection_excludes_protected_stages_and_files(self):
        folders = AR.selected_folders(self.root)
        names = sorted(os.path.basename(f) for f in folders)
        self.assertEqual(names, ["actuated_e", "fixed_a", "fixed_c", "fixed_d", "tod_f"])   # fixed_b protected
        files = AR.files_of(self.root, folders)
        self.assertFalse(any(f.startswith(("orders", "selections", "manifests", "plan.json")) for f in files))

    def test_deletion_is_disabled_in_this_delivery(self):
        self.assertFalse(AR.DELETION_ENABLED)
        code, _ = self.q(["archive", "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(code, 0)
        ver = AR.read_json(self.zip + ".verification.json")
        before = sorted(os.path.relpath(os.path.join(a, x), self.root) for a, d, fs in os.walk(self.root) for x in d + fs)
        code, out = self.q(["--delete", "--confirm", ver["zip_sha256"], "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(code, 1)
        self.assertIn("disabled in this delivery", out)
        after = sorted(os.path.relpath(os.path.join(a, x), self.root) for a, d, fs in os.walk(self.root) for x in d + fs)
        self.assertEqual(before, after)                                           # nothing deleted
        self.assertFalse(os.path.exists(self.zip + ".deleted.json"))

    def enable_deletion_for_this_test(self):
        """The kept two-step logic is tested with deletion enabled in-process only (a later delivery)."""
        AR.DELETION_ENABLED = True
        self.addCleanup(setattr, AR, "DELETION_ENABLED", False)

    def test_archive_verify_dry_run_and_two_step_delete(self):
        self.enable_deletion_for_this_test()
        code, _ = self.q(["archive", "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(code, 0)
        ver = AR.read_json(self.zip + ".verification.json")
        self.assertTrue(ver["ok"])
        self.assertEqual(ver["members"], 10)
        code, out = self.q(["--dry-run", "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(json.loads(out)["folders_to_delete"], 5)
        self.assertTrue(all(os.path.isdir(os.path.join(self.root, "runs", "R1", s, n)) for s, n in
                            (("8111", "fixed_a"), ("8112", "fixed_c"))))                  # dry run changes nothing
        code, out = self.q(["--delete", "--confirm", "0" * 64, "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(code, 1)
        self.assertIn("--confirm must be", out)
        code, out = self.q(["--delete", "--confirm", ver["zip_sha256"], "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "runs", "R1", "8111", "fixed_a")))
        for kept in (("8111", "fixed_b"), ("8121", "fixed_g"), ("8121", "actuated_h"), ("8101", "fixed_i_full")):
            self.assertTrue(os.path.isdir(os.path.join(self.root, "runs", "R1", *kept)), kept)
        for kept in ("plan.json", "orders", "selections", "manifests", "run_log_coarse_shard0of4.jsonl"):
            self.assertTrue(os.path.exists(os.path.join(self.root, kept)))

    def test_delete_refused_when_a_source_changed_or_the_zip_changed(self):
        self.enable_deletion_for_this_test()
        self.q(["archive", "--a-root", self.root, "--zip", self.zip])
        ver = AR.read_json(self.zip + ".verification.json")
        with open(os.path.join(self.root, "runs", "R1", "8111", "fixed_a", "evaluation_metrics.json"), "w") as f:
            f.write("{}")
        code, out = self.q(["--delete", "--confirm", ver["zip_sha256"], "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(code, 1)
        self.assertIn("source changed", out)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "runs", "R1", "8112", "fixed_c")))
        with open(self.zip, "ab") as f:
            f.write(b"x")
        code, out = self.q(["--delete", "--confirm", ver["zip_sha256"], "--a-root", self.root, "--zip", self.zip])
        self.assertIn("zip changed", out)

    def test_existing_zip_is_refused_and_pointer_is_written(self):
        self.assertEqual(self.q(["archive", "--a-root", self.root, "--zip", self.zip])[0], 0)
        self.assertTrue(os.path.isfile(os.path.join("logs", "campaignA_archive.json")))
        code, out = self.q(["archive", "--a-root", self.root, "--zip", self.zip])
        self.assertEqual(code, 1)
        code, out = self.q(["--dry-run", "--a-root", self.root])                       # zip read from the pointer
        self.assertTrue(json.loads(out)["zip_verified"])


class Audit(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.root = make_root(self.base)
        os.makedirs(os.path.join(self.base, "iev", "deep", "deeper"))
        with open(os.path.join(self.base, "iev", "deep", "deeper", "x.bin"), "wb") as f:
            f.write(b"0" * 1000)

    def tearDown(self):
        shutil.rmtree(self.base)

    def test_audit_reports_stages_iev_total_and_need(self):
        out = os.path.join(self.base, "audit.json")
        with redirect_stdout(io.StringIO()):
            AU.main(["--qmix-results", self.base, "--iev", os.path.join(self.base, "iev"), "--a-root", self.root,
                     "--b-root", os.path.join(self.base, "B"), "--aext-root", os.path.join(self.base, "X"),
                     "--drives", self.base, "--out", out])
        with open(out) as f:
            r = json.load(f)
        stages = r["campaign_A"]["runs_by_stage"]
        self.assertEqual(stages["coarse"]["folders"], 2)
        self.assertEqual(stages["fine-min7"]["folders"], 1)          # fixed_c counted once, under fine-g5
        self.assertEqual(r["iev_results_total_gb"], round(1000 / 1e9, 3))
        self.assertNotIn("deep", json.dumps(r["iev_results_total_gb"]))
        self.assertEqual(r["need"]["campaign_B"]["runs"], AU.DEFAULT_B_EVALUATIONS)
        self.assertIsNotNone(r["B_can_start_on_free_space"])


if __name__ == "__main__":
    unittest.main()
