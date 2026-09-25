"""Tests for the revised Amendment-002 driver, against the frozen code.

    set AQ_FROZEN_REPOSITORY=C:\\Users\\LENOVO\\QMIX_Traffic_Coordination
    python -B -m unittest test_amendment002 -v

Nothing here starts SUMO. The end-to-end case builds an original campaign, a
boundary audit and the amendment on disk with a stub runner whose outcome
depends only on the REALIZED plan, and drives every stage through the frozen
campaign, search and protocol modules.
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
from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.protocol import authorization  # noqa: E402
from adaptive_qmix.protocol import stages as protocol_stages  # noqa: E402


AUDIT_WINNERS = [(20, 650, 10), (25, 650, 0), (25, 700, 0), (20, 550, 10),
                 (20, 600, 10)]
ORIGINAL_WINNERS = [(40, 650, 25), (40, 700, 25), (40, 650, 20),
                    (40, 700, 20), (40, 700, 15)]
RUNTIME = {"python": "3.7.16", "numpy": "1.21.6", "pytorch": "1.13.1+cpu",
           "sumo": "Eclipse SUMO sumo Version 1.25.0"}


def _plans(keys):
    return [P.make_plan(*key) for key in keys]


class GridTests(unittest.TestCase):

    def test_generator_is_the_frozen_one_at_the_old_clip(self):
        for winners in (ORIGINAL_WINNERS, AUDIT_WINNERS):
            for invalid in (False, True):
                self.assertEqual(
                    A.fine_candidates(_plans(winners), (40, 140), invalid),
                    P.fine_timing_candidates(_plans(winners), invalid))

    def test_realized_identity_changes_nothing_at_c40_and_above(self):
        coarse = P.coarse_timing_candidates()
        fine = P.fine_timing_candidates(_plans(ORIGINAL_WINNERS))
        offsets = P.fixed_offset_candidates()
        self.assertEqual(len(A.label_groups(coarse)), 1980)
        self.assertEqual((len(fine), len(A.label_groups(fine))), (621, 621))
        self.assertEqual(len(A.label_groups(offsets)), 90)
        self.assertEqual(len(A.label_groups(coarse + fine)),
                         len({A.key_of(p) for p in coarse + fine}))

    def test_accepted_findings(self):
        audit = A.audit_coarse_candidates()
        self.assertEqual((len(audit), len(A.label_groups(audit))), (208, 195))
        fine = A.fine_candidates(_plans(AUDIT_WINNERS))
        self.assertEqual((len(fine), len(A.label_groups(fine))), (834, 486))
        a, b = _plans([(20, 550, 10), (20, 600, 10)])
        self.assertEqual(A.realized_key(a), (20, 8, 6, 10))
        self.assertEqual(A.realized_key(a), A.realized_key(b))

    def test_structural_floor_grid(self):
        report = A.floor_report()
        self.assertEqual(report["labels"], 68)
        self.assertEqual(report["realized_plans"], 40)
        self.assertEqual(report["runs"], 200)
        for cycle in A.FLOOR_CYCLES_S:
            self.assertEqual(A.floor_offsets(cycle), [0, 5, 10, 15])
        self.assertEqual(
            [report["per_cycle"][c]["realized_plans"] for c in (16, 17, 18,
                                                                19)],
            [4, 8, 12, 16])
        for plan in A.floor_candidates():
            P.validate_plan(plan)
            self.assertTrue(P.candidate_is_valid(plan))
        self.assertEqual(A.STRUCTURAL_MIN_CYCLE_S, 16)

    def test_fine_rule_for_a_sub20_centre(self):
        cycles = {p["cycle_s"] for p in A.fine_candidates(
            [P.make_plan(18, 500, 10)])}
        self.assertEqual(cycles, {18, 23, 28})
        lattice = _plans(AUDIT_WINNERS)
        self.assertEqual(A.fine_candidates(lattice),
                         A.fine_candidates(lattice, (20, 140)))

    # --- Union-of-aliases rule and label-free tie-breaks -------------------

    def _realized(self, plans):
        return {A.realized_key(p) for p in plans}

    def test_two_aliases_differ_alone_but_their_union_does_not_depend_on_either(self):
        a, b = _plans([(20, 550, 10), (20, 600, 10)])
        self.assertEqual(A.realized_key(a), A.realized_key(b))
        alone_a = self._realized(A.fine_candidates([a]))
        alone_b = self._realized(A.fine_candidates([b]))
        self.assertNotEqual(alone_a, alone_b)
        self.assertNotIn((20, 9, 5, 10), alone_a)     # lowest-label defect
        self.assertIn((20, 9, 5, 10), alone_b)
        grid = A.combined_coarse_labels()
        via_a, _ = A.fine_union([a], grid)
        via_b, _ = A.fine_union([b], grid)
        self.assertEqual(self._realized(via_a), self._realized(via_b))
        self.assertEqual(self._realized(via_a), alone_a | alone_b)

    def test_every_alias_group_gives_the_same_fine_plans_whichever_names_it(self):
        grid = A.combined_coarse_labels()
        self.assertEqual(len(grid), 1980 + 208 + 68)
        groups = [m for m in A.label_groups(grid).values() if len(m) > 1]
        self.assertEqual(len(groups), 13 + 28)
        for members in groups:
            results = set()
            for alias in members:
                union, report = A.fine_union([alias], grid)
                results.add(frozenset(self._realized(union)))
                self.assertEqual(report[0]["aliases"],
                                 [list(A.key_of(m)) for m in members])
            self.assertEqual(len(results), 1, members)
            name = A.canonical_label(A.realized_key(members[0]))
            union, _ = A.fine_union([name], grid)
            self.assertEqual({frozenset(self._realized(union))}, results)

    def _records(self, evidence_choice, j_of, family=search.DESIGN_FAMILY):
        """Scored records for the combined grid with a chosen alias per plan."""
        records = []
        for realized, members in sorted(A.label_groups(
                A.combined_coarse_labels()).items()):
            alias = members[evidence_choice(realized, len(members))]
            item = {"identity": realized,
                    "name": A.canonical_label(realized),
                    "evidence_label": alias, "members": members}
            record = {"plan": dict(alias), "key": A.key_of(alias),
                      "family": family, "valid": True,
                      "mean_J_primary_s": j_of(realized),
                      "mean_time_loss_s": 1.0 + j_of(realized) % 1,
                      "failed_seeds": []}
            records.append(A.relabel(record, item))
        return records

    def test_ranking_and_selection_do_not_depend_on_which_alias_was_run(self):
        # Coarse J values with massive exact ties, as integer-second SUMO
        # totals can produce.
        def j_of(realized):
            return float((realized[1] * 7 + realized[3]) % 5)
        orders = set()
        selections = set()
        choices = (lambda r, n: 0, lambda r, n: n - 1, lambda r, n: n // 2,
                   lambda r, n: (r[3] + r[1]) % n)
        for choice in choices:
            records = self._records(choice, j_of)
            for retain in (5, 10):
                orders.add((retain, tuple(tuple(r["identity"]) for r in
                                          A.rank_realized(records, retain))))
            chosen = self._records(choice, j_of, search.VALIDATION_FAMILY)
            selections.add(tuple(A.select_realized(chosen)["identity"]))
        self.assertEqual(len(orders), 2)
        self.assertEqual(len(selections), 1)

    def test_the_frozen_label_tie_break_alone_would_have_depended_on_it(self):
        """Negative control: the label-dependence item B asks about is real.

        (20,8,6,10) is realized by (20,550,10) and (20,600,10); (20,8,6,5) by
        (20,550,5) and (20,600,5). With an exact J tie, ordering the ALIASES
        that were run flips with the choice; ordering realized plans cannot.
        """
        tied = ((20, 8, 6, 10), (20, 8, 6, 5))

        def j_of(realized):
            return 1.0 if realized in tied else 9.0

        def pick(low_for):
            return lambda r, n: 0 if r == low_for else n - 1
        raw, named = [], []
        for choice in (pick(tied[0]), pick(tied[1])):
            records = self._records(choice, j_of)
            unnamed = [dict(r, key=tuple(r["evidence_key"])) for r in records]
            raw.append([tuple(r["identity"]) for r in
                        search.rank_by_design(unnamed, 2)])
            named.append([tuple(r["identity"]) for r in
                          A.rank_realized(records, 2)])
        self.assertNotEqual(raw[0], raw[1])
        self.assertEqual(named[0], named[1])
        self.assertEqual(named[0], [(20, 8, 6, 5), (20, 8, 6, 10)])

    def test_canonical_names_order_exactly_like_realized_keys(self):
        grid = A.combined_coarse_labels()
        fine = A.fine_candidates(_plans(AUDIT_WINNERS + ORIGINAL_WINNERS))
        realized = sorted({A.realized_key(p) for p in grid + fine})
        names = [A.key_of(A.canonical_label(r)) for r in realized]
        self.assertEqual(names, sorted(names))
        for r in realized:
            self.assertEqual(A.realized_key(A.canonical_label(r)), r)

    def test_union_rule_and_tie_break_are_no_ops_on_the_original_campaign(self):
        original = P.coarse_timing_candidates()
        frozen = P.fine_timing_candidates(_plans(ORIGINAL_WINNERS))
        union, report = A.fine_union(_plans(ORIGINAL_WINNERS), original,
                                     (40, 140))
        self.assertEqual(union, frozen)
        self.assertTrue(all(len(item["aliases"]) == 1 for item in report))
        labels = original + frozen
        by_label = [A.realized_key(p) for p in sorted(labels, key=A.key_of)]
        self.assertEqual(by_label, sorted(by_label))
        self.assertEqual(len(set(by_label)), len({A.key_of(p) for p in labels}))

    def test_active_constraints(self):
        self.assertEqual(A.active_constraints(P.make_plan(20, 650, 10)),
                         ["gV=5"])
        self.assertEqual(A.active_constraints(P.make_plan(16, 500, 0)),
                         ["cycle floor C=16", "gV=5", "gH=5"])


# ---------------------------------------------------------------------------
# End to end.
# ---------------------------------------------------------------------------

TABLE = {
    (20, 9, 5, 10): 3.0,     # (20,650,10)
    (18, 5, 7, 10): 3.05,    # floor (18,400,10) == (18,450,10)
    (25, 12, 7, 0): 3.1,     # (25,650,0)
    (25, 13, 6, 0): 3.2,     # (25,700,0)
    (20, 8, 6, 10): 3.3,     # (20,550,10) == (20,600,10)
    (40, 22, 12, 25): 5.0,   # the original campaign's winners
    (40, 24, 10, 25): 5.1,
    (40, 22, 12, 20): 5.2,
    (40, 24, 10, 20): 5.3,
    (40, 24, 10, 15): 5.4,
}
FLOOR_FAILURE = (16, 5, 5, 0)


def _stub_j(realized):
    if realized in TABLE:
        return TABLE[realized]
    cycle, g_h, g_v, offset = realized
    return 10.0 + 0.01 * cycle + 0.001 * abs(g_h - 2 * g_v) + 1e-5 * offset


def _run_manifest(**overrides):
    manifest = {"git_commit": A.FROZEN_COMMIT, "git_status_porcelain": "",
                "git_describe": "8c14f32", "runtime": dict(RUNTIME)}
    manifest.update(overrides)
    return manifest


class StubRunner(object):
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)
        self.hashes = {}

    def _sha(self, path):
        if path not in self.hashes:
            self.hashes[path] = A._sha256_file(path)
        return self.hashes[path]

    def __call__(self, traci_module, config, repository_root, controller,
                 manifest_csv_path, route_xml_path, family, seed, sumo_seed,
                 output_directory, plan=None, manifest_index=0, **kwargs):
        realized = A.realized_key(plan)
        self.calls.append((P.candidate_key(plan), realized, family, int(seed)))
        cleared = realized not in self.fail
        value = _stub_j(realized) + 0.001 * (int(seed) % 100)
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
        with open(os.path.join(output_directory,
                               A.RUN_MANIFEST_FILENAME), "w") as handle:
            json.dump(_run_manifest(), handle, sort_keys=True)
        return metrics


def _snapshot(root):
    state = {}
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(directory, name)
            state[path] = (os.path.getsize(path), os.path.getmtime(path))
    return state


class _Patched(object):
    """Temporarily replace a module attribute."""

    def __init__(self, name, value):
        self.name, self.value = name, value

    def __enter__(self):
        self.saved = getattr(A, self.name)
        setattr(A, self.name, self.value)

    def __exit__(self, *exc):
        setattr(A, self.name, self.saved)


class EndToEnd(unittest.TestCase):
    """One world: original campaign, boundary audit, withdrawn root, amendment."""

    @classmethod
    def setUpClass(cls):
        cls._fsync = os.fsync
        os.fsync = lambda _fd: None      # speed only; atomic rename unchanged
        cls.base = tempfile.mkdtemp()
        withdrawn = os.path.join(cls.base, "withdrawn")
        os.makedirs(withdrawn)
        for name in A.WITHDRAWN_FILES:
            with open(os.path.join(withdrawn, name), "w") as handle:
                handle.write("withdrawn " + name + "\n")
        cls.layout = A.Layout(
            os.path.join(cls.base, "original"),
            os.path.join(cls.base, "audit"),
            os.path.join(cls.base, "amendment"),
            withdrawn_root=withdrawn,
        )
        cls.document = os.path.join(cls.base, "ADDENDUM.md")
        with open(cls.document, "w") as handle:
            handle.write("sealed addendum\n")
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
                L.original_manifests, repo, allow_manifest_generation=False)

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
        execute(A.CONTROLLER, P.coarse_timing_candidates(),
                search.DESIGN_FAMILY, L.original_runs)
        campaign.finalise_stage(campaign.TIMING_COARSE_DESIGN,
                                L.original_runs, L.original_manifests,
                                L.original_artefacts, config, repo)
        os.makedirs(L.original_state)
        cls.original_freeze = protocol_stages.artefact_path(
            L.original_state, protocol_stages.FREEZE_BASELINE_PLANS)
        with open(cls.original_freeze, "w") as handle:
            json.dump({"payload": {
                "optimized_fixed_offset": {"selected_key": list(
                    P.candidate_key(offsets[0]))},
                "optimized_fixed_timing": {"selected_key": [40, 650, 23]},
            }}, handle)
        execute(A.CONTROLLER, A.audit_coarse_candidates(),
                search.DESIGN_FAMILY, L.audit_runs)
        best = [_stub_j((20, 9, 5, 10)) + 0.001 * s for s in range(1, 6)]
        cls.patch = _Patched("REPORTED_BEST_BELOW_40", (
            (20, 650, 10), sum(best) / 5.0))
        cls.patch.__enter__()
        cls.protected = [L.original_root, L.audit_root, withdrawn]
        cls.protected_before = dict(
            (root, _snapshot(root)) for root in cls.protected)

    @classmethod
    def tearDownClass(cls):
        cls.patch.__exit__()
        os.fsync = cls._fsync
        shutil.rmtree(cls.base, ignore_errors=True)

    def _precheck(self, **kwargs):
        return A.precheck(self.layout, self.config, RUNTIME, **kwargs)

    # Stages run in name order and build on each other.

    def test_01_precheck_verifies_and_writes_nothing(self):
        before = _snapshot(self.base)
        result = self._precheck()
        existing = result["existing"]
        self.assertEqual(existing["labels"], 2188)
        self.assertEqual(existing["runs"], 10940)
        self.assertEqual(existing["realized_plans"], 2175)
        self.assertEqual(len(existing["aliases"]["groups"]), 13)
        self.assertEqual(existing["aliases"]["checks"], 13 * 5)
        self.assertEqual(existing["aliases"]["max_abs_difference"], 0.0)
        self.assertEqual(tuple(existing["leader"]["identity"]), (20, 9, 5, 10))
        self.assertEqual([A.key_of(p) for p in existing["leader_aliases"]],
                         [(20, 650, 10)])
        self.assertEqual(result["floor"]["runs"], 200)
        self.assertEqual(result["no_op"]["original_coarse"], (1980, 1980))
        A.print_precheck(result)
        self.assertEqual(_snapshot(self.base), before)
        self.assertFalse(os.path.exists(self.layout.amendment_root))

    def test_02_floor_needs_a_sealed_addendum_first(self):
        with self.assertRaises(A.AmendmentError):
            A.run_stage(self.layout, self.config, A.STAGE_FLOOR, StubRunner())
        with self.assertRaises(A.AmendmentError):
            A.prepare_floor(self.layout, self.config, None, RUNTIME)
        A.prepare_floor(self.layout, self.config, self.document, RUNTIME)
        with self.assertRaises(A.AmendmentError):
            A.prepare_floor(self.layout, self.config, self.document, RUNTIME)

    def test_03_floor_runs_40_plans_on_design_only_failures_once(self):
        stub = StubRunner(fail=[FLOOR_FAILURE])
        for shard in range(2):
            A.run_stage(self.layout, self.config, A.STAGE_FLOOR, stub,
                        shard_index=shard, shard_count=2)
        self.assertEqual(len(stub.calls), 200)
        self.assertEqual(len({c[1] for c in stub.calls}), 40)
        self.assertEqual({c[2] for c in stub.calls}, {search.DESIGN_FAMILY})
        self.assertTrue(all(c[1][0] < 20 for c in stub.calls))
        again = StubRunner(fail=[FLOOR_FAILURE])
        A.run_stage(self.layout, self.config, A.STAGE_FLOOR, again)
        self.assertEqual(again.calls, [])      # cleared and failed: none rerun

    def test_04_validation_is_closed_before_the_fine_stage(self):
        with self.assertRaises(Exception):
            A.run_stage(self.layout, self.config, A.STAGE_VALIDATION,
                        StubRunner())
        evidence = A.Evidence(self.layout, self.config, A.EvaluatedIndex())
        with self.assertRaises(A.AmendmentError):
            evidence.manifests(search.VALIDATION_FAMILY)

    def test_05_floor_enters_the_ranking_before_the_top_five(self):
        result = A.finalise_coarse(self.layout, self.config, RUNTIME)
        winners = [tuple(r["identity"]) for r in result["winners"]]
        self.assertEqual(winners, [(20, 9, 5, 10), (18, 5, 7, 10),
                                   (25, 12, 7, 0), (25, 13, 6, 0),
                                   (20, 8, 6, 10)])
        # The (20,8,6,10) winner seeds its fine search from BOTH aliases, so
        # the greens of the current best plan, (9,5) at C=20, are reachable.
        report = dict((tuple(i["realized_key"]), i)
                      for i in result["fine"]["per_winner"])
        pair = report[(20, 8, 6, 10)]
        self.assertEqual(pair["aliases"], [[20, 550, 10], [20, 600, 10]])
        self.assertEqual(len(pair["per_alias_realized_plans"]), 2)
        floor = report[(18, 5, 7, 10)]
        self.assertEqual(floor["aliases"], [[18, 400, 10], [18, 450, 10]])
        greens = {(c["identity"][0], c["identity"][1], c["identity"][2])
                  for c in result["fine"]["classes"]}
        self.assertIn((20, 9, 5), greens)
        A.print_coarse_finalisation(result)
        self.assertEqual(len({tuple(r["identity"]) for r in result["winners"]}),
                         5)
        invalid = [tuple(r["identity"]) for r in result["records"]
                   if not r["valid"]]
        self.assertEqual(invalid, [FLOOR_FAILURE])
        cycles = {c["identity"][0] for c in result["fine"]["classes"]}
        self.assertTrue({18, 23, 28} <= cycles)
        campaign.read_shortlist_artefact(self.layout.artefacts,
                                         campaign.TIMING_COARSE_DESIGN)
        with self.assertRaises(A.AmendmentError):
            A.finalise_coarse(self.layout, self.config, RUNTIME)

    def test_06_fine_simulates_each_new_realized_plan_once(self):
        order = A.read_fine_order(self.layout)
        index = A.evaluated_index(self.layout, include_floor=True)
        stub = StubRunner()
        for shard in range(3):
            A.run_stage(self.layout, self.config, A.STAGE_FINE, stub,
                        shard_index=shard, shard_count=3)
        realized = [c[1] for c in stub.calls]
        self.assertEqual(len(stub.calls), 5 * order["new_plans"])
        self.assertEqual(len(set(realized)), order["new_plans"])
        self.assertFalse(set(realized) & set(index.by_realized))
        self.assertEqual(order["realized_plans"],
                         order["reused_plans"] + order["new_plans"])

    def test_07_fine_top_ten_are_distinct_realized_plans(self):
        result = A.finalise_fine(self.layout, self.config, RUNTIME)
        self.assertEqual(len(result["retained"]), 10)
        self.assertEqual(
            len({tuple(r["identity"]) for r in result["retained"]}), 10)
        self.assertTrue(result["global_stage"]["written"])

    def test_08_validation_uses_only_this_amendments_runs(self):
        stub = StubRunner()
        A.run_stage(self.layout, self.config, A.STAGE_VALIDATION, stub)
        self.assertEqual(len(stub.calls), 50)
        self.assertEqual({c[2] for c in stub.calls},
                         {search.VALIDATION_FAMILY})
        result = A.finalise_validation(self.layout, self.config, RUNTIME)
        self.assertEqual(tuple(result["selected"]["identity"]), (20, 9, 5, 10))

    def test_09_one_freeze_in_a_new_state_that_records_what_it_supersedes(self):
        result = A.freeze(self.layout, self.config, self.adaptive)
        amendment = result["payload"]["protocol_amendment_002"]
        self.assertEqual(amendment["driver_sha256"], A.DRIVER_SHA256)
        self.assertEqual(amendment["supersedes"]["optimized_fixed_timing_key"],
                         [40, 650, 23])
        self.assertEqual(amendment["supersedes"]["artefact_sha256"],
                         A._sha256_file(self.original_freeze))
        evidence = authorization.authorization_evidence(self.layout.state)
        self.assertEqual(evidence["authorising_artefact_sha256"],
                         result["artefact_sha256"])
        with self.assertRaises(A.AmendmentError):
            A.freeze(self.layout, self.config, self.adaptive)

    def test_10_training_is_launched_only_against_the_amended_freeze(self):
        command = A.training_command(self.layout, "qmix", 101)
        self.assertIn("--campaign-state", command)
        self.assertEqual(command[command.index("--campaign-state") + 1],
                         self.layout.state)
        self.assertEqual(command[command.index("--run-kind") + 1],
                         "official_training")
        with self.assertRaises(A.AmendmentError):
            A.training_command(self.layout, "qmix", 101, os.path.join(
                self.layout.original_root, "learners", "qmix", "seed101"))
        taken = os.path.join(self.layout.learners, "vdn", "seed102")
        os.makedirs(taken)
        with self.assertRaises(A.AmendmentError):
            A.training_command(self.layout, "vdn", 102)

    def test_11_learner_evidence_from_the_old_freeze_is_excluded(self):
        required = A.amended_freeze_sha256(self.layout)
        root = os.path.join(self.base, "learners")
        for name, sha in (("seed101_pre_amendment",
                           A._sha256_file(self.original_freeze)),
                          ("seed101", required), ("seed102", required)):
            os.makedirs(os.path.join(root, name))
            with open(os.path.join(root, name, "run_manifest.json"), "w") as h:
                json.dump({"official_scientific_result": True,
                           "method": "qmix", "training_seed": 101,
                           "authorising_artefact_sha256": sha}, h)
        result = A.verify_learners(self.layout, root)
        self.assertEqual(len(result["accepted"]), 2)
        self.assertEqual([os.path.basename(e["directory"])
                          for e in result["excluded"]],
                         ["seed101_pre_amendment"])

    def test_12_protected_roots_were_never_written(self):
        for root in self.protected:
            self.assertEqual(_snapshot(root), self.protected_before[root])
        with self.assertRaises(A.AmendmentError):
            self.layout.assert_writable(os.path.join(
                self.layout.original_artefacts, "x.json"))
        with self.assertRaises(A.AmendmentError):
            A.Layout(self.layout.original_root, self.layout.audit_root,
                     self.layout.withdrawn_root,
                     withdrawn_root=os.path.join(self.base, "elsewhere"))

    def test_13_archive_copies_the_withdrawn_files_read_only(self):
        before = _snapshot(self.layout.withdrawn_root)
        with self.assertRaises(A.AmendmentError):
            A.archive_withdrawn(self.layout.withdrawn_root, os.path.join(
                self.layout.withdrawn_root, "archive"))
        archive = os.path.join(self.base, "WITHDRAWN_v1")
        result = A.archive_withdrawn(self.layout.withdrawn_root, archive)
        self.assertEqual(len(result["files"]), 2)
        self.assertTrue(os.path.isfile(os.path.join(archive,
                                                    "README_WITHDRAWN.md")))
        self.assertEqual(_snapshot(self.layout.withdrawn_root), before)
        with self.assertRaises(A.AmendmentError):
            A.archive_withdrawn(self.layout.withdrawn_root, archive)

    def test_14_edited_orders_and_another_driver_are_refused(self):
        for path in (self.layout.floor_order, self.layout.fine_order):
            backup = path + ".bak"
            shutil.copyfile(path, backup)
            with open(path) as handle:
                order = json.load(handle)
            order["amendment_version"] = "edited"
            with open(path, "w") as handle:
                json.dump(order, handle)
            with self.assertRaises(A.AmendmentError):
                A.run_stage(self.layout, self.config, A.STAGE_FINE,
                            StubRunner())
            shutil.move(backup, path)
        with _Patched("DRIVER_SHA256", "0" * 64):
            with self.assertRaises(A.AmendmentError):
                A.run_stage(self.layout, self.config, A.STAGE_FINE,
                            StubRunner())


class PrecheckFailures(unittest.TestCase):
    """Each check fails closed on its own defect, and says which one."""

    @classmethod
    def setUpClass(cls):
        cls._fsync = os.fsync
        os.fsync = lambda _fd: None
        cls.base = tempfile.mkdtemp()
        cls.layout = A.Layout(
            os.path.join(cls.base, "original"),
            os.path.join(cls.base, "audit"),
            os.path.join(cls.base, "amendment"),
            withdrawn_root=os.path.join(cls.base, "withdrawn"),
        )
        cls.config = load_config(cls.layout.config_path)
        L, config, repo = cls.layout, cls.config, A.REPOSITORY_ROOT
        stub = StubRunner()
        campaign.prepare_seed_manifests(L.original_manifests, config,
                                        search.DESIGN_FAMILY)
        campaign.execute_campaign(
            stub, A.CONTROLLER, P.coarse_timing_candidates(),
            search.DESIGN_FAMILY, config, L.original_runs,
            L.original_manifests, repo, allow_manifest_generation=False)
        campaign.finalise_stage(campaign.TIMING_COARSE_DESIGN,
                                L.original_runs, L.original_manifests,
                                L.original_artefacts, config, repo)
        campaign.execute_campaign(
            stub, A.CONTROLLER, A.audit_coarse_candidates(),
            search.DESIGN_FAMILY, config, L.audit_runs,
            L.original_manifests, repo, allow_manifest_generation=False)
        best = [_stub_j((20, 9, 5, 10)) + 0.001 * s for s in range(1, 6)]
        cls.patch = _Patched("REPORTED_BEST_BELOW_40", (
            (20, 650, 10), sum(best) / 5.0))
        cls.patch.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.patch.__exit__()
        os.fsync = cls._fsync
        shutil.rmtree(cls.base, ignore_errors=True)

    def _audit_run(self, key, seed=2001):
        return campaign.run_directory_for(
            self.layout.audit_runs, A.CONTROLLER, P.make_plan(*key),
            search.DESIGN_FAMILY, seed)

    def _fails(self, fragment, runtime=RUNTIME):
        with self.assertRaises(A.AmendmentError) as caught:
            A.precheck(self.layout, self.config, runtime)
        self.assertIn(fragment, str(caught.exception))

    def _edit_json(self, path, change):
        with open(path) as handle:
            saved = handle.read()
        data = json.loads(saved)
        change(data)
        with open(path, "w") as handle:
            json.dump(data, handle, sort_keys=True)
        return saved

    def test_passes_clean(self):
        A.precheck(self.layout, self.config, RUNTIME)

    def test_label_disagreement_beyond_1e12_stops(self):
        directory = self._audit_run((20, 600, 10))
        metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
        marker_path = os.path.join(directory, campaign.MARKER_FILENAME)
        with open(marker_path) as handle:
            saved_marker = handle.read()
        for delta, fails in ((1e-13, False), (1e-9, True)):
            saved = self._edit_json(metrics_path, lambda m: m.update({
                search.PRIMARY_FIELD: m[search.PRIMARY_FIELD] + delta}))
            marker = json.loads(saved_marker)
            marker.pop("marker_sha256")
            marker["metrics_sha256"] = A._sha256_file(metrics_path)
            campaign.write_completion_marker(directory, marker)
            if fails:
                self._fails("realize the same plan")
            else:
                result = A.precheck(self.layout, self.config, RUNTIME)
                self.assertGreater(
                    result["existing"]["aliases"]["max_abs_difference"], 0)
            with open(metrics_path, "w") as handle:
                handle.write(saved)
            with open(marker_path, "w") as handle:
                handle.write(saved_marker)

    def test_a_dirty_tree_at_run_time_fails(self):
        path = os.path.join(self._audit_run((25, 650, 0), 2003),
                            A.RUN_MANIFEST_FILENAME)
        saved = self._edit_json(path, lambda m: m.update(
            {"git_status_porcelain": " M src/x.py"}))
        self._fails("not clean")
        with open(path, "w") as handle:
            handle.write(saved)

    def test_another_software_stack_fails(self):
        path = os.path.join(self._audit_run((30, 500, 5), 2002),
                            A.RUN_MANIFEST_FILENAME)
        saved = self._edit_json(path, lambda m: m["runtime"].update(
            {"sumo": "Eclipse SUMO sumo Version 1.24.0"}))
        self._fails("software stacks")
        with open(path, "w") as handle:
            handle.write(saved)
        self._fails("this process runs", runtime=dict(RUNTIME, numpy="1.24"))

    def test_another_source_commit_fails(self):
        directory = self._audit_run((35, 400, 20), 2004)
        path = os.path.join(directory, campaign.MARKER_FILENAME)
        with open(path) as handle:
            saved = handle.read()
        marker = json.loads(saved)
        marker.pop("marker_sha256")
        marker["environment"]["source_commit"] = "f" * 40
        campaign.write_completion_marker(directory, marker)
        self._fails("different environment")
        with open(path, "w") as handle:
            handle.write(saved)

    def test_a_missing_audit_run_fails(self):
        directory = self._audit_run((20, 550, 0), 2005)
        path = os.path.join(directory, campaign.MARKER_FILENAME)
        shutil.move(path, path + ".bak")
        self._fails("do not verify")
        shutil.move(path + ".bak", path)

    def test_a_sub20_run_that_predates_the_addendum_fails(self):
        stray = os.path.join(self.layout.audit_runs,
                             A.CONTROLLER + "__C018_f500_D000")
        os.makedirs(stray)
        self._fails("C < 20 runs exist")
        os.rmdir(stray)

    def test_validation_traffic_in_the_audit_fails(self):
        stray = os.path.join(self.layout.audit_runs, "x",
                             "benchmark_validation_seed2101")
        os.makedirs(stray)
        self._fails("Held-out or validation")
        shutil.rmtree(os.path.dirname(stray))

    def test_a_different_audit_report_fails(self):
        with _Patched("REPORTED_BEST_BELOW_40", ((20, 650, 10), 3.0)):
            self._fails("audit reported")

    def test_an_amendment_root_holding_the_withdrawn_files_is_refused(self):
        root = os.path.join(self.base, "old_amendment")
        os.makedirs(root)
        open(os.path.join(root, A.WITHDRAWN_FILES[0]), "w").close()
        with self.assertRaises(A.AmendmentError):
            A.Layout(self.layout.original_root, self.layout.audit_root, root,
                     withdrawn_root=os.path.join(self.base, "w"))


if __name__ == "__main__":
    unittest.main()
