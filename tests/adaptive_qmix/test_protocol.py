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
    behaviour, decision, freeze, semantics, stages, statistics,
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
            validity_passed=True, behaviour_review_recorded=True,
        )
        self.assertEqual(verdict["verdict"], "GO")
        self.assertEqual(verdict["reasons"], [])

    def test_one_interval_touching_zero_is_no_go(self):
        verdict = decision.evaluate_go_no_go(
            {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, 0.2)},
            validity_passed=True, behaviour_review_recorded=True,
        )
        self.assertEqual(verdict["verdict"], "NO-GO")
        self.assertIn("delta_J_IDQN", verdict["reasons"][0])

    def test_a_losing_max_pressure_comparison_does_not_block_go(self):
        verdict = decision.evaluate_go_no_go(
            {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5),
             "delta_J_MP": (2.0, 8.0)},
            validity_passed=True, behaviour_review_recorded=True,
        )
        self.assertEqual(verdict["verdict"], "GO")
        self.assertIn("delta_J_MP", verdict["reported_only"])

    def test_failed_validity_or_missing_behaviour_review_is_no_go(self):
        intervals = {"delta_J_OFT": (-5.0, -1.0), "delta_J_IDQN": (-4.0, -0.5)}
        self.assertEqual(
            decision.evaluate_go_no_go(intervals, False, True)["verdict"],
            "NO-GO",
        )
        self.assertEqual(
            decision.evaluate_go_no_go(intervals, True, False)["verdict"],
            "NO-GO",
        )

    def test_a_missing_deciding_comparison_cannot_be_decided(self):
        with self.assertRaises(decision.DecisionProtocolError):
            decision.evaluate_go_no_go(
                {"delta_J_OFT": (-5.0, -1.0)}, True, True
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
        records = [
            {"transition_index": 200000, "mean_J_primary_s": 10.0,
             "mean_time_loss_s": 5.0, "seeds": statistics.LEARNER_VALIDATION_SEEDS},
            {"transition_index": 100000, "mean_J_primary_s": 9.0,
             "mean_time_loss_s": 7.0, "seeds": statistics.LEARNER_VALIDATION_SEEDS},
        ]
        chosen = statistics.select_checkpoint(records)
        self.assertEqual(chosen["transition_index"], 100000)

    def test_time_loss_breaks_a_j_primary_tie(self):
        records = [
            {"transition_index": 100000, "mean_J_primary_s": 9.0,
             "mean_time_loss_s": 7.0, "seeds": statistics.LEARNER_VALIDATION_SEEDS},
            {"transition_index": 200000, "mean_J_primary_s": 9.0,
             "mean_time_loss_s": 6.0, "seeds": statistics.LEARNER_VALIDATION_SEEDS},
        ]
        self.assertEqual(
            statistics.select_checkpoint(records)["transition_index"], 200000
        )

    def test_the_earliest_checkpoint_wins_a_full_tie(self):
        records = [
            {"transition_index": 350000, "mean_J_primary_s": 9.0,
             "mean_time_loss_s": 6.0, "seeds": statistics.LEARNER_VALIDATION_SEEDS},
            {"transition_index": 75000, "mean_J_primary_s": 9.0,
             "mean_time_loss_s": 6.0, "seeds": statistics.LEARNER_VALIDATION_SEEDS},
        ]
        self.assertEqual(
            statistics.select_checkpoint(records)["transition_index"], 75000
        )

    def test_a_checkpoint_may_not_be_selected_on_final_test(self):
        records = [{
            "transition_index": 100000, "mean_J_primary_s": 9.0,
            "mean_time_loss_s": 7.0, "family": "final_test",
            "seeds": statistics.LEARNER_VALIDATION_SEEDS,
        }]
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.select_checkpoint(records)
        self.assertIn("choosing the answer", str(caught.exception))

    def test_checkpoint_selection_requires_the_exact_validation_seeds(self):
        records = [{
            "transition_index": 100000, "mean_J_primary_s": 9.0,
            "mean_time_loss_s": 7.0, "seeds": (2201, 2202, 2203),
        }]
        with self.assertRaises(statistics.StatisticsError):
            statistics.select_checkpoint(records)

    def test_an_unlisted_checkpoint_is_refused(self):
        records = [{
            "transition_index": 123456, "mean_J_primary_s": 9.0,
            "mean_time_loss_s": 7.0, "seeds": statistics.LEARNER_VALIDATION_SEEDS,
        }]
        with self.assertRaises(statistics.StatisticsError):
            statistics.select_checkpoint(records)

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
        result = statistics.hierarchical_paired_bootstrap(
            treatment, comparator, replicates=500
        )
        self.assertAlmostEqual(result["observed_mean_difference"], -4.0, 6)
        self.assertTrue(result["entirely_below_zero"])
        self.assertLess(result["ci_high"], 0.0)
        self.assertEqual(result["training_seed_count"], 10)
        self.assertEqual(result["evaluation_seed_count"], 10)

    def test_the_bootstrap_does_not_separate_identical_panels(self):
        panel = self._panel(10.0)
        result = statistics.hierarchical_paired_bootstrap(
            panel, panel, replicates=500
        )
        self.assertAlmostEqual(result["observed_mean_difference"], 0.0, 9)
        self.assertFalse(result["entirely_below_zero"])

    def test_unpaired_panels_are_refused(self):
        treatment = self._panel(10.0)
        comparator = self._panel(12.0, seeds=tuple(range(201, 211)))
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.hierarchical_paired_bootstrap(treatment, comparator)
        self.assertIn("Unpaired training seeds", str(caught.exception))

    def test_mismatched_evaluation_seeds_are_refused(self):
        treatment = self._panel(10.0)
        comparator = self._panel(12.0, episodes=tuple(range(3001, 3009)))
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.hierarchical_paired_bootstrap(treatment, comparator)
        self.assertIn("Unpaired evaluation seeds", str(caught.exception))

    def test_a_non_finite_metric_never_reaches_the_bootstrap(self):
        treatment = self._panel(10.0)
        comparator = self._panel(12.0)
        comparator[101][3001] = float("nan")
        with self.assertRaises(statistics.StatisticsError) as caught:
            statistics.hierarchical_paired_bootstrap(treatment, comparator)
        self.assertIn("excluded by the validity gates", str(caught.exception))

    def test_the_bootstrap_is_deterministic(self):
        treatment = self._panel(10.0)
        comparator = self._panel(11.0)
        first = statistics.hierarchical_paired_bootstrap(
            treatment, comparator, replicates=200
        )
        second = statistics.hierarchical_paired_bootstrap(
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
            stages.write_stage_artefact(
                self.directory, stage, {"step": index}
            )
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

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

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

    @staticmethod
    def _checkpoints():
        return dict(
            (method, {
                "training_seed": 101, "transition_index": 250000,
                "checkpoint_sha256": "a" * 64,
                "selected_on_family": "learner_validation",
            })
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
        checkpoints["qmix"]["checkpoint_sha256"] = ""
        artefact = freeze.build_freeze_artefact(
            "adaptive-sha", "baseline-sha", "network-sha", "network-blob",
            self._plan_entry(45), self._plan_entry(20), checkpoints,
        )
        with self.assertRaises(freeze.FreezeError):
            freeze.assert_freeze_complete(artefact)

    def test_a_checkpoint_selected_on_final_test_blocks_the_freeze(self):
        checkpoints = self._checkpoints()
        checkpoints["qmix"]["selected_on_family"] = "final_test"
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


if __name__ == "__main__":
    unittest.main()
