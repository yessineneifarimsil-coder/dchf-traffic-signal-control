"""Batch S3: campaign execution that can be interrupted without lying.

The runner is a stub throughout, so what is exercised is the orchestration --
resume, pairing, ledger, sharding, pruning policy -- rather than SUMO.
"""

from __future__ import absolute_import

import json
import os
import shutil
import tempfile
import unittest

from .common import REPOSITORY_ROOT

from adaptive_qmix.baselines import campaign, plans
from adaptive_qmix.baselines import plans as plans_module
from adaptive_qmix.baselines.integrity import sha256_file
from adaptive_qmix.baselines.runner import (
    OPTIMIZED_FIXED_OFFSET, OPTIMIZED_FIXED_TIMING,
)
from adaptive_qmix.baselines.search import (
    DESIGN_FAMILY,
    DESIGN_SEEDS,
    VALIDATION_FAMILY,
)
from adaptive_qmix.config import load_config
from adaptive_qmix.protocol import authorization
from adaptive_qmix.protocol import stages as protocol_stages


BASELINE_CONFIG_PATH = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)


class StubRunner(object):
    """Writes a plausible evaluation_metrics.json and records its calls."""

    def __init__(self, fail_keys=(), clearance="CLEARED"):
        self.calls = []
        self.fail_keys = set(fail_keys)
        self.clearance = clearance

    def __call__(self, traci_module, config, repository_root, controller,
                 manifest_csv_path, route_xml_path, family, seed, sumo_seed,
                 output_directory, plan=None, manifest_index=0,
                 manifest_prefix=None, **kwargs):
        key = plans.candidate_key(plan)
        self.calls.append({
            "controller": controller, "key": key, "family": family,
            "seed": int(seed), "sumo_seed": int(sumo_seed),
            "manifest_csv_path": manifest_csv_path,
            "route_xml_path": route_xml_path,
            "output_directory": output_directory,
            "manifest_index": manifest_index,
        })
        cleared = key not in self.fail_keys
        metrics = {
            "controller": controller,
            "clearance_status": self.clearance if cleared
            else "CLEARANCE_FAILURE",
            "J_primary_valid": cleared,
            "J_primary_mean_scheduled_waiting_burden_s": (
                12.0 + key[2] if cleared else float("nan")
            ),
            "mean_completed_time_loss_s": (
                20.0 + key[2] if cleared else float("nan")
            ),
            "traffic_family": family, "traffic_seed": int(seed),
            "manifest_index": manifest_index,
            "phase_parameters": dict(plan),
            "sumo_seed": int(sumo_seed),
            "manifest_csv_sha256": sha256_file(manifest_csv_path),
            "route_xml_sha256": sha256_file(route_xml_path),
        }
        with open(
            os.path.join(output_directory, campaign.METRICS_FILENAME), "w"
        ) as handle:
            json.dump(metrics, handle, sort_keys=True)
        return metrics


def make_shortlist(directory, stage, plans, expected_candidates=None,
                   seeds=(2001, 2002, 2003, 2004, 2005)):
    """Build a shortlist artefact with derivation evidence that verifies.

    Tests need fixtures, but they must be fixtures of the real shape: a
    shortlist whose retained plans are genuinely the top N of the scores it
    carries. Anything looser would make the guard untestable.
    """
    spec = campaign.CAMPAIGN_STAGES[stage]
    expected = list(expected_candidates or plans)
    keys = [plans_module.candidate_key(plan) for plan in plans]
    scores = []
    for plan in expected:
        key = plans_module.candidate_key(plan)
        rank = keys.index(key) if key in keys else len(keys) + 1
        scores.append({
            "key": list(key), "valid": True,
            "mean_J_primary_s": float(rank),
            "mean_time_loss_s": float(rank) / 2.0,
            "failed_seeds": [],
        })
    derivation = {
        "expected_candidate_count": len(expected),
        "expected_run_count": len(expected) * len(seeds),
        "verified_run_count": len(expected) * len(seeds),
        "seeds": list(seeds),
        "family": spec["family"],
        "controller": spec["controller"],
        "ranking": "search.rank_by_design on mean design J_primary",
        "scores": scores,
    }
    return campaign._write_shortlist_artefact(
        directory, stage, plans, {"ranked_on": spec["family"]}, derivation
    )


class CampaignBase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.output_root = os.path.join(self.directory, "runs")
        self.manifest_root = os.path.join(self.directory, "manifests")
        self.config = load_config(BASELINE_CONFIG_PATH)
        self.candidates = [
            plans.fixed_offset_plan(offset) for offset in (0, 10, 20)
        ]

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def execute(self, runner, candidates=None, seeds=(2001, 2002), **kwargs):
        return campaign.execute_campaign(
            runner, OPTIMIZED_FIXED_OFFSET,
            candidates if candidates is not None else self.candidates,
            DESIGN_FAMILY, self.config, self.output_root, self.manifest_root,
            REPOSITORY_ROOT, seeds=seeds, **kwargs
        )


class WorkListTests(CampaignBase):
    """Deterministic ordering, sharding, and no pruning."""

    def test_the_work_list_is_every_candidate_times_every_seed(self):
        work = campaign.plan_campaign(
            OPTIMIZED_FIXED_OFFSET, self.candidates, DESIGN_FAMILY
        )
        self.assertEqual(len(work), 3 * len(DESIGN_SEEDS))
        self.assertEqual(
            sorted(set(item["seed"] for item in work)), list(DESIGN_SEEDS)
        )

    def test_ordering_is_deterministic_and_independent_of_input_order(self):
        forward = campaign.plan_campaign(
            OPTIMIZED_FIXED_OFFSET, self.candidates, DESIGN_FAMILY
        )
        backward = campaign.plan_campaign(
            OPTIMIZED_FIXED_OFFSET, list(reversed(self.candidates)),
            DESIGN_FAMILY,
        )
        self.assertEqual(
            [item["key"] for item in forward],
            [item["key"] for item in backward],
        )

    def test_shards_partition_the_work_without_overlap_or_loss(self):
        whole = campaign.plan_campaign(
            OPTIMIZED_FIXED_OFFSET, self.candidates, DESIGN_FAMILY
        )
        collected = []
        for index in range(4):
            collected.extend(campaign.plan_campaign(
                OPTIMIZED_FIXED_OFFSET, self.candidates, DESIGN_FAMILY,
                shard_index=index, shard_count=4,
            ))
        as_tuples = sorted(
            (item["key"], item["seed"]) for item in collected
        )
        self.assertEqual(
            as_tuples, sorted((item["key"], item["seed"]) for item in whole)
        )
        self.assertEqual(len(as_tuples), len(set(as_tuples)))

    def test_no_candidate_pruning_occurs(self):
        """Every candidate is run on every seed, including poor ones."""
        runner = StubRunner()
        self.execute(runner, seeds=DESIGN_SEEDS)
        executed = sorted(
            (call["key"], call["seed"]) for call in runner.calls
        )
        expected = sorted(
            (plans.candidate_key(plan), seed)
            for plan in self.candidates for seed in DESIGN_SEEDS
        )
        self.assertEqual(executed, expected)
        self.assertEqual(len(runner.calls), 3 * 5)

    def test_a_failing_candidate_is_still_run_on_every_seed(self):
        """No early stopping: a bad first seed does not cancel the rest."""
        failing = plans.candidate_key(self.candidates[1])
        runner = StubRunner(fail_keys=[failing])
        self.execute(runner, seeds=DESIGN_SEEDS)
        for_failing = [
            call for call in runner.calls if call["key"] == failing
        ]
        self.assertEqual(len(for_failing), len(DESIGN_SEEDS))

    def test_the_pruning_policy_is_stated(self):
        self.assertIn("no candidate pruning", campaign.PRUNING_POLICY)
        self.assertIn("no adaptive early stopping", campaign.PRUNING_POLICY)

    def test_the_campaign_refuses_the_final_family(self):
        with self.assertRaises(campaign.CampaignError):
            campaign.plan_campaign(
                OPTIMIZED_FIXED_OFFSET, self.candidates, "final_test"
            )

    def test_the_campaign_refuses_a_final_seed(self):
        with self.assertRaises(campaign.CampaignError) as caught:
            campaign.plan_campaign(
                OPTIMIZED_FIXED_OFFSET, self.candidates, DESIGN_FAMILY,
                seeds=(2001, 3001),
            )
        self.assertIn("3001", str(caught.exception))


