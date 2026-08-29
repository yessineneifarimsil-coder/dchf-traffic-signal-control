"""Equivalence of the getter and subscription TraCI transports.

These run without SUMO against a fake that implements both transports over one
shared world, so a divergence can only come from the access layer itself. The
decisive end-to-end check is scripts/adaptive_qmix/ab_equivalence.py against a
real SUMO.
"""

from __future__ import absolute_import

import unittest

from .common import config_copy

from adaptive_qmix.coordination import VirtualDetectorTracker
from adaptive_qmix.ledger import VehicleLedger
from adaptive_qmix.logging import LANE_LOG_DECISION, LANE_LOG_FULL
from adaptive_qmix.observation import SymmetricObservationBuilder
from adaptive_qmix.reward import NetworkDelayReward, legacy_waiting_state
from adaptive_qmix.traci_access import (
    GETTER,
    SUBSCRIPTION,
    GetterDataSource,
    SubscriptionDataSource,
    TraciAccessError,
    create_data_source,
)


try:
    import traci.constants as REAL_CONSTANTS
except ImportError:  # pragma: no cover - exercised only without SUMO installed
    REAL_CONSTANTS = None


class _StubConstants(object):
    """Distinct stand-ins used when SUMO is not installed.

    The values only need to be distinct: a test that swapped two accessors
    would then read a different field and fail against the getter path.
    """

    VAR_SPEED = 901
    VAR_WAITING_TIME = 902
    VAR_LANE_ID = 903
    VAR_LANEPOSITION = 904
    LAST_STEP_VEHICLE_HALTING_NUMBER = 911
    LAST_STEP_VEHICLE_NUMBER = 912
    LAST_STEP_OCCUPANCY = 913
    LAST_STEP_MEAN_SPEED = 914
    LAST_STEP_VEHICLE_ID_LIST = 915


CONSTANTS = REAL_CONSTANTS or _StubConstants()


class FakeWorld(object):
    """One state of the simulated world, readable through both transports."""

    def __init__(self, lane_ids):
        self.vehicles = {}
        self.lanes = dict(
            (lane_id, {"halting": 0, "number": 0, "occupancy": 0.0,
                       "mean_speed": 0.0, "ids": ()})
            for lane_id in lane_ids
        )

    def add_vehicle(self, vehicle_id, speed, waiting, lane, position):
        self.vehicles[vehicle_id] = {
            "speed": speed, "waiting": waiting,
            "lane": lane, "position": position,
        }
        if lane in self.lanes:
            existing = self.lanes[lane]
            existing["ids"] = tuple(sorted(set(existing["ids"]) | {vehicle_id}))
            existing["number"] = len(existing["ids"])

    def set_lane(self, lane_id, **fields):
        self.lanes[lane_id].update(fields)


class _FakeVehicleApi(object):
    def __init__(self, world):
        self.world = world
        self.subscriptions = {}
        self.subscribe_calls = []

    def getIDList(self):
        return tuple(sorted(self.world.vehicles))

    def getSpeed(self, vehicle_id):
        return self.world.vehicles[vehicle_id]["speed"]

    def getWaitingTime(self, vehicle_id):
        return self.world.vehicles[vehicle_id]["waiting"]

    def getLaneID(self, vehicle_id):
        return self.world.vehicles[vehicle_id]["lane"]

    def getLanePosition(self, vehicle_id):
        return self.world.vehicles[vehicle_id]["position"]

    def subscribe(self, vehicle_id, variables):
        self.subscriptions[vehicle_id] = list(variables)
        self.subscribe_calls.append(vehicle_id)

    def getAllSubscriptionResults(self):
        # Mirrors SUMO: subscribing returns the object's current values at
        # once, so a vehicle subscribed this second is already visible.
        field = {
            CONSTANTS.VAR_SPEED: "speed",
            CONSTANTS.VAR_WAITING_TIME: "waiting",
            CONSTANTS.VAR_LANE_ID: "lane",
            CONSTANTS.VAR_LANEPOSITION: "position",
        }
        results = {}
        for vehicle_id, variables in self.subscriptions.items():
            if vehicle_id not in self.world.vehicles:
                continue
            results[vehicle_id] = dict(
                (variable, self.world.vehicles[vehicle_id][field[variable]])
                for variable in variables
            )
        return results


