from __future__ import absolute_import

import collections
import unittest

import numpy as np

from .common import config_copy

from adaptive_qmix.rng import IndependentEpsilonStreams, namespace_manifest, numpy_rng
from adaptive_qmix.traffic import generate_manifest_records


class TrafficAndRngTests(unittest.TestCase):
    def test_conditioned_multinomial_manifest_has_exact_counts_and_range(self):
        config = config_copy()
        records = generate_manifest_records(config, "training", 101, 0)
        counts = collections.Counter(row["stream"] for row in records)
        self.assertEqual(len(records), 2800)
        self.assertEqual(counts["WE"], 900)
        self.assertEqual(counts["EW"], 700)
        for name in ("N1S1", "S1N1", "N2S2", "S2N2"):
            self.assertEqual(counts[name], 300)
        self.assertTrue(all(0 <= row["depart"] <= 3599 for row in records))
        # Sampling is with replacement; simultaneous integer-second departures are legal.
        seconds = [row["depart"] for row in records]
        self.assertLess(len(set(seconds)), len(seconds))

    def test_tie_order_and_generation_are_deterministic(self):
        config = config_copy()
        first = generate_manifest_records(config, "training", 101, 4)
        second = generate_manifest_records(config, "training", 101, 4)
        self.assertEqual(first, second)
        ordered_keys = [
            (row["depart"], row["stream_rank"], row["within_stream_rank"])
            for row in first
        ]
        self.assertEqual(ordered_keys, sorted(ordered_keys))

    def test_manifest_families_and_seed_values_are_disjoint(self):
        config = config_copy()
        training = generate_manifest_records(config, "training", 101, 0)
        validation = generate_manifest_records(config, "learner_validation", 101, 0)
        other_seed = generate_manifest_records(config, "training", 102, 0)
        self.assertNotEqual(
            [row["depart"] for row in training],
            [row["depart"] for row in validation],
        )
        self.assertNotEqual(
            [row["depart"] for row in training],
            [row["depart"] for row in other_seed],
        )

    def test_epsilon_streams_are_agent_independent_and_consumption_stable(self):
        first = IndependentEpsilonStreams(101)
        second = IndependentEpsilonStreams(101)
        sequence_first = [first.select([0, 1], epsilon) for epsilon in (1.0, 0.0, 0.5)]
        sequence_second = [second.select([1, 0], epsilon) for epsilon in (1.0, 0.0, 0.5)]
        diagnostics_first = [item[1] for item in sequence_first]
        diagnostics_second = [item[1] for item in sequence_second]
        self.assertEqual(diagnostics_first, diagnostics_second)
        self.assertNotEqual(
            diagnostics_first[0][0]["threshold"],
            diagnostics_first[0][1]["threshold"],
        )

    def test_replay_rng_does_not_consume_traffic_rng(self):
        traffic_a = numpy_rng(101, "traffic_manifest")
        replay = numpy_rng(101, "replay_sampling")
        expected = traffic_a.integers(0, 100000, size=10).tolist()
        replay.integers(0, 100000, size=1000)
        traffic_b = numpy_rng(101, "traffic_manifest")
        self.assertEqual(expected, traffic_b.integers(0, 100000, size=10).tolist())
        self.assertIn("sumo_episode", namespace_manifest(101))


if __name__ == "__main__":
    unittest.main()

