"""Batch S3: the decision rules, and the impossibility of changing them later.

Every assertion here is about a rule rather than a result, which is the point:
these tests fail if someone loosens a criterion, reorders a stage, or reaches
for the held-out data, regardless of what any campaign produced.
"""

from __future__ import absolute_import

import hashlib
import json
import math
import os
import shutil
import tempfile
import unittest

from .common import REPOSITORY_ROOT, config_copy

from adaptive_qmix.config import (
    ContractError, ScientificRunBlocked, load_config,
    require_scientific_run_allowed, validate_config,
)
from adaptive_qmix.protocol import (
    authorization, behaviour, decision, freeze, semantics, stages,
    statistics,
)


QUALIFICATION_CONFIG_PATH = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
)
BASELINE_CONFIG_PATH = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)


class FrozenPrimarySemanticsTests(unittest.TestCase):
    """A: 5 s decisions, EXTEND 5, SWITCH 3 + 2, and no green bounds."""

    def setUp(self):
        self.config = config_copy()

    def test_the_official_yellow_is_three_and_new_green_is_two(self):
        self.assertEqual(semantics.YELLOW_S, 3)
        self.assertEqual(semantics.SWITCH_NEW_GREEN_S, 2)
        self.assertEqual(semantics.SWITCH_DURATION_S, 5)
        executor = self.config["executor"]
        self.assertEqual(int(executor["yellow_duration_s"]), 3)
        self.assertEqual(int(executor["switch_new_green_s"]), 2)

    def test_the_decision_interval_and_extend_are_five_seconds(self):
        self.assertEqual(semantics.CONTROL_INTERVAL_S, 5)
        self.assertEqual(semantics.EXTEND_GREEN_S, 5)
        executor = self.config["executor"]
        self.assertEqual(int(executor["control_interval_s"]), 5)
        self.assertEqual(int(executor["extend_duration_s"]), 5)

    def test_the_frozen_timing_check_rejects_any_other_value(self):
        for field, value in (
            ("yellow_duration_s", 4), ("switch_new_green_s", 1),
            ("control_interval_s", 10), ("extend_duration_s", 4),
        ):
            executor = dict(self.config["executor"])
            executor[field] = value
            with self.assertRaises(semantics.SemanticsError, msg=field):
                semantics.assert_frozen_timing(executor)

    def test_no_minimum_or_maximum_green_appears_in_primary_semantics(self):
        self.assertIsNone(
            semantics.PRIMARY_SPECIFICATION["imposed_minimum_green_s"]
        )
        self.assertIsNone(
            semantics.PRIMARY_SPECIFICATION["imposed_maximum_green_s"]
        )
        self.assertIsNone(semantics.PRIMARY_SPECIFICATION["fixed_cycle"])
        self.assertTrue(
            semantics.assert_no_imposed_green_bounds(self.config["executor"])
        )

    def test_a_green_bound_added_to_the_executor_is_refused(self):
        for key in ("minimum_green_s", "maximum_green_s", "cycle_s"):
            executor = dict(self.config["executor"])
            executor[key] = 10
            with self.assertRaises(semantics.SemanticsError, msg=key):
                semantics.assert_no_imposed_green_bounds(executor)

    def test_the_qualification_config_carries_no_green_bounds(self):
        config = load_config(QUALIFICATION_CONFIG_PATH)
        for key in semantics.FORBIDDEN_PRIMARY_KEYS:
            self.assertNotIn(key, config["executor"], key)

    def test_the_minimum_green_wrapper_is_not_implemented(self):
        """It is a post-GO sensitivity, deliberately unavailable now."""
        note = semantics.PRIMARY_SPECIFICATION["minimum_green_wrapper"]
        self.assertIn("POST-GO", note)
        self.assertIn("not implemented", note)
        self.assertFalse(hasattr(semantics, "MinimumGreenWrapper"))

    def test_other_controllers_green_bounds_are_not_qmix_constraints(self):
        note = semantics.PRIMARY_SPECIFICATION["green_bound_note"]
        self.assertIn("never of QMIX", note)

    def test_the_declaration_replaced_the_provisional_blocker(self):
        config = load_config(QUALIFICATION_CONFIG_PATH)
        declared = config["executor"]["yellow_semantics"]
        self.assertEqual(declared, semantics.FROZEN_YELLOW_SEMANTICS)
        self.assertFalse(declared.startswith(semantics.PROVISIONAL_PREFIX))
        self.assertTrue(semantics.assert_primary_semantics_frozen(config))

    def test_a_provisional_declaration_is_still_refused(self):
        config = config_copy()
        config["executor"]["yellow_semantics"] = "provisional_something"
        with self.assertRaises(semantics.SemanticsError) as caught:
            semantics.assert_primary_semantics_frozen(config)
        self.assertIn("still declared provisional", str(caught.exception))

    def test_the_frozen_declaration_is_verified_by_config_validation(self):
        config = config_copy()
        config["executor"]["yellow_duration_s"] = 2
        config["executor"]["switch_new_green_s"] = 3
        with self.assertRaises(ContractError):
            validate_config(config)

    def test_the_specification_is_hashable_and_stable(self):
        first = semantics.specification_sha256()
        self.assertEqual(first, semantics.specification_sha256())
        self.assertEqual(len(first), 64)

    def test_both_configurations_declare_the_same_frozen_semantics(self):
        for path in (QUALIFICATION_CONFIG_PATH, BASELINE_CONFIG_PATH):
            config = load_config(path)
            self.assertTrue(
                semantics.assert_primary_semantics_frozen(config), path
            )


def checkpoint_fixture(directory):
    """A real file whose bytes the frozen checkpoint hash must match."""
    path = os.path.join(directory, "checkpoint.pt")
    with open(path, "wb") as handle:
        handle.write(b"frozen policy bytes")
    digest = hashlib.sha256(b"frozen policy bytes").hexdigest()
    return path, digest


def full_validation_records(best_index=100000):
    """Every preregistered checkpoint exactly once, each stating its source."""
    records = []
    for index in statistics.CHECKPOINT_TRANSITIONS:
        records.append({
            "transition_index": index,
            "family": statistics.LEARNER_VALIDATION_FAMILY,
            "seeds": list(statistics.LEARNER_VALIDATION_SEEDS),
            "mean_J_primary_s": 9.0 if index == best_index else 12.0,
            "mean_time_loss_s": 6.0,
        })
    return records


ADAPTIVE_SHA = "adaptive-config-sha"


def baseline_freeze_payload(directory=None, config_sha="baseline-sha",
                            network_sha="network-sha",
                            network_blob="network-blob",
                            adaptive_sha=ADAPTIVE_SHA):
    """A semantically real freeze_baseline_plans payload.

    The two selected-plan artefacts it rests on are written to disk, because
    the validator now checks that they exist and still hash to what the freeze
    recorded.
    """
    directory = directory or tempfile.mkdtemp()
    if not os.path.isdir(directory):
        os.makedirs(directory)

    def track(name, offset):
        artefact_path = os.path.join(directory, name + ".selected.json")
        with open(artefact_path, "w") as handle:
            json.dump({"stage": name, "selected_key": [90, 500, offset]},
                      handle, sort_keys=True)
        with open(artefact_path, "rb") as handle:
            artefact_sha = hashlib.sha256(handle.read()).hexdigest()
        return {
            "plan": {"cycle_s": 90, "split_thousandths": 500,
                     "offset_s": offset, "green_H_s": 42, "green_V_s": 42,
                     "yellow_s": 3},
            "selected_key": [90, 500, offset],
            "provenance": {
                "design_family": "benchmark_design",
                "design_seeds": [2001, 2002, 2003, 2004, 2005],
                "validation_family": "benchmark_validation",
                "validation_seeds": [2101, 2102, 2103, 2104, 2105],
                "selected_key": [90, 500, offset],
                "protocol": "ranked on design; selected on validation",
            },
            "baseline_config_sha256": config_sha,
            "network_sha256": network_sha,
            "network_git_blob": network_blob,
            "selected_plan_artefact_path": artefact_path,
            "selected_plan_artefact_sha256": artefact_sha,
        }
    return {
        "optimized_fixed_offset": track("offset_validation", 45),
        "optimized_fixed_timing": track("timing_validation", 20),
        "adaptive_config_sha256": adaptive_sha,
        "baseline_config_sha256": config_sha,
        "network_sha256": network_sha,
        "network_git_blob": network_blob,
    }


def clean_reviews(pathology=(), methods=("qmix", "vdn", "idqn"),
                  omit=()):
    """Structured behavioural reviews for every learned method and seed."""
    report = dict(
        (name, {"value": 1.0}) for name in behaviour.REQUIRED_REPORT_NAMES
    )
    reviews = {}
    for method in methods:
        per_seed = {}
        for seed in statistics.TRAINING_SEEDS:
            if (method, seed) in omit:
                continue
            per_seed[seed] = behaviour.record_review(
                "{}_seed{}".format(method, seed), report, "reviewer",
                behaviour.CONCLUSION_PATHOLOGY
                if (method, seed) in pathology
                else behaviour.CONCLUSION_CLEAN,
                training_seed=seed, method=method,
            )
        reviews[method] = per_seed
    return reviews


