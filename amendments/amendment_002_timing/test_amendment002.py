"""Tests for the Amendment-002 driver, against the frozen code it imports.

Run with the frozen checkout on the path:

    set AQ_FROZEN_REPOSITORY=C:\\Users\\LENOVO\\QMIX_Traffic_Coordination
    python -m unittest test_amendment002 -v

Nothing here starts SUMO. The end-to-end case builds an original campaign, a
boundary audit and the amendment on disk with a stub runner whose outcome is a
function of the EXECUTED plan only, which is the property the executed-plan
collapse relies on, and then drives every stage through the frozen campaign,
search and protocol modules.
"""

from __future__ import absolute_import

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if not os.environ.get("AQ_FROZEN_REPOSITORY"):
    raise unittest.SkipTest("AQ_FROZEN_REPOSITORY is not set")

import amendment002 as A  # noqa: E402
from adaptive_qmix.baselines import campaign, search  # noqa: E402
from adaptive_qmix.baselines import plans as P  # noqa: E402
from adaptive_qmix.baselines.integrity import sha256_file  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.protocol import authorization  # noqa: E402
from adaptive_qmix.protocol import stages as protocol_stages  # noqa: E402


AUDIT_WINNERS = [(20, 650, 10), (25, 650, 0), (25, 700, 0), (20, 550, 10),
                 (20, 600, 10)]
ORIGINAL_WINNERS = [(40, 650, 25), (40, 700, 25), (40, 650, 20),
                    (40, 700, 20), (40, 700, 15)]


def _plans(keys):
    return [P.make_plan(*key) for key in keys]


class GridTests(unittest.TestCase):
    """The numbers the amendment rests on, recomputed from frozen code."""

    def test_parameterised_generator_is_the_frozen_one_at_the_old_clip(self):
        for winners in (ORIGINAL_WINNERS, AUDIT_WINNERS):
            for invalid in (False, True):
                ours = A.fine_candidates(_plans(winners), (40, 140), invalid)
                theirs = P.fine_timing_candidates(_plans(winners), invalid)
                self.assertEqual(ours, theirs)

    def test_amended_counts_under_the_frozen_key_rule(self):
        fine = A.fine_candidates(_plans(AUDIT_WINNERS))
        every = A.fine_candidates(_plans(AUDIT_WINNERS), include_invalid=True)
        audit = set(map(A.key_of, A.audit_coarse_candidates()))
        keys = [A.key_of(p) for p in fine]
        self.assertEqual(len(keys), 834)
        self.assertEqual(len(set(keys)), 834)
        self.assertEqual(len(every) - len(fine), 60)
        self.assertEqual(sum(k in audit for k in keys), 99)
        self.assertEqual(sum(k not in audit for k in keys), 735)
        self.assertEqual(sorted({p["cycle_s"] for p in fine}),
                         [20, 25, 30, 35])

    def test_834_keys_are_486_executed_plans_396_of_them_new(self):
        fine = A.fine_candidates(_plans(AUDIT_WINNERS))
        audit = set(map(A.key_of, A.audit_coarse_candidates()))
        classes = A.plan_classes(fine, prior_keys=audit)
        self.assertEqual(len(classes), 486)
        reused = [c for c in classes if A.key_of(c["representative"]) in audit]
        self.assertEqual(len(reused), 90)
        self.assertEqual(len(classes) - len(reused), 396)
        # A class with an audit member is never re-simulated.
        for item in classes:
            members = set(map(A.key_of, item["members"]))
            if members & audit:
                self.assertIn(A.key_of(item["representative"]), audit)

    def test_collapse_is_a_no_op_on_the_original_campaign(self):
        coarse = P.coarse_timing_candidates()
        self.assertEqual(len(A.plan_classes(coarse)), 1980)
        fine = P.fine_timing_candidates(_plans(ORIGINAL_WINNERS))
        self.assertEqual(len(fine), 621)
        self.assertEqual(len(A.plan_classes(fine)), 621)

    def test_two_audit_winners_are_one_plan_and_add_nothing(self):
        a, b = _plans([(20, 550, 10), (20, 600, 10)])
        self.assertEqual(A.executed_identity(a), A.executed_identity(b))
        four = set(map(A.key_of, A.fine_candidates(_plans(AUDIT_WINNERS[:4]))))
        five = set(map(A.key_of, A.fine_candidates(_plans(AUDIT_WINNERS))))
        self.assertEqual(four, five)
        self.assertEqual(len(A.audit_coarse_candidates()), 208)
        self.assertEqual(len(A.plan_classes(A.audit_coarse_candidates())), 195)

    def test_the_lower_clip_does_no_work_the_min_green_rule_does_not(self):
        clipped = A.fine_candidates(_plans(AUDIT_WINNERS))
        unclipped = A.fine_candidates(_plans(AUDIT_WINNERS), (1, 1000))
        self.assertEqual(clipped, unclipped)
        for plan in clipped:
            P.validate_plan(plan)
            self.assertTrue(P.candidate_is_valid(plan))
            self.assertGreaterEqual(min(plan["green_H_s"],
                                        plan["green_V_s"]), 5)


