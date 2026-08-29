"""The subscription-healing counter must reach the run outputs.

The counter is engineering metadata: it records how many active vehicles
needed their TraCI subscription re-established, is normally zero, and never
influences reward, observations, actions, termination, RNG or metrics. It is
only useful if it is persisted, so these tests check that it survives into the
episode summary and the written CSV rather than living in memory.
"""

from __future__ import absolute_import

import csv
import os
import shutil
import tempfile
import unittest

from .common import REPOSITORY_ROOT, config_copy

from adaptive_qmix.environment import AdaptiveTrafficEnvironment
from adaptive_qmix.ledger import VehicleLedger
from adaptive_qmix.logging import SCHEMAS, RunLogger
from adaptive_qmix.traci_access import GetterDataSource, SubscriptionDataSource

from .test_traci_access import FakeTraci, FakeWorld, build_world


DIAGNOSTIC_FIELD = "transport_healed_subscriptions"


class _StubSimulation(object):
    def getTime(self):
        return 3765.0

    def getMinExpectedNumber(self):
        return 0


class _StubVehicles(object):
    def getIDList(self):
        return ()


class _StubTraci(object):
    def __init__(self):
        self.simulation = _StubSimulation()
        self.vehicle = _StubVehicles()


def cleared_environment(source):
    """A minimal environment able to produce a CLEARED episode summary."""
    environment = AdaptiveTrafficEnvironment.__new__(AdaptiveTrafficEnvironment)
    environment.traci = _StubTraci()
    environment.config = config_copy()
    environment.source = source
    environment.episode_index = 0
    environment.network_reward_total = -1234.0
    environment.active_stopped_total = 1000
    environment.pending_due_total = 234
    environment.legacy_waiting_integral = 900.0
    environment.legacy_waiting_samples = 3600
    ledger = VehicleLedger([
        {"vehicle_id": "veh_{:04d}".format(index), "depart": 0}
        for index in range(2800)
    ])
    for vehicle_id in ledger.scheduled:
        ledger.inserted_at[vehicle_id] = 0.0
        ledger.completed_at[vehicle_id] = 10.0
    environment.ledger = ledger
    return environment


class SchemaTests(unittest.TestCase):
    def test_episode_summary_schema_carries_the_diagnostic(self):
        self.assertIn(DIAGNOSTIC_FIELD, SCHEMAS["episode_summary"])


class EpisodeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.config = config_copy()
        self.lane_ids = sorted(
            self.config["observation"]["expected_lane_lengths_m"]
        )

    def _subscription_source(self):
        world = FakeWorld(self.lane_ids)
        traci_module = FakeTraci(world)
        source = SubscriptionDataSource(traci_module)
        source.begin_episode(self.lane_ids)
        return world, traci_module, source

    def test_a_normal_subscription_run_reports_zero(self):
        world, _traci, source = self._subscription_source()
        for index in range(4):
            name = "v_{}".format(index)
            world.add_vehicle(name, 5.0, 0.0, "E1_0", 10.0 * index)
            source.note_departures([name])
            source.refresh()
        summary = cleared_environment(source).episode_summary("CLEARED")
        self.assertEqual(summary[DIAGNOSTIC_FIELD], 0)

    def test_a_healed_subscription_reports_a_positive_count(self):
        world, traci_module, source = self._subscription_source()
        world.add_vehicle("v_tele", 3.0, 0.0, "E1_0", 50.0)
        source.note_departures(["v_tele"])
        source.refresh()
        del traci_module.vehicle.subscriptions["v_tele"]
        source.refresh()
        summary = cleared_environment(source).episode_summary("CLEARED")
        self.assertEqual(summary[DIAGNOSTIC_FIELD], 1)

    def test_getter_mode_reports_zero(self):
        world, lane_ids = build_world(self.config)
        source = GetterDataSource(FakeTraci(world))
        source.begin_episode(lane_ids)
        source.refresh()
        summary = cleared_environment(source).episode_summary("CLEARED")
        self.assertEqual(summary[DIAGNOSTIC_FIELD], 0)

    def test_a_new_episode_resets_the_counter(self):
        world, traci_module, source = self._subscription_source()
        world.add_vehicle("v_tele", 3.0, 0.0, "E1_0", 50.0)
        source.note_departures(["v_tele"])
        source.refresh()
        del traci_module.vehicle.subscriptions["v_tele"]
        source.refresh()
        self.assertEqual(source.healed_subscriptions, 1)
        source.begin_episode(self.lane_ids)
        self.assertEqual(source.healed_subscriptions, 0)


class PersistenceTests(unittest.TestCase):
    """The value must reach disk, not merely the in-memory summary."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = config_copy()
        self.lane_ids = sorted(
            self.config["observation"]["expected_lane_lengths_m"]
        )

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _written_summary_row(self, source):
        summary = cleared_environment(source).episode_summary("CLEARED")
        logger = RunLogger(self.directory, {"schema_version": "1.3a"})
        try:
            logger.write("episode_summary", summary)
            logger.flush()
        finally:
            logger.close()
        path = os.path.join(self.directory, "episode_summary.csv")
        with open(path, "r") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_healed_count_round_trips_through_the_csv(self):
        world = FakeWorld(self.lane_ids)
        traci_module = FakeTraci(world)
        source = SubscriptionDataSource(traci_module)
        source.begin_episode(self.lane_ids)
        world.add_vehicle("v_tele", 3.0, 0.0, "E1_0", 50.0)
        source.note_departures(["v_tele"])
        source.refresh()
        del traci_module.vehicle.subscriptions["v_tele"]
        source.refresh()
        row = self._written_summary_row(source)
        self.assertEqual(row[DIAGNOSTIC_FIELD], "1")

    def test_zero_is_written_explicitly_rather_than_omitted(self):
        world = FakeWorld(self.lane_ids)
        source = SubscriptionDataSource(FakeTraci(world))
        source.begin_episode(self.lane_ids)
        source.refresh()
        row = self._written_summary_row(source)
        self.assertEqual(row[DIAGNOSTIC_FIELD], "0")


class AbHarnessDiagnosticTests(unittest.TestCase):
    """A healed subscription must not by itself fail the A/B comparison."""

    @staticmethod
    def _harness():
        # importlib.util works on Python 3.7 through current releases; imp is
        # deprecated on 3.7 and gone from 3.12.
        import importlib.util
        path = os.path.join(
            REPOSITORY_ROOT, "scripts", "adaptive_qmix", "ab_equivalence.py"
        )
        spec = importlib.util.spec_from_file_location(
            "ab_equivalence_under_test", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_diagnostics_are_excluded_from_the_scientific_comparison(self):
        harness = self._harness()
        self.assertIn(DIAGNOSTIC_FIELD, harness.TRANSPORT_DIAGNOSTIC_FIELDS)
        getter = {"completed": 2800, DIAGNOSTIC_FIELD: 0}
        subscription = {"completed": 2800, DIAGNOSTIC_FIELD: 3}
        self.assertEqual(
            harness.scientific_only(getter),
            harness.scientific_only(subscription),
            "a healing difference alone must not fail the comparison",
        )
        self.assertNotIn(DIAGNOSTIC_FIELD, harness.scientific_only(subscription))

    def test_a_real_scientific_difference_still_fails(self):
        harness = self._harness()
        getter = {"completed": 2800, DIAGNOSTIC_FIELD: 0}
        subscription = {"completed": 2799, DIAGNOSTIC_FIELD: 0}
        self.assertNotEqual(
            harness.scientific_only(getter), harness.scientific_only(subscription)
        )


if __name__ == "__main__":
    unittest.main()
