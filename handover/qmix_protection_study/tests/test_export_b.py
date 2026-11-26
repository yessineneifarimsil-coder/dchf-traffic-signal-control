"""Public export of B (tools/export_b, EXPORT_B.cmd), on the frozen fixture of test_b_runner (2470 synthetic cells).

The fixture is frozen and prepared by the real b_runner; 30 cells of the descriptive "none" arms do not clear; the
frozen analysis (b_runner.analyse) then writes decisions.csv, which reestimate_B.py must find again from
B_episodes.csv alone. Replicates are reduced to 1000 in the analysis and in the re-estimation alike (speed only).
"""
import csv
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
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import test_b_runner as TB  # noqa: E402

BR = TB.BR
sys.path.insert(0, os.path.join(ROOT, "tools", "export_b"))
import common as XC  # noqa: E402
import export_episodes as XE  # noqa: E402
import reestimate_B as RE  # noqa: E402
import search_counts as SC  # noqa: E402
import network_facts as NF  # noqa: E402
import training_facts as TF  # noqa: E402
import check_export as CK  # noqa: E402
import finalize_export as FE  # noqa: E402

FROZEN = os.environ.get("AQ_FROZEN_REPOSITORY", r"C:\Users\LENOVO\QMIX_Traffic_Coordination")
HAVE_FROZEN = os.path.isfile(os.path.join(FROZEN, "src", "adaptive_qmix", "learner.py"))


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def sha_tree(path):
    out = {}
    for d, _s, names in os.walk(path):
        for n in names:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, path)] = hashlib.sha256(f.read()).hexdigest()
    return out