class GoNoGoDefinitionTests(unittest.TestCase):
    """B: the decision rule is written down, serialised and hashed."""

    def test_the_definition_is_serialised_and_hashable(self):
        text = decision.serialize()
        self.assertIsInstance(text, str)
        parsed = json.loads(text)
        self.assertEqual(parsed["protocol_version"], decision.PROTOCOL_VERSION)
        digest = hashlib.sha256(text.encode("ascii")).hexdigest()
        self.assertEqual(digest, decision.protocol_sha256())
        self.assertEqual(len(digest), 64)

    def test_the_hash_is_stable_across_calls(self):
        self.assertEqual(
            decision.protocol_sha256(), decision.protocol_sha256()
        )

    def test_the_hash_changes_if_the_rule_changes(self):
        """A silently loosened criterion cannot keep the same hash."""
        payload = json.loads(decision.serialize())
        payload["go_rule"] = "GO if it looks promising"
        altered = hashlib.sha256(
            decision.canonical_bytes(payload)
        ).hexdigest()
        self.assertNotEqual(altered, decision.protocol_sha256())

    def test_the_deciding_comparisons_are_oft_and_idqn(self):
        self.assertEqual(
            decision.DECIDING_COMPARISONS, ("delta_J_OFT", "delta_J_IDQN")
        )
        self.assertEqual(
            decision.comparison("delta_J_OFT")["comparator"],
            decision.OPTIMIZED_FIXED_TIMING,
        )
        self.assertEqual(
            decision.comparison("delta_J_IDQN")["comparator"], decision.IDQN
        )

    def test_vdn_is_reported_but_does_not_decide(self):
        item = decision.comparison("delta_J_VDN")
        self.assertEqual(item["role"], decision.ROLE_REPORTED)
        self.assertIsNone(item["go_criterion"])
        self.assertNotIn("delta_J_VDN", decision.DECIDING_COMPARISONS)

    def test_max_pressure_is_mandatory_but_not_a_gate(self):
        item = decision.comparison("delta_J_MP")
        self.assertEqual(item["role"], decision.ROLE_REPORTED)
        self.assertTrue(decision.GO_NO_GO["max_pressure_is_not_a_gate"])
        self.assertIn(
            decision.CANONICAL_MAX_PRESSURE, decision.OFFICIAL_CONTROLLERS
        )
        self.assertNotIn("delta_J_MP", decision.DECIDING_COMPARISONS)

    def test_p5_is_a_diagnostic_and_never_official(self):
        self.assertIn(
            decision.MATCHED_INTERVAL_PRESSURE_P5,
            decision.DIAGNOSTIC_CONTROLLERS,
        )
        self.assertNotIn(
            decision.MATCHED_INTERVAL_PRESSURE_P5,
            decision.OFFICIAL_CONTROLLERS,
        )
        self.assertTrue(decision.GO_NO_GO["p5_is_not_an_official_controller"])
        self.assertNotIn("delta_J_P5", decision.DECIDING_COMPARISONS)

    def test_the_official_set_is_exactly_seven(self):
        self.assertEqual(len(decision.OFFICIAL_CONTROLLERS), 7)

    def test_no_percentage_improvement_threshold_exists(self):
        text = decision.serialize()
        self.assertIn("No minimum percentage improvement is required", text)
        for key in decision.GO_NO_GO:
            self.assertNotIn("threshold_percent", key)
        self.assertNotIn("minimum_improvement", text)

    def test_go_requires_every_deciding_interval_below_zero(self):
        verdict = decision.evaluate_go_no_go(
            {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5)},
            validity_passed=True, behaviour_reviews=clean_reviews(),
        )
        self.assertEqual(verdict["verdict"], "GO")
        self.assertEqual(verdict["reasons"], [])

    def test_one_interval_touching_zero_is_no_go(self):
        verdict = decision.evaluate_go_no_go(
            {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, 0.2)},
            validity_passed=True, behaviour_reviews=clean_reviews(),
        )
        self.assertEqual(verdict["verdict"], "NO-GO")
        self.assertIn("delta_J_IDQN", verdict["reasons"][0])

    def test_a_losing_max_pressure_comparison_does_not_block_go(self):
        verdict = decision.evaluate_go_no_go(
            {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5),
             "delta_J_MP": (2.0, 8.0)},
            validity_passed=True, behaviour_reviews=clean_reviews(),
        )
        self.assertEqual(verdict["verdict"], "GO")
        self.assertIn("delta_J_MP", verdict["reported_only"])

    def test_failed_validity_or_missing_behaviour_review_is_no_go(self):
        intervals = {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5)}
        self.assertEqual(
            decision.evaluate_go_no_go(
                intervals, False, clean_reviews()
            )["verdict"],
            "NO-GO",
        )
        self.assertEqual(
            decision.evaluate_go_no_go(intervals, True, {})["verdict"],
            "NO-GO",
        )

    def test_a_missing_deciding_comparison_cannot_be_decided(self):
        with self.assertRaises(decision.DecisionProtocolError):
            decision.evaluate_go_no_go(
                {"delta_J_OFT": (-5.0, -1.0)}, True, clean_reviews()
            )


