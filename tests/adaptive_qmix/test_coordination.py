from __future__ import absolute_import

import math
import unittest

from adaptive_qmix.coordination import (
    green_at_approach_detector,
    green_start_lag_distribution,
    phase_cross_correlation,
    projected_aog_percentage,
    projected_stop_line_arrival_events,
)


class CoordinationTests(unittest.TestCase):
    def test_gad50_and_projected_aog_are_distinct(self):
        events = [
            {"vehicle_id": "a", "event": "GAD50", "time": 0.0, "signal_state": "H"},
            {"vehicle_id": "b", "event": "GAD50", "time": 10.0, "signal_state": "V"},
        ]
        intervals = [
            {"start": 0.0, "end": 3.0, "phase": "H"},
            {"start": 3.0, "end": 20.0, "phase": "V"},
        ]
        self.assertEqual(green_at_approach_detector(events), 50.0)
        projected = projected_stop_line_arrival_events(events, intervals)
        self.assertTrue(all(row["is_proxy"] for row in projected))
        self.assertEqual(projected_aog_percentage(projected), 0.0)

    def test_green_start_lags_save_complete_distribution_and_censoring(self):
        rows = green_start_lag_distribution([0, 100, 300], [20, 250], 120)
        self.assertEqual(rows[0]["lag_s"], 20.0)
        self.assertTrue(rows[1]["censored"])
        self.assertTrue(rows[2]["censored"])
        self.assertEqual(len(rows), 3)

    def test_cross_correlation_positive_lag_means_j2_follows_j1(self):
        j1 = [0, 1, 1, 0, 0, 1, 1, 0]
        j2 = [0, 0, 1, 1, 0, 0, 1, 1]
        result = phase_cross_correlation(j1, j2, max_lag_s=2)
        self.assertEqual(result["dominant"]["lag_s"], 1)
        self.assertEqual(len(result["distribution"]), 5)


if __name__ == "__main__":
    unittest.main()

