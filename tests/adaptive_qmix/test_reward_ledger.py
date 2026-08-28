from __future__ import absolute_import

import unittest

from .common import ledger_records

from adaptive_qmix.ledger import LedgerError, VehicleLedger, reconcile_scheduled_outcomes
from adaptive_qmix.reward import NetworkDelayReward, is_stopped


class FakeVehicleAPI(object):
    def __init__(self, speeds):
        self.speeds = speeds

    def getIDList(self):
        return list(self.speeds)

    def getSpeed(self, vehicle_id):
        return self.speeds[vehicle_id]


class FakeTraci(object):
    def __init__(self, speeds):
        self.vehicle = FakeVehicleAPI(speeds)


class RewardAndLedgerTests(unittest.TestCase):
    def test_stopped_threshold_is_inclusive(self):
        self.assertTrue(is_stopped(0.0))
        self.assertTrue(is_stopped(0.1))
        self.assertFalse(is_stopped(0.1000001))

    def test_reward_includes_only_due_pending_and_active_stopped(self):
        records = ledger_records(depart=10)
        records[0]["depart"] = 20
        ledger = VehicleLedger(records)
        ledger.mark_departed([records[1]["vehicle_id"]], 10)
        traci = FakeTraci({records[1]["vehicle_id"]: 0.1})
        reward = NetworkDelayReward(traci, ledger)
        row = reward.sample_second(10)
        # vehicle 0 is future; vehicle 1 is inserted; remaining 2798 are due pending.
        self.assertEqual(row["stopped_active_count"], 1)
        self.assertEqual(row["pending_due_count"], 2798)
        self.assertEqual(reward.finish_block()["reward"], -2799.0)

    def test_medium_no_buffer_reduces_to_active_stopped_delay(self):
        records = ledger_records(depart=0)
        ledger = VehicleLedger(records)
        ids = [record["vehicle_id"] for record in records]
        ledger.mark_departed(ids, 0)
        traci = FakeTraci({ids[0]: 0.1, ids[1]: 0.2})
        reward = NetworkDelayReward(traci, ledger)
        row = reward.sample_second(1)
        self.assertEqual(row["pending_due_count"], 0)
        self.assertEqual(row["incremental_delay_vehicle_seconds"], 1)

    def test_clearance_requires_sumo_empty_and_all_ids_accounted(self):
        records = ledger_records(depart=0)
        ledger = VehicleLedger(records)
        for record in records:
            ledger.mark_exceptional(record["vehicle_id"], "TEST", 3600)
        self.assertFalse(ledger.is_reconciled_clear(3600, ["vehicle_0000"], 0))
        self.assertFalse(ledger.is_reconciled_clear(3600, [], 1))
        self.assertTrue(ledger.is_reconciled_clear(3600, [], 0))
        self.assertTrue(reconcile_scheduled_outcomes(ledger)["valid"])

    def test_disappearing_inserted_vehicle_is_fatal(self):
        records = ledger_records(depart=0)
        ledger = VehicleLedger(records)
        ledger.mark_departed([records[0]["vehicle_id"]], 0)
        with self.assertRaises(LedgerError):
            ledger.assert_active_consistency([])


if __name__ == "__main__":
    unittest.main()