class ValidityGateTests(unittest.TestCase):
    """C: what makes one run admissible evidence."""

    @staticmethod
    def _metrics(**overrides):
        base = {
            "scheduled_count": 2800, "completed_count": 2800,
            "tripinfo_count": 2800, "exceptional_count": 0,
            "exceptional_outcomes": {}, "missing_tripinfo_ids": [],
            "clearance_status": "CLEARED", "J_primary_valid": True,
            "J_primary_mean_scheduled_waiting_burden_s": 12.5,
            "mean_completed_time_loss_s": 20.0,
            "mean_completed_travel_time_s": 80.0,
            "mean_completed_waiting_time_s": 12.0,
            "mean_completed_depart_delay_s": 0.5,
            "mean_completed_stops": 0.7,
            "controller": "qmix", "traffic_family": "final_test",
            "traffic_seed": 3001,
        }
        base.update(overrides)
        return base

    @staticmethod
    def _behaviour(**overrides):
        base = {
            "lane_state_sampling_cadence": "full_1s",
            "demand_active_seconds_logged": 3600,
            "demand_active_seconds_required": 3600,
            "scientific_analysis_permitted": True,
            "episode_status": "CLEARED",
        }
        base.update(overrides)
        return base

    def test_a_clean_run_passes_every_gate(self):
        verdict = validity_module().evaluate_run_validity(
            self._metrics(), self._behaviour()
        )
        self.assertTrue(verdict["valid"])
        self.assertEqual(verdict["failed_gates"], [])

    def test_a_missing_vehicle_fails(self):
        verdict = validity_module().evaluate_run_validity(
            self._metrics(completed_count=2799, tripinfo_count=2799,
                          missing_tripinfo_ids=["veh_0001"]),
            self._behaviour(),
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("all_scheduled_accounted_for", verdict["failed_gates"])
        self.assertIn("no_unexpected_disappearance", verdict["failed_gates"])

    def test_a_non_cleared_run_fails(self):
        verdict = validity_module().evaluate_run_validity(
            self._metrics(clearance_status="CLEARANCE_FAILURE"),
            self._behaviour(),
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("cleared", verdict["failed_gates"])

    def test_an_exceptional_outcome_fails(self):
        verdict = validity_module().evaluate_run_validity(
            self._metrics(exceptional_count=1,
                          exceptional_outcomes={"veh_0007": "TELEPORTED"}),
            self._behaviour(),
        )
        self.assertFalse(verdict["valid"])
        self.assertIn(
            "no_unresolved_teleport_or_accounting_error",
            verdict["failed_gates"],
        )

    def test_incomplete_one_second_logging_fails(self):
        verdict = validity_module().evaluate_run_validity(
            self._metrics(),
            self._behaviour(lane_state_sampling_cadence="decision"),
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("complete_one_second_logging", verdict["failed_gates"])

    def test_a_truncated_episode_fails_the_permission_gate(self):
        verdict = validity_module().evaluate_run_validity(
            self._metrics(),
            self._behaviour(scientific_analysis_permitted=False,
                            demand_active_seconds_logged=1235,
                            episode_status="BUDGET_TRUNCATED"),
        )
        self.assertFalse(verdict["valid"])
        self.assertIn(
            "scientific_analysis_permitted", verdict["failed_gates"]
        )

    def test_a_non_finite_secondary_metric_fails(self):
        verdict = validity_module().evaluate_run_validity(
            self._metrics(mean_completed_time_loss_s=float("nan")),
            self._behaviour(),
        )
        self.assertFalse(verdict["valid"])
        self.assertIn(
            "finite_primary_and_secondary_metrics", verdict["failed_gates"]
        )

    def test_a_failed_run_contributes_nan_not_a_favourable_value(self):
        module = validity_module()
        self.assertTrue(math.isnan(module.invalid_primary_value()))
        verdict = module.evaluate_run_validity(
            self._metrics(clearance_status="CLEARANCE_FAILURE",
                          J_primary_valid=False,
                          J_primary_mean_scheduled_waiting_burden_s=float("nan")),
            self._behaviour(),
        )
        self.assertTrue(math.isnan(verdict["primary_value"]))

    def test_imputing_a_finite_value_into_a_failed_run_is_refused(self):
        module = validity_module()
        with self.assertRaises(module.ValidityError) as caught:
            module.assert_no_favourable_imputation(3.2, "CLEARANCE_FAILURE")
        self.assertIn("rewards a controller for the ones it never served",
                      str(caught.exception))
        self.assertTrue(
            module.assert_no_favourable_imputation(float("nan"),
                                                   "CLEARANCE_FAILURE")
        )

    def test_assert_run_valid_raises_with_the_failed_gates(self):
        module = validity_module()
        with self.assertRaises(module.ValidityError) as caught:
            module.assert_run_valid(
                self._metrics(clearance_status="CLEARANCE_FAILURE"),
                self._behaviour(),
            )
        self.assertIn("cleared", str(caught.exception))


def validity_module():
    from adaptive_qmix.protocol import validity
    return validity


class BehaviourGateTests(unittest.TestCase):
    """D: distributions reported and reviewed before performance is read."""

    @staticmethod
    def _complete_report():
        return dict(
            (name, {"value": 1.0}) for name in behaviour.REQUIRED_REPORT_NAMES
        )

    def test_every_required_distribution_is_named(self):
        for name in ("max_service_deprivation_s", "p95_service_deprivation_s",
                     "green_duration_distribution", "switch_rate",
                     "yellow_fraction", "service_frequency", "green_share",
                     "queue_p95", "queue_max",
                     "emergent_cycle_distribution"):
            self.assertIn(name, behaviour.REQUIRED_REPORT_NAMES, name)
        self.assertEqual(len(behaviour.REQUIRED_REPORT_NAMES), 10)

    def test_service_deprivation_is_reported_per_movement(self):
        for item in behaviour.REQUIRED_REPORTS:
            if item["name"].endswith("service_deprivation_s"):
                self.assertEqual(item["movements"], ("H", "V"))

    def test_an_incomplete_report_does_not_open_the_gate(self):
        report = self._complete_report()
        del report["queue_p95"]
        self.assertEqual(behaviour.missing_reports(report), ["queue_p95"])
        with self.assertRaises(behaviour.BehaviourGateError):
            behaviour.assert_reports_complete(report)

    def test_no_arbitrary_starvation_threshold_exists_in_code(self):
        definition = behaviour.gate_definition()
        serialised = json.dumps(definition)
        self.assertNotIn("threshold_s", serialised)
        self.assertNotIn("starvation_limit", serialised)
        self.assertIn("must be scientifically justified and preregistered",
                      definition["threshold_policy"])

    def test_the_preregistered_review_rule_is_stated_verbatim(self):
        self.assertEqual(
            behaviour.REVIEW_RULE,
            "No qualitatively pathological starvation or flickering may be "
            "hidden by a good network-average J_primary.",
        )

    def test_a_review_records_who_judged_and_on_what(self):
        record = behaviour.record_review(
            "qmix_seed101", self._complete_report(), "reviewer",
            "no_pathology_observed", notes="greens 12-48 s",
        )
        self.assertEqual(record["conclusion"], "no_pathology_observed")
        self.assertEqual(record["reviewer"], "reviewer")
        self.assertTrue(record["reviewed_before_performance"])
        self.assertEqual(record["review_rule"], behaviour.REVIEW_RULE)

    def test_a_review_cannot_be_recorded_without_the_distributions(self):
        report = self._complete_report()
        del report["switch_rate"]
        with self.assertRaises(behaviour.BehaviourGateError):
            behaviour.record_review(
                "qmix_seed101", report, "reviewer", "no_pathology_observed"
            )

    def test_a_review_must_name_a_reviewer_and_a_valid_conclusion(self):
        with self.assertRaises(behaviour.BehaviourGateError):
            behaviour.record_review(
                "qmix", self._complete_report(), "", "no_pathology_observed"
            )
        with self.assertRaises(behaviour.BehaviourGateError):
            behaviour.record_review(
                "qmix", self._complete_report(), "reviewer", "looks fine"
            )

    def test_the_gate_precedes_the_performance_comparison(self):
        self.assertIn(
            "before the performance comparison",
            behaviour.gate_definition()["ordering"],
        )
        self.assertIn("precede", decision.GATE_ORDER_NOTE)


class StatisticalProtocolTests(unittest.TestCase):
    """E: the analysis is fixed before the data exist."""

    def test_the_seeds_and_checkpoints_are_the_preregistered_ones(self):
        self.assertEqual(statistics.TRAINING_SEEDS, tuple(range(101, 111)))
        self.assertEqual(
            statistics.LEARNER_VALIDATION_SEEDS,
            (2201, 2202, 2203, 2204, 2205),
        )
        self.assertEqual(statistics.FINAL_SEEDS, tuple(range(3001, 3011)))
        self.assertEqual(
            statistics.CHECKPOINT_TRANSITIONS,
            tuple(list(range(50000, 350001, 25000)) + [360000]),
        )
        self.assertEqual(len(statistics.CHECKPOINT_TRANSITIONS), 14)

    def test_the_inferential_unit_is_the_training_seed(self):
        self.assertEqual(statistics.INFERENTIAL_UNIT, "training_seed")
        self.assertEqual(statistics.BOOTSTRAP_REPLICATES, 10000)

    def test_checkpoint_selection_follows_the_frozen_order(self):
        chosen = statistics.select_checkpoint(full_validation_records(100000))
        self.assertEqual(chosen["transition_index"], 100000)

    def test_time_loss_breaks_a_j_primary_tie(self):
        records = full_validation_records()
        for record in records:
            record["mean_J_primary_s"] = 9.0
        for record in records:
            if record["transition_index"] == 200000:
                record["mean_time_loss_s"] = 5.0
        self.assertEqual(
            statistics.select_checkpoint(records)["transition_index"], 200000
        )

    def test_the_earliest_checkpoint_wins_a_full_tie(self):
        records = full_validation_records()
        for record in records:
            record["mean_J_primary_s"] = 9.0
            record["mean_time_loss_s"] = 6.0
        self.assertEqual(
            statistics.select_checkpoint(records)["transition_index"], 50000
        )

    def test_a_checkpoint_may_not_be_selected_on_final_test(self):
        records = full_validation_records()
        records[0]["family"] = "final_test"
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.select_checkpoint(records)
        self.assertIn("choosing the answer", str(caught.exception))

    def test_checkpoint_selection_requires_the_exact_validation_seeds(self):
        records = full_validation_records()
        records[2]["seeds"] = [2201, 2202, 2203]
        with self.assertRaises(statistics.StatisticsError):
            statistics.select_checkpoint(records)

    def test_an_unlisted_checkpoint_is_refused(self):
        records = full_validation_records()
        records[0]["transition_index"] = 123456
        with self.assertRaises(statistics.StatisticsError):
            statistics.select_checkpoint(records)

    def test_thirteen_of_fourteen_checkpoints_is_refused(self):
        """Choosing the best of a subset is choosing from a filtered set."""
        records = full_validation_records()[:-1]
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.select_checkpoint(records)
        message = str(caught.exception)
        self.assertIn("all 14 preregistered checkpoints exactly once", message)
        self.assertIn("missing [360000]", message)

    def test_a_duplicated_checkpoint_is_refused(self):
        records = full_validation_records()
        records.append(dict(records[0]))
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.select_checkpoint(records)
        self.assertIn("duplicated", str(caught.exception))

    def test_a_missing_family_is_not_defaulted(self):
        records = full_validation_records()
        del records[1]["family"]
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.select_checkpoint(records)
        self.assertIn("never defaults", str(caught.exception))

    def test_missing_seeds_are_not_defaulted(self):
        records = full_validation_records()
        del records[4]["seeds"]
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.select_checkpoint(records)
        self.assertIn("'seeds'", str(caught.exception))

    def test_a_non_finite_validation_metric_is_refused(self):
        records = full_validation_records()
        records[3]["mean_time_loss_s"] = float("nan")
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.select_checkpoint(records)
        self.assertIn("non-finite", str(caught.exception))

    @staticmethod
    def _panel(offset, seeds=None, episodes=None):
        seeds = seeds or statistics.TRAINING_SEEDS
        episodes = episodes or statistics.FINAL_SEEDS
        return dict(
            (seed, dict(
                (episode, float(offset + 0.01 * (seed % 7) + 0.001 * episode))
                for episode in episodes
            ))
            for seed in seeds
        )

    def test_the_bootstrap_recovers_a_clear_separation(self):
        treatment = self._panel(10.0)
        comparator = self._panel(14.0)
        result = statistics.paired_crossed_bootstrap(
            treatment, comparator, replicates=500
        )
        self.assertAlmostEqual(result["observed_mean_difference"], -4.0, 6)
        self.assertTrue(result["entirely_below_zero"])
        self.assertLess(result["ci_high"], 0.0)
        self.assertEqual(result["training_seed_count"], 10)
        self.assertEqual(result["evaluation_seed_count"], 10)

    def test_the_bootstrap_does_not_separate_identical_panels(self):
        panel = self._panel(10.0)
        result = statistics.paired_crossed_bootstrap(
            panel, panel, replicates=500
        )
        self.assertAlmostEqual(result["observed_mean_difference"], 0.0, 9)
        self.assertFalse(result["entirely_below_zero"])

    def test_unpaired_panels_are_refused(self):
        treatment = self._panel(10.0)
        comparator = self._panel(12.0, seeds=tuple(range(201, 211)))
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.paired_crossed_bootstrap(treatment, comparator)
        self.assertIn("Unpaired training seeds", str(caught.exception))

    def test_mismatched_evaluation_seeds_are_refused(self):
        treatment = self._panel(10.0)
        comparator = self._panel(12.0, episodes=tuple(range(3001, 3009)))
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.paired_crossed_bootstrap(treatment, comparator)
        self.assertIn("Unpaired evaluation seeds", str(caught.exception))

    def test_a_non_finite_metric_never_reaches_the_bootstrap(self):
        treatment = self._panel(10.0)
        comparator = self._panel(12.0)
        comparator[101][3001] = float("nan")
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.paired_crossed_bootstrap(treatment, comparator)
        self.assertIn("excluded by the validity gates", str(caught.exception))

    def test_the_bootstrap_is_deterministic(self):
        treatment = self._panel(10.0)
        comparator = self._panel(11.0)
        first = statistics.paired_crossed_bootstrap(
            treatment, comparator, replicates=200
        )
        second = statistics.paired_crossed_bootstrap(
            treatment, comparator, replicates=200
        )
        self.assertEqual(first["ci_low"], second["ci_low"])
        self.assertEqual(first["ci_high"], second["ci_high"])

    def test_cohen_dz_is_the_paired_effect_size(self):
        self.assertAlmostEqual(
            statistics.paired_cohen_dz([-2.0, -2.0, -2.0, -2.0]), float("inf")
        )
        value = statistics.paired_cohen_dz([-1.0, -2.0, -3.0])
        self.assertAlmostEqual(value, -2.0 / 1.0, 6)

    def test_the_wilson_interval_behaves_at_the_boundaries(self):
        perfect = statistics.wilson_interval(10, 10)
        self.assertAlmostEqual(perfect["ci_high"], 1.0)
        self.assertLess(perfect["ci_low"], 1.0)
        self.assertGreater(perfect["ci_low"], 0.7)
        none = statistics.wilson_interval(0, 10)
        self.assertAlmostEqual(none["ci_low"], 0.0)
        self.assertGreater(none["ci_high"], 0.0)

    def test_the_summary_reports_every_required_quantity(self):
        treatment = self._panel(10.0)
        comparator = self._panel(13.0)
        summary = statistics.summarise_comparison(
            "delta_J_OFT", treatment, comparator, 9, replicates=300
        )
        for field in ("treatment_mean", "treatment_sd", "paired_difference",
                      "ci_95", "paired_cohen_dz", "training_success_count",
                      "wilson_interval",
                      "fraction_of_training_seeds_outperforming_comparator"):
            self.assertIn(field, summary, field)
        self.assertEqual(summary["training_success_count"], 9)
        self.assertEqual(summary["wilson_interval"]["trials"], 10)
        self.assertAlmostEqual(
            summary["fraction_of_training_seeds_outperforming_comparator"], 1.0
        )

    def test_the_protocol_is_hashable(self):
        self.assertEqual(len(statistics.protocol_sha256()), 64)
        self.assertEqual(
            statistics.protocol_sha256(), statistics.protocol_sha256()
        )


class StageOrderTests(unittest.TestCase):
    """F: a stage cannot run before its predecessors have frozen."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_the_ten_stages_are_in_the_specified_order(self):
        self.assertEqual(stages.STAGES, (
            "baseline_design", "baseline_validation", "freeze_baseline_plans",
            "train_learners", "learner_validation_and_checkpoint_freeze",
            "pre_final_audit", "unlock_final_test", "final_paired_evaluation",
            "statistics", "mechanism_interpretation",
        ))
        self.assertEqual(len(stages.STAGES), 10)

    def test_the_first_stage_may_start_immediately(self):
        self.assertTrue(
            stages.assert_stage_allowed(self.directory, stages.BASELINE_DESIGN)
        )

    def test_a_later_stage_cannot_be_skipped_to(self):
        with self.assertRaises(stages.StageOrderError) as caught:
            stages.assert_stage_allowed(
                self.directory, stages.FINAL_EVALUATION
            )
        message = str(caught.exception)
        self.assertIn("cannot start", message)
        self.assertIn("baseline_design incomplete", message)

    def test_each_stage_unlocks_only_the_next(self):
        for index, stage in enumerate(stages.STAGES[:-1]):
            payload = (
                baseline_freeze_payload(self.directory)
                if stage == stages.FREEZE_BASELINE_PLANS else {"step": index}
            )
            stages.write_stage_artefact(self.directory, stage, payload)
            following = stages.STAGES[index + 1]
            self.assertTrue(
                stages.assert_stage_allowed(self.directory, following)
            )
            if index + 2 < len(stages.STAGES):
                with self.assertRaises(stages.StageOrderError):
                    stages.assert_stage_allowed(
                        self.directory, stages.STAGES[index + 2]
                    )

    def test_a_tampered_artefact_does_not_authorise_the_next_stage(self):
        stages.write_stage_artefact(
            self.directory, stages.BASELINE_DESIGN, {"candidates": 90}
        )
        path = stages.artefact_path(self.directory, stages.BASELINE_DESIGN)
        with open(path) as handle:
            artefact = json.load(handle)
        artefact["payload"]["candidates"] = 5
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(stages.ArtefactError) as caught:
            stages.verify_stage_artefact(
                self.directory, stages.BASELINE_DESIGN
            )
        self.assertIn("modified since it was written", str(caught.exception))
        with self.assertRaises(stages.StageOrderError):
            stages.assert_stage_allowed(
                self.directory, stages.BASELINE_VALIDATION
            )

    def test_next_stage_reports_the_first_incomplete_one(self):
        self.assertEqual(
            stages.next_stage(self.directory), stages.BASELINE_DESIGN
        )
        stages.write_stage_artefact(
            self.directory, stages.BASELINE_DESIGN, {"ok": True}
        )
        self.assertEqual(
            stages.next_stage(self.directory), stages.BASELINE_VALIDATION
        )

    def test_unlocking_is_its_own_stage(self):
        definition = stages.state_machine_definition()
        self.assertTrue(definition["unlock_is_its_own_stage"])
        self.assertIn(stages.UNLOCK_FINAL_TEST, stages.STAGES)
        self.assertLess(
            stages.STAGE_INDEX[stages.PRE_FINAL_AUDIT],
            stages.STAGE_INDEX[stages.UNLOCK_FINAL_TEST],
        )
        self.assertLess(
            stages.STAGE_INDEX[stages.UNLOCK_FINAL_TEST],
            stages.STAGE_INDEX[stages.FINAL_EVALUATION],
        )

    def test_an_incomplete_search_result_is_not_a_freeze(self):
        """A stage with no artefact is not frozen, however much work was done."""
        self.assertEqual(stages.completed_stages(self.directory), [])
        with self.assertRaises(stages.ArtefactError):
            stages.verify_stage_artefact(
                self.directory, stages.FREEZE_BASELINE_PLANS
            )


class FreezeAndUnlockTests(unittest.TestCase):
    """I: final_test stays locked, and an incomplete freeze unlocks nothing."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.state = os.path.join(self.directory, "state")
        FreezeAndUnlockTests.CHECKPOINT_PATH, \
            FreezeAndUnlockTests.CHECKPOINT_SHA = checkpoint_fixture(
                self.directory
            )

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)
        FreezeAndUnlockTests.CHECKPOINT_PATH = None
        FreezeAndUnlockTests.CHECKPOINT_SHA = None

    @staticmethod
    def _plan_entry(offset=45):
        return {
            "plan": {"cycle_s": 90, "split_thousandths": 500,
                     "offset_s": offset, "green_H_s": 42, "green_V_s": 42,
                     "yellow_s": 3},
            "provenance": {
                "design_family": "benchmark_design",
                "design_seeds": [2001, 2002, 2003, 2004, 2005],
                "validation_family": "benchmark_validation",
                "validation_seeds": [2101, 2102, 2103, 2104, 2105],
                "selected_key": [90, 500, offset],
                "protocol": "ranked on design; selected on validation",
            },
        }

    CHECKPOINT_PATH = None
    CHECKPOINT_SHA = None

    @classmethod
    def _checkpoint(cls, seed, **overrides):
        entry = {
            "training_seed": seed, "transition_index": 250000,
            "checkpoint_sha256": cls.CHECKPOINT_SHA or "a" * 64,
            "checkpoint_path": cls.CHECKPOINT_PATH or "checkpoint.pt",
            "selected_on_family": "learner_validation",
            "selected_on_seeds": list(statistics.LEARNER_VALIDATION_SEEDS),
            "validation_mean_J_primary_s": 11.5,
            "validation_mean_time_loss_s": 19.0,
        }
        entry.update(overrides)
        return entry

    @classmethod
    def _checkpoints(cls):
        """Ten independently selected policies per method, one per seed."""
        return dict(
            (method, dict(
                (seed, cls._checkpoint(seed))
                for seed in statistics.TRAINING_SEEDS
            ))
            for method in decision.LEARNED_METHODS
        )

    def _complete(self):
        return freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            self._plan_entry(45), self._plan_entry(20), self._checkpoints(),
        )

    def test_the_schema_names_every_required_field(self):
        schema = freeze.freeze_schema()
        for field in ("adaptive_config_sha256", "baseline_config_sha256",
                      "network_sha256", "network_git_blob",
                      "selected_optimized_fixed_offset",
                      "selected_optimized_fixed_timing",
                      "selected_checkpoints",
                      "statistical_protocol_version",
                      "go_no_go_protocol_version"):
            self.assertIn(field, schema["required_fields"], field)
        self.assertFalse(schema["unlock_implemented"])

    def test_a_complete_artefact_verifies(self):
        self.assertTrue(freeze.assert_freeze_complete(self._complete()))

    def test_a_missing_baseline_plan_blocks_the_freeze(self):
        artefact = self._complete()
        artefact["selected_optimized_fixed_timing"] = None
        artefact["freeze_sha256"] = None
        artefact = freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            self._plan_entry(45), None, self._checkpoints(),
        )
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(artefact)
        self.assertIn("selected_optimized_fixed_timing", str(caught.exception))

    def test_a_plan_without_provenance_blocks_the_freeze(self):
        entry = self._plan_entry(45)
        del entry["provenance"]["validation_seeds"]
        artefact = freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            entry, self._plan_entry(20), self._checkpoints(),
        )
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(artefact)
        self.assertIn("provenance.validation_seeds", str(caught.exception))

    def test_a_missing_learned_checkpoint_blocks_the_freeze(self):
        checkpoints = self._checkpoints()
        del checkpoints["vdn"]
        artefact = freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            self._plan_entry(45), self._plan_entry(20), checkpoints,
        )
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(artefact)
        self.assertIn("selected_checkpoints.vdn", str(caught.exception))

    def test_a_checkpoint_without_a_hash_blocks_the_freeze(self):
        checkpoints = self._checkpoints()
        checkpoints["qmix"][101]["checkpoint_sha256"] = ""
        artefact = freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            self._plan_entry(45), self._plan_entry(20), checkpoints,
        )
        with self.assertRaises(freeze.FreezeError):
            freeze.assert_freeze_complete(artefact)

    def test_a_checkpoint_selected_on_final_test_blocks_the_freeze(self):
        checkpoints = self._checkpoints()
        checkpoints["qmix"][107]["selected_on_family"] = "final_test"
        artefact = freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            self._plan_entry(45), self._plan_entry(20), checkpoints,
        )
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(artefact)
        self.assertIn("only 'learner_validation'", str(caught.exception))

    def test_a_tampered_freeze_artefact_is_refused(self):
        artefact = self._complete()
        artefact["adaptive_config_sha256"] = "something-else"
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.verify_freeze_hash(artefact)
        self.assertIn("modified since it was written", str(caught.exception))

    def test_a_changed_protocol_invalidates_an_earlier_freeze(self):
        artefact = self._complete()
        payload = dict(
            (k, v) for k, v in artefact.items() if k != "freeze_sha256"
        )
        payload["go_no_go_protocol_sha256"] = "0" * 64
        payload["freeze_sha256"] = None
        rebuilt = dict(payload)
        rebuilt["freeze_sha256"] = hashlib.sha256(
            json.dumps(
                dict((k, v) for k, v in payload.items()
                     if k != "freeze_sha256"),
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(rebuilt)
        self.assertIn("decision rule changed after the freeze",
                      str(caught.exception))

    def test_final_test_cannot_be_unlocked_even_with_a_complete_freeze(self):
        freeze.write_freeze_artefact(self.directory, self._complete())
        stages.write_stage_artefact(
            self.state, stages.PRE_FINAL_AUDIT, {"reviewed": True}
        )
        with self.assertRaises(freeze.UnlockRefused) as caught:
            freeze.assert_final_test_unlock(self.directory, self.state)
        message = str(caught.exception)
        self.assertIn("final_test remains locked", message)
        self.assertIn("deliberately not implemented", message)

    def test_the_refusal_reports_outstanding_preconditions(self):
        with self.assertRaises(freeze.UnlockRefused) as caught:
            freeze.assert_final_test_unlock(self.directory, self.state)
        message = str(caught.exception)
        self.assertIn("No pre-final freeze artefact", message)
        self.assertIn("pre_final_audit", message)

    def test_an_incomplete_freeze_cannot_be_written(self):
        artefact = freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            self._plan_entry(45), self._plan_entry(20), {},
        )
        with self.assertRaises(freeze.FreezeError):
            freeze.write_freeze_artefact(self.directory, artefact)
        self.assertFalse(os.path.exists(
            os.path.join(self.directory, freeze.FREEZE_FILENAME)
        ))

    def test_no_final_test_manifest_exists_anywhere(self):
        found = []
        for root, _dirs, files in os.walk(
            os.path.join(REPOSITORY_ROOT, "results")
        ):
            for name in files:
                if "final_test" in name:
                    found.append(os.path.join(root, name))
        self.assertEqual(found, [])


class PerTrainingSeedCheckpointTests(unittest.TestCase):
    """1: ten independently selected policies per method, not one."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        FreezeAndUnlockTests.CHECKPOINT_PATH, \
            FreezeAndUnlockTests.CHECKPOINT_SHA = checkpoint_fixture(
                self.directory
            )

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)
        FreezeAndUnlockTests.CHECKPOINT_PATH = None
        FreezeAndUnlockTests.CHECKPOINT_SHA = None

    def _checkpoints(self, **mutate):
        base = dict(
            (method, dict(
                (seed, FreezeAndUnlockTests._checkpoint(seed))
                for seed in statistics.TRAINING_SEEDS
            ))
            for method in decision.LEARNED_METHODS
        )
        base.update(mutate)
        return base

    def _artefact(self, checkpoints):
        return freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            FreezeAndUnlockTests._plan_entry(45),
            FreezeAndUnlockTests._plan_entry(20), checkpoints,
        )

    def test_ten_per_method_is_complete(self):
        artefact = self._artefact(self._checkpoints())
        self.assertTrue(freeze.assert_freeze_complete(artefact))
        for method in decision.LEARNED_METHODS:
            self.assertEqual(
                len(artefact["selected_checkpoints"][method]), 10, method
            )

    def test_a_single_checkpoint_per_method_is_incomplete(self):
        """The old shape would discard nine of the ten measurements."""
        single = dict(
            (method, FreezeAndUnlockTests._checkpoint(101))
            for method in decision.LEARNED_METHODS
        )
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(single))
        self.assertIn("must map each training seed", str(caught.exception))

    def test_a_missing_training_seed_is_incomplete(self):
        checkpoints = self._checkpoints()
        del checkpoints["qmix"][110]
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(checkpoints))
        self.assertIn("missing training seeds [110]", str(caught.exception))

    def test_a_foreign_training_seed_is_incomplete(self):
        checkpoints = self._checkpoints()
        del checkpoints["vdn"][110]
        checkpoints["vdn"][999] = FreezeAndUnlockTests._checkpoint(999)
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(checkpoints))
        message = str(caught.exception)
        self.assertIn("foreign training seeds [999]", message)
        self.assertIn("missing training seeds [110]", message)

    def test_a_record_filed_under_the_wrong_seed_is_incomplete(self):
        """A duplicate policy hiding under another seed's key."""
        checkpoints = self._checkpoints()
        checkpoints["idqn"][105] = FreezeAndUnlockTests._checkpoint(104)
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(checkpoints))
        self.assertIn("not the key it is filed under", str(caught.exception))

    def test_every_required_checkpoint_field_is_demanded(self):
        for field in ("training_seed", "transition_index", "checkpoint_sha256",
                      "selected_on_family", "selected_on_seeds",
                      "validation_mean_J_primary_s",
                      "validation_mean_time_loss_s"):
            checkpoints = self._checkpoints()
            del checkpoints["qmix"][103][field]
            with self.assertRaises(freeze.FreezeError, msg=field) as caught:
                freeze.assert_freeze_complete(self._artefact(checkpoints))
            self.assertIn(field, str(caught.exception))

    def test_wrong_selection_seeds_block_the_freeze(self):
        checkpoints = self._checkpoints()
        checkpoints["qmix"][102]["selected_on_seeds"] = [2201, 2202, 2203]
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(checkpoints))
        self.assertIn("selection requires exactly", str(caught.exception))

    def test_an_unlisted_transition_index_blocks_the_freeze(self):
        checkpoints = self._checkpoints()
        checkpoints["vdn"][108]["transition_index"] = 123456
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(checkpoints))
        self.assertIn("not a preregistered checkpoint", str(caught.exception))

    def test_string_seed_keys_survive_a_json_round_trip(self):
        artefact = self._artefact(self._checkpoints())
        restored = json.loads(json.dumps(artefact))
        self.assertTrue(freeze.assert_freeze_complete(restored))


