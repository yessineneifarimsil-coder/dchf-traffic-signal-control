from __future__ import absolute_import

import unittest

from .common import ledger_records

from adaptive_qmix.ledger import VehicleLedger
from adaptive_qmix.metrics import MetricReconciliationError, legacy_metric, scheduled_demand_metrics


class MetricTests(unittest.TestCase):
    def test_primary_is_mean_waiting_plus_depart_delay_over_2800(self):
        records = ledger_records(depart=0)
        ledger = VehicleLedger(records)
        rows = {}
        for record in records:
            vehicle_id = record["vehicle_id"]
            ledger.mark_departed([vehicle_id], 2)
            ledger.mark_arrived([vehicle_id], 12)
            rows[vehicle_id] = {
                "waitingTime": 3.0,
                "departDelay": 2.0,
                "timeLoss": 4.0,
                "duration": 10.0,
                "waitingCount": 1.0,
            }
        metrics = scheduled_demand_metrics(ledger, rows, "CLEARED")
        self.assertTrue(metrics["J_primary_valid"])
        self.assertEqual(metrics["J_primary_mean_scheduled_waiting_burden_s"], 5.0)
        self.assertEqual(
            metrics["J_primary_total_scheduled_waiting_burden_vehicle_s"],
            14000.0,
        )

    def test_clearance_failure_is_not_silently_an_ordinary_primary_value(self):
        ledger = VehicleLedger(ledger_records(depart=0))
        metrics = scheduled_demand_metrics(ledger, {}, "CLEARANCE_FAILURE")
        self.assertFalse(metrics["J_primary_valid"])
        self.assertNotEqual(
            metrics["J_primary_mean_scheduled_waiting_burden_s"],
            metrics["J_primary_mean_scheduled_waiting_burden_s"],
        )

    def test_cleared_run_missing_trip_is_fatal(self):
        ledger = VehicleLedger(ledger_records(depart=0))
        for vehicle_id in ledger.scheduled:
            ledger.inserted_at[vehicle_id] = 0.0
            ledger.completed_at[vehicle_id] = 1.0
        with self.assertRaises(MetricReconciliationError):
            scheduled_demand_metrics(ledger, {}, "CLEARED")

    def test_legacy_metric_is_separate_time_average(self):
        self.assertEqual(legacy_metric(120.0, 4), 30.0)


if __name__ == "__main__":
    unittest.main()