class OutputIsolationTests(CampaignBase):
    """Candidate identity is in the path, so nothing can be overwritten."""

    def test_every_candidate_and_seed_gets_its_own_directory(self):
        runner = StubRunner()
        ledger = self.execute(runner)
        directories = [entry["run_directory"] for entry in ledger]
        self.assertEqual(len(directories), len(set(directories)))

    def test_the_directory_name_carries_the_candidate_key(self):
        name = campaign.candidate_directory_name(
            OPTIMIZED_FIXED_TIMING, plans.make_plan(70, 450, 15)
        )
        self.assertIn("optimized_fixed_timing", name)
        self.assertIn("C070", name)
        self.assertIn("f450", name)
        self.assertIn("D015", name)

    def test_two_candidates_never_share_a_path(self):
        first = campaign.run_directory_for(
            self.output_root, OPTIMIZED_FIXED_OFFSET,
            plans.fixed_offset_plan(10), DESIGN_FAMILY, 2001,
        )
        second = campaign.run_directory_for(
            self.output_root, OPTIMIZED_FIXED_OFFSET,
            plans.fixed_offset_plan(11), DESIGN_FAMILY, 2001,
        )
        self.assertNotEqual(first, second)

    def test_the_same_seed_shares_one_manifest_across_candidates(self):
        runner = StubRunner()
        self.execute(runner)
        by_seed = {}
        for call in runner.calls:
            by_seed.setdefault(call["seed"], set()).add(
                call["manifest_csv_path"]
            )
        for seed, paths in by_seed.items():
            self.assertEqual(len(paths), 1, seed)

    def test_different_seeds_use_different_manifests(self):
        runner = StubRunner()
        self.execute(runner)
        paths = set(call["manifest_csv_path"] for call in runner.calls)
        self.assertEqual(len(paths), 2)


class ResumeTests(CampaignBase):
    """Resume skips only what it can prove is complete and unchanged."""

    def test_a_completed_run_is_skipped_on_the_second_pass(self):
        first = StubRunner()
        self.execute(first)
        self.assertEqual(len(first.calls), 6)
        second = StubRunner()
        ledger = self.execute(second)
        self.assertEqual(second.calls, [])
        self.assertTrue(all(
            entry["status"] == campaign.STATUS_SKIPPED_COMPLETE
            for entry in ledger
        ))

    def test_a_failed_run_is_rerun(self):
        failing = plans.candidate_key(self.candidates[0])
        first = StubRunner(fail_keys=[failing])
        ledger = self.execute(first)
        failed = [
            entry for entry in ledger
            if entry["status"] == campaign.STATUS_FAILED
        ]
        self.assertEqual(len(failed), 2)
        second = StubRunner()
        self.execute(second)
        rerun = sorted(set(call["key"] for call in second.calls))
        self.assertEqual(rerun, [failing])

    def test_a_run_without_a_marker_is_rerun(self):
        first = StubRunner()
        ledger = self.execute(first)
        os.remove(os.path.join(
            ledger[0]["run_directory"], campaign.MARKER_FILENAME
        ))
        second = StubRunner()
        self.execute(second)
        self.assertEqual(len(second.calls), 1)

    def test_a_tampered_marker_is_not_trusted(self):
        first = StubRunner()
        ledger = self.execute(first)
        path = os.path.join(
            ledger[0]["run_directory"], campaign.MARKER_FILENAME
        )
        with open(path) as handle:
            marker = json.load(handle)
        marker["route_xml_sha256"] = "0" * 64
        with open(path, "w") as handle:
            json.dump(marker, handle)
        second = StubRunner()
        self.execute(second)
        self.assertEqual(len(second.calls), 1)

    def test_a_marker_edited_to_keep_its_hash_fields_is_still_caught(self):
        """Editing the payload without recomputing the marker hash fails."""
        first = StubRunner()
        ledger = self.execute(first)
        directory = ledger[0]["run_directory"]
        path = os.path.join(directory, campaign.MARKER_FILENAME)
        with open(path) as handle:
            marker = json.load(handle)
        marker["elapsed_wall_s"] = 0.0001
        with open(path, "w") as handle:
            json.dump(marker, handle)
        problems = campaign.completion_problems(
            directory, OPTIMIZED_FIXED_OFFSET, self.candidates[0],
            DESIGN_FAMILY, 2001, marker["manifest_csv_sha256"],
            marker["route_xml_sha256"], marker["sumo_seed"],
        )
        self.assertIn(
            "the completion marker has been modified since it was written",
            problems,
        )

    def test_a_stale_metrics_file_is_not_trusted(self):
        first = StubRunner()
        ledger = self.execute(first)
        directory = ledger[0]["run_directory"]
        path = os.path.join(directory, campaign.METRICS_FILENAME)
        with open(path) as handle:
            metrics = json.load(handle)
        metrics["J_primary_mean_scheduled_waiting_burden_s"] = 0.001
        with open(path, "w") as handle:
            json.dump(metrics, handle, sort_keys=True)
        second = StubRunner()
        self.execute(second)
        self.assertEqual(len(second.calls), 1)

    def test_a_deleted_metrics_file_is_not_trusted(self):
        first = StubRunner()
        ledger = self.execute(first)
        os.remove(os.path.join(
            ledger[0]["run_directory"], campaign.METRICS_FILENAME
        ))
        second = StubRunner()
        self.execute(second)
        self.assertEqual(len(second.calls), 1)

    def test_a_marker_from_a_different_candidate_is_not_trusted(self):
        first = StubRunner()
        ledger = self.execute(first)
        directory = ledger[0]["run_directory"]
        problems = campaign.completion_problems(
            directory, OPTIMIZED_FIXED_OFFSET, self.candidates[2],
            DESIGN_FAMILY, 2001, "x", "y", 1,
        )
        self.assertTrue(any("candidate_key" in item for item in problems))

    def test_candidate_and_seed_pairing_survives_resume(self):
        """After resume, every run still points at its own seed's manifest."""
        first = StubRunner()
        ledger = self.execute(first)
        for entry in ledger[:2]:
            shutil.rmtree(entry["run_directory"], ignore_errors=True)
        second = StubRunner()
        resumed = self.execute(second)
        for call in second.calls:
            expected = campaign.manifest_prefix_for(
                self.manifest_root, DESIGN_FAMILY, call["seed"]
            )
            self.assertEqual(call["manifest_csv_path"], expected + ".csv")
            self.assertEqual(call["route_xml_path"], expected + ".rou.xml")
        by_seed = {}
        for entry in resumed:
            by_seed.setdefault(entry["traffic_seed"], set()).add(
                (entry["manifest_csv_sha256"], entry["route_xml_sha256"],
                 entry["sumo_seed"])
            )
        for seed, realisations in by_seed.items():
            self.assertEqual(len(realisations), 1, seed)

    def test_resume_does_not_regenerate_a_manifest(self):
        first = StubRunner()
        self.execute(first)
        prefix = campaign.manifest_prefix_for(
            self.manifest_root, DESIGN_FAMILY, 2001
        )
        before = sha256_file(prefix + ".rou.xml")
        second = StubRunner()
        self.execute(second)
        self.assertEqual(sha256_file(prefix + ".rou.xml"), before)

    def test_a_partial_marker_write_is_ignored(self):
        """The temporary name is what a crash leaves behind."""
        first = StubRunner()
        ledger = self.execute(first)
        directory = ledger[0]["run_directory"]
        os.rename(
            os.path.join(directory, campaign.MARKER_FILENAME),
            os.path.join(directory, campaign.MARKER_FILENAME + ".partial"),
        )
        second = StubRunner()
        self.execute(second)
        self.assertEqual(len(second.calls), 1)