class BehaviourGatingTests(unittest.TestCase):
    """2: a pathology-observed review must not pass as a GO gate."""

    INTERVALS = {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5)}

    def test_recorded_and_clean_passes_the_behaviour_gate(self):
        verdict = decision.evaluate_go_no_go(
            self.INTERVALS, True, clean_reviews()
        )
        self.assertEqual(verdict["verdict"], "GO")
        self.assertTrue(verdict["behaviour_review_complete"])
        self.assertFalse(verdict["behaviour_pathology_observed"])

    def test_recorded_pathology_blocks_go_despite_good_intervals(self):
        verdict = decision.evaluate_go_no_go(
            self.INTERVALS, True, clean_reviews(pathology=[("qmix", 106)])
        )
        self.assertEqual(verdict["verdict"], "NO-GO")
        self.assertTrue(verdict["behaviour_review_complete"])
        self.assertTrue(verdict["behaviour_pathology_observed"])
        self.assertIn("pathology was observed", verdict["reasons"][0])
        self.assertIn("106", verdict["reasons"][0])
        # The intervals were fine; the gate is what stopped it.
        for finding in verdict["deciding"].values():
            self.assertTrue(finding["entirely_below_zero"])

    def test_a_missing_qmix_review_blocks_go(self):
        verdict = decision.evaluate_go_no_go(
            self.INTERVALS, True, clean_reviews(omit=[("qmix", 103)])
        )
        self.assertEqual(verdict["verdict"], "NO-GO")
        self.assertFalse(verdict["behaviour_review_complete"])
        self.assertIn("incomplete", verdict["reasons"][0])
        self.assertIn("103", verdict["reasons"][0])

    def test_completeness_and_conclusion_are_separate_facts(self):
        """A review that found a problem is complete AND blocking."""
        summary = behaviour.summarise_reviews(
            clean_reviews(pathology=[("qmix", 101)]),
            statistics.TRAINING_SEEDS, "qmix",
        )
        self.assertTrue(summary["gating_review_complete"])
        self.assertTrue(summary["gating_pathology_observed"])
        self.assertEqual(
            summary["methods"]["qmix"]["pathology_training_seeds"], [101]
        )

    def test_comparator_pathology_is_reported_but_does_not_gate(self):
        """Complete comparator reviews that FOUND pathology still allow GO."""
        verdict = decision.evaluate_go_no_go(
            self.INTERVALS, True,
            clean_reviews(pathology=[("idqn", 102), ("vdn", 109)]),
        )
        self.assertEqual(verdict["verdict"], "GO")
        self.assertEqual(
            verdict["comparator_pathology"], {"idqn": [102], "vdn": [109]}
        )
        self.assertNotIn("idqn", " ".join(verdict["reasons"]))

    def test_an_incomplete_comparator_review_set_is_not_a_go(self):
        """An unreviewed comparator is an incomplete protocol, not a neutral one."""
        verdict = decision.evaluate_go_no_go(
            self.INTERVALS, True, clean_reviews(omit=[("vdn", 104)])
        )
        self.assertEqual(verdict["verdict"], "NO-GO")
        # QMIX itself is fine; the protocol is not complete.
        self.assertTrue(verdict["behaviour_review_complete"])
        self.assertFalse(verdict["all_behaviour_reviews_complete"])
        self.assertIn("vdn", verdict["incomplete_review_methods"])
        self.assertIn("not evidence for or against", " ".join(
            verdict["reasons"]
        ))

    def test_an_invalid_conclusion_is_not_a_completed_review(self):
        reviews = clean_reviews()
        reviews["qmix"][105]["conclusion"] = "probably fine"
        verdict = decision.evaluate_go_no_go(self.INTERVALS, True, reviews)
        self.assertEqual(verdict["verdict"], "NO-GO")
        self.assertFalse(verdict["behaviour_review_complete"])

    def test_reviews_may_be_supplied_as_a_list(self):
        reviews = dict(
            (method, list(per_seed.values()))
            for method, per_seed in clean_reviews().items()
        )
        verdict = decision.evaluate_go_no_go(self.INTERVALS, True, reviews)
        self.assertEqual(verdict["verdict"], "GO")

    def test_the_go_rule_states_the_behaviour_requirement(self):
        self.assertIn("behavioural review", decision.GO_NO_GO["go_rule"])
        self.assertIn("none of those reviews concluded pathology",
                      decision.GO_NO_GO["go_rule"])


