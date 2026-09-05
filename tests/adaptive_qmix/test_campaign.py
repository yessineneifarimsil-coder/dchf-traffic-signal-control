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
from adaptive_qmix.baselines.integrity import sha256_file
from adaptive_qmix.baselines.runner import (
    OPTIMIZED_FIXED_OFFSET, OPTIMIZED_FIXED_TIMING,
)
from adaptive_qmix.baselines.search import DESIGN_FAMILY, DESIGN_SEEDS
from adaptive_qmix.config import load_config
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
        return campaign.write_shortlist_artefact(
            self.directory, campaign.OFFSET_DESIGN,
            [plans.fixed_offset_plan(offset) for offset in range(count)],
            {"ranked_on": "benchmark_design"},
        )

    def _write_coarse_shortlist(self, count=5):
        return campaign.write_shortlist_artefact(
            self.directory, campaign.TIMING_COARSE_DESIGN,
            [plans.make_plan(90, 500, offset * 5) for offset in range(count)],
            {"ranked_on": "benchmark_design"},
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
    """3: a real CLI invocation, not just the library, enforces the order."""

    SCRIPT = os.path.join(
        REPOSITORY_ROOT, "scripts", "adaptive_qmix",
        "run_baseline_campaign.py",
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

    def test_the_cli_offers_no_arbitrary_shortlist_option(self):
        """An unauthenticated candidate list must not be acceptable input."""
        code, text = self._invoke(["--help"])
        self.assertEqual(code, 0)
        self.assertNotIn("--shortlist ", text)
        self.assertIn("--stage", text)

    def test_the_cli_refuses_validation_before_design(self):
        output = os.path.join(self.directory, "out")
        code, text = self._invoke([
            "--stage", "offset_validation", "--output-root", output,
            "--campaign-state", os.path.join(self.directory, "state"),
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("produced no shortlist artefact", text)
        self.assertFalse(os.path.exists(output))

    def test_the_cli_refuses_timing_validation_before_the_fine_stage(self):
        output = os.path.join(self.directory, "out2")
        state = os.path.join(self.directory, "state2")
        campaign.write_shortlist_artefact(
            state, campaign.TIMING_COARSE_DESIGN,
            [plans.make_plan(90, 500, index * 5) for index in range(5)],
            {"ranked_on": "benchmark_design"},
        )
        code, text = self._invoke([
            "--stage", "timing_validation", "--output-root", output,
            "--campaign-state", state,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("timing_fine_design", text)
        self.assertFalse(os.path.exists(output))

    def test_the_cli_requires_a_campaign_state_for_a_real_run(self):
        output = os.path.join(self.directory, "out3")
        code, text = self._invoke([
            "--stage", "offset_design", "--output-root", output,
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("--campaign-state is required", text)
        self.assertFalse(os.path.exists(output))

    def test_a_dry_run_of_the_first_stage_is_allowed(self):
        code, text = self._invoke([
            "--stage", "offset_design",
            "--output-root", os.path.join(self.directory, "dry"),
            "--dry-run",
        ])
        self.assertEqual(code, 0)
        self.assertIn("candidates : 90", text)
        self.assertIn("frozen grid", text)

    def test_a_dry_run_of_the_fine_stage_uses_the_verified_shortlist(self):
        state = os.path.join(self.directory, "state4")
        campaign.write_shortlist_artefact(
            state, campaign.TIMING_COARSE_DESIGN,
            [plans.make_plan(90, 500, index * 5) for index in range(5)],
            {"ranked_on": "benchmark_design"},
        )
        code, text = self._invoke([
            "--stage", "timing_fine_design",
            "--output-root", os.path.join(self.directory, "dry2"),
            "--shortlist-directory", state, "--dry-run",
        ])
        self.assertEqual(code, 0)
        self.assertIn("verified shortlist of timing_coarse_design", text)
        self.assertIn("family     : benchmark_design", text)


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


if __name__ == "__main__":
    unittest.main()