# ---------------------------------------------------------------------------
# End to end.
# ---------------------------------------------------------------------------

def _stub_j(identity):
    cycle, g_h, g_v, _yellow, offset = identity
    table = {
        (20, 9, 5, 3, 10): 3.0,     # (20,650,10)
        (25, 12, 7, 3, 0): 3.1,     # (25,650,0)
        (25, 13, 6, 3, 0): 3.2,     # (25,700,0)
        (20, 8, 6, 3, 10): 3.3,     # (20,550,10) == (20,600,10)
        (25, 11, 8, 3, 5): 3.4,     # (25,600,5): first distinct runner-up
        (40, 22, 12, 3, 25): 5.0,   # the original campaign's winners
        (40, 24, 10, 3, 25): 5.1,
        (40, 22, 12, 3, 20): 5.2,
        (40, 24, 10, 3, 20): 5.3,
        (40, 24, 10, 3, 15): 5.4,
    }
    if identity in table:
        return table[identity]
    return 10.0 + 0.01 * cycle + 0.001 * abs(g_h - 2 * g_v) + 1e-5 * offset


class StubRunner(object):
    def __init__(self, fail_identities=()):
        self.calls = []
        self.fail = set(fail_identities)
        self.hashes = {}

    def _sha(self, path):
        if path not in self.hashes:
            self.hashes[path] = sha256_file(path)
        return self.hashes[path]

    def __call__(self, traci_module, config, repository_root, controller,
                 manifest_csv_path, route_xml_path, family, seed, sumo_seed,
                 output_directory, plan=None, manifest_index=0, **kwargs):
        identity = A.executed_identity(plan)
        self.calls.append((P.candidate_key(plan), family, int(seed)))
        cleared = identity not in self.fail
        value = _stub_j(identity) + 0.001 * (int(seed) % 100)
        metrics = {
            "controller": controller,
            "clearance_status": "CLEARED" if cleared else "CLEARANCE_FAILURE",
            "J_primary_valid": cleared,
            search.PRIMARY_FIELD: value if cleared else float("nan"),
            search.TIME_LOSS_FIELD: value + 1.0 if cleared else float("nan"),
            "traffic_family": family, "traffic_seed": int(seed),
            "manifest_index": manifest_index,
            "phase_parameters": dict(plan), "sumo_seed": int(sumo_seed),
            "manifest_csv_sha256": self._sha(manifest_csv_path),
            "route_xml_sha256": self._sha(route_xml_path),
        }
        with open(os.path.join(output_directory,
                               campaign.METRICS_FILENAME), "w") as handle:
            json.dump(metrics, handle, sort_keys=True)
        return metrics