def slurp(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@unittest.skipUnless(TB.HAVE_STATS, "frozen statistics module not available")
class Export(TB.Base):

    def setUp(self):
        TB.Base.setUp(self)
        saved = BR.conf_plan

        def fast():
            p = saved()
            p["statistics"]["replicates"] = 1000
            return p
        BR.conf_plan = fast
        self.addCleanup(setattr, BR, "conf_plan", saved)
        self.addCleanup(setattr, RE, "REPLICATES", RE.REPLICATES)
        self.addCleanup(setattr, RE, "SENSITIVITY_REPLICATES", RE.SENSITIVITY_REPLICATES)
        RE.REPLICATES, RE.SENSITIVITY_REPLICATES = 1000, 2000
        self.plan = self.frozen_and_prepared()
        none_cells = [j["directory"] for j in BR.unique_jobs(self.plan["jobs"])
                      if j["kind"] == "learned" and j["arm"] == "none"]
        self.failed = set(none_cells[::len(none_cells) // 30][:30])
        ev = TB.FakeEvaluator(effect=-0.5, idqn_effect=-0.1, not_cleared=self.failed)
        self.q(BR.run, self.root, "0/1", evaluator=ev, free=10 ** 13)
        self.analysis = os.path.join(self.base, "analysis")
        self.q(BR.analyse, self.root, self.analysis)
        self.export = os.path.join(self.base, "export")
        self.stats = BR.statistics_path(self.root)

    def episodes(self):
        before = sha_tree(self.root)
        code = quiet(XE.main, ["--root", self.root, "--out", self.export])
        self.assertEqual(sha_tree(self.root), before)                     # read-only on BCONF
        return code

    def reestimate(self, episodes=None, out=None, sensitivity=False):
        out = out or self.export
        args = ["--episodes", episodes or os.path.join(self.export, "B_episodes.csv"),
                "--margins", os.path.join(self.export, "B_margins.json"), "--statistics", self.stats, "--out", out,
                "--frozen-decisions", os.path.join(self.analysis, "decisions.csv")]
        return quiet(RE.main, args + (["--sensitivity"] if sensitivity else []))

    def test_episodes_reestimation_sensitivity_and_check(self):
        self.assertEqual(self.episodes(), 0)
        rows = read_csv(os.path.join(self.export, "B_episodes.csv"))
        self.assertEqual(len(rows), 2470)
        self.assertEqual(list(rows[0])[:len(XE.COLUMNS)], XE.COLUMNS)
        self.assertEqual(sum(r["cell_state"] == "scientific_failure" for r in rows), 30)
        self.assertTrue(all(r["J_s"] == "" for r in rows if r["status"] != "CLEARED"))
        g = [r for r in rows if r["controller_kind"] == "learned" and r["arm"] == "guarantee"]
        self.assertEqual((len(g), sum(r["status"] != "CLEARED" for r in g)), (1100, 0))
        self.assertEqual(sorted(set(r["controller_kind"] for r in rows)), ["actuated", "fixed", "learned", "max_pressure", "tod"])
        report = json.loads(slurp(os.path.join(self.export, "B_episodes_report.json")))
        self.assertIn("end_time_s", report["absent_columns"])               # the fake summary has none: reported
        with open(os.path.join(self.export, "B_episodes.csv"), encoding="utf-8") as f:
            self.assertNotIn(os.path.abspath(self.root), f.read())
        # 1.3 / 1.4: the 12 decisions found again from B_episodes.csv alone
        self.assertEqual(self.reestimate(sensitivity=True), 0)
        text = slurp(os.path.join(self.export, "reestimation_vs_frozen.txt"))
        self.assertIn("decisions identical: 12/12", text)
        self.assertIn("VERDICT: IDENTICAL", text)
        mine = read_csv(os.path.join(self.export, "reestimate_B.csv"))
        frozen = read_csv(os.path.join(self.analysis, "decisions.csv"))
        self.assertEqual(sorted(r["decision"] for r in mine), sorted(r["decision"] for r in frozen))
        for a, b in zip(sorted(mine, key=lambda r: (r["question"], r["profile"], r["method"])),
                        sorted(frozen, key=lambda r: (r["question"], r["profile"], r["method"]))):
            for col in ("mean_difference_s", "ci_decision_low", "ci_decision_high", "ci_95_low", "ci_95_high"):
                self.assertEqual(float(a[col]), float(b[col]), (a["profile"], a["method"], col))
        # 1.5: sensitivity, not decisional
        sens = read_csv(os.path.join(self.export, "sensitivity_B.csv"))
        self.assertEqual(len([r for r in sens if r["analysis"].startswith("a_")]), 12 * 6)
        self.assertEqual(len([r for r in sens if r["analysis"] == "b_unpaired_training_seeds"]), 2 * 2)
        self.assertTrue(all(r["status"] == "NOT DECISIONAL (sensitivity)" for r in sens))
        self.assertEqual(set(r["method"] for r in sens if r["analysis"].startswith("b_")), {"qmix", "vdn"})
        # the check before delivery (the other files are stand-ins here)
        for name in ("search_counts.csv", "search_counts_details.json", "network_facts.json", "training_facts.json"):
            with open(os.path.join(self.export, name), "w", encoding="utf-8") as f:
                f.write("{}")
        shutil.copyfile(os.path.join(ROOT, "tools", "export_b", "reestimate_B.py"), os.path.join(self.export, "reestimate_B.py"))
        self.assertEqual(quiet(CK.main, ["--export", self.export, "--bconf", self.root]), 0)
        self.assertIn("0 failed", slurp(os.path.join(self.export, "check_export.txt")))
        self.assertEqual(quiet(FE.main, ["--export", self.export, "--name", "B_export_test"]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.export, "B_export_test.zip.sha256")))
        readme = slurp(os.path.join(self.export, "README_EXPORT.md"))
        self.assertIn("VERDICT: IDENTICAL", readme)
        self.assertIn("non disponible", readme + "non disponible")

    def test_a_changed_value_is_reported_not_corrected(self):
        self.episodes()
        rows = read_csv(os.path.join(self.export, "B_episodes.csv"))
        victim = next(r for r in rows if r["controller_kind"] == "learned" and r["arm"] == "guarantee"
                      and r["profile"] == "R1_sparse_secondary_heavy_main" and r["method"] == "qmix")
        victim["J_s"] = repr(float(victim["J_s"]) + 5.0)
        tampered = os.path.join(self.base, "tampered.csv")
        with open(tampered, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        out = os.path.join(self.base, "re2")
        os.makedirs(out)
        self.assertEqual(self.reestimate(tampered, out), 4)
        text = slurp(os.path.join(out, "reestimation_vs_frozen.txt"))
        self.assertIn("DIFFERENCES FOUND", text)
        self.assertIn("R1_sparse_secondary_heavy_main", text)

    def test_the_export_goes_into_a_new_folder_and_a_wrong_module_is_refused(self):
        os.makedirs(self.export)
        with open(os.path.join(self.export, "x"), "w", encoding="utf-8") as f:
            f.write("x")
        self.assertEqual(quiet(XE.main, ["--root", self.root, "--out", self.export]), 1)
        bad = os.path.join(self.base, "statistics.py")
        with open(self.stats, "rb") as a, open(bad, "wb") as b:
            b.write(a.read() + b"\n# changed\n")
        with self.assertRaises(RE.ReestimationError):
            RE.load_statistics(bad)


class SearchCounts(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base)
        import comparator_search as CS
        self.CS = CS

    def order(self, root, stage, jobs):
        path = os.path.join(root, "orders", stage + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {"stage": stage, "jobs": jobs, "inputs": {}}
        payload["sha256"] = self.CS.sha_obj(payload)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def finish(self, root, j, spec_sha=None):
        d = os.path.join(root, *j["directory"].replace("\\", "/").split("/"))
        os.makedirs(d)
        with open(os.path.join(d, "evaluation_metrics.json"), "w", encoding="utf-8") as f:
            json.dump({"scenario": j["profile"], "traffic_seed": j["seed"], "clearance_status": "CLEARED",
                       "comparator_spec_sha256": spec_sha or j["spec_sha256"]}, f)

    def test_tasks_reuses_repeats_conflicts_and_orphans(self):
        cmp_root, aext = os.path.join(self.base, "cmp"), os.path.join(self.base, "aext")
        P = "R1_sparse_secondary_heavy_main"
        spec = lambda c: self.CS.fixed_spec((c, 10, 5, 0))  # noqa: E731
        j = lambda c, s=8121: self.CS.job(P, s, spec(c))  # noqa: E731
        self.order(cmp_root, "coarse", [j(20), j(21), j(22)])
        self.order(cmp_root, "fine-g5", [j(22), j(23)])                     # 22 reused from coarse
        self.order(cmp_root, "fine-min7", [j(21), j(23), j(24)])            # 21 from coarse, 23 from fine-g5
        clash = dict(j(25), spec_sha256="0" * 64)                            # same folder, another identity
        self.order(cmp_root, "validation-g5", [j(25), j(25), clash])
        for c in (20, 21, 22, 23):
            self.finish(cmp_root, j(c))
        self.finish(cmp_root, j(24), spec_sha="f" * 64)                       # on disk: another identity
        os.makedirs(os.path.join(cmp_root, "runs", P, "8121", "orphan_0000"))
        self.order(aext, "aext-design", [self.CS.job(P, 8121, {"kind": "actuated_g5", "params": {"zone_m": 40}})])
        out = os.path.join(self.base, "out")
        os.makedirs(out)
        quiet(SC.main, ["--cmp", cmp_root, "--aext", aext, "--out", out])
        rows = dict(((r["root"][:5], r["stage"]), r) for r in read_csv(os.path.join(out, "search_counts.csv")))
        A = lambda s: rows[("A (co", s)]  # noqa: E731
        self.assertEqual([A(s)["tasks_in_order"] for s in ("coarse", "fine-g5", "fine-min7", "validation-g5")],
                         ["3", "2", "3", "3"])
        self.assertEqual([A(s)["reused_from_earlier_stage"] for s in ("coarse", "fine-g5", "fine-min7")], ["0", "1", "2"])
        self.assertEqual(A("fine-min7")["reused_from_stages"], "coarse:1;fine-g5:1")
        self.assertEqual(A("validation-g5")["repeated_within_stage"], "2")
        self.assertEqual(A("TOTAL")["tasks_in_order"], "11")
        self.assertEqual(A("TOTAL")["distinct_folders_in_stage"], "6")
        self.assertIn("not named by any order: 1", A("TOTAL")["reused_from_stages"])
        details = json.loads(slurp(os.path.join(out, "search_counts_details.json")))
        kinds = sorted("on_disk" if "on_disk" in c else "identities" for c in details["conflicts"])
        self.assertEqual(kinds, ["identities", "on_disk"])
        self.assertEqual(details["hypothesis_checked"]["reused_fine_min7"]["observed"], 2)
        self.assertEqual(rows[("A-ext", "aext-design")]["tasks_in_order"], "1")


class Facts(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base)

    @unittest.skipUnless(HAVE_FROZEN, "frozen repository not available")
    def test_network_facts_from_the_frozen_network(self):
        config = os.path.join(FROZEN, "config", "adaptive_qmix", "qualification_300m_medium.json")
        net = os.path.join(FROZEN, json.loads(slurp(config))["network"]["path"])
        if not os.path.isfile(net):
            self.skipTest("network file not in this copy of the frozen repository: {}".format(net))
        plan = {"jobs": [{"kind": "comparator", "profile": "R2_single_secondary_trickle", "spec_sha256": "a" * 64,
                          "labels": ["actuated_min7"], "spec": {"kind": "actuated", "params": {"zone_m": 40, "gap_s": 2}}}]}
        f = NF.facts(config, net, plan)
        between = f["storage_between_J1_and_J2"]
        self.assertEqual(between["junction_distance_m"], 300.0)
        self.assertEqual(sorted(e["id"] for e in between["edges"]), ["-E1", "E1"])
        self.assertTrue(all(e["number_of_lanes"] == 2 for e in between["edges"]))
        zone = f["actuated_detection_zones"][0]
        self.assertEqual(zone["zone_m"], 40.0)
        lane = next(l for l in zone["lanes"] if l["lane"] == "E0_0")
        self.assertAlmostEqual(lane["zone_from_lane_start_m"], lane["lane_length_m"] - 40.0)
        for tl in ("J1", "J2"):
            for rec in f["approach_lanes"][tl]["H_in"] + f["approach_lanes"][tl]["V_in"]:
                self.assertAlmostEqual(rec["net_length_m"], rec["config_expected_length_m"], places=1)

    @unittest.skipUnless(HAVE_FROZEN, "frozen repository not available")
    def test_training_facts_cite_file_and_line(self):
        facts = TF.collect(FROZEN)
        self.assertEqual(facts["optimizer"]["learning_rate"]["value"], 0.0005)
        self.assertIn("torch.optim.Adam", facts["optimizer"]["class"]["text"])
        self.assertTrue(isinstance(facts["optimizer"]["class"]["line"], int))
        self.assertEqual(facts["update_schedule"]["target_hard_update_every_learner_events"]["value"], 500)
        self.assertEqual(len(facts["shared_by_two_methods_with_the_same_seed_number"]["namespaces"]), 9)
        self.assertEqual(facts["checkpoint_selection"]["episodes_per_validation_seed"]["value"], "non disponible")
        self.assertEqual(facts["checkpoints_of_B"]["from_robustness_plan"], "non disponible")

    def test_scrubber_removes_home_and_roots(self):
        s = XC.Scrubber(bconf=r"C:\research\confirmation_B_2026-11-24")
        text = s(r"C:\Users\LENOVO\QMIX_PROTECTED\src and C:\research\confirmation_B_2026-11-24\cells\x and "
                 r"c:/users/lenovo/x and C:\\Users\\LENOVO\\y")
        self.assertNotIn("LENOVO", text.upper().replace("<HOME>", ""))
        self.assertIn("<home>", text)
        self.assertIn("<BCONF>", text)


class Static(unittest.TestCase):

    def test_export_cmd_is_crlf_ascii_with_an_exit_at_the_end_of_every_block(self):
        with open(os.path.join(ROOT, "EXPORT_B.cmd"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        lines = raw.decode("ascii").split("\r\n")
        labels, current = {}, None
        for line in lines:
            if line.startswith(":"):
                current = line[1:]
                labels[current] = []
            elif current and line.strip():
                labels[current].append(line)
        self.assertEqual(sorted(labels), ["x_all", "x_check", "x_episodes", "x_facts", "x_finalize", "x_reestimate", "x_search"])
        for label, body in labels.items():
            self.assertTrue(body[-1].startswith("exit /b "), label)
        for word in ("del ", "rmdir", "rd ", "erase ", "move "):
            self.assertFalse([l for l in lines if l.lower().startswith(word)], word)
        self.assertTrue(any("python -I %BEXPORT%\\reestimate_B.py" in l for l in labels["x_reestimate"]))


if __name__ == "__main__":
    unittest.main()