class _FakeLaneApi(object):
    def __init__(self, world):
        self.world = world
        self.subscriptions = {}

    def getIDList(self):
        return tuple(sorted(self.world.lanes))

    def getLastStepHaltingNumber(self, lane_id):
        return self.world.lanes[lane_id]["halting"]

    def getLastStepVehicleNumber(self, lane_id):
        return self.world.lanes[lane_id]["number"]

    def getLastStepOccupancy(self, lane_id):
        return self.world.lanes[lane_id]["occupancy"]

    def getLastStepMeanSpeed(self, lane_id):
        return self.world.lanes[lane_id]["mean_speed"]

    def getLastStepVehicleIDs(self, lane_id):
        return self.world.lanes[lane_id]["ids"]

    def getLength(self, lane_id):
        return 0.0

    def subscribe(self, lane_id, variables):
        self.subscriptions[lane_id] = list(variables)

    def getAllSubscriptionResults(self):
        field = {
            CONSTANTS.LAST_STEP_VEHICLE_HALTING_NUMBER: "halting",
            CONSTANTS.LAST_STEP_VEHICLE_NUMBER: "number",
            CONSTANTS.LAST_STEP_OCCUPANCY: "occupancy",
            CONSTANTS.LAST_STEP_MEAN_SPEED: "mean_speed",
            CONSTANTS.LAST_STEP_VEHICLE_ID_LIST: "ids",
        }
        return dict(
            (lane_id, dict(
                (variable, self.world.lanes[lane_id][field[variable]])
                for variable in variables
            ))
            for lane_id, variables in self.subscriptions.items()
        )


class FakeTraci(object):
    constants = CONSTANTS

    def __init__(self, world):
        self.world = world
        self.vehicle = _FakeVehicleApi(world)
        self.lane = _FakeLaneApi(world)


def build_world(config):
    lane_ids = sorted(config["observation"]["expected_lane_lengths_m"])
    world = FakeWorld(lane_ids)
    for index, lane_id in enumerate(lane_ids):
        world.set_lane(
            lane_id,
            halting=index,
            number=index + 1,
            occupancy=float(index) * 1.5,
            mean_speed=float(index) * 0.25 + 0.125,
        )
    world.add_vehicle("v_stopped", 0.05, 12.0, "E1_0", 240.5)
    world.add_vehicle("v_exact", 0.1, 3.0, "E1_1", 231.25)
    world.add_vehicle("v_moving", 8.75, 0.0, "E0_0", 100.0)
    return world, lane_ids


def prepared_sources(config):
    """A getter source and a subscription source over one identical world."""
    world, lane_ids = build_world(config)
    traci_module = FakeTraci(world)
    sources = []
    for mode in (GETTER, SUBSCRIPTION):
        source = create_data_source(traci_module, mode)
        source.begin_episode(lane_ids)
        source.note_departures(traci_module.vehicle.getIDList())
        source.refresh()
        sources.append(source)
    return world, lane_ids, traci_module, sources[0], sources[1]


class TransportMappingTests(unittest.TestCase):
    def setUp(self):
        self.config = config_copy()
        (self.world, self.lane_ids, self.traci,
         self.getter, self.subscription) = prepared_sources(self.config)

    def test_every_vehicle_quantity_matches(self):
        for vehicle_id in self.getter.vehicle_ids():
            for name in ("vehicle_speed", "vehicle_waiting_time",
                         "vehicle_lane_id", "vehicle_lane_position"):
                self.assertEqual(
                    getattr(self.getter, name)(vehicle_id),
                    getattr(self.subscription, name)(vehicle_id),
                    "{} differs for {}".format(name, vehicle_id),
                )

    def test_every_lane_quantity_matches(self):
        for lane_id in self.lane_ids:
            for name in ("lane_halting_number", "lane_vehicle_number",
                         "lane_occupancy", "lane_mean_speed",
                         "lane_vehicle_ids"):
                self.assertEqual(
                    getattr(self.getter, name)(lane_id),
                    getattr(self.subscription, name)(lane_id),
                    "{} differs for {}".format(name, lane_id),
                )

    def test_active_vehicle_list_matches(self):
        self.assertEqual(
            list(self.getter.vehicle_ids()), list(self.subscription.vehicle_ids())
        )

    def test_each_accessor_reads_its_own_variable(self):
        """Distinct world values mean a swapped accessor could not pass."""
        values = [
            self.subscription.vehicle_speed("v_stopped"),
            self.subscription.vehicle_waiting_time("v_stopped"),
            self.subscription.vehicle_lane_position("v_stopped"),
        ]
        self.assertEqual(len(set(values)), len(values))
        self.assertEqual(self.subscription.vehicle_lane_id("v_stopped"), "E1_0")