class CrossedBootstrapTests(unittest.TestCase):
    """5: one row draw and one column draw per replicate, Cartesian."""

    @staticmethod
    def _panel(offset, seeds=None, episodes=None):
        seeds = seeds or statistics.TRAINING_SEEDS
        episodes = episodes or statistics.FINAL_SEEDS
        return dict(
            (seed, dict(
                (episode, float(offset + 0.01 * (seed % 7) + 0.001 * episode))
                for episode in episodes
            ))
            for seed in seeds
        )

    def test_the_protocol_names_the_crossed_design(self):
        self.assertEqual(
            statistics.RESAMPLING_DESIGN, "paired crossed two-factor bootstrap"
        )
        self.assertEqual(
            statistics.PROTOCOL["resampling"], statistics.RESAMPLING_DESIGN
        )
        self.assertIn("crossed", statistics.PROTOCOL["design"])
        self.assertFalse(hasattr(statistics, "hierarchical_paired_bootstrap"))

    def test_the_same_traffic_columns_apply_to_every_sampled_row(self):
        """The crossed structure, checked on the draws actually used."""
        draws = []
        statistics.paired_crossed_bootstrap(
            self._panel(10.0), self._panel(12.0), replicates=25,
            draw_log=draws,
        )
        self.assertEqual(len(draws), 25)
        for draw in draws:
            self.assertEqual(len(draw["rows"]), 10)
            self.assertEqual(len(draw["columns"]), 10)
            # One column draw per replicate, not one per row: the sampled
            # matrix is the Cartesian product of the two index vectors.
            self.assertIsInstance(draw["columns"][0], int)
        distinct_column_draws = set(
            tuple(draw["columns"]) for draw in draws
        )
        self.assertGreater(len(distinct_column_draws), 1,
                           "columns must actually be resampled")

    def test_the_replicate_mean_is_the_cartesian_sampled_matrix(self):
        import numpy as np
        differences = np.arange(9, dtype=np.float64).reshape(3, 3)
        rows = np.array([0, 0, 2])
        columns = np.array([1, 1, 2])
        # Every sampled row uses the same sampled columns.
        expected = np.mean([
            differences[r][c] for r in rows for c in columns
        ])
        self.assertAlmostEqual(
            statistics.crossed_replicate_mean(differences, rows, columns),
            float(expected),
        )

    def test_a_learned_comparator_is_paired_on_training_seeds(self):
        built = statistics.difference_matrix(
            self._panel(10.0), self._panel(13.0)
        )
        self.assertEqual(built["comparator_kind"], statistics.COMPARATOR_LEARNED)
        self.assertEqual(
            built["comparator_training_seeds"],
            list(statistics.TRAINING_SEEDS),
        )
        self.assertEqual(built["differences"].shape, (10, 10))

    def test_a_deterministic_comparator_is_one_value_per_traffic_seed(self):
        baseline = dict(
            (episode, 14.0 + 0.001 * episode)
            for episode in statistics.FINAL_SEEDS
        )
        built = statistics.difference_matrix(self._panel(10.0), baseline)
        self.assertEqual(
            built["comparator_kind"], statistics.COMPARATOR_DETERMINISTIC
        )
        self.assertIsNone(built["comparator_training_seeds"])
        self.assertEqual(built["differences"].shape, (10, 10))

    def test_a_deterministic_baseline_is_not_ten_trained_samples(self):
        """Its value is reused down the training-seed axis, not replicated."""
        baseline = dict(
            (episode, 14.0) for episode in statistics.FINAL_SEEDS
        )
        treatment = self._panel(10.0)
        built = statistics.difference_matrix(treatment, baseline)
        column = built["differences"][:, 0]
        expected = [
            treatment[seed][statistics.FINAL_SEEDS[0]] - 14.0
            for seed in statistics.TRAINING_SEEDS
        ]
        for actual, want in zip(column, expected):
            self.assertAlmostEqual(actual, want)

    def test_a_deterministic_comparator_missing_a_traffic_seed_is_refused(self):
        baseline = dict(
            (episode, 14.0) for episode in statistics.FINAL_SEEDS[:-1]
        )
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.difference_matrix(self._panel(10.0), baseline)
        self.assertIn("exactly one value for each", str(caught.exception))

    def test_a_mislabelled_comparator_kind_is_refused(self):
        baseline = dict(
            (episode, 14.0) for episode in statistics.FINAL_SEEDS
        )
        with self.assertRaises(statistics.StatisticsError):
            statistics.difference_matrix(
                self._panel(10.0), baseline,
                comparator_kind=statistics.COMPARATOR_LEARNED,
            )
        with self.assertRaises(statistics.StatisticsError):
            statistics.difference_matrix(
                self._panel(10.0), self._panel(12.0),
                comparator_kind=statistics.COMPARATOR_DETERMINISTIC,
            )

    def test_the_summary_reports_the_comparator_kind_and_sd_axis(self):
        baseline = dict(
            (episode, 14.0 + 0.01 * episode)
            for episode in statistics.FINAL_SEEDS
        )
        summary = statistics.summarise_comparison(
            "delta_J_OFT", self._panel(10.0), baseline, 10, replicates=200
        )
        self.assertEqual(
            summary["comparator_kind"], statistics.COMPARATOR_DETERMINISTIC
        )
        self.assertEqual(summary["comparator_sd_axis"], "traffic_seed")
        self.assertEqual(summary["resampling"], statistics.RESAMPLING_DESIGN)


