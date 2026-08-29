from __future__ import absolute_import

import unittest

import numpy as np

from .common import config_copy

from adaptive_qmix.observation import NetworkSchemaError, SymmetricObservationBuilder
from adaptive_qmix.replay import JointReplayBuffer
from adaptive_qmix.traci_access import GetterDataSource


class FakeLaneAPI(object):
    def __init__(self, config):
        self.lengths = dict(config["observation"]["expected_lane_lengths_m"])
        self.vehicles = {lane_id: [] for lane_id in self.lengths}
        self.queues = {lane_id: 0 for lane_id in self.lengths}
        self.occupancy = {lane_id: 0.0 for lane_id in self.lengths}

    def getIDList(self):
        return list(self.lengths)

    def getLength(self, lane_id):
        return self.lengths[lane_id]

    def getLastStepVehicleIDs(self, lane_id):
        return self.vehicles[lane_id]

    def getLastStepHaltingNumber(self, lane_id):
        return self.queues[lane_id]

    def getLastStepOccupancy(self, lane_id):
        return self.occupancy[lane_id]


class FakeVehicleTypeAPI(object):
    def getLength(self, _vehicle_type):
        return 5.0

    def getMinGap(self, _vehicle_type):
        return 2.5


class FakeTraci(object):
    def __init__(self, config):
        self.lane = FakeLaneAPI(config)
        self.vehicletype = FakeVehicleTypeAPI()


class ObservationAndReplayTests(unittest.TestCase):
    def test_symmetric_observation_exact_features(self):
        config = config_copy()
        traci = FakeTraci(config)
        builder = SymmetricObservationBuilder(traci, config, GetterDataSource(traci))
        builder.validate_runtime_schema()
        j1 = config["observation"]["lanes"]["J1"]
        for lane_id in j1["H_in"]:
            traci.lane.queues[lane_id] = 3
        for lane_id in j1["V_in"]:
            traci.lane.queues[lane_id] = 2
        traci.lane.occupancy[j1["H_out"][0]] = 80.0
        traci.lane.occupancy[j1["V_out"][0]] = 25.0
        builder.update_arrivals_one_second()
        observations, state, rows = builder.build(
            {"J1": "H", "J2": "V"}, {"J1": 60, "J2": 2}
        )
        self.assertEqual(observations.shape, (2, 8))
        self.assertEqual(state.shape, (16,))
        self.assertAlmostEqual(observations[0, 0], 12.0 / 150.0)
        self.assertAlmostEqual(observations[0, 1], 8.0 / 100.0)
        self.assertEqual(observations[0, 2], 1.0)
        self.assertAlmostEqual(observations[0, 3], 0.5)
        self.assertAlmostEqual(observations[0, 6], 0.8)
        self.assertAlmostEqual(observations[0, 7], 0.25)
        self.assertEqual(rows[0]["intersection"], "J1")

    def test_changed_lane_length_is_fatal(self):
        config = config_copy()
        traci = FakeTraci(config)
        first_lane = next(iter(traci.lane.lengths))
        traci.lane.lengths[first_lane] += 1.0
        with self.assertRaises(NetworkSchemaError):
            SymmetricObservationBuilder(
                traci, config, GetterDataSource(traci)
            ).validate_runtime_schema()

    def test_replay_keeps_elapsed_and_truncation_separate_from_terminal(self):
        replay = JointReplayBuffer(capacity=4)
        replay.push(
            np.zeros(16), np.zeros((2, 8)), [0, 1], -1.0,
            np.ones(16), np.ones((2, 8)), False, 8.0,
            budget_truncated=True, timeout_truncated=False,
        )
        sample = replay.sample(1, np.random.default_rng(1))
        self.assertFalse(bool(sample["terminated"][0]))
        self.assertTrue(bool(sample["budget_truncated"][0]))
        self.assertEqual(float(sample["elapsed_seconds"][0]), 8.0)

    def test_invalid_failure_transition_cannot_enter_replay(self):
        replay = JointReplayBuffer(capacity=4)
        with self.assertRaises(ValueError):
            replay.push(
                np.zeros(16), np.zeros((2, 8)), [0, 1], -1.0,
                np.ones(16), np.ones((2, 8)), False, 5.0,
                failure_truncated=True,
            )


if __name__ == "__main__":
    unittest.main()
