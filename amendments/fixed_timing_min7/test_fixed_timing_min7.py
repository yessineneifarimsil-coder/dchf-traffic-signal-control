"""Tests for the min-7 fixed-timing driver, against the frozen code.

    set AQ_FROZEN_REPOSITORY=C:\\Users\\LENOVO\\QMIX_Traffic_Coordination
    python -B -m unittest test_fixed_timing_min7 -v

Nothing here starts SUMO (see sumo_checks_min7.py for that). The end-to-end
case builds, with a stub runner whose outcome depends only on the REALIZED
plan, an original campaign, a boundary audit and a complete Amendment 002
(floor, fine, validation, amended freeze selecting (19, 577, 9) as the real one
did), plus historical QMIX checkpoints and protected-pilot results; then it
drives every min-7 stage and the development comparison through the frozen
campaign, search and protocol modules.
"""

from __future__ import absolute_import

import argparse
import hashlib
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

import fixed_timing_min7 as M  # noqa: E402
from adaptive_qmix.baselines import campaign, search  # noqa: E402
from adaptive_qmix.baselines import plans as P  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402

A = M.A
RUNTIME = {"python": "3.7.16", "numpy": "1.21.6", "pytorch": "1.13.1+cpu",
           "sumo": "Eclipse SUMO sumo Version 1.25.0"}
G5 = 5


def _plans(keys):
    return [P.make_plan(*key) for key in keys]


def _record(plan, j, time_loss, family=search.DESIGN_FAMILY):
    realized = A.realized_key(plan)
    item = {"identity": realized, "name": A.canonical_label(realized),
            "evidence_label": plan, "members": [plan]}
    return A.relabel({"plan": dict(plan), "key": A.key_of(plan), "family": family,
                      "valid": True, "mean_J_primary_s": j,
                      "mean_time_loss_s": time_loss, "failed_seeds": []}, item)


class GridTests(unittest.TestCase):

    def test_at_minimum_green_5_the_grids_are_amendment_002s(self):
        self.assertEqual(M.coarse_labels(G5), A.combined_coarse_labels())
        self.assertEqual(M.floor_cycles(G5), A.FLOOR_CYCLES_S)
        winners = _plans([(20, 650, 10), (25, 650, 0), (18, 400, 10),
                          (40, 650, 25), (19, 600, 10)])
        for invalid in (False, True):
            self.assertEqual(M.fine_candidates(winners, (16, 140), G5, invalid),
                             A.fine_candidates(winners, (16, 140), invalid))
            self.assertEqual(M.fine_candidates(winners, (40, 140), G5, invalid),
                             P.fine_timing_candidates(winners, invalid))
        grid = A.combined_coarse_labels()
        mine, _ = M.fine_union(winners[:2], grid, (16, 140), G5)
        theirs, _ = A.fine_union(winners[:2], grid)
        self.assertEqual(mine, theirs)

    def test_greens_below_7_are_filtered_everywhere(self):
        labels = M.coarse_labels()
        self.assertTrue(labels)
        self.assertTrue(all(p["green_H_s"] >= 7 and p["green_V_s"] >= 7 for p in labels))
        rejected = [p for p in M.short_cycle_labels(include_invalid=True)
                    if not M.admissible(p)]
        self.assertEqual(len(rejected), 220 - 163)
        self.assertTrue(all(min(p["green_H_s"], p["green_V_s"]) < 7 for p in rejected))
        winners = _plans([(20, 500, 10), (25, 650, 0), (40, 300, 0), (140, 750, 135)])
        fine = M.fine_candidates(winners)
        every = M.fine_candidates(winners, include_invalid=True)
        self.assertTrue(len(fine) < len(every))
        self.assertTrue(all(M.admissible(p) for p in fine))
        self.assertTrue(all(not M.admissible(p) for p in every
                            if A.key_of(p) not in set(map(A.key_of, fine))))

    def test_short_cycles_and_the_20_second_bound(self):
        self.assertEqual(M.STRUCTURAL_MIN_CYCLE_S, 20)
        self.assertEqual(M.CYCLE_BOUNDS_S, (20, 140))
        self.assertEqual(M.FLOOR_CYCLES_S, ())
        self.assertEqual(M.floor_labels(), [])
        report = M.grid_report()
        self.assertEqual(report["original_coarse"]["labels"], 1980)
        self.assertEqual((report["short_cycles"]["labels"],
                          report["short_cycles"]["realized_plans"]), (163, 158))
        self.assertEqual((report["combined"]["labels"],
                          report["combined"]["realized_plans"]), (2143, 2138))
        per = dict((c["cycle_s"], c) for c in report["per_cycle"])
        self.assertEqual(per[20]["greens"], [(7, 7)])
        self.assertEqual(per[20]["offsets"], [0, 5, 10, 15])
        self.assertEqual([per[c]["labels"] for c in (20, 25, 30, 35)], [4, 35, 54, 70])
        self.assertNotIn(16, per)
        # A centre at the bound searches 20, 25, 30 and nothing shorter.
        cycles = {p["cycle_s"] for p in M.fine_candidates(_plans([(20, 500, 10)]))}
        self.assertEqual(cycles, {20, 25, 30})
        self.assertIn((20, 7, 7, 3), {A.realized_key(p) for p in M.fine_candidates(
            _plans([(20, 500, 10)]))})

    def test_every_min7_coarse_plan_was_evaluated_by_an_earlier_stage(self):
        earlier = set(A.label_groups(A.combined_coarse_labels()))
        self.assertTrue(set(A.label_groups(M.coarse_labels())) <= earlier)

    def test_union_of_aliases_does_not_depend_on_which_alias_names_the_winner(self):
        grid = M.coarse_labels()
        groups = [m for m in A.label_groups(grid).values() if len(m) > 1]
        self.assertTrue(groups)
        for members in groups:
            unions = set()
            for alias in members + [A.canonical_label(A.realized_key(members[0]))]:
                union, report = M.fine_union([alias], grid)
                unions.add(frozenset(A.realized_key(p) for p in union))
                self.assertEqual(report[0]["aliases"], [list(A.key_of(m)) for m in members])
            self.assertEqual(len(unions), 1)

    def test_selection_and_tie_break_are_deterministic(self):
        tied = _plans([(25, 650, 0), (20, 500, 10), (20, 500, 5), (30, 500, 0)])
        records = [_record(p, 3.0, 11.0, search.VALIDATION_FAMILY) for p in tied]
        records.append(_record(P.make_plan(35, 500, 0), 2.9, 12.0,
                               search.VALIDATION_FAMILY))
        choices = set()
        for order in (records, list(reversed(records)), records[2:] + records[:2]):
            choices.add(tuple(A.select_realized(order)["identity"]))
        self.assertEqual(choices, {(35, 15, 14, 0)})        # lowest J first
        records.pop()
        choices = set(tuple(A.select_realized(o)["identity"])
                      for o in (records, list(reversed(records))))
        self.assertEqual(choices, {(20, 7, 7, 5)})          # then cycle, then key
        ranked = [tuple(r["identity"]) for r in A.rank_realized(
            [_record(p, 3.0, 11.0) for p in tied], 3)]
        self.assertEqual(ranked, [(20, 7, 7, 5), (20, 7, 7, 10), (25, 12, 7, 0)])

    def test_active_constraints(self):
        self.assertEqual(M.active_constraints(P.make_plan(20, 500, 0)),
                         ["cycle floor C=20", "gV=7", "gH=7"])
        self.assertEqual(M.active_constraints(P.make_plan(25, 650, 0)), ["gV=7"])
        self.assertEqual(M.active_constraints(P.make_plan(60, 500, 0)), [])

    def test_development_traffic_cannot_enter_the_search(self):
        for seed in M.COMPARISON_SEEDS:
            with self.assertRaises(Exception):
                search.assert_family_allowed(M.DEVELOPMENT_FAMILY, [seed])
        self.assertFalse(set(M.COMPARISON_SEEDS) & set(search.DESIGN_SEEDS))
        self.assertFalse(set(M.COMPARISON_SEEDS) & set(search.VALIDATION_SEEDS))