class TrainingSuccessDefinitionTests(unittest.TestCase):
    """6: success is a process property, never a performance one."""

    @staticmethod
    def _record(seed, **overrides):
        record = {
            "training_seed": seed,
            "transitions_completed": 360000,
            "completed_under_contract": True,
            "checkpoints_present": list(statistics.CHECKPOINT_TRANSITIONS),
            "selected_checkpoint": {
                "transition_index": 250000,
                "selected_on_family": "learner_validation",
                "selected_on_seeds": list(
                    statistics.LEARNER_VALIDATION_SEEDS
                ),
            },
        }
        record.update(overrides)
        return record

    def test_a_complete_run_counts_as_successful(self):
        self.assertTrue(statistics.training_seed_succeeded(self._record(101)))

    def test_a_short_run_does_not_count(self):
        self.assertFalse(statistics.training_seed_succeeded(
            self._record(101, transitions_completed=350000)
        ))

    def test_a_run_that_broke_contract_does_not_count(self):
        self.assertFalse(statistics.training_seed_succeeded(
            self._record(101, completed_under_contract=False)
        ))

    def test_a_missing_checkpoint_does_not_count(self):
        self.assertFalse(statistics.training_seed_succeeded(
            self._record(
                101,
                checkpoints_present=list(
                    statistics.CHECKPOINT_TRANSITIONS[:-1]
                ),
            )
        ))

    def test_a_checkpoint_selected_elsewhere_does_not_count(self):
        record = self._record(101)
        record["selected_checkpoint"]["selected_on_family"] = "final_test"
        self.assertFalse(statistics.training_seed_succeeded(record))

    def test_wrong_selection_seeds_do_not_count(self):
        record = self._record(101)
        record["selected_checkpoint"]["selected_on_seeds"] = [2201, 2202]
        self.assertFalse(statistics.training_seed_succeeded(record))

    def test_success_is_never_defined_by_final_test_performance(self):
        definition = statistics.TRAINING_SUCCESS_DEFINITION
        self.assertIn("never defined using final-test performance",
                      definition["explicitly_not"])
        self.assertIn(
            "fraction_of_training_seeds_outperforming_comparator",
            definition["explicitly_not"],
        )
        for criterion in definition["criteria"]:
            self.assertNotIn("final_test", criterion)

    def test_counting_requires_exactly_the_ten_training_seeds(self):
        records = [self._record(seed) for seed in statistics.TRAINING_SEEDS]
        self.assertEqual(statistics.count_training_successes(records), 10)
        records[3]["completed_under_contract"] = False
        self.assertEqual(statistics.count_training_successes(records), 9)
        with self.assertRaises(statistics.StatisticsError):
            statistics.count_training_successes(records[:9])


class OfficialTrainingAuthorizationTests(unittest.TestCase):
    """4: stage 4 is authorised by evidence, not by editing the config."""

    def setUp(self):
        self.state = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def _complete_through_freeze(self):
        for stage in (stages.BASELINE_DESIGN, stages.BASELINE_VALIDATION):
            stages.write_stage_artefact(self.state, stage, {"stage": stage})
        stages.write_stage_artefact(
            self.state, stages.FREEZE_BASELINE_PLANS,
            baseline_freeze_payload(self.state),
        )

    def test_development_and_feasibility_need_no_authorization(self):
        for run_kind in ("development", "compute_feasibility"):
            self.assertIsNone(authorization.authorize_run(run_kind))
            self.assertIsNone(authorization.authorize_run(run_kind, None))

    def test_official_training_without_a_state_directory_is_refused(self):
        with self.assertRaises(
            authorization.TrainingAuthorizationError
        ) as caught:
            authorization.authorize_run("official_training")
        self.assertIn("requires a campaign-state directory",
                      str(caught.exception))

    def test_official_training_before_the_baseline_freeze_is_refused(self):
        stages.write_stage_artefact(
            self.state, stages.BASELINE_DESIGN, {"ok": True}
        )
        with self.assertRaises(
            authorization.TrainingAuthorizationError
        ) as caught:
            authorization.authorize_run("official_training", self.state)
        self.assertIn("freeze_baseline_plans", str(caught.exception))

    def test_official_training_after_the_freeze_is_authorised(self):
        self._complete_through_freeze()
        evidence = authorization.authorize_run("official_training", self.state)
        self.assertEqual(
            evidence["authorising_stage"], stages.FREEZE_BASELINE_PLANS
        )
        self.assertEqual(len(evidence["authorising_artefact_sha256"]), 64)
        self.assertEqual(
            evidence["stage_protocol_version"], stages.PROTOCOL_VERSION
        )
        self.assertFalse(evidence["final_test_unlocked"])

    def test_a_tampered_freeze_artefact_withdraws_authorization(self):
        self._complete_through_freeze()
        path = stages.artefact_path(self.state, stages.FREEZE_BASELINE_PLANS)
        with open(path) as handle:
            artefact = json.load(handle)
        artefact["payload"]["network_sha256"] = "tampered"
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(authorization.TrainingAuthorizationError):
            authorization.authorize_run("official_training", self.state)

    def test_authorization_does_not_consult_the_deprecated_flag(self):
        self._complete_through_freeze()
        evidence = authorization.authorize_run("official_training", self.state)
        self.assertIn("not consulted", evidence["deprecated_flag_note"])
        self.assertIn(
            "NOT authoritative", authorization.DEPRECATION_NOTE
        )
        self.assertNotIn(
            "scientific_run_allowed",
            open(os.path.join(
                REPOSITORY_ROOT, "src", "adaptive_qmix", "training.py"
            )).read(),
        )

    def test_authorising_training_does_not_unlock_final_test(self):
        self._complete_through_freeze()
        evidence = authorization.authorize_run("official_training", self.state)
        self.assertFalse(evidence["final_test_unlocked"])
        self.assertIn("unlocked separately", evidence["final_test_note"])
        with self.assertRaises(freeze.UnlockRefused):
            freeze.assert_final_test_unlock(self.state, self.state)

    def test_the_deprecated_flag_no_longer_needs_flipping(self):
        """Stage-4 training never requires mutating the scientific config."""
        config = load_config(QUALIFICATION_CONFIG_PATH)
        self.assertFalse(config.get("scientific_run_allowed", False))
        self._complete_through_freeze()
        # Authorised despite the flag being false, and the config untouched.
        self.assertIsNotNone(
            authorization.authorize_run("official_training", self.state)
        )
        self.assertEqual(
            load_config(QUALIFICATION_CONFIG_PATH)["_config_sha256"],
            config["_config_sha256"],
        )