class LedgerTests(CampaignBase):
    """The ledger has to say what happened, including how long it took."""

    def test_the_ledger_records_every_required_field(self):
        runner = StubRunner()
        self.execute(runner)
        path = os.path.join(self.output_root, campaign.LEDGER_JSON)
        with open(path) as handle:
            payload = json.load(handle)
        entry = payload["entries"][0]
        for field in ("controller", "candidate_key", "traffic_family",
                      "traffic_seed", "manifest_index", "sumo_seed",
                      "manifest_csv_sha256", "route_xml_sha256",
                      "run_directory", "status", "clearance_status",
                      "elapsed_wall_s", "exit_status"):
            self.assertIn(field, entry, field)
        self.assertIn("pruning_policy", payload)

    def test_the_csv_ledger_is_written_too(self):
        runner = StubRunner()
        self.execute(runner)
        path = os.path.join(self.output_root, campaign.LEDGER_CSV)
        self.assertTrue(os.path.isfile(path))
        with open(path) as handle:
            header = handle.readline().strip().split(",")
        self.assertEqual(header, list(campaign.LEDGER_FIELDS))

    def test_elapsed_runtime_is_recorded_per_run(self):
        runner = StubRunner()
        ledger = self.execute(runner)
        for entry in ledger:
            self.assertGreaterEqual(entry["elapsed_wall_s"], 0.0)
            self.assertIsNotNone(entry["started_at"])
            self.assertIsNotNone(entry["finished_at"])

    def test_a_failure_is_recorded_with_a_nonzero_exit_status(self):
        def exploding(*args, **kwargs):
            raise RuntimeError("SUMO died")

        ledger = self.execute(exploding)
        self.assertTrue(all(
            entry["status"] == campaign.STATUS_FAILED for entry in ledger
        ))
        self.assertTrue(all(entry["exit_status"] == 1 for entry in ledger))
        self.assertIn("SUMO died", ledger[0]["failure"])

    def test_the_ledger_distinguishes_skipped_from_completed(self):
        first = StubRunner()
        first_ledger = self.execute(first)
        self.assertTrue(all(
            entry["status"] == campaign.STATUS_COMPLETED
            for entry in first_ledger
        ))
        second_ledger = self.execute(StubRunner())
        self.assertTrue(all(
            entry["status"] == campaign.STATUS_SKIPPED_COMPLETE
            for entry in second_ledger
        ))