# ---------------------------------------------------------------------------
# End to end.
# ---------------------------------------------------------------------------

TABLE = {
    # Amendment 002 (minimum green 5), as the test of the executed driver
    (20, 9, 5, 10): 3.0,
    (18, 5, 7, 10): 3.05,
    (25, 12, 7, 0): 3.1,        # admissible under min 7 (gV = 7)
    (25, 13, 6, 0): 3.2,
    (20, 8, 6, 10): 3.3,
    (40, 22, 12, 25): 5.0,
    (40, 24, 10, 25): 5.1,
    (40, 22, 12, 20): 5.2,
    (40, 24, 10, 20): 5.3,
    (40, 24, 10, 15): 5.4,
    # ... with a floor plan and its fine neighbour, so that the amended freeze
    # selects (19, 577, 9) = C 19, gH 8, gV 5, Delta 9, as the real one did.
    (19, 8, 5, 10): 2.9,
    (19, 8, 5, 9): 2.7,
    # Min-7 plans: the cycle bound and a fine-only plan.
    (20, 7, 7, 10): 3.35,
    (20, 7, 7, 12): 2.8,
}
FLOOR_FAILURE = (16, 5, 5, 0)
MIN7_FAILURE = (20, 7, 7, 13)          # a new min-7 fine plan that does not clear


def _stub_j(realized):
    if realized in TABLE:
        return TABLE[realized]
    cycle, g_h, g_v, offset = realized
    return 10.0 + 0.01 * cycle + 0.001 * abs(g_h - 2 * g_v) + 1e-5 * offset


def _write_tripinfo(directory, j_value, arrived=2800):
    """As the frozen runs write it: unfinished trips too, with arrival -1."""
    with open(os.path.join(directory, "tripinfo.xml"), "w") as handle:
        handle.write("<tripinfos>\n")
        for index in range(2800):
            handle.write('<tripinfo id="v{}" depart="0" departDelay="0.00" '
                         'arrival="{}" duration="10" routeLength="1" waitingTime="{!r}" '
                         'waitingCount="1" timeLoss="1"/>\n'.format(
                             index, "10" if index < arrived else "-1.00", j_value))
        handle.write("</tripinfos>\n")


class KeyboardInterruptLike(RuntimeError):
    """An interruption between the metrics and the outcome marker."""


class StubRunner(object):
    def __init__(self, fail=(), drift=None, tripinfo=(), interrupt_after_metrics=()):
        self.calls = []
        self.fail = set(fail)
        self.drift = drift or {}
        self.tripinfo = set(tripinfo)
        self.interrupt_after_metrics = set(interrupt_after_metrics)
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
        value = _stub_j(realized) + 0.001 * (int(seed) % 100) + self.drift.get(
            (realized, int(seed)), 0.0)
        metrics = {
            "controller": controller,
            "clearance_status": "CLEARED" if cleared else "CLEARANCE_FAILURE",
            "J_primary_valid": cleared,
            search.PRIMARY_FIELD: value if cleared else float("nan"),
            search.TIME_LOSS_FIELD: value + 1.0 if cleared else float("nan"),
            "completed_count": 2800 if cleared else 2700,
            "traffic_family": family, "traffic_seed": int(seed),
            "manifest_index": manifest_index,
            "phase_parameters": dict(plan), "sumo_seed": int(sumo_seed),
            "manifest_csv_sha256": self._sha(manifest_csv_path),
            "route_xml_sha256": self._sha(route_xml_path),
            "baseline_config_sha256": config["_config_sha256"],
        }
        # As the frozen runner: run_manifest first, tripinfo, then the metrics.
        with open(os.path.join(output_directory, A.RUN_MANIFEST_FILENAME), "w") as handle:
            json.dump({"git_commit": A.FROZEN_COMMIT, "git_status_porcelain": "",
                       "git_describe": "8c14f32", "runtime": dict(RUNTIME),
                       "controller": controller, "phase_parameters": dict(plan),
                       "traffic_family": family, "traffic_seed": int(seed),
                       "sumo_seed": int(sumo_seed),
                       "route_xml_sha256": self._sha(route_xml_path),
                       "network_sha256": config["network"]["sha256"]},
                      handle, sort_keys=True)
        if family == M.DEVELOPMENT_FAMILY or P.candidate_key(plan) in self.tripinfo:
            _write_tripinfo(output_directory, value, 2800 if cleared else 2700)
        with open(os.path.join(output_directory, campaign.METRICS_FILENAME), "w") as handle:
            json.dump(metrics, handle, sort_keys=True)
        if P.candidate_key(plan) in self.interrupt_after_metrics:
            raise KeyboardInterruptLike("interrupted after the metrics, before the marker")
        return metrics