class HashSealedWordingTests(unittest.TestCase):
    """8: artefacts are hash-sealed, and nothing claims a signature."""

    def test_stage_artefacts_are_described_as_hash_sealed(self):
        self.assertIn("Hash-sealed, not cryptographically signed",
                      stages.__doc__)
        self.assertIn("hash-sealed completion artefact", stages.__doc__)

    def test_the_freeze_module_makes_the_same_distinction(self):
        self.assertIn("hash-sealed rather than cryptographically signed",
                      freeze.__doc__)

    def test_no_module_claims_a_signature_mechanism(self):
        for module in (stages, freeze, decision, statistics, behaviour,
                       authorization):
            for name in dir(module):
                self.assertNotIn("sign", name.lower().replace("design", ""),
                                 "{}.{}".format(module.__name__, name))


class SemanticStageCompletionTests(unittest.TestCase):
    """B: a hash-consistent file is not evidence that a stage happened."""

    def setUp(self):
        self.state = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def test_a_real_freeze_payload_is_accepted(self):
        path = stages.write_stage_artefact(
            self.state, stages.FREEZE_BASELINE_PLANS,
            baseline_freeze_payload(self.state),
        )
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(
            stages.verify_stage_artefact(
                self.state, stages.FREEZE_BASELINE_PLANS
            )
        )

    def test_an_empty_freeze_payload_cannot_be_written(self):
        with self.assertRaises(stages.StagePayloadError) as caught:
            stages.write_stage_artefact(
                self.state, stages.FREEZE_BASELINE_PLANS, {"done": True}
            )
        self.assertIn("does not record a real baseline freeze",
                      str(caught.exception))

    def test_a_freeze_missing_one_track_is_refused(self):
        payload = baseline_freeze_payload(self.state)
        del payload["optimized_fixed_timing"]
        with self.assertRaises(stages.StagePayloadError) as caught:
            stages.write_stage_artefact(
                self.state, stages.FREEZE_BASELINE_PLANS, payload
            )
        self.assertIn("optimized_fixed_timing", str(caught.exception))

    def test_a_plan_without_provenance_is_refused(self):
        payload = baseline_freeze_payload(self.state)
        del payload["optimized_fixed_offset"]["provenance"]["design_seeds"]
        with self.assertRaises(stages.StagePayloadError) as caught:
            stages.write_stage_artefact(
                self.state, stages.FREEZE_BASELINE_PLANS, payload
            )
        self.assertIn("provenance.design_seeds", str(caught.exception))

    def test_a_plan_selected_on_the_wrong_family_is_refused(self):
        payload = baseline_freeze_payload(self.state)
        payload["optimized_fixed_timing"]["provenance"][
            "validation_family"
        ] = "benchmark_design"
        with self.assertRaises(stages.StagePayloadError) as caught:
            stages.write_stage_artefact(
                self.state, stages.FREEZE_BASELINE_PLANS, payload
            )
        self.assertIn("not benchmark_validation", str(caught.exception))

    def test_a_plan_identity_disagreeing_with_the_stage_is_refused(self):
        payload = baseline_freeze_payload(self.state)
        payload["optimized_fixed_offset"]["network_sha256"] = "another-network"
        with self.assertRaises(stages.StagePayloadError) as caught:
            stages.write_stage_artefact(
                self.state, stages.FREEZE_BASELINE_PLANS, payload
            )
        self.assertIn("disagrees with the stage payload", str(caught.exception))

    def test_a_hollowed_out_payload_fails_verification_after_the_fact(self):
        """Written properly, then emptied and re-hashed."""
        stages.write_stage_artefact(
            self.state, stages.FREEZE_BASELINE_PLANS,
            baseline_freeze_payload(self.state),
        )
        path = stages.artefact_path(self.state, stages.FREEZE_BASELINE_PLANS)
        with open(path) as handle:
            artefact = json.load(handle)
        artefact["payload"] = {"done": True}
        artefact["payload_sha256"] = hashlib.sha256(
            json.dumps({"done": True}, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(stages.StagePayloadError):
            stages.verify_stage_artefact(
                self.state, stages.FREEZE_BASELINE_PLANS
            )

    def test_a_fake_freeze_cannot_authorise_training(self):
        for stage in (stages.BASELINE_DESIGN, stages.BASELINE_VALIDATION):
            stages.write_stage_artefact(self.state, stage, {"ok": True})
        path = stages.artefact_path(self.state, stages.FREEZE_BASELINE_PLANS)
        payload = {"looks": "official"}
        artefact = {
            "protocol_version": stages.PROTOCOL_VERSION,
            "stage": stages.FREEZE_BASELINE_PLANS,
            "stage_index": stages.STAGE_INDEX[stages.FREEZE_BASELINE_PLANS],
            "payload": payload,
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        with open(path, "w") as handle:
            json.dump(artefact, handle)
        with self.assertRaises(
            authorization.TrainingAuthorizationError
        ) as caught:
            authorization.authorize_run("official_training", self.state)
        self.assertIn("does not record a real baseline freeze",
                      str(caught.exception))


class OfficialTrainingLockTests(unittest.TestCase):
    """D: official training is the frozen campaign, not a variation."""

    def setUp(self):
        self.state = tempfile.mkdtemp()
        for stage in (stages.BASELINE_DESIGN, stages.BASELINE_VALIDATION):
            stages.write_stage_artefact(self.state, stage, {"ok": True})
        stages.write_stage_artefact(
            self.state, stages.FREEZE_BASELINE_PLANS,
            baseline_freeze_payload(self.state),
        )

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def test_every_preregistered_seed_is_accepted(self):
        for seed in statistics.TRAINING_SEEDS:
            self.assertIsNotNone(authorization.authorize_run(
                "official_training", self.state, seed, None, 360000,
                ADAPTIVE_SHA,
            ))

    def test_a_seed_outside_the_preregistered_set_is_refused(self):
        with self.assertRaises(
            authorization.TrainingAuthorizationError
        ) as caught:
            authorization.authorize_run(
                "official_training", self.state, 999, None, 360000
            )
        message = str(caught.exception)
        self.assertIn("must be one of", message)
        self.assertIn("999", message)

    def test_a_shortened_official_run_is_refused(self):
        with self.assertRaises(
            authorization.TrainingAuthorizationError
        ) as caught:
            authorization.authorize_run(
                "official_training", self.state, 101, 1000, 360000
            )
        message = str(caught.exception)
        self.assertIn("exactly 360000 transitions", message)
        self.assertIn("matched interaction budget", message)

    def test_the_full_budget_may_be_stated_explicitly(self):
        self.assertIsNotNone(authorization.authorize_run(
            "official_training", self.state, 101, 360000, 360000, ADAPTIVE_SHA
        ))

    def test_development_is_unaffected_by_the_seed_and_budget_lock(self):
        self.assertIsNone(authorization.authorize_run(
            "development", None, 999, 1000, 360000
        ))
        self.assertIsNone(authorization.authorize_run(
            "compute_feasibility", None, 999, 20000, 360000
        ))

    def test_the_authorization_records_the_frozen_plans(self):
        evidence = authorization.authorize_run(
            "official_training", self.state, 101, None, 360000, ADAPTIVE_SHA
        )
        self.assertEqual(
            sorted(evidence["frozen_baseline_plans"]),
            ["optimized_fixed_offset", "optimized_fixed_timing"],
        )
        self.assertEqual(evidence["baseline_config_sha256"], "baseline-sha")


class CheckpointFileBindingTests(unittest.TestCase):
    """E: a frozen checkpoint hash must bind the bytes actually frozen."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path, self.digest = checkpoint_fixture(self.directory)
        FreezeAndUnlockTests.CHECKPOINT_PATH = self.path
        FreezeAndUnlockTests.CHECKPOINT_SHA = self.digest

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)
        FreezeAndUnlockTests.CHECKPOINT_PATH = None
        FreezeAndUnlockTests.CHECKPOINT_SHA = None

    def _artefact(self, mutate=None):
        checkpoints = dict(
            (method, dict(
                (seed, FreezeAndUnlockTests._checkpoint(seed))
                for seed in statistics.TRAINING_SEEDS
            ))
            for method in decision.LEARNED_METHODS
        )
        if mutate:
            mutate(checkpoints)
        return freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            FreezeAndUnlockTests._plan_entry(45),
            FreezeAndUnlockTests._plan_entry(20), checkpoints,
        )

    def test_a_matching_hash_and_file_verify(self):
        self.assertTrue(freeze.assert_freeze_complete(self._artefact()))

    def test_an_arbitrary_hash_string_no_longer_passes(self):
        def mutate(checkpoints):
            checkpoints["qmix"][101]["checkpoint_sha256"] = "a" * 64

        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(mutate))
        self.assertIn("hashes to", str(caught.exception))

    def test_a_missing_checkpoint_file_is_refused(self):
        def mutate(checkpoints):
            checkpoints["vdn"][105]["checkpoint_path"] = os.path.join(
                self.directory, "absent.pt"
            )

        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(mutate))
        self.assertIn("does not exist, so its hash binds nothing",
                      str(caught.exception))

    def test_a_malformed_hash_is_refused(self):
        def mutate(checkpoints):
            checkpoints["idqn"][108]["checkpoint_sha256"] = "not-a-hash"
            checkpoints["idqn"][108]["checkpoint_path"] = None

        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(self._artefact(mutate))
        self.assertIn("64 lowercase hex characters", str(caught.exception))

    def test_a_checkpoint_edited_after_freezing_is_detected(self):
        artefact = self._artefact()
        self.assertTrue(freeze.assert_freeze_complete(artefact))
        with open(self.path, "wb") as handle:
            handle.write(b"different policy bytes")
        with self.assertRaises(freeze.FreezeError) as caught:
            freeze.assert_freeze_complete(artefact)
        self.assertIn("hashes to", str(caught.exception))


class OfficialPanelTests(unittest.TestCase):
    """F: official inference requires exactly 10 x 10."""

    @staticmethod
    def _panel(offset, seeds=None, episodes=None):
        seeds = seeds or statistics.TRAINING_SEEDS
        episodes = episodes or statistics.FINAL_SEEDS
        return dict(
            (seed, dict((episode, float(offset + 0.001 * episode))
                        for episode in episodes))
            for seed in seeds
        )

    def test_the_exact_panel_is_accepted(self):
        result = statistics.paired_crossed_bootstrap(
            self._panel(10.0), self._panel(12.0), replicates=50,
            official=True,
        )
        self.assertEqual(result["training_seed_count"], 10)
        self.assertEqual(result["evaluation_seed_count"], 10)

    def test_a_nine_by_ten_panel_is_refused(self):
        nine = statistics.TRAINING_SEEDS[:-1]
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.paired_crossed_bootstrap(
                self._panel(10.0, seeds=nine),
                self._panel(12.0, seeds=nine),
                replicates=10, official=True,
            )
        self.assertIn("training seeds", str(caught.exception))
        self.assertIn("are not exactly", str(caught.exception))

    def test_a_ten_by_nine_panel_is_refused(self):
        nine = statistics.FINAL_SEEDS[:-1]
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.paired_crossed_bootstrap(
                self._panel(10.0, episodes=nine),
                self._panel(12.0, episodes=nine),
                replicates=10, official=True,
            )
        self.assertIn("final traffic seeds", str(caught.exception))

    def test_a_foreign_training_seed_is_refused(self):
        foreign = tuple(statistics.TRAINING_SEEDS[:-1]) + (999,)
        with self.assertRaises(statistics.StatisticsError):
            statistics.paired_crossed_bootstrap(
                self._panel(10.0, seeds=foreign),
                self._panel(12.0, seeds=foreign),
                replicates=10, official=True,
            )

    def test_a_foreign_final_seed_is_refused(self):
        foreign = tuple(statistics.FINAL_SEEDS[:-1]) + (4001,)
        with self.assertRaises(statistics.StatisticsError):
            statistics.paired_crossed_bootstrap(
                self._panel(10.0, episodes=foreign),
                self._panel(12.0, episodes=foreign),
                replicates=10, official=True,
            )

    def test_a_deterministic_comparator_needs_all_ten_final_seeds(self):
        baseline = dict(
            (episode, 14.0) for episode in statistics.FINAL_SEEDS[:-1]
        )
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.paired_crossed_bootstrap(
                self._panel(10.0), baseline, replicates=10, official=True
            )
        self.assertIn("exactly one value for each", str(caught.exception))

    def test_a_deterministic_comparator_value_must_be_finite(self):
        baseline = dict(
            (episode, 14.0) for episode in statistics.FINAL_SEEDS
        )
        baseline[3005] = float("nan")
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.paired_crossed_bootstrap(
                self._panel(10.0), baseline, replicates=10, official=True
            )
        self.assertIn("one FINITE value per final traffic seed",
                      str(caught.exception))

    def test_a_non_official_call_still_permits_a_smaller_panel(self):
        """Exploratory work is not blocked; official inference is."""
        nine = statistics.TRAINING_SEEDS[:-1]
        result = statistics.paired_crossed_bootstrap(
            self._panel(10.0, seeds=nine), self._panel(12.0, seeds=nine),
            replicates=10,
        )
        self.assertEqual(result["training_seed_count"], 9)

    def test_summarise_comparison_can_demand_the_official_panel(self):
        nine = statistics.TRAINING_SEEDS[:-1]
        with self.assertRaises(statistics.StatisticsError):
            statistics.summarise_comparison(
                "delta_J_OFT", self._panel(10.0, seeds=nine),
                self._panel(12.0, seeds=nine), 9, replicates=10,
                official=True,
            )


class ReviewStructureTests(unittest.TestCase):
    """G: a review record must be a real one, for every learned method."""

    @staticmethod
    def _report():
        return dict(
            (name, {"value": 1.0}) for name in behaviour.REQUIRED_REPORT_NAMES
        )

    def test_a_conclusion_only_dict_is_not_a_review(self):
        problems = behaviour.review_problems(
            {"conclusion": "no_pathology_observed"}, "qmix", 101
        )
        self.assertTrue(problems)
        self.assertIn("missing gate_version", problems)
        self.assertIn("missing reviewer", problems)

    def test_conclusion_only_reviews_leave_the_gate_incomplete(self):
        reviews = dict(
            (method, dict(
                (seed, {"conclusion": "no_pathology_observed"})
                for seed in statistics.TRAINING_SEEDS
            ))
            for method in ("qmix", "vdn", "idqn")
        )
        verdict = decision.evaluate_go_no_go(
            {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5)},
            True, reviews,
        )
        self.assertEqual(verdict["verdict"], "NO-GO")
        self.assertFalse(verdict["behaviour_review_complete"])

    def test_a_review_made_after_performance_is_refused(self):
        review = behaviour.record_review(
            "qmix_101", self._report(), "reviewer",
            behaviour.CONCLUSION_CLEAN, training_seed=101, method="qmix",
        )
        review["reviewed_before_performance"] = False
        problems = behaviour.review_problems(review, "qmix", 101)
        self.assertTrue(
            any("after the numbers were seen" in item for item in problems)
        )

    def test_a_review_filed_under_the_wrong_seed_is_refused(self):
        review = behaviour.record_review(
            "qmix_101", self._report(), "reviewer",
            behaviour.CONCLUSION_CLEAN, training_seed=101, method="qmix",
        )
        problems = behaviour.review_problems(review, "qmix", 102)
        self.assertTrue(
            any("filed under 102" in item for item in problems)
        )

    def test_a_review_filed_under_the_wrong_method_is_refused(self):
        review = behaviour.record_review(
            "qmix_101", self._report(), "reviewer",
            behaviour.CONCLUSION_CLEAN, training_seed=101, method="qmix",
        )
        problems = behaviour.review_problems(review, "vdn", 101)
        self.assertTrue(any("filed under 'vdn'" in item for item in problems))

    def test_a_review_missing_a_distribution_is_refused(self):
        report = self._report()
        del report["queue_max"]
        review = behaviour.record_review(
            "qmix_101", dict(report, queue_max={"value": 1.0}), "reviewer",
            behaviour.CONCLUSION_CLEAN, training_seed=101, method="qmix",
        )
        review["reported"] = report
        problems = behaviour.review_problems(review, "qmix", 101)
        self.assertTrue(
            any("queue_max" in item for item in problems)
        )

    def test_a_wrong_gate_version_is_refused(self):
        review = behaviour.record_review(
            "qmix_101", self._report(), "reviewer",
            behaviour.CONCLUSION_CLEAN, training_seed=101, method="qmix",
        )
        review["gate_version"] = "behavioural-safety-0.9"
        problems = behaviour.review_problems(review, "qmix", 101)
        self.assertTrue(any("gate_version" in item for item in problems))

    def test_all_three_learned_methods_are_required(self):
        summary = behaviour.summarise_reviews(
            clean_reviews(methods=("qmix",)), statistics.TRAINING_SEEDS,
            "qmix", required_methods=("qmix", "vdn", "idqn"),
        )
        self.assertTrue(summary["gating_review_complete"])
        self.assertEqual(
            sorted(summary["comparator_review_incomplete"]), ["idqn", "vdn"]
        )
        for method in ("idqn", "vdn"):
            self.assertEqual(
                summary["methods"][method]["missing_training_seeds"],
                list(statistics.TRAINING_SEEDS),
            )

    def test_missing_comparator_reviews_are_explicitly_incomplete(self):
        verdict = decision.evaluate_go_no_go(
            {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5)},
            True, clean_reviews(methods=("qmix",)),
        )
        self.assertEqual(verdict["verdict"], "NO-GO")
        self.assertEqual(
            sorted(verdict["comparator_review_incomplete"]), ["idqn", "vdn"]
        )
        self.assertEqual(
            sorted(verdict["incomplete_review_methods"]), ["idqn", "vdn"]
        )

    def test_a_malformed_qmix_review_is_not_counted_as_pathology_free(self):
        reviews = clean_reviews()
        del reviews["qmix"][104]["reviewer"]
        summary = behaviour.summarise_reviews(
            reviews, statistics.TRAINING_SEEDS, "qmix",
            required_methods=decision.LEARNED_METHODS,
        )
        self.assertFalse(summary["gating_review_complete"])
        self.assertIn(104, summary["methods"]["qmix"]["malformed_reviews"])


class ProtocolVersionTests(unittest.TestCase):
    """H: the two materially changed protocols are bumped once, now."""

    def test_the_changed_protocols_are_version_1_1(self):
        self.assertEqual(statistics.PROTOCOL_VERSION, "statistics-1.1")
        self.assertEqual(decision.PROTOCOL_VERSION, "go-no-go-1.1")

    def test_the_unchanged_protocols_remain_1_0(self):
        self.assertEqual(
            semantics.SPECIFICATION_VERSION, "primary-adaptive-semantics-1.0"
        )
        self.assertEqual(stages.PROTOCOL_VERSION, "campaign-stages-1.0")

    def test_the_version_appears_in_the_hashed_payload(self):
        self.assertIn("statistics-1.1", json.dumps(statistics.PROTOCOL))
        self.assertIn("go-no-go-1.1", decision.serialize())

    def test_the_decision_criteria_are_unchanged_by_the_bump(self):
        self.assertEqual(
            decision.DECIDING_COMPARISONS, ("delta_J_OFT", "delta_J_IDQN")
        )
        self.assertTrue(decision.GO_NO_GO["max_pressure_is_not_a_gate"])
        self.assertIn("No minimum percentage improvement is required",
                      decision.serialize())

    def test_a_freeze_binds_the_bumped_versions(self):
        artefact = freeze.build_freeze_artefact(
            "a", "b", "c", "d", {"plan": {}, "provenance": {}},
            {"plan": {}, "provenance": {}}, {},
        )
        self.assertEqual(
            artefact["statistical_protocol_version"], "statistics-1.1"
        )
        self.assertEqual(
            artefact["go_no_go_protocol_version"], "go-no-go-1.1"
        )


if __name__ == "__main__":
    unittest.main()