class EndToEnd(unittest.TestCase):
    """One world, built once: original campaign, audit, amendment."""

    @classmethod
    def setUpClass(cls):
        cls._fsync = os.fsync
        os.fsync = lambda _fd: None      # speed only; atomic rename unchanged
        cls.base = tempfile.mkdtemp()
        cls.layout = A.Layout(
            os.path.join(cls.base, "original"),
            os.path.join(cls.base, "audit"),
            os.path.join(cls.base, "amendment"),
        )
        cls.config = load_config(cls.layout.config_path)
        cls.adaptive = load_config(cls.layout.adaptive_config_path)
        L, config, repo = cls.layout, cls.config, A.REPOSITORY_ROOT
        stub = StubRunner()
        for family in (search.DESIGN_FAMILY, search.VALIDATION_FAMILY):
            campaign.prepare_seed_manifests(L.original_manifests, config,
                                            family)

        def execute(controller, plans, family, runs):
            campaign.execute_campaign(
                stub, controller, plans, family, config, runs,
                L.original_manifests, repo, allow_manifest_generation=False,
            )

        # Original offset track, through the frozen finaliser.
        execute("optimized_fixed_offset", P.fixed_offset_candidates(),
                search.DESIGN_FAMILY, L.original_runs)
        campaign.finalise_stage(campaign.OFFSET_DESIGN, L.original_runs,
                                L.original_manifests, L.original_artefacts,
                                config, repo)
        offsets = campaign.read_shortlist_artefact(
            L.original_artefacts, campaign.OFFSET_DESIGN)["plans"]
        execute("optimized_fixed_offset", offsets, search.VALIDATION_FAMILY,
                L.original_runs)
        campaign.finalise_stage(campaign.OFFSET_VALIDATION, L.original_runs,
                                L.original_manifests, L.original_artefacts,
                                config, repo)
        # Original timing coarse stage, through the frozen finaliser.
        execute(A.CONTROLLER, P.coarse_timing_candidates(),
                search.DESIGN_FAMILY, L.original_runs)
        campaign.finalise_stage(campaign.TIMING_COARSE_DESIGN,
                                L.original_runs, L.original_manifests,
                                L.original_artefacts, config, repo)
        # A stand-in for the original freeze that Amendment 002 supersedes.
        os.makedirs(L.original_state)
        with open(protocol_stages.artefact_path(
                L.original_state, protocol_stages.FREEZE_BASELINE_PLANS),
                "w") as handle:
            json.dump({"payload": {
                "optimized_fixed_offset": {"selected_key": list(
                    P.candidate_key(offsets[0]))},
                "optimized_fixed_timing": {"selected_key": [40, 650, 23]},
            }}, handle)
        # Boundary audit, 208 x 5 on design traffic only.
        execute(A.CONTROLLER, A.audit_coarse_candidates(),
                search.DESIGN_FAMILY, L.audit_runs)
        cls.world = stub

    @classmethod
    def tearDownClass(cls):
        os.fsync = cls._fsync
        shutil.rmtree(cls.base, ignore_errors=True)

    # Tests run in name order; each stage builds on the previous one.

    def test_1_precheck_counts_and_writes_nothing(self):
        before = set(os.listdir(self.base))
        result = A.precheck(self.layout, self.config)
        coarse, fine = result["coarse"], result["fine"]
        self.assertEqual(coarse["key_count"], 2188)
        self.assertEqual(coarse["run_count"], 10940)
        self.assertEqual(len(coarse["records"]), 1980 + 195)
        self.assertGreaterEqual(coarse["alias_checks"], 13 * 5)
        self.assertEqual(coarse["frozen_rule_top_five"], AUDIT_WINNERS)
        winners = [tuple(r["key"]) for r in coarse["winners"]]
        self.assertEqual(winners, AUDIT_WINNERS[:4] + [(25, 600, 5)])
        expected = A.fine_candidates(_plans(winners))
        self.assertEqual(fine["fine_key_count"], len(expected))
        self.assertEqual(fine["executed_plan_count"],
                         len(A.plan_classes(expected)))
        self.assertEqual(fine["new_run_count"], 5 * fine["new_plan_count"])
        self.assertEqual(fine["reused_plan_count"] + fine["new_plan_count"],
                         fine["executed_plan_count"])
        self.assertEqual(set(os.listdir(self.base)), before)
        A._print_counts(result)
        self.assertFalse(os.path.exists(self.layout.amendment_root))

    def test_2_finalise_coarse_seals_a_frozen_readable_artefact(self):
        A.finalise_coarse(self.layout, self.config)
        artefact = campaign.read_shortlist_artefact(
            self.layout.artefacts, campaign.TIMING_COARSE_DESIGN)
        self.assertEqual([tuple(k) for k in artefact["candidate_keys"]],
                         AUDIT_WINNERS[:4] + [(25, 600, 5)])
        with self.assertRaises(A.AmendmentError):
            A.finalise_coarse(self.layout, self.config)

    def test_3_run_fine_simulates_only_new_plans_and_records_failures(self):
        order = A.read_work_order(self.layout)
        new = order["fine"]["new_work"]
        failing = A.executed_identity(new[-1])
        stub = StubRunner(fail_identities=[failing])
        for shard in range(3):
            A.run_stage(self.layout, self.config, "fine", stub,
                        shard_index=shard, shard_count=3)
        called = set(key for key, _f, _s in stub.calls)
        self.assertEqual(len(stub.calls), 5 * len(new))
        self.assertEqual(called, set(map(A.key_of, new)))
        earlier = A.designations(self.layout)
        self.assertFalse(called & set(earlier))
        # A resumed shard neither reruns a cleared run nor a verified failure.
        again = StubRunner(fail_identities=[failing])
        A.run_stage(self.layout, self.config, "fine", again)
        self.assertEqual(again.calls, [])
        EndToEnd.failing = failing

    def test_4_finalise_fine_keeps_ten_distinct_plans(self):
        result = A.finalise_fine(self.layout, self.config)
        retained = result["retained"]
        self.assertEqual(len(retained), 10)
        self.assertEqual(len({tuple(r["identity"]) for r in retained}), 10)
        invalid = [r for r in result["records"] if not r["valid"]]
        self.assertEqual([tuple(r["identity"]) for r in invalid],
                         [EndToEnd.failing])
        campaign.read_shortlist_artefact(self.layout.artefacts,
                                         campaign.TIMING_FINE_DESIGN)
        self.assertTrue(result["global_stage"]["written"])

    def test_5_validation_selects_with_the_frozen_tie_break(self):
        stub = StubRunner()
        A.run_stage(self.layout, self.config, "validation", stub)
        self.assertEqual(len(stub.calls), 50)
        self.assertEqual({f for _k, f, _s in stub.calls},
                         {search.VALIDATION_FAMILY})
        result = A.finalise_validation(self.layout, self.config)
        self.assertEqual(tuple(result["selected"]["key"]), (20, 650, 10))
        artefact = campaign.read_selected_plan_artefact(
            self.layout.artefacts, campaign.TIMING_VALIDATION)
        self.assertEqual(artefact["selected_key"], [20, 650, 10])

    def test_6_freeze_authorises_training_from_the_new_state_only(self):
        result = A.freeze(self.layout, self.config, self.adaptive)
        payload = result["payload"]
        self.assertEqual(payload["optimized_fixed_timing"]["selected_key"],
                         [20, 650, 10])
        self.assertEqual(
            payload["protocol_amendment_002"]["supersedes"][
                "optimized_fixed_timing_key"], [40, 650, 23])
        evidence = authorization.authorization_evidence(self.layout.state)
        self.assertEqual(
            evidence["frozen_baseline_plans"]["optimized_fixed_timing"],
            [20, 650, 10])
        self.assertEqual(evidence["authorising_artefact_sha256"],
                         result["artefact_sha256"])
        with self.assertRaises(A.AmendmentError):
            A.freeze(self.layout, self.config, self.adaptive)

    def test_7_learners_authorised_by_the_old_freeze_are_excluded(self):
        freeze_sha = sha256_file(protocol_stages.artefact_path(
            self.layout.state, protocol_stages.FREEZE_BASELINE_PLANS))
        root = os.path.join(self.base, "learners")
        for name, sha in (("seed101_pre", "0" * 64), ("seed101", freeze_sha),
                          ("seed102", freeze_sha)):
            os.makedirs(os.path.join(root, name))
            with open(os.path.join(root, name, "run_manifest.json"), "w") as h:
                json.dump({"official_scientific_result": True,
                           "method": "qmix", "training_seed": 101,
                           "authorising_artefact_sha256": sha}, h)
        result = A.verify_learners(self.layout, root)
        self.assertEqual(len(result["accepted"]), 2)
        self.assertEqual([os.path.basename(e["directory"])
                          for e in result["excluded"]], ["seed101_pre"])

    def test_8_tampering_is_refused(self):
        # An edited work order.
        with open(self.layout.work_order, "r") as handle:
            order = json.load(handle)
        order["fine"]["new_plan_count"] += 1
        backup = self.layout.work_order + ".bak"
        shutil.copyfile(self.layout.work_order, backup)
        with open(self.layout.work_order, "w") as handle:
            json.dump(order, handle)
        with self.assertRaises(A.AmendmentError):
            A.read_work_order(self.layout)
        shutil.move(backup, self.layout.work_order)
        # An edited copy of the offset artefact.
        name = A.COPIED_ARTEFACTS[1]
        target = os.path.join(self.layout.artefacts, name)
        shutil.copyfile(target, target + ".bak")
        with open(target, "a") as handle:
            handle.write(" ")
        with self.assertRaises(A.AmendmentError):
            A.verify_offset_copies(self.layout)
        shutil.move(target + ".bak", target)

    def test_9_leakage_and_alias_disagreement_are_refused(self):
        final = os.path.join(self.layout.amendment_root, "manifests")
        os.makedirs(final)
        open(os.path.join(final, "final_test_seed3001.csv"), "w").close()
        with self.assertRaises(A.AmendmentError):
            A.scan_for_leakage(self.layout)
        shutil.rmtree(final)
        validation = os.path.join(self.layout.audit_runs, "x",
                                  "benchmark_validation_seed2101")
        os.makedirs(validation)
        with self.assertRaises(A.AmendmentError):
            A.scan_for_leakage(self.layout)
        shutil.rmtree(os.path.dirname(validation))
        A.scan_for_leakage(self.layout)
        # Two keys of one executed plan that disagree break the collapse.
        plan = P.make_plan(20, 600, 10)
        directory = campaign.run_directory_for(
            self.layout.audit_runs, A.CONTROLLER, plan,
            search.DESIGN_FAMILY, 2001)
        metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
        marker_path = os.path.join(directory, campaign.MARKER_FILENAME)
        saved = []
        for path in (metrics_path, marker_path):
            with open(path) as handle:
                saved.append(handle.read())
        with open(metrics_path) as handle:
            metrics = json.load(handle)
        metrics[search.PRIMARY_FIELD] += 1e-9
        with open(metrics_path, "w") as handle:
            json.dump(metrics, handle, sort_keys=True)
        with open(marker_path) as handle:
            marker = json.load(handle)
        marker.pop("marker_sha256")
        marker["metrics_sha256"] = sha256_file(metrics_path)
        campaign.write_completion_marker(directory, marker)
        with self.assertRaises(A.AmendmentError):
            A.evaluate_coarse(self.layout, self.config)
        for path, text in zip((metrics_path, marker_path), saved):
            with open(path, "w") as handle:
                handle.write(text)


if __name__ == "__main__":
    unittest.main()