class ParallelismUtilityTests(unittest.TestCase):
    """H: engineering measurement, and it must not assume four-way."""

    @staticmethod
    def _module():
        import importlib.util
        path = os.path.join(
            REPOSITORY_ROOT, "scripts", "adaptive_qmix",
            "benchmark_parallelism.py",
        )
        spec = importlib.util.spec_from_file_location(
            "benchmark_parallelism_under_test", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_identical_results_compare_equal(self):
        module = self._module()
        results = [{
            "identity": {"family": "development", "seed": 101,
                         "sumo_seed": 7},
            "metrics": dict((f, 1.0) for f in module.COMPARED_FIELDS),
        }]
        self.assertEqual(module.compare(results, list(results)), [])

    def test_a_differing_metric_is_a_hard_failure(self):
        module = self._module()
        left = [{
            "identity": {"family": "development", "seed": 101, "sumo_seed": 7},
            "metrics": dict((f, 1.0) for f in module.COMPARED_FIELDS),
        }]
        right = [{
            "identity": {"family": "development", "seed": 101, "sumo_seed": 7},
            "metrics": dict((f, 1.0) for f in module.COMPARED_FIELDS),
        }]
        right[0]["metrics"]["J_primary_mean_scheduled_waiting_burden_s"] = 2.0
        differences = module.compare(left, right)
        self.assertEqual(len(differences), 1)
        self.assertIn("J_primary", differences[0])

    def test_a_differing_identity_is_reported(self):
        module = self._module()
        left = [{
            "identity": {"family": "development", "seed": 101, "sumo_seed": 7},
            "metrics": dict((f, 1.0) for f in module.COMPARED_FIELDS),
        }]
        right = [{
            "identity": {"family": "development", "seed": 102, "sumo_seed": 7},
            "metrics": dict((f, 1.0) for f in module.COMPARED_FIELDS),
        }]
        self.assertIn("identity differs", module.compare(left, right)[0])

    def test_the_default_is_two_workers_not_four(self):
        """Read from the running parser, not from the file's text."""
        import subprocess
        import sys
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.path.join(REPOSITORY_ROOT, "src")
        completed = subprocess.run(
            [sys.executable,
             os.path.join(REPOSITORY_ROOT, "scripts", "adaptive_qmix",
                          "benchmark_parallelism.py"),
             "--help"],
            cwd=REPOSITORY_ROOT, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        # argparse rewraps help text, so compare on collapsed whitespace.
        help_text = " ".join(
            completed.stdout.decode("utf-8", "replace").split()
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("4-way is not assumed", help_text)
        self.assertIn("default: 2", help_text)
        self.assertNotIn("default: 4", help_text)

    def test_the_resource_snapshot_degrades_gracefully(self):
        module = self._module()
        snapshot = module.resource_snapshot()
        self.assertIn("available", snapshot)
        if snapshot["available"]:
            self.assertIn("peak_rss_children_bytes", snapshot)
        else:
            self.assertIn("reason", snapshot)

    def test_the_compared_fields_include_the_metrics_that_matter(self):
        module = self._module()
        for field in ("clearance_status",
                      "J_primary_mean_scheduled_waiting_burden_s",
                      "route_xml_sha256", "sumo_seed"):
            self.assertIn(field, module.COMPARED_FIELDS, field)


class CampaignStageGraphTests(unittest.TestCase):
    """3: the stage order is structural, and shortlists are hash-sealed."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.state = os.path.join(self.directory, "state")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write_offset_shortlist(self, count=10):
        return make_shortlist(
            self.directory, campaign.OFFSET_DESIGN,
            [plans.fixed_offset_plan(offset) for offset in range(count)],
        )

    def _write_coarse_shortlist(self, count=5):
        return make_shortlist(
            self.directory, campaign.TIMING_COARSE_DESIGN,
            [plans.make_plan(90, 500, offset * 5) for offset in range(count)],
        )

    def test_the_fine_timing_stage_is_a_design_family_stage(self):
        """It refines on benchmark_design; only the last stage validates."""
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_FINE_DESIGN]["family"],
            "benchmark_design",
        )
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_COARSE_DESIGN]["family"],
            "benchmark_design",
        )
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_VALIDATION]["family"],
            "benchmark_validation",
        )

    def test_the_track_order_is_coarse_then_fine_then_validation(self):
        self.assertIsNone(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_COARSE_DESIGN]["requires"]
        )
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_FINE_DESIGN]["requires"],
            campaign.TIMING_COARSE_DESIGN,
        )
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_VALIDATION]["requires"],
            campaign.TIMING_FINE_DESIGN,
        )
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.OFFSET_VALIDATION]["requires"],
            campaign.OFFSET_DESIGN,
        )

    def test_the_retained_counts_are_the_frozen_ones(self):
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.OFFSET_DESIGN]["retain"], 10
        )
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_COARSE_DESIGN]["retain"],
            5,
        )
        self.assertEqual(
            campaign.CAMPAIGN_STAGES[campaign.TIMING_FINE_DESIGN]["retain"], 10
        )

    def test_a_design_stage_generates_from_the_frozen_grid(self):
        candidates, source = campaign.candidates_for_stage(
            campaign.OFFSET_DESIGN, self.directory
        )
        self.assertEqual(len(candidates), 90)
        self.assertIsNone(source)
        candidates, source = campaign.candidates_for_stage(
            campaign.TIMING_COARSE_DESIGN, self.directory
        )
        self.assertEqual(len(candidates), 1980)
        self.assertIsNone(source)

    def test_a_validation_stage_consumes_the_verified_shortlist(self):
        self._write_offset_shortlist()
        candidates, source = campaign.candidates_for_stage(
            campaign.OFFSET_VALIDATION, self.directory
        )
        self.assertEqual(len(candidates), 10)
        self.assertEqual(source["stage"], campaign.OFFSET_DESIGN)

    def test_the_fine_stage_regenerates_from_the_verified_winners(self):
        """So the neighbourhood cannot be widened by editing a file."""
        self._write_coarse_shortlist()
        candidates, source = campaign.candidates_for_stage(
            campaign.TIMING_FINE_DESIGN, self.directory
        )
        expected = plans.fine_timing_candidates(source["plans"])
        self.assertEqual(
            [plans.candidate_key(p) for p in candidates],
            [plans.candidate_key(p) for p in expected],
        )

    def test_validation_before_design_is_refused(self):
        with self.assertRaises(campaign.StageSequenceError) as caught:
            campaign.assert_campaign_stage_allowed(
                campaign.OFFSET_VALIDATION, self.directory
            )
        self.assertIn("produced no shortlist artefact", str(caught.exception))

    def test_timing_validation_before_the_fine_stage_is_refused(self):
        self._write_coarse_shortlist()
        with self.assertRaises(campaign.StageSequenceError) as caught:
            campaign.assert_campaign_stage_allowed(
                campaign.TIMING_VALIDATION, self.directory
            )
        self.assertIn(campaign.TIMING_FINE_DESIGN, str(caught.exception))

    def test_a_tampered_shortlist_is_refused(self):
        path = self._write_offset_shortlist()
        with open(path) as handle:
            artefact = json.load(handle)
        artefact["plans"][0]["offset_s"] = 77
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(campaign.StageSequenceError) as caught:
            campaign.read_shortlist_artefact(
                self.directory, campaign.OFFSET_DESIGN
            )
        self.assertIn("modified since it was written", str(caught.exception))

    def test_a_shortlist_of_the_wrong_size_is_refused(self):
        with self.assertRaises(campaign.StageSequenceError) as caught:
            self._write_offset_shortlist(count=7)
        self.assertIn("must retain exactly 10", str(caught.exception))

    def test_an_arbitrary_right_sized_shortlist_cannot_be_promoted(self):
        """Ten plausible plans with no derivation evidence are not a shortlist."""
        path = campaign.shortlist_path(
            self.directory, campaign.OFFSET_DESIGN
        )
        chosen = [plans.fixed_offset_plan(offset) for offset in range(10)]
        payload = {
            "campaign_version": campaign.CAMPAIGN_VERSION,
            "stage": campaign.OFFSET_DESIGN,
            "controller": "optimized_fixed_offset",
            "family": "benchmark_design",
            "plans": [dict(plan) for plan in chosen],
            "candidate_keys": [
                list(plans.candidate_key(plan)) for plan in chosen
            ],
            "provenance": {"ranked_on": "benchmark_design"},
        }
        artefact = dict(payload)
        artefact["payload_sha256"] = campaign._sha256_payload(payload)
        os.makedirs(self.directory, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(campaign.StageSequenceError) as caught:
            campaign.read_shortlist_artefact(
                self.directory, campaign.OFFSET_DESIGN
            )
        self.assertIn("no derivation evidence", str(caught.exception))

    def test_a_shortlist_that_is_not_the_top_of_its_own_scores_is_refused(self):
        """Right length, real-looking evidence, wrong candidates."""
        chosen = [plans.fixed_offset_plan(offset) for offset in range(10)]
        every = [plans.fixed_offset_plan(offset) for offset in range(20)]
        path = make_shortlist(
            self.directory, campaign.OFFSET_DESIGN, chosen, every
        )
        with open(path) as handle:
            artefact = json.load(handle)
        # Swap in a candidate the recorded scores rank 15th.
        artefact["plans"][0] = dict(plans.fixed_offset_plan(15))
        artefact["candidate_keys"][0] = list(
            plans.candidate_key(plans.fixed_offset_plan(15))
        )
        payload = dict(
            (k, v) for k, v in artefact.items() if k != "payload_sha256"
        )
        artefact["payload_sha256"] = campaign._sha256_payload(payload)
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(campaign.StageSequenceError) as caught:
            campaign.read_shortlist_artefact(
                self.directory, campaign.OFFSET_DESIGN
            )
        self.assertIn("not the top 10 of its own scores", str(caught.exception))

    def test_a_shortlist_from_another_controller_is_refused(self):
        path = self._write_offset_shortlist()
        with open(path) as handle:
            artefact = json.load(handle)
        artefact["controller"] = "optimized_fixed_timing"
        payload = dict(
            (k, v) for k, v in artefact.items() if k != "payload_sha256"
        )
        artefact["payload_sha256"] = campaign._sha256_payload(payload)
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(campaign.StageSequenceError) as caught:
            campaign.read_shortlist_artefact(
                self.directory, campaign.OFFSET_DESIGN
            )
        self.assertIn("produced by controller", str(caught.exception))

    def test_the_protocol_stage_guard_is_consulted_too(self):
        self._write_offset_shortlist()
        with self.assertRaises(protocol_stages.StageOrderError):
            campaign.assert_campaign_stage_allowed(
                campaign.OFFSET_VALIDATION, self.directory, self.state
            )
        protocol_stages.write_stage_artefact(
            self.state, protocol_stages.BASELINE_DESIGN, {"done": True}
        )
        self.assertTrue(campaign.assert_campaign_stage_allowed(
            campaign.OFFSET_VALIDATION, self.directory, self.state
        ))

    def test_each_stage_maps_to_its_protocol_stage(self):
        for stage, spec in campaign.CAMPAIGN_STAGES.items():
            expected = (
                protocol_stages.BASELINE_VALIDATION
                if spec["family"] == "benchmark_validation"
                else protocol_stages.BASELINE_DESIGN
            )
            self.assertEqual(spec["protocol_stage"], expected, stage)


class CampaignCliStageTests(unittest.TestCase):
    """1: the supported command path executes the frozen workflow.

    The runner is monkeypatched inside the subprocess through a sitecustomize
    shim, so the whole coordinator -- prepare, two shards, aggregate, finalise
    -- executes for real without SUMO.
    """

    SCRIPT = os.path.join(
        REPOSITORY_ROOT, "scripts", "adaptive_qmix",
        "run_baseline_campaign.py",
    )

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.root = os.path.join(self.directory, "campaign")
        self.shim = os.path.join(self.directory, "shim")
        os.makedirs(self.shim)
        # A stub runner injected into the child process, so the CLI itself is
        # what runs rather than a re-implementation of it in the test.
        with open(os.path.join(self.shim, "sitecustomize.py"), "w") as handle:
            handle.write(STUB_RUNNER_SHIM)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _invoke(self, arguments):
        import subprocess
        import sys
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join([
            self.shim, os.path.join(REPOSITORY_ROOT, "src"),
        ])
        completed = subprocess.run(
            [sys.executable, self.SCRIPT, "--campaign-root", self.root]
            + list(arguments),
            cwd=REPOSITORY_ROOT, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        return completed.returncode, completed.stdout.decode("utf-8", "replace")

    def _offset_design_end_to_end(self):
        code, text = self._invoke([
            "--action", "prepare", "--stage", "offset_design",
        ])
        self.assertEqual(code, 0, text)
        self.assertIn("prepared 5 manifests for benchmark_design", text)
        for index in range(2):
            code, text = self._invoke([
                "--action", "run-shard", "--stage", "offset_design",
                "--shard-index", str(index), "--shard-count", "2",
            ])
            self.assertEqual(code, 0, text)
            self.assertIn("shard {} of 2".format(index), text)
        return self._invoke([
            "--action", "finalise", "--stage", "offset_design",
            "--shard-count", "2",
        ])

    def test_prepare_then_two_shards_then_finalise_yields_a_shortlist(self):
        code, text = self._offset_design_end_to_end()
        self.assertEqual(code, 0, text)
        self.assertIn("aggregated 2 shard ledgers", text)
        self.assertIn("450 runs covered exactly once", text)
        self.assertIn("finalised offset_design: shortlist", text)
        artefact = campaign.read_shortlist_artefact(
            os.path.join(self.root, "artefacts"), campaign.OFFSET_DESIGN
        )
        self.assertEqual(len(artefact["plans"]), 10)
        self.assertEqual(artefact["derivation"]["verified_run_count"], 450)
        # The stub scores 12 + offset, so the ten smallest offsets are kept.
        self.assertEqual(
            [key[2] for key in artefact["candidate_keys"]], list(range(10))
        )

    def test_a_fresh_two_shard_run_needs_prepare_first(self):
        """The failure the review asked about: manifests never prepared."""
        code, text = self._invoke([
            "--action", "run-shard", "--stage", "offset_design",
            "--shard-index", "0", "--shard-count", "2",
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("consume manifests read-only", text)

    def test_each_shard_writes_its_own_ledger(self):
        self._invoke(["--action", "prepare", "--stage", "offset_design"])
        for index in range(2):
            self._invoke([
                "--action", "run-shard", "--stage", "offset_design",
                "--shard-index", str(index), "--shard-count", "2",
            ])
        names = sorted(
            name for name in os.listdir(os.path.join(self.root, "runs"))
            if name.startswith("campaign_ledger")
        )
        self.assertIn("campaign_ledger.shard000of002.json", names)
        self.assertIn("campaign_ledger.shard001of002.json", names)

    def test_finalising_with_a_shard_missing_is_refused(self):
        self._invoke(["--action", "prepare", "--stage", "offset_design"])
        self._invoke([
            "--action", "run-shard", "--stage", "offset_design",
            "--shard-index", "0", "--shard-count", "2",
        ])
        code, text = self._invoke([
            "--action", "finalise", "--stage", "offset_design",
            "--shard-count", "2",
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("do not cover the work exactly", text)

    def test_a_worker_never_finalises(self):
        """run-shard has no path to a shortlist artefact."""
        self._invoke(["--action", "prepare", "--stage", "offset_design"])
        self._invoke([
            "--action", "run-shard", "--stage", "offset_design",
            "--shard-index", "0", "--shard-count", "1",
        ])
        with self.assertRaises(campaign.StageSequenceError):
            campaign.read_shortlist_artefact(
                os.path.join(self.root, "artefacts"), campaign.OFFSET_DESIGN
            )

    def test_validation_cannot_start_before_the_design_stages_complete(self):
        code, text = self._invoke([
            "--action", "prepare", "--stage", "offset_validation",
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("produced no shortlist artefact", text)

    def test_validation_still_blocked_after_only_the_offset_track(self):
        """The global design stage needs the timing tracks too."""
        code, text = self._offset_design_end_to_end()
        self.assertEqual(code, 0, text)
        self.assertIn("global stage baseline_design still needs", text)
        self.assertIn("timing_coarse_design", text)
        code, text = self._invoke([
            "--action", "prepare", "--stage", "offset_validation",
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("baseline_design incomplete", text)

    def test_status_reports_progress(self):
        code, text = self._invoke(["--action", "status"])
        self.assertEqual(code, 0, text)
        self.assertIn("baseline_design       : 0 of 3 tracks complete", text)
        self._offset_design_end_to_end()
        code, text = self._invoke(["--action", "status"])
        self.assertIn("baseline_design       : 1 of 3 tracks complete", text)

    def test_the_cli_offers_no_arbitrary_shortlist_option(self):
        code, text = self._invoke(["--help"])
        self.assertEqual(code, 0)
        self.assertNotIn("--shortlist ", text)
        self.assertIn("--action", text)


STUB_RUNNER_SHIM = '''
"""Injected into the campaign CLI subprocess to stand in for SUMO."""
import json
import os
import sys


def _install():
    try:
        from adaptive_qmix.baselines import campaign, plans
    except Exception:
        return

    def stub(traci_module, config, repository_root, controller,
             manifest_csv_path, route_xml_path, family, seed, sumo_seed,
             output_directory, plan=None, manifest_index=0,
             manifest_prefix=None, **kwargs):
        from adaptive_qmix.baselines.integrity import sha256_file
        key = plans.candidate_key(plan)
        metrics = {
            "controller": controller,
            "clearance_status": "CLEARED",
            "J_primary_valid": True,
            "J_primary_mean_scheduled_waiting_burden_s": 12.0 + key[2],
            "mean_completed_time_loss_s": 20.0 + key[2],
            "traffic_family": family,
            "traffic_seed": int(seed),
            "manifest_index": manifest_index,
            "phase_parameters": dict(plan),
            "sumo_seed": int(sumo_seed),
            "manifest_csv_sha256": sha256_file(manifest_csv_path),
            "route_xml_sha256": sha256_file(route_xml_path),
        }
        with open(os.path.join(output_directory, "evaluation_metrics.json"),
                  "w") as handle:
            json.dump(metrics, handle, sort_keys=True)
        return metrics

    import adaptive_qmix.baselines.runner as runner_module
    runner_module.run_baseline = stub
    sys.modules["traci"] = type(sys)("traci")


_install()
'''


class TrainingCliAuthorizationTests(unittest.TestCase):
    """4: the training CLI refuses an unauthorised official run."""

    SCRIPT = os.path.join(
        REPOSITORY_ROOT, "scripts", "adaptive_qmix", "train_adaptive.py"
    )

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _invoke(self, arguments):
        import subprocess
        import sys
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.path.join(REPOSITORY_ROOT, "src")
        completed = subprocess.run(
            [sys.executable, self.SCRIPT] + list(arguments),
            cwd=REPOSITORY_ROOT, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        return completed.returncode, completed.stdout.decode("utf-8", "replace")

    def test_official_training_without_a_campaign_state_is_refused(self):
        output = os.path.join(self.directory, "run")
        code, text = self._invoke([
            "--method", "qmix", "--training-seed", "101",
            "--run-kind", "official_training",
            "--output-directory", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("requires a campaign-state directory", text)
        self.assertFalse(
            os.path.exists(output),
            "an unauthorised run must not create its output directory",
        )

    def test_official_training_before_the_baseline_freeze_is_refused(self):
        state = os.path.join(self.directory, "state")
        protocol_stages.write_stage_artefact(
            state, protocol_stages.BASELINE_DESIGN, {"ok": True}
        )
        output = os.path.join(self.directory, "run2")
        code, text = self._invoke([
            "--method", "qmix", "--training-seed", "101",
            "--run-kind", "official_training", "--campaign-state", state,
            "--output-directory", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("freeze_baseline_plans", text)
        self.assertFalse(os.path.exists(output))

    def test_the_cli_exposes_the_campaign_state_option(self):
        code, text = self._invoke(["--help"])
        self.assertEqual(code, 0)
        collapsed = " ".join(text.split())
        self.assertIn("--campaign-state", collapsed)
        self.assertIn("freeze_baseline_plans", collapsed)


class StageFinaliserTests(CampaignBase):
    """A: shortlists are derived from the complete verified result set."""

    def setUp(self):
        super(StageFinaliserTests, self).setUp()
        self.shortlists = os.path.join(self.directory, "shortlists")
        # A three-candidate offset track, so a stage is finalisable in a test.
        self.stage = campaign.OFFSET_DESIGN

    def _finalise(self, **kwargs):
        return campaign.finalise_stage(
            self.stage, self.output_root, self.manifest_root,
            self.shortlists, self.config, REPOSITORY_ROOT, **kwargs
        )

    def _run_everything(self, candidates=None):
        campaign.prepare_seed_manifests(
            self.manifest_root, self.config, DESIGN_FAMILY, DESIGN_SEEDS
        )
        return self.execute(
            StubRunner(), candidates=candidates, seeds=DESIGN_SEEDS
        )

    def test_the_seed_set_is_not_a_caller_parameter(self):
        """A finaliser that took seeds could be pointed at a subset."""
        import inspect
        signature = inspect.signature(campaign.finalise_stage)
        self.assertNotIn("seeds", signature.parameters)
        self.assertNotIn(
            "seeds", inspect.signature(campaign.collect_stage_runs).parameters
        )

    def test_an_incomplete_stage_cannot_finalise(self):
        """Ranking a partial set would rank candidates on unequal evidence."""
        self._run_everything()
        with self.assertRaises(campaign.StageSequenceError) as caught:
            self._finalise()
        message = str(caught.exception)
        self.assertIn("is not complete", message)
        self.assertIn("expected runs verify", message)

    def test_a_complete_stage_derives_its_shortlist_from_the_scores(self):
        every = [plans.fixed_offset_plan(offset) for offset in range(90)]
        self._run_everything(candidates=every)
        result = self._finalise()
        self.assertEqual(result["kind"], "shortlist")
        self.assertEqual(len(result["retained_keys"]), 10)
        self.assertEqual(result["verified_run_count"], 450)
        # The stub scores 12.0 + offset, so the ten smallest offsets win.
        self.assertEqual(
            [key[2] for key in result["retained_keys"]], list(range(10))
        )
        artefact = campaign.read_shortlist_artefact(
            self.shortlists, self.stage
        )
        self.assertEqual(len(artefact["plans"]), 10)
        self.assertEqual(artefact["derivation"]["verified_run_count"], 450)

    def test_a_missing_run_blocks_finalisation(self):
        every = [plans.fixed_offset_plan(offset) for offset in range(90)]
        ledger = self._run_everything(candidates=every)
        shutil.rmtree(ledger[0]["run_directory"], ignore_errors=True)
        with self.assertRaises(campaign.StageSequenceError) as caught:
            self._finalise()
        self.assertIn("449 of 450", str(caught.exception))

    def test_there_is_no_public_way_to_declare_plans_selected(self):
        """Only the finaliser may produce an official shortlist."""
        self.assertFalse(hasattr(campaign, "write_shortlist_artefact"))
        self.assertTrue(hasattr(campaign, "_write_shortlist_artefact"))
        self.assertTrue(hasattr(campaign, "finalise_stage"))

    def test_a_validation_stage_writes_a_selected_plan_artefact(self):
        chosen = [plans.fixed_offset_plan(offset) for offset in range(10)]
        make_shortlist(self.shortlists, campaign.OFFSET_DESIGN, chosen)
        campaign.prepare_seed_manifests(
            self.manifest_root, self.config, VALIDATION_FAMILY
        )
        campaign.execute_campaign(
            StubRunner(), "optimized_fixed_offset", chosen,
            VALIDATION_FAMILY, self.config, self.output_root,
            self.manifest_root, REPOSITORY_ROOT,
        )
        result = campaign.finalise_stage(
            campaign.OFFSET_VALIDATION, self.output_root, self.manifest_root,
            self.shortlists, self.config, REPOSITORY_ROOT,
        )
        self.assertEqual(result["kind"], "selected_plan")
        artefact = campaign.read_selected_plan_artefact(
            self.shortlists, campaign.OFFSET_VALIDATION
        )
        self.assertIn("provenance", artefact)
        self.assertEqual(
            artefact["provenance"]["validation_family"], VALIDATION_FAMILY
        )
        self.assertTrue(artefact["baseline_config_sha256"])
        self.assertTrue(artefact["network_sha256"])
        # The stub scores 12.0 + offset, so offset 0 wins on J_primary.
        self.assertEqual(artefact["plan"]["offset_s"], 0)

    def test_a_tampered_selected_plan_artefact_is_refused(self):
        chosen = [plans.fixed_offset_plan(offset) for offset in range(10)]
        make_shortlist(self.shortlists, campaign.OFFSET_DESIGN, chosen)
        campaign.prepare_seed_manifests(
            self.manifest_root, self.config, VALIDATION_FAMILY
        )
        campaign.execute_campaign(
            StubRunner(), "optimized_fixed_offset", chosen,
            VALIDATION_FAMILY, self.config, self.output_root,
            self.manifest_root, REPOSITORY_ROOT,
        )
        campaign.finalise_stage(
            campaign.OFFSET_VALIDATION, self.output_root, self.manifest_root,
            self.shortlists, self.config, REPOSITORY_ROOT,
        )
        path = campaign.selected_plan_path(
            self.shortlists, campaign.OFFSET_VALIDATION
        )
        with open(path) as handle:
            artefact = json.load(handle)
        artefact["plan"]["offset_s"] = 77
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(campaign.StageSequenceError):
            campaign.read_selected_plan_artefact(
                self.shortlists, campaign.OFFSET_VALIDATION
            )


class EnvironmentBindingTests(CampaignBase):
    """C: a run made under another configuration must be rerun."""

    def test_a_marker_records_the_environment_it_was_produced_under(self):
        first = StubRunner()
        ledger = self.execute(first)
        marker = campaign.read_completion_marker(ledger[0]["run_directory"])
        environment = marker["environment"]
        self.assertEqual(
            environment["baseline_config_sha256"],
            self.config["_config_sha256"],
        )
        self.assertTrue(environment["network_sha256"])
        self.assertTrue(environment["network_git_blob"])

    def test_a_run_from_another_config_is_rerun_not_reused(self):
        first = StubRunner()
        ledger = self.execute(first)
        directory = ledger[0]["run_directory"]
        marker_path = os.path.join(directory, campaign.MARKER_FILENAME)
        with open(marker_path) as handle:
            marker = json.load(handle)
        marker["environment"]["baseline_config_sha256"] = "an-older-config"
        payload = dict(
            (k, v) for k, v in marker.items() if k != "marker_sha256"
        )
        marker["marker_sha256"] = campaign._sha256_payload(payload)
        with open(marker_path, "w") as handle:
            json.dump(marker, handle)
        second = StubRunner()
        self.execute(second)
        self.assertEqual(len(second.calls), 1)

    def test_a_run_from_another_network_is_rerun(self):
        first = StubRunner()
        ledger = self.execute(first)
        directory = ledger[0]["run_directory"]
        problems = campaign.completion_problems(
            directory, OPTIMIZED_FIXED_OFFSET, self.candidates[0],
            DESIGN_FAMILY, 2001,
            *self._identity(2001),
            environment=dict(
                campaign.environment_identity(self.config, REPOSITORY_ROOT),
                network_sha256="a-different-network",
            )
        )
        self.assertTrue(
            any("different environment" in item for item in problems)
        )

    def _identity(self, seed):
        manifest = campaign.ensure_seed_manifest(
            self.manifest_root, self.config, DESIGN_FAMILY, seed
        )
        return (
            manifest["manifest_csv_sha256"], manifest["route_xml_sha256"],
            manifest["sumo_seed"],
        )

    def test_a_cleared_run_without_a_finite_tie_metric_is_not_complete(self):
        """CLEARED alone does not make a run usable evidence."""
        class NoTieMetric(StubRunner):
            def __call__(self, *args, **kwargs):
                metrics = StubRunner.__call__(self, *args, **kwargs)
                metrics["mean_completed_time_loss_s"] = float("nan")
                with open(os.path.join(
                    kwargs.get("output_directory") or args[9],
                    campaign.METRICS_FILENAME,
                ), "w") as handle:
                    json.dump(metrics, handle, sort_keys=True)
                return metrics

        ledger = self.execute(NoTieMetric())
        self.assertTrue(all(
            entry["status"] == campaign.STATUS_FAILED for entry in ledger
        ))
        self.assertIsNone(
            campaign.read_completion_marker(ledger[0]["run_directory"])
        )


class ShardLedgerTests(CampaignBase):
    """C: concurrent shards must not rewrite one another's ledger."""

    def test_each_shard_writes_its_own_ledger(self):
        campaign.prepare_seed_manifests(
            self.manifest_root, self.config, DESIGN_FAMILY, (2001, 2002)
        )
        for index in range(2):
            self.execute(
                StubRunner(), shard_index=index, shard_count=2,
                allow_manifest_generation=False,
            )
        names = sorted(
            name for name in os.listdir(self.output_root)
            if name.startswith("campaign_ledger")
        )
        self.assertEqual(names, [
            "campaign_ledger.shard000of002.csv",
            "campaign_ledger.shard000of002.json",
            "campaign_ledger.shard001of002.csv",
            "campaign_ledger.shard001of002.json",
        ])
        self.assertNotIn(campaign.LEDGER_JSON, names)

    def test_the_shard_ledgers_aggregate_to_the_whole_work_list(self):
        campaign.prepare_seed_manifests(
            self.manifest_root, self.config, DESIGN_FAMILY, (2001, 2002)
        )
        for index in range(2):
            self.execute(
                StubRunner(), shard_index=index, shard_count=2,
                allow_manifest_generation=False,
            )
        aggregate = campaign.aggregate_ledgers(self.output_root)
        self.assertEqual(len(aggregate["entries"]), 6)
        self.assertEqual(len(aggregate["shard_ledgers"]), 2)
        keys = [
            (tuple(entry["candidate_key"]), entry["traffic_seed"])
            for entry in aggregate["entries"]
        ]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, sorted(keys))

    def test_overlapping_shards_are_an_error_not_a_silent_merge(self):
        """Two shards claiming one run would halve or double the evidence."""
        campaign.prepare_seed_manifests(
            self.manifest_root, self.config, DESIGN_FAMILY, (2001, 2002)
        )
        ledger = self.execute(
            StubRunner(), allow_manifest_generation=False
        )
        for index in range(2):
            # Both shard ledgers claim the same first run.
            campaign.write_ledger(
                self.output_root, ledger[:1],
                shard_index=index, shard_count=2,
            )
        with self.assertRaises(campaign.CampaignError) as caught:
            campaign.aggregate_ledgers(self.output_root)
        self.assertIn("partition the work exactly once", str(caught.exception))

    def test_a_worker_may_not_generate_a_missing_manifest(self):
        with self.assertRaises(campaign.CampaignError) as caught:
            self.execute(
                StubRunner(), shard_index=0, shard_count=2,
                allow_manifest_generation=False,
            )
        self.assertIn("consume manifests read-only", str(caught.exception))

    def test_sharded_runs_default_to_read_only_manifests(self):
        with self.assertRaises(campaign.CampaignError):
            self.execute(StubRunner(), shard_index=0, shard_count=2)

    def test_pre_generated_manifests_are_verified_not_rewritten(self):
        prepared = campaign.prepare_seed_manifests(
            self.manifest_root, self.config, DESIGN_FAMILY, (2001, 2002)
        )
        before = dict(
            (seed, entry["route_xml_sha256"])
            for seed, entry in prepared.items()
        )
        loaded = campaign.load_seed_manifests(
            self.manifest_root, self.config, DESIGN_FAMILY, (2001, 2002)
        )
        for seed, entry in loaded.items():
            self.assertEqual(entry["route_xml_sha256"], before[seed])


class BaselineFreezeFromArtefactsTests(CampaignBase):
    """2: stage 3 is built from the two verified selected-plan artefacts."""

    def setUp(self):
        super(BaselineFreezeFromArtefactsTests, self).setUp()
        self.shortlists = os.path.join(self.directory, "artefacts")
        self.state = os.path.join(self.directory, "state")
        self.adaptive = load_config(os.path.join(
            REPOSITORY_ROOT, "config", "adaptive_qmix",
            "qualification_300m_medium.json",
        ))

    def _complete_validation_track(self, stage, design_stage, plans_list):
        make_shortlist(self.shortlists, design_stage, plans_list)
        campaign.prepare_seed_manifests(
            self.manifest_root, self.config, VALIDATION_FAMILY
        )
        campaign.execute_campaign(
            StubRunner(), campaign.CAMPAIGN_STAGES[stage]["controller"],
            plans_list, VALIDATION_FAMILY, self.config, self.output_root,
            self.manifest_root, REPOSITORY_ROOT,
        )
        return campaign.finalise_stage(
            stage, self.output_root, self.manifest_root, self.shortlists,
            self.config, REPOSITORY_ROOT,
        )

    def _both_tracks(self):
        protocol_stages.write_stage_artefact(
            self.state, protocol_stages.BASELINE_DESIGN, {"ok": True}
        )
        self._complete_validation_track(
            campaign.OFFSET_VALIDATION, campaign.OFFSET_DESIGN,
            [plans.fixed_offset_plan(offset) for offset in range(10)],
        )
        self._complete_validation_track(
            campaign.TIMING_VALIDATION, campaign.TIMING_FINE_DESIGN,
            [plans.make_plan(90, 500, offset * 5) for offset in range(10)],
        )
        campaign.complete_global_stage(
            protocol_stages.BASELINE_VALIDATION, self.shortlists, self.state
        )

    def test_the_freeze_is_built_from_the_verified_artefacts(self):
        self._both_tracks()
        result = campaign.freeze_baseline_plans(
            self.shortlists, self.state, self.config, REPOSITORY_ROOT,
            self.adaptive,
        )
        payload = result["payload"]
        self.assertEqual(
            payload["adaptive_config_sha256"],
            self.adaptive["_config_sha256"],
        )
        self.assertEqual(
            payload["baseline_config_sha256"], self.config["_config_sha256"]
        )
        for track in ("optimized_fixed_offset", "optimized_fixed_timing"):
            entry = payload[track]
            self.assertEqual(
                entry["selected_key"],
                list(plans.candidate_key(entry["plan"])),
            )
            self.assertEqual(
                entry["provenance"]["design_seeds"],
                list(DESIGN_SEEDS),
            )
            self.assertTrue(os.path.isfile(
                entry["selected_plan_artefact_path"]
            ))
        # And it verifies as a stage artefact.
        self.assertTrue(protocol_stages.verify_stage_artefact(
            self.state, protocol_stages.FREEZE_BASELINE_PLANS
        ))

    def test_the_freeze_cannot_be_built_without_both_tracks(self):
        protocol_stages.write_stage_artefact(
            self.state, protocol_stages.BASELINE_DESIGN, {"ok": True}
        )
        self._complete_validation_track(
            campaign.OFFSET_VALIDATION, campaign.OFFSET_DESIGN,
            [plans.fixed_offset_plan(offset) for offset in range(10)],
        )
        with self.assertRaises(campaign.StageSequenceError) as caught:
            campaign.freeze_baseline_plans(
                self.shortlists, self.state, self.config, REPOSITORY_ROOT,
                self.adaptive,
            )
        self.assertIn("timing_validation", str(caught.exception))

    def test_a_tampered_selected_plan_blocks_the_freeze(self):
        self._both_tracks()
        path = campaign.selected_plan_path(
            self.shortlists, campaign.OFFSET_VALIDATION
        )
        with open(path) as handle:
            artefact = json.load(handle)
        artefact["plan"]["offset_s"] = 77
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(campaign.StageSequenceError):
            campaign.freeze_baseline_plans(
                self.shortlists, self.state, self.config, REPOSITORY_ROOT,
                self.adaptive,
            )

    def test_an_artefact_edited_after_freezing_invalidates_the_stage(self):
        self._both_tracks()
        campaign.freeze_baseline_plans(
            self.shortlists, self.state, self.config, REPOSITORY_ROOT,
            self.adaptive,
        )
        path = campaign.selected_plan_path(
            self.shortlists, campaign.TIMING_VALIDATION
        )
        with open(path, "a") as handle:
            handle.write("\n")
        with self.assertRaises(protocol_stages.StagePayloadError) as caught:
            protocol_stages.verify_stage_artefact(
                self.state, protocol_stages.FREEZE_BASELINE_PLANS
            )
        self.assertIn("no longer hashes to the value the freeze recorded",
                      str(caught.exception))

    def test_the_global_validation_stage_needs_both_tracks(self):
        protocol_stages.write_stage_artefact(
            self.state, protocol_stages.BASELINE_DESIGN, {"ok": True}
        )
        self._complete_validation_track(
            campaign.OFFSET_VALIDATION, campaign.OFFSET_DESIGN,
            [plans.fixed_offset_plan(offset) for offset in range(10)],
        )
        partial = campaign.complete_global_stage(
            protocol_stages.BASELINE_VALIDATION, self.shortlists, self.state
        )
        self.assertFalse(partial["written"])
        self.assertEqual(
            partial["outstanding"], [campaign.TIMING_VALIDATION]
        )

    def test_official_training_refuses_a_near_identical_adaptive_config(self):
        """A copy that changes only the learning rate is a different config."""
        self._both_tracks()
        campaign.freeze_baseline_plans(
            self.shortlists, self.state, self.config, REPOSITORY_ROOT,
            self.adaptive,
        )
        variant_path = os.path.join(self.directory, "variant.json")
        with open(os.path.join(
            REPOSITORY_ROOT, "config", "adaptive_qmix",
            "qualification_300m_medium.json",
        )) as handle:
            data = json.load(handle)
        original_rate = data["training"]["learning_rate"]
        data["training"]["learning_rate"] = float(original_rate) * 2.0
        with open(variant_path, "w") as handle:
            json.dump(data, handle, indent=2)
        variant = load_config(variant_path)
        self.assertNotEqual(
            variant["_config_sha256"], self.adaptive["_config_sha256"]
        )
        # Everything else about it is scientifically plausible.
        self.assertEqual(variant["executor"], self.adaptive["executor"])
        self.assertEqual(variant["network"], self.adaptive["network"])
        with self.assertRaises(
            authorization.TrainingAuthorizationError
        ) as caught:
            authorization.authorize_run(
                "official_training", self.state, 101, None, 360000,
                variant["_config_sha256"],
            )
        message = str(caught.exception)
        self.assertIn("must use the frozen adaptive configuration", message)
        self.assertIn("different specification", message)
        # The frozen one is accepted.
        self.assertIsNotNone(authorization.authorize_run(
            "official_training", self.state, 101, None, 360000,
            self.adaptive["_config_sha256"],
        ))


class CodeProvenanceResumeTests(CampaignBase):
    """4: a run made under another commit is rerun, not reused."""

    def test_the_marker_records_the_source_commit(self):
        first = StubRunner()
        ledger = self.execute(first)
        marker = campaign.read_completion_marker(ledger[0]["run_directory"])
        commit = marker["environment"]["source_commit"]
        self.assertTrue(commit)
        self.assertEqual(len(commit), 40)

    def test_a_run_from_another_commit_is_rerun(self):
        first = StubRunner()
        ledger = self.execute(first)
        directory = ledger[0]["run_directory"]
        marker_path = os.path.join(directory, campaign.MARKER_FILENAME)
        with open(marker_path) as handle:
            marker = json.load(handle)
        marker["environment"]["source_commit"] = "0" * 40
        payload = dict(
            (k, v) for k, v in marker.items() if k != "marker_sha256"
        )
        marker["marker_sha256"] = campaign._sha256_payload(payload)
        with open(marker_path, "w") as handle:
            json.dump(marker, handle)
        second = StubRunner()
        self.execute(second)
        self.assertEqual(
            len(second.calls), 1,
            "a run produced under another commit must not be reused",
        )

    def test_the_difference_is_reported_by_name(self):
        first = StubRunner()
        ledger = self.execute(first)
        problems = campaign.completion_problems(
            ledger[0]["run_directory"], OPTIMIZED_FIXED_OFFSET,
            self.candidates[0], DESIGN_FAMILY, 2001,
            *self._identity(2001),
            environment=dict(
                campaign.environment_identity(self.config, REPOSITORY_ROOT),
                source_commit="0" * 40,
            )
        )
        joined = " ".join(problems)
        self.assertIn("different environment", joined)
        self.assertIn("source_commit", joined)

    def _identity(self, seed):
        manifest = campaign.ensure_seed_manifest(
            self.manifest_root, self.config, DESIGN_FAMILY, seed
        )
        return (
            manifest["manifest_csv_sha256"], manifest["route_xml_sha256"],
            manifest["sumo_seed"],
        )

    def test_the_environment_identity_names_every_bound_field(self):
        identity = campaign.environment_identity(self.config, REPOSITORY_ROOT)
        for field in ("baseline_config_sha256", "network_sha256",
                      "network_git_blob", "source_commit",
                      "campaign_version", "raw_log_schema_version"):
            self.assertIn(field, identity, field)


if __name__ == "__main__":
    unittest.main()