class SubscriptionTimingTests(unittest.TestCase):
    """Starts from an empty network, as reset() does at t = 0."""

    def setUp(self):
        self.config = config_copy()
        lane_ids = sorted(self.config["observation"]["expected_lane_lengths_m"])
        self.lane_ids = lane_ids
        self.world = FakeWorld(lane_ids)
        self.traci = FakeTraci(self.world)
        self.source = SubscriptionDataSource(self.traci)
        self.source.begin_episode(self.lane_ids)

    def test_vehicle_inserted_this_second_is_readable_this_second(self):
        """No missing departure-second contribution, and no healing needed."""
        self.world.add_vehicle("v_new", 0.0, 0.0, "E1_0", 5.0)
        self.source.note_departures(["v_new"])
        self.source.refresh()
        self.assertEqual(self.source.vehicle_speed("v_new"), 0.0)
        self.assertEqual(self.source.vehicle_lane_id("v_new"), "E1_0")
        self.assertIn("v_new", self.source.vehicle_ids())
        self.assertEqual(self.source.healed_subscriptions, 0)

    def test_healing_does_not_trigger_in_normal_operation(self):
        for index in range(4):
            name = "v_{}".format(index)
            self.world.add_vehicle(name, 5.0, 0.0, "E1_0", 10.0 * index)
            self.source.note_departures([name])
            self.source.refresh()
        self.assertEqual(self.source.healed_subscriptions, 0)

    def test_an_active_vehicle_without_a_subscription_is_healed(self):
        """Reachable if SUMO reinserts a vehicle without a departure event."""
        self.world.add_vehicle("v_orphan", 4.25, 1.0, "E1_1", 60.0)
        self.source.refresh()
        self.assertEqual(self.source.healed_subscriptions, 1)
        self.assertEqual(self.source.vehicle_speed("v_orphan"), 4.25)
        self.assertEqual(self.source.vehicle_waiting_time("v_orphan"), 1.0)

    def test_a_vehicle_whose_subscription_vanished_is_healed(self):
        """A teleported vehicle re-enters without a second departure event."""
        self.world.add_vehicle("v_tele", 3.0, 0.0, "E1_0", 50.0)
        self.source.note_departures(["v_tele"])
        self.source.refresh()
        self.assertEqual(self.source.healed_subscriptions, 0)
        del self.traci.vehicle.subscriptions["v_tele"]
        self.source.refresh()
        self.assertEqual(self.source.vehicle_speed("v_tele"), 3.0)
        self.assertEqual(self.source.healed_subscriptions, 1)

    def test_reading_a_vehicle_that_is_not_active_still_raises(self):
        """Healing must not mask a genuinely absent vehicle."""
        self.source.refresh()
        with self.assertRaises(TraciAccessError):
            self.source.vehicle_speed("never_existed")

    def test_note_departures_is_idempotent(self):
        self.world.add_vehicle("v_new", 1.0, 0.0, "E1_0", 5.0)
        self.source.note_departures(["v_new"])
        self.source.note_departures(["v_new"])
        self.assertEqual(self.traci.vehicle.subscribe_calls.count("v_new"), 1)

    def test_lane_view_is_available_before_the_first_step(self):
        """reset() builds the first observation before any simulation step."""
        self.assertEqual(
            self.source.lane_halting_number(self.lane_ids[3]),
            self.traci.lane.getLastStepHaltingNumber(self.lane_ids[3]),
        )


class EpisodeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.config = config_copy()
        self.world, self.lane_ids = build_world(self.config)
        self.traci = FakeTraci(self.world)
        self.source = SubscriptionDataSource(self.traci)

    def test_new_episode_clears_vehicle_subscription_state(self):
        self.source.begin_episode(self.lane_ids)
        self.source.note_departures(["v_stopped"])
        self.assertIn("v_stopped", self.source.subscribed_vehicles)
        self.source.begin_episode(self.lane_ids)
        self.assertEqual(self.source.subscribed_vehicles, set())

    def test_new_episode_resubscribes_every_lane(self):
        self.source.begin_episode(self.lane_ids)
        self.traci.lane.subscriptions = {}
        self.source.begin_episode(self.lane_ids)
        self.assertEqual(
            sorted(self.traci.lane.subscriptions), sorted(self.lane_ids)
        )

    def test_a_stale_vehicle_is_resubscribed_in_the_next_episode(self):
        self.source.begin_episode(self.lane_ids)
        self.source.note_departures(["v_stopped"])
        self.source.begin_episode(self.lane_ids)
        self.source.note_departures(["v_stopped"])
        self.assertEqual(
            self.traci.vehicle.subscribe_calls.count("v_stopped"), 2
        )