class StubEvaluator(object):
    """Stands in for the frozen evaluate_checkpoint.py subprocess."""

    def __init__(self, network_sha256, fail=(), crash=(), interrupt_after_metrics=(),
                 wrong_checkpoint=()):
        self.calls, self.fail, self.crash = [], set(fail), set(crash)
        self.network_sha256 = network_sha256
        self.interrupt_after_metrics = set(interrupt_after_metrics)
        self.wrong_checkpoint = set(wrong_checkpoint)

    def __call__(self, layout, cell, prefix, sumo_seed, directory):
        self.calls.append(cell["id"])
        if cell["id"] in self.crash:
            self.crash.discard(cell["id"])
            with open(os.path.join(directory, "lane_states.csv"), "w") as handle:
                handle.write("partial log of an attempt that crashed\n")
            raise RuntimeError("simulated crash before any result")
        cleared = cell["id"] not in self.fail
        training_seed = int(cell["model"].split("seed")[1][:3])
        value = 4.0 + 0.1 * (training_seed - 100) + 0.01 * (cell["traffic_seed"] - 9300)
        with open(os.path.join(directory, A.RUN_MANIFEST_FILENAME), "w") as handle:
            json.dump({"git_commit": A.FROZEN_COMMIT, "git_status_porcelain": "",
                       "git_describe": "8c14f32", "runtime": dict(RUNTIME),
                       "checkpoint_sha256": "0" * 64 if cell["id"] in self.wrong_checkpoint
                       else cell["checkpoint_sha256"],
                       "traffic_seed": cell["traffic_seed"], "sumo_seed": int(sumo_seed),
                       "route_manifest_sha256": _sha(prefix + ".csv"),
                       "run_kind": "development_evaluation", "method": "qmix",
                       "training_seed": training_seed,
                       "network_sha256": self.network_sha256}, handle, sort_keys=True)
        metrics = {"clearance_status": "CLEARED" if cleared else "CLEARANCE_FAILURE",
                   "J_primary_valid": cleared,
                   search.PRIMARY_FIELD: value if cleared else float("nan"),
                   search.TIME_LOSS_FIELD: value + 2.0 if cleared else float("nan"),
                   "completed_count": 2800 if cleared else 2650,
                   "traffic_seed": cell["traffic_seed"], "method": "qmix",
                   "training_seed": training_seed}
        _write_tripinfo(directory, value, 2800 if cleared else 2650)
        with open(os.path.join(directory, campaign.METRICS_FILENAME), "w") as handle:
            json.dump(metrics, handle, sort_keys=True)
        if cell["id"] in self.interrupt_after_metrics:
            self.interrupt_after_metrics.discard(cell["id"])
            raise KeyboardInterruptLike("interrupted after the metrics, before the marker")
        return metrics


class MetricTests(unittest.TestCase):

    def test_a_j_declared_valid_must_be_finite_and_match_tripinfo(self):
        valid = {"clearance_status": "CLEARED", "J_primary_valid": True,
                 search.PRIMARY_FIELD: 3.25}
        self.assertEqual(M.j_problems(valid, 3.25), [])
        self.assertTrue(M.j_problems(valid, 4.0))                      # differs
        self.assertTrue(M.j_problems(valid, None))                     # no tripinfo
        for bad in (float("nan"), None, float("inf")):
            self.assertTrue(M.j_problems(dict(valid, **{search.PRIMARY_FIELD: bad}), 3.25))
        self.assertTrue(M.j_problems(dict(valid, clearance_status="CLEARANCE_FAILURE"), 3.25))
        invalid = {"clearance_status": "CLEARANCE_FAILURE", "J_primary_valid": False,
                   search.PRIMARY_FIELD: float("nan")}
        self.assertEqual(M.j_problems(invalid, None), [])              # never imputed

    def test_j_is_recomputed_from_tripinfo_and_invalid_if_any_trip_is_unfinished(self):
        directory = tempfile.mkdtemp()
        try:
            _write_tripinfo(directory, 3.25)
            self.assertAlmostEqual(M.recompute_j(directory), 3.25, places=12)
            _write_tripinfo(directory, 3.25, arrived=2740)
            self.assertIsNone(M.recompute_j(directory))
            os.remove(os.path.join(directory, "tripinfo.xml"))
            self.assertIsNone(M.recompute_j(directory))
        finally:
            shutil.rmtree(directory)


class SignalStringTests(unittest.TestCase):
    """sumo_checks_min7.check_schedule against the frozen tlLogic, without SUMO."""

    @classmethod
    def setUpClass(cls):
        import sumo_checks_min7 as SC
        cls.SC = SC
        cls.config = load_config(os.path.join(M.REPOSITORY_ROOT, "config", "adaptive_qmix",
                                              "baselines_300m_medium.json"))
        cls.programs = SC.load_programs(M.REPOSITORY_ROOT, cls.config)

    def _seconds(self, plan, duration=200):
        """What SUMO holds when the frozen executor runs the plan correctly."""
        phase_map = self.config["network"]["phase_map"]
        offsets = {"J1": 0, "J2": plan["offset_s"] % plan["cycle_s"]}
        seconds = []
        for t in range(duration):
            row = {"time": float(t)}
            for tl, offset in offsets.items():
                index, _actual = self.SC.expected_phase(plan, phase_map, t, offset)
                row[tl] = (index, self.programs[tl]["0"][index], "0")
            seconds.append(row)
        return seconds

    def test_frozen_tl_logic_is_read_from_the_frozen_network(self):
        self.assertEqual(sorted(self.programs), ["J1", "J2"])
        states = self.programs["J1"]["0"]
        phase_map = self.config["network"]["phase_map"]
        self.assertIn("G", states[phase_map["H_GREEN"]])
        self.assertIn("G", states[phase_map["V_GREEN"]])
        self.assertIn("y", states[phase_map["H_TO_V_YELLOW"]])
        self.assertIn("y", states[phase_map["V_TO_H_YELLOW"]])

    def test_a_correct_run_passes(self):
        for key in ((20, 500, 10), (25, 650, 0), (19, 577, 9)):
            plan = P.make_plan(*key)
            problems, summary = self.SC.check_schedule(plan, self.config, self._seconds(plan),
                                                       5, self.programs)
            self.assertEqual(problems, [], key)
            self.assertEqual(summary["J1"]["signal_string_mismatches"], 0)

    def test_correct_index_but_wrong_signal_string_fails(self):
        plan = P.make_plan(20, 500, 10)
        seconds = self._seconds(plan)
        green = self.config["network"]["phase_map"]["H_GREEN"]
        target = [r for r in seconds if r["J2"][0] == green][3]
        target["J2"] = (green, "r" * 16, "0")              # index right, all red
        problems, summary = self.SC.check_schedule(plan, self.config, seconds, 7, self.programs)
        self.assertEqual(summary["J2"]["schedule_mismatches"], 0)
        self.assertEqual(summary["J2"]["signal_string_mismatches"], 1)
        self.assertTrue(any("signal string" in p and "rrrrrrrrrrrrrrrr" in p for p in problems))
        # one movement wrong only (a G turned to r), same index
        seconds = self._seconds(plan)
        row = [r for r in seconds if r["J1"][0] == green][0]
        state = row["J1"][1]
        first_green = state.index("G")
        row["J1"] = (green, state[:first_green] + "r" + state[first_green + 1:], "0")
        problems, _ = self.SC.check_schedule(plan, self.config, seconds, 7, self.programs)
        self.assertTrue(any("J1" in p and "signal string" in p for p in problems))

    def test_another_program_fails(self):
        plan = P.make_plan(20, 500, 10)
        seconds = self._seconds(plan)
        seconds[5]["J1"] = seconds[5]["J1"][:2] + ("off",)
        problems, _ = self.SC.check_schedule(plan, self.config, seconds, 7, self.programs)
        self.assertTrue(any("program" in p for p in problems))

    def test_another_network_file_is_refused(self):
        config = dict(self.config, network=dict(self.config["network"], sha256="0" * 64))
        with self.assertRaises(M.Min7Error):
            self.SC.load_programs(M.REPOSITORY_ROOT, config)


def _read_text(path):
    with open(path) as handle:
        return handle.read()


def _snapshot(root):
    state = {}
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(directory, name)
            state[path] = (os.path.getsize(path), os.path.getmtime(path))
    return state


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class EndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._fsync = os.fsync
        os.fsync = lambda _fd: None      # speed only; atomic rename unchanged
        cls.base = tempfile.mkdtemp()
        b = lambda *p: os.path.join(cls.base, *p)  # noqa: E731
        os.makedirs(b("withdrawn"))
        cls.a002 = A.Layout(b("original"), b("audit"), b("a002"),
                            withdrawn_root=b("withdrawn"))
        L, repo = cls.a002, A.REPOSITORY_ROOT
        cls.config = load_config(L.config_path)
        adaptive = load_config(L.adaptive_config_path)
        config = cls.config
        stub = StubRunner(fail=[FLOOR_FAILURE])
        for family in (search.DESIGN_FAMILY, search.VALIDATION_FAMILY):
            campaign.prepare_seed_manifests(L.original_manifests, config, family)

        def execute(controller, plans, family, runs):
            campaign.execute_campaign(stub, controller, plans, family, config, runs,
                                      L.original_manifests, repo,
                                      allow_manifest_generation=False)

        # The original campaign and the boundary audit.
        execute("optimized_fixed_offset", P.fixed_offset_candidates(),
                search.DESIGN_FAMILY, L.original_runs)
        campaign.finalise_stage(campaign.OFFSET_DESIGN, L.original_runs,
                                L.original_manifests, L.original_artefacts, config, repo)
        offsets = campaign.read_shortlist_artefact(L.original_artefacts,
                                                   campaign.OFFSET_DESIGN)["plans"]
        execute("optimized_fixed_offset", offsets, search.VALIDATION_FAMILY, L.original_runs)
        campaign.finalise_stage(campaign.OFFSET_VALIDATION, L.original_runs,
                                L.original_manifests, L.original_artefacts, config, repo)
        execute(A.CONTROLLER, P.coarse_timing_candidates(), search.DESIGN_FAMILY,
                L.original_runs)
        campaign.finalise_stage(campaign.TIMING_COARSE_DESIGN, L.original_runs,
                                L.original_manifests, L.original_artefacts, config, repo)
        execute(A.CONTROLLER, A.original_fine_labels(L), search.DESIGN_FAMILY,
                L.original_runs)
        os.makedirs(L.original_state)
        cls.offset_key = tuple(P.candidate_key(campaign.read_selected_plan_artefact(
            L.original_artefacts, campaign.OFFSET_VALIDATION)["plan"]))
        with open(A.protocol_stages.artefact_path(
                L.original_state, A.protocol_stages.FREEZE_BASELINE_PLANS), "w") as handle:
            json.dump({"payload": {
                "optimized_fixed_offset": {"selected_key": list(cls.offset_key)},
                "optimized_fixed_timing": {"selected_key": [40, 650, 23]}}}, handle)
        execute(A.CONTROLLER, A.audit_coarse_candidates(), search.DESIGN_FAMILY, L.audit_runs)
        # Amendment 002, every stage, as executed.
        best = [_stub_j((20, 9, 5, 10)) + 0.001 * s for s in range(1, 6)]
        cls.saved = (A.REPORTED_BEST_BELOW_40, M.OFFSET_PLAN_KEY)
        A.REPORTED_BEST_BELOW_40 = ((20, 650, 10), sum(best) / 5.0)
        M.OFFSET_PLAN_KEY = cls.offset_key
        addendum = b("ADDENDUM.md")
        with open(addendum, "w") as handle:
            handle.write("sealed addendum\n")
        A.prepare_floor(L, config, addendum, RUNTIME)
        A.run_stage(L, config, A.STAGE_FLOOR, stub)
        A.finalise_coarse(L, config, RUNTIME)
        A.run_stage(L, config, A.STAGE_FINE, stub)
        A.finalise_fine(L, config, RUNTIME)
        A.run_stage(L, config, A.STAGE_VALIDATION, stub)
        A.finalise_validation(L, config, RUNTIME)
        cls.saved_constants = (M.A002_ADDENDUM_SHA256,)
        M.A002_ADDENDUM_SHA256 = A._sha256_file(addendum)
        A.freeze(L, config, adaptive)
        # Historical QMIX checkpoints, selection records, protected pilots.
        learners = os.path.join(L.amendment_root, "learners")
        records = []
        for seed in M.QMIX_SEEDS:
            directory = os.path.join(learners, "qmix", "seed{}".format(seed), "checkpoints")
            os.makedirs(directory)
            path = os.path.join(directory, "qmix_seed{}_t{:06d}.pth".format(seed, 300000 + seed))
            with open(path, "wb") as handle:
                handle.write(("weights of seed {}".format(seed)).encode("utf-8"))
            records.append({"training_seed": seed, "selected": {
                "transition_index": 300000 + seed, "checkpoint_sha256": _sha(path)}})
        os.makedirs(b("a003", "selection"))
        with open(b("a003", "selection", "selection_records.json"), "w") as handle:
            json.dump({"selection": {"qmix": records, "vdn": []}}, handle)
        pilot = b("pilot")
        campaign.prepare_seed_manifests(os.path.join(pilot, "manifests"), config,
                                        M.DEVELOPMENT_FAMILY, seeds=M.COMPARISON_SEEDS)
        for method in M.PILOT_METHODS:
            base = os.path.join(pilot, "{}_seed{}".format(method, M.PILOT_SEED))
            os.makedirs(base)
            with open(os.path.join(base, "pilot_check.json"), "w") as handle:
                json.dump({"verdict": "PASS"}, handle)
            for transition in M.PILOT_CHECKPOINTS:
                for seed in M.COMPARISON_SEEDS:
                    directory = os.path.join(base, "evaluations", "t{:06d}".format(transition),
                                             "traffic{}".format(seed))
                    os.makedirs(directory)
                    value = 3.5 + 0.01 * (seed - 9300)
                    _write_tripinfo(directory, value)
                    with open(os.path.join(directory, "evaluation_metrics.json"), "w") as h:
                        json.dump({"clearance_status": "CLEARED", "J_primary_valid": True,
                                   search.PRIMARY_FIELD: value,
                                   search.TIME_LOSS_FIELD: value + 1.0,
                                   "completed_count": 2800}, h)
                    with open(os.path.join(directory, "protection_record.json"), "w") as h:
                        json.dump({"interventions_guarantee": 0,
                                   "interventions_min_green": 3}, h)
        cls.args = argparse.Namespace(**dict(
            (name, b(*part)) for name, part in (
                ("repository_root", ()), ("original_root", ("original",)),
                ("audit_root", ("audit",)), ("withdrawn_root", ("withdrawn",)),
                ("a002_root", ("a002",)), ("a003_root", ("a003",)),
                ("learner_root", ("a002", "learners")), ("pilot_root", ("pilot",)),
                ("root", ("min7",)))))
        cls.args.repository_root = repo
        cls.layout = M.Layout(cls.args)
        cls.protected = [b("original"), b("audit"), b("a002"), b("a003"), b("pilot")]
        cls.before = dict((root, _snapshot(root)) for root in cls.protected)
        cls.lines = []

    @classmethod
    def tearDownClass(cls):
        A.REPORTED_BEST_BELOW_40, M.OFFSET_PLAN_KEY = cls.saved
        (M.A002_ADDENDUM_SHA256,) = cls.saved_constants
        os.fsync = cls._fsync
        shutil.rmtree(cls.base, ignore_errors=True)

    def out(self, line):
        self.lines.append(line)

    def _cli(self, *arguments):
        argv = list(arguments)
        for name in sorted(vars(self.args)):
            if name != "repository_root":
                argv += ["--" + name.replace("_", "-"), getattr(self.args, name)]
        lines = []
        saved = A.current_runtime
        A.current_runtime = lambda: dict(RUNTIME)
        try:
            code = M.main(argv, lines.append)
        finally:
            A.current_runtime = saved
        return code, lines

    def _local_checks(self, report_changes=None, measure_changes=None, run_problem=None):
        """A report of the local SUMO checks, as sumo_checks_min7.py writes it."""
        checks = os.path.join(self.layout.root, M.CHECKS_DIRECTORY)
        if not os.path.isdir(checks):
            os.makedirs(checks)
        measurement = {"seconds_per_run": 40.0, "bytes_per_run": 30e3,
                       "seconds_per_qmix_evaluation": 60.0, "measured_on": "this machine",
                       "date": "2026-10-28 10:00:00"}
        runs = dict((name, {"problems": []}) for name in M.LOCAL_CHECK_RUNS)
        if run_problem:
            runs["min7_cycle_bound"]["problems"] = [run_problem]
        report = {"verdict": "OK", "complete": True, "runs": runs,
                  "measurement": dict(measurement), "driver_sha256": M.DRIVER_SHA256,
                  "a002_driver_sha256": M.A002_DRIVER_SHA256,
                  "sumo_checks_sha256": M.sha256_file(M.SUMO_CHECKS_PATH),
                  "frozen_commit": M.FROZEN_COMMIT, "runtime": dict(RUNTIME),
                  "network_sha256": self.config["network"]["sha256"]}
        report.update(report_changes or {})
        measurement.update(measure_changes or {})
        with open(os.path.join(checks, M.LOCAL_CHECK_REPORT), "w") as handle:
            json.dump(report, handle)
        with open(os.path.join(checks, "measure.json"), "w") as handle:
            json.dump(measurement, handle)

    def _prepare(self):
        """Through the command line: plan, refusals, then prepare."""
        code, lines = self._cli("plan")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.layout.root))
        fingerprint = [l for l in lines if l.startswith("Empreinte du plan")][0].split()[-1]
        self.assertTrue(any("NON mesurees" in l for l in lines))
        code, lines = self._cli("prepare", "--approved-plan", fingerprint)
        self.assertEqual(code, 2)                       # no local measurement yet
        # Defect 5: a measurement is refused unless the local SUMO checks that
        # produced it are complete, passed, and match this code and stack.
        refused = (
            {"report_changes": {"verdict": "ECHEC"},
             "run_problem": "J1: 12 seconds differ from the schedule"},
            {"run_problem": "J1: 140 seconds show another signal string"},   # verdict lies
            {"report_changes": {"complete": False}},
            {"measure_changes": {"seconds_per_run": 4.0}},
            {"report_changes": {"runtime": dict(RUNTIME, sumo="Eclipse SUMO sumo 1.28.0")}},
            {"report_changes": {"sumo_checks_sha256": "0" * 64}},
            {"report_changes": {"driver_sha256": "0" * 64}},
        )
        for case in refused:
            self._local_checks(**case)
            code, lines = self._cli("prepare", "--approved-plan", fingerprint)
            self.assertEqual(code, 2, case)
            self.assertTrue(any(l.startswith("CONTROLES LOCAUX NON VALIDES") for l in lines))
            self.assertFalse(os.path.exists(self.layout.plan_path), case)
        self._local_checks(report_changes={"runs": dict(
            (name, {"problems": []}) for name in M.LOCAL_CHECK_RUNS[:3])})
        code, lines = self._cli("prepare", "--approved-plan", fingerprint)
        self.assertEqual(code, 2)                       # synthetic QMIX check missing
        self._local_checks()
        code, lines = self._cli("prepare", "--approved-plan", "0" * 64)
        self.assertEqual(code, 2)
        code, lines = self._cli("prepare", "--approved-plan", fingerprint)
        self.assertEqual(code, 0, lines)
        self.assertTrue(any("mesure locale" in l for l in lines))
        sealed = M.read_sealed(self.layout.plan_path, "plan")
        self.assertEqual(sealed["preparation"]["local_checks_sha256"], M.sha256_file(
            os.path.join(self.layout.root, M.CHECKS_DIRECTORY, M.LOCAL_CHECK_REPORT)))
        code, lines = self._cli("prepare", "--approved-plan", fingerprint)
        self.assertEqual(code, 2)                       # written once
        code, lines = self._cli("prepare-comparison", "--workers", "2")
        self.assertEqual(code, 1)                       # only run stages take workers
        self.assertEqual(M.without_options(
            ["run-fine", "--workers", "2", "--shard=1/3", "--approved-coarse", "x"],
            ("--workers", "--shard")), ["run-fine", "--approved-coarse", "x"])
        return sealed

    def _plan(self):
        return M.read_sealed(self.layout.plan_path, "plan")

    def _fine_refused(self, approved, fragment):
        """run-fine stops before any simulation, directly and with workers."""
        stub = StubRunner()
        with self.assertRaises(M.Min7Error) as caught:
            M.run_stage(self.layout, self.config, M.STAGE_FINE, stub, approved_coarse=approved,
                        runtime=RUNTIME)
        self.assertIn(fragment, str(caught.exception))
        self.assertEqual(stub.calls, [])
        code, lines = self._cli("run-fine", "--workers", "2", "--approved-coarse", approved)
        self.assertEqual(code, 1)
        self.assertTrue(any(fragment in l for l in lines), lines)
        self.assertFalse(os.path.exists(os.path.join(self.layout.root, "logs")))
        self.assertFalse(os.path.exists(self.layout.runs))

    # Stages run in name order and build on each other.

    def test_01_reconstruction_reads_the_executed_procedure(self):
        before = _snapshot(self.base)
        rebuilt = M.reconstruction(self.layout)
        self.assertEqual(rebuilt["old_plan_realized"], [19, 8, 5, 9])
        self.assertEqual(rebuilt["old_plan_key"], [19, 577, 9])
        self.assertEqual(rebuilt["superseded_original_timing_key"], [40, 650, 23])
        self.assertEqual(tuple(rebuilt["offset_plan_key"]), self.offset_key)
        self.assertNotEqual(tuple(rebuilt["offset_plan_key"]), (19, 577, 9))
        self.assertEqual(rebuilt["a002_software_stack"], RUNTIME)
        plan, models = M.build_plan(self.layout, self.config, RUNTIME)
        self.assertEqual(len(models), 10)
        self.assertEqual(plan["comparison"]["expected_evaluations"]["total"], 60)
        self.assertIsNone(M.stack_problem(plan))
        other = dict(RUNTIME, sumo="Eclipse SUMO sumo Version 1.26.0")
        self.assertIn("cannot be pooled", M.stack_problem(
            M.build_plan(self.layout, self.config, other)[0]))
        again, _ = M.build_plan(self.layout, self.config, RUNTIME)
        self.assertEqual(plan["fingerprint"], again["fingerprint"])
        bound = M.fine_upper_bound()
        estimate = M.estimates(plan, bound, None)
        M.print_plan(plan, bound, estimate, 10 ** 12, self.out)
        self.assertEqual(_snapshot(self.base), before)          # plan writes nothing

    def test_02_a_wrong_or_changed_checkpoint_stops_the_plan(self):
        path = os.path.join(self.layout.paths["learner_root"], "qmix", "seed101",
                            "checkpoints", "qmix_seed101_t300101.pth")
        with open(path, "rb") as handle:
            saved = handle.read()
        stat = os.stat(path)
        try:
            with open(path, "wb") as handle:
                handle.write(b"other weights")
            with self.assertRaises(M.Min7Error):
                M.build_plan(self.layout, self.config, RUNTIME)
        finally:
            with open(path, "wb") as handle:
                handle.write(saved)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    def test_03_coarse_reuses_verified_runs_and_seals_the_fine_order(self):
        self._prepare()
        with self.assertRaises(M.Min7Error):
            M.run_stage(self.layout, self.config, M.STAGE_FINE, StubRunner(), runtime=RUNTIME)
        order, records = M.finalise_coarse(self.layout, self.config, RUNTIME)
        self.assertEqual(order["labels"], 2143)
        self.assertEqual(order["realized_plans"], 2138)
        self.assertEqual(len(records), 2138)
        self.assertTrue(all(M.admissible(r["plan"]) for r in records))
        winners = [tuple(w["realized_key"]) for w in order["winners"]]
        self.assertEqual(winners, [(25, 12, 7, 0), (20, 7, 7, 10), (40, 22, 12, 25),
                                   (40, 24, 10, 25), (40, 22, 12, 20)])
        self.assertTrue(all(min(w[1], w[2]) >= 7 for w in winners))
        classes = [c["identity"] for c in order["fine_classes"]]
        self.assertTrue(all(c[0] >= 20 and min(c[1], c[2]) >= 7 for c in classes))
        self.assertIn([20, 7, 7, 12], classes)
        self.assertEqual(order["fine_realized_plans"],
                         order["fine_reused_plans"] + order["fine_new_plans"])
        self.assertTrue(order["fine_reused_plans"] > 0)
        self.assertEqual(len(order["repro_work"]), 5)
        M.print_coarse(order, self.out)
        with self.assertRaises(M.Min7Error):
            M.finalise_coarse(self.layout, self.config, RUNTIME)

    def test_04_fine_needs_the_approved_count_and_a_reproduction(self):
        self._fine_refused("0" * 64, "--approved-coarse")
        # Defect 2: the right approval is not enough without the reproduction.
        self._fine_refused(M.coarse_order_seal(self.layout), "absent or incomplete")

    def test_05_reproduction_complete_and_identical_before_any_fine_run(self):
        approved = M.coarse_order_seal(self.layout)
        drift = StubRunner(drift={((25, 12, 7, 0), 2003): 1e-9})
        M.run_stage(self.layout, self.config, M.STAGE_REPRO, drift, shard_index=0,
                    shard_count=2, runtime=RUNTIME)
        self.assertTrue(0 < len(drift.calls) < 25)
        self._fine_refused(approved, "absent or incomplete")        # half of it
        M.run_stage(self.layout, self.config, M.STAGE_REPRO, drift, shard_index=1,
                    shard_count=2, runtime=RUNTIME)
        self.assertEqual(len(drift.calls), 25)
        self._fine_refused(approved, "do not reproduce")            # one differs by 1e-9
        with self.assertRaises(M.Min7Error) as caught:
            M.finalise_fine(self.layout, self.config, RUNTIME)
        self.assertIn("do not reproduce", str(caught.exception))
        # Test-only repair: remove the drifted run, then re-simulate it.
        shutil.rmtree(campaign.run_directory_for(
            self.layout.repro_runs, M.CONTROLLER, P.make_plan(25, 650, 0),
            search.DESIGN_FAMILY, 2003))
        good = StubRunner()
        M.run_stage(self.layout, self.config, M.STAGE_REPRO, good, runtime=RUNTIME)
        self.assertEqual(len(good.calls), 1)

    def _fine_run_directories(self, key):
        plan = P.make_plan(*key)
        return [campaign.run_directory_for(self.layout.runs, M.CONTROLLER, plan,
                                           search.DESIGN_FAMILY, seed)
                for seed in search.DESIGN_SEEDS]

    def test_06_fine_runs_once_and_an_existing_result_is_never_rerun(self):
        order = M.read_coarse_order(self.layout, self._plan())
        approved = M.coarse_order_seal(self.layout)
        candidates = [tuple(A.key_of(p)) for p in order["new_work"]
                      if A.realized_key(p) not in (MIN7_FAILURE, (20, 7, 7, 12))]
        interrupted, tampered = candidates[0], candidates[1]
        stub = StubRunner(fail=[MIN7_FAILURE], tripinfo=[interrupted],
                          interrupt_after_metrics=[interrupted])
        for shard in range(3):
            M.run_stage(self.layout, self.config, M.STAGE_FINE, stub, shard_index=shard,
                        shard_count=3, approved_coarse=approved, runtime=RUNTIME)
        self.assertEqual(len(stub.calls), order["fine_new_runs"])
        self.assertEqual(len({c[1] for c in stub.calls}), order["fine_new_plans"])
        self.assertEqual({c[2] for c in stub.calls}, {search.DESIGN_FAMILY})
        self.assertIn(MIN7_FAILURE, {c[1] for c in stub.calls})
        # Defect 3, search side. Metrics written, interrupted before the marker:
        interrupted_dirs = self._fine_run_directories(interrupted)
        hashes = dict((d, _sha(os.path.join(d, campaign.METRICS_FILENAME)))
                      for d in interrupted_dirs)
        for directory in interrupted_dirs:
            self.assertFalse(os.path.exists(os.path.join(directory, M.OUTCOME_MARKER)))
        # A marker that no longer verifies, on a recorded run:
        tampered_dir = self._fine_run_directories(tampered)[0]
        marker_path = os.path.join(tampered_dir, M.OUTCOME_MARKER)
        completion = os.path.join(tampered_dir, campaign.MARKER_FILENAME)
        saved = dict((p, _read_text(p)) for p in (marker_path, completion))
        marker = json.loads(saved[marker_path])
        marker["outcome"] = "CLEARANCE_FAILURE"
        with open(marker_path, "w") as handle:
            json.dump(marker, handle)
        os.remove(completion)
        again = StubRunner()                      # never asked for any of these
        ledger = M.run_stage(self.layout, self.config, M.STAGE_FINE, again,
                             approved_coarse=approved, runtime=RUNTIME)
        self.assertEqual(again.calls, [])
        failures = [e["failure"] for e in ledger if e.get("failure")]
        self.assertEqual(sum("RESULT WITHOUT MARKER" in f for f in failures), 5)
        self.assertEqual(sum("INVALID MARKER" in f for f in failures), 1)
        with self.assertRaises(A.AmendmentError):
            M.finalise_fine(self.layout, self.config, RUNTIME)
        # Adoption: the five interrupted results are verified and sealed; the
        # invalid marker is refused; no other file changes.
        lines = []
        self.assertEqual(M.adopt_results(self.layout, self.config, RUNTIME, lines.append), 1)
        self.assertTrue(any(l.startswith("REFUSE") and tampered_dir in l for l in lines))
        for directory in interrupted_dirs:
            sealed = M.read_json(os.path.join(directory, M.OUTCOME_MARKER))
            self.assertEqual(sealed["adopted"]["by"], "adopt-results")
            self.assertEqual(_sha(os.path.join(directory, campaign.METRICS_FILENAME)),
                             hashes[directory])
        self.assertEqual(json.loads(_read_text(marker_path))["outcome"], "CLEARANCE_FAILURE")
        # Test-only repair of the tampered marker, as a person would after
        # inspection; then the frozen campaign records completion, no simulation.
        for path, text in saved.items():
            with open(path, "w") as handle:
                handle.write(text)
        third = StubRunner()
        ledger = M.run_stage(self.layout, self.config, M.STAGE_FINE, third,
                             approved_coarse=approved, runtime=RUNTIME)
        self.assertEqual(third.calls, [])
        self.assertEqual([e for e in ledger if e.get("failure")], [])
        for directory in interrupted_dirs:
            self.assertTrue(os.path.isfile(os.path.join(directory, campaign.MARKER_FILENAME)))
        lines = []
        self.assertEqual(M.adopt_results(self.layout, self.config, RUNTIME, lines.append), 0)

    def test_07_validation_is_closed_before_the_fine_stage_is_sealed(self):
        with self.assertRaises(M.Min7Error):
            M.run_stage(self.layout, self.config, M.STAGE_VALIDATION, StubRunner(),
                        runtime=RUNTIME)

    def test_08_fine_top_ten(self):
        result = M.finalise_fine(self.layout, self.config, RUNTIME)
        retained = [tuple(r["realized_key"]) for r in result["retained"]]
        self.assertEqual(len(set(retained)), 10)
        self.assertEqual(retained[0], (20, 7, 7, 12))
        self.assertNotIn(MIN7_FAILURE, retained)
        self.assertEqual(result["invalid_plans"], 1)
        self.assertTrue(all(not r["differing"] for r in result["repro"]))
        self.assertEqual(len(result["repro"]), 25)

    def test_09_validation_selects_with_the_frozen_rule(self):
        stub = StubRunner()
        M.run_stage(self.layout, self.config, M.STAGE_VALIDATION, stub, runtime=RUNTIME)
        self.assertEqual(len(stub.calls), 50)
        self.assertEqual({c[2] for c in stub.calls}, {search.VALIDATION_FAMILY})
        result = M.finalise_validation(self.layout, self.config, RUNTIME)
        self.assertEqual(result["selected_realized_key"], [20, 7, 7, 12])
        self.assertEqual(result["selected_key"], list(A.key_of(
            A.canonical_label((20, 7, 7, 12)))))
        self.assertEqual(result["active_constraints"], ["cycle floor C=20", "gV=7", "gH=7"])
        with self.assertRaises(M.Min7Error):
            M.finalise_validation(self.layout, self.config, RUNTIME)

    def test_10_comparison_has_60_cells_on_pilot_identical_traffic(self):
        order = M.prepare_comparison(self.layout, self.config, runtime=RUNTIME)
        cells = order["cells"]
        self.assertEqual(len(cells), 60)
        self.assertEqual(sum(c["arm"] == "A_old_fixed" for c in cells), 5)
        self.assertEqual(sum(c["arm"] == "B_min7_fixed" for c in cells), 5)
        self.assertEqual(sum(c["arm"] == "C_qmix_historical" for c in cells), 50)
        self.assertEqual(len({c["id"] for c in cells}), 60)
        old = [c["plan"] for c in cells if c["arm"] == "A_old_fixed"][0]
        self.assertEqual(A.realized_key(old), (19, 8, 5, 9))
        self.assertEqual({c["traffic_seed"] for c in cells}, set(M.COMPARISON_SEEDS))
        with self.assertRaises(M.Min7Error):
            M.prepare_comparison(self.layout, self.config, runtime=RUNTIME)

    def test_11_comparison_never_resubmits_an_existing_result(self):
        failed = "C_qmix_seed103_t300103__traffic9302"
        crashed = "C_qmix_seed105_t300105__traffic9304"
        adoptable = "C_qmix_seed106_t300106__traffic9301"
        foreign = "C_qmix_seed107_t300107__traffic9303"
        network = self.config["network"]["sha256"]
        stub = StubRunner()
        evaluator = StubEvaluator(network, fail=[failed], crash=[crashed],
                                  interrupt_after_metrics=[adoptable, foreign],
                                  wrong_checkpoint=[foreign])
        for shard in range(2):
            M.run_comparison(self.layout, self.config, stub, evaluator, shard_index=shard,
                             shard_count=2, out=self.out, runtime=RUNTIME)
        self.assertEqual(len(stub.calls), 10)
        self.assertEqual(len(evaluator.calls), 50)
        self.assertEqual({c[2] for c in stub.calls}, {M.DEVELOPMENT_FAMILY})
        lines = []
        self.assertEqual(M.progress(self.layout, self.config, lines.append, RUNTIME), 3)
        self.assertTrue(any(M.RESULT_WITHOUT_MARKER in l and adoptable in l for l in lines))
        self.assertEqual(M.summarise(self.layout, self.config, self.out, RUNTIME), 1)
        # Defect 3, comparison side: results without a marker are never
        # resubmitted; only the crash before any result is run again, after its
        # files are set aside unchanged.
        directory = lambda cell_id: os.path.join(self.layout.comparison_runs, cell_id)  # noqa
        before = dict((c, _sha(os.path.join(directory(c), campaign.METRICS_FILENAME)))
                      for c in (adoptable, foreign))
        evaluator2 = StubEvaluator(network)
        lines = []
        code = M.run_comparison(self.layout, self.config, StubRunner(), evaluator2,
                                out=lines.append, runtime=RUNTIME)
        self.assertEqual(code, 4)
        self.assertEqual(evaluator2.calls, [crashed])
        self.assertEqual(sum(l.startswith("REFUS") for l in lines), 2)
        kept = directory(crashed) + ".interrupted-1"
        self.assertTrue(os.path.isfile(os.path.join(kept, "lane_states.csv")))
        lines = []
        self.assertEqual(M.adopt_results(self.layout, self.config, RUNTIME, lines.append), 1)
        self.assertEqual(M.read_json(os.path.join(directory(adoptable), M.OUTCOME_MARKER))[
            "adopted"]["by"], "adopt-results")
        self.assertTrue(any(l.startswith("REFUSE") and foreign in l and "checkpoint_sha256" in l
                            for l in lines))
        self.assertFalse(os.path.exists(os.path.join(directory(foreign), M.OUTCOME_MARKER)))
        for cell_id, digest in before.items():
            self.assertEqual(_sha(os.path.join(directory(cell_id), campaign.METRICS_FILENAME)),
                             digest)
        evaluator3 = StubEvaluator(network)
        M.run_comparison(self.layout, self.config, StubRunner(), evaluator3, out=self.out,
                         runtime=RUNTIME)
        self.assertEqual(evaluator3.calls, [])                 # still refused, not rerun
        # The refused result is set aside by a person's explicit decision (here
        # the test), then the cell is evaluated once.
        os.rename(directory(foreign), directory(foreign) + ".refused-by-operator")
        M.run_comparison(self.layout, self.config, StubRunner(), evaluator3, out=self.out,
                         runtime=RUNTIME)
        self.assertEqual(evaluator3.calls, [foreign])
        self.assertEqual(M.progress(self.layout, self.config, self.out, RUNTIME), 0)

    def test_12_summary_keeps_failures_and_never_imputes(self):
        lines = []
        self.assertEqual(M.summarise(self.layout, self.config, lines.append, RUNTIME), 0)
        with open(os.path.join(self.layout.summary, "comparison_summary.json")) as handle:
            summary = json.load(handle)
        groups = dict(((g["arm"], g["model"]), g) for g in summary["by_group"])
        self.assertEqual(len(groups), 2 + 10 + 6)
        failed = groups[("C_qmix_historical", "qmix_seed103_t300103")]
        self.assertEqual((failed["evaluations"], failed["clearance_failures"],
                          failed["J_valid"]), (5, 1, 4))
        paired = summary["paired_B_minus_A"]
        self.assertEqual(len(paired), 5)
        for row in paired:
            j_a = TABLE[(19, 8, 5, 9)] + 0.001 * (row["traffic_seed"] % 100)
            j_b = TABLE[(20, 7, 7, 12)] + 0.001 * (row["traffic_seed"] % 100)
            self.assertAlmostEqual(row["delta_B_minus_A_s"], j_b - j_a, places=12)
        self.assertEqual(summary["qmix_historical_pooled"]["evaluations"], 50)
        self.assertEqual(summary["qmix_historical_pooled"]["clearance_failures"], 1)
        pilots = [g for g in summary["by_group"] if g["arm"].startswith("pilot_")]
        self.assertEqual(sorted((g["arm"], g["model"]) for g in pilots), sorted(
            ("pilot_{}_seed201".format(m), "t{:06d}".format(t))
            for m in M.PILOT_METHODS for t in M.PILOT_CHECKPOINTS))
        with open(os.path.join(self.layout.summary, "comparison_runs.csv")) as handle:
            text = handle.read()
        self.assertIn("CLEARANCE_FAILURE", text)
        self.assertNotIn("nan", text.lower())
        self.assertTrue(any("B - A" in line for line in lines))
        if os.environ.get("MIN7_SHOW_REPORT"):
            print("\n".join(self.lines + lines))

    def test_13_an_inconsistent_metric_file_is_reported_not_summarised(self):
        cell = [c for c in M.read_sealed(self.layout.comparison_order, "o")["cells"]
                if c["arm"] == "B_min7_fixed"][0]
        path = os.path.join(M.cell_directory(self.layout, cell), "tripinfo.xml")
        with open(path) as handle:
            saved = handle.read()
        try:
            _write_tripinfo(os.path.dirname(path), 99.0)
            lines = []
            self.assertEqual(M.summarise(self.layout, self.config, lines.append, RUNTIME), 1)
            self.assertTrue(any("incoherent" in line for line in lines))
        finally:
            with open(path, "w") as handle:
                handle.write(saved)

    def _with_pilot_metrics(self, change):
        """Run summarise with one pilot result altered, then restore it exactly."""
        path = os.path.join(self.layout.paths["pilot_root"], "vdn_seed201", "evaluations",
                            "t360000", "traffic9303", "evaluation_metrics.json")
        summary = os.path.join(self.layout.summary, "comparison_summary.json")
        written = os.stat(summary).st_mtime_ns
        with open(path) as handle:
            saved = handle.read()
        stat = os.stat(path)
        try:
            data = json.loads(saved)
            change(data)
            with open(path, "w") as handle:
                json.dump(data, handle)
            lines = []
            code = M.summarise(self.layout, self.config, lines.append, RUNTIME)
        finally:
            with open(path, "w") as handle:
                handle.write(saved)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        if code != 0:
            self.assertEqual(os.stat(summary).st_mtime_ns, written)  # nothing rewritten
        return code, lines

    def test_13b_a_pilot_j_inconsistent_with_tripinfo_blocks_the_summary(self):
        # Defect 1: the pilot declares J = 1 s but its tripinfo gives about 3.5 s.
        code, lines = self._with_pilot_metrics(
            lambda d: d.update({search.PRIMARY_FIELD: 1.0}))
        self.assertEqual(code, 1)
        self.assertTrue(any(l.startswith("  PROBLEME : pilot vdn t360000 traffic 9303")
                            and "differs from tripinfo" in l for l in lines), lines)
        self.assertTrue(any("NON ECRITE" in l for l in lines))
        for bad in (float("nan"), None):
            code, lines = self._with_pilot_metrics(
                lambda d: d.update({search.PRIMARY_FIELD: bad}))
            self.assertEqual(code, 1)
            self.assertTrue(any("pilot vdn" in l and "not finite" in l for l in lines), lines)
        code, lines = self._with_pilot_metrics(lambda d: None)
        self.assertEqual(code, 0)                                   # restored: passes

    def test_14_protected_roots_were_never_written(self):
        for root in self.protected:
            self.assertEqual(_snapshot(root), self.before[root])
        self.assertTrue(all(M.inside(path, self.layout.root) or path.endswith(".log")
                            for path in _snapshot(self.layout.root)))

    def test_15_the_new_root_may_not_overlap_a_protected_root(self):
        for name in ("a002_root", "pilot_root", "original_root"):
            args = argparse.Namespace(**vars(self.args))
            args.root = os.path.join(getattr(self.args, name), "min7")
            with self.assertRaises(M.Min7Error):
                M.Layout(args)


if __name__ == "__main__":
    unittest.main()