class ConsumerEquivalenceTests(unittest.TestCase):
    """The consuming code is identical; only the transport differs."""

    def setUp(self):
        self.config = config_copy()
        (self.world, self.lane_ids, self.traci,
         self.getter, self.subscription) = prepared_sources(self.config)

    def _ledger(self):
        return VehicleLedger([
            {"vehicle_id": "veh_{:04d}".format(index), "depart": 0}
            for index in range(2800)
        ])

    def test_reward_is_identical(self):
        rows = []
        for source in (self.getter, self.subscription):
            reward = NetworkDelayReward(source, self._ledger())
            reward.sample_second(10.0)
            block = reward.finish_block()
            rows.append((block["reward"], block["active_stopped_vehicle_seconds"],
                         block["pending_due_vehicle_seconds"]))
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0][1], 2, "v_stopped and v_exact are both halted")

    def test_legacy_waiting_state_is_identical(self):
        self.assertEqual(
            legacy_waiting_state(self.getter), legacy_waiting_state(self.subscription)
        )

    def test_observation_vector_and_state_are_identical(self):
        outputs = []
        for source in (self.getter, self.subscription):
            builder = SymmetricObservationBuilder(self.traci, self.config, source)
            builder.reset_history()
            for _ in range(3):
                builder.update_arrivals_one_second()
            observations, state, rows = builder.build(
                {"J1": "H", "J2": "V"}, {"J1": 17, "J2": 2}
            )
            outputs.append((observations.tolist(), state.tolist(), rows))
        self.assertEqual(outputs[0][0], outputs[1][0])
        self.assertEqual(outputs[0][1], outputs[1][1])
        self.assertEqual(outputs[0][2], outputs[1][2])

    def test_arrival_window_is_identical(self):
        windows = []
        for source in (self.getter, self.subscription):
            builder = SymmetricObservationBuilder(self.traci, self.config, source)
            builder.reset_history()
            for _ in range(5):
                builder.update_arrivals_one_second()
            windows.append(dict(
                ("{}_{}".format(key[0], key[1]), list(value))
                for key, value in builder.arrival_counts.items()
            ))
        self.assertEqual(windows[0], windows[1])

    def test_detector_events_are_identical(self):
        events = []
        for source in (self.getter, self.subscription):
            detector = VirtualDetectorTracker(source, ["E1_0", "E1_1"], 229.2)
            first = detector.sample(1.0, "H", "H")
            second = detector.sample(2.0, "H", "H")
            events.append((first, second))
        self.assertEqual(events[0], events[1])
        self.assertTrue(
            any(item["event"] == "GAD50" for item in events[0][0]),
            "the fixture places vehicles beyond the 229.2 m detector",
        )


class LaneLogCadenceTests(unittest.TestCase):
    """Cadence is an evidence setting; it must not touch control."""

    def _environment(self, mode):
        from adaptive_qmix.environment import AdaptiveTrafficEnvironment
        environment = AdaptiveTrafficEnvironment.__new__(AdaptiveTrafficEnvironment)
        environment.config = config_copy()
        environment.lane_state_logging = mode
        return environment

    def test_full_cadence_logs_every_second(self):
        environment = self._environment(LANE_LOG_FULL)
        self.assertTrue(all(
            environment._lane_log_due(offset) for offset in range(5)
        ))

    def test_decision_cadence_logs_the_last_second_of_each_block(self):
        environment = self._environment(LANE_LOG_DECISION)
        due = [offset for offset in range(5) if environment._lane_log_due(offset)]
        self.assertEqual(due, [4])

    def test_decision_timestamps_are_a_strict_subset_of_full_timestamps(self):
        full = self._environment(LANE_LOG_FULL)
        decision = self._environment(LANE_LOG_DECISION)
        full_times, decision_times = [], []
        time_value = 0
        for _block in range(40):
            for offset in range(5):
                time_value += 1
                if full._lane_log_due(offset):
                    full_times.append(time_value)
                if decision._lane_log_due(offset):
                    decision_times.append(time_value)
        self.assertTrue(set(decision_times).issubset(set(full_times)))
        self.assertLess(len(decision_times), len(full_times))
        self.assertEqual(len(full_times), 5 * len(decision_times))
        # Every retained timestamp is a decision boundary, which is the instant
        # the next observation is built.
        self.assertTrue(all(value % 5 == 0 for value in decision_times))

    def test_unknown_modes_are_rejected(self):
        from adaptive_qmix.environment import AdaptiveTrafficEnvironment
        with self.assertRaises(ValueError):
            AdaptiveTrafficEnvironment(
                None, config_copy(), ".", "m.csv", "m.rou.xml", "t.xml", 1,
                lane_state_logging="off",
            )
        with self.assertRaises(ValueError):
            AdaptiveTrafficEnvironment(
                None, config_copy(), ".", "m.csv", "m.rou.xml", "t.xml", 1,
                traci_access_mode="magic",
            )


class ProvenanceRecordingTests(unittest.TestCase):
    def test_manifest_records_transport_and_cadence(self):
        from .common import REPOSITORY_ROOT
        from adaptive_qmix.provenance import build_run_manifest
        config = config_copy()
        manifest = build_run_manifest(
            REPOSITORY_ROOT, config,
            config["_config_path"], None, "qmix", 101, 101, "cpu",
            "development", SUBSCRIPTION, LANE_LOG_DECISION,
        )
        self.assertEqual(manifest["traci_access_mode"], SUBSCRIPTION)
        self.assertEqual(manifest["lane_state_logging"], LANE_LOG_DECISION)


if __name__ == "__main__":
    unittest.main()
