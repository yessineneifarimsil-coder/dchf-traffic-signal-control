from __future__ import absolute_import

import hashlib
import math
import os
import unittest
import xml.etree.ElementTree as ET

from .common import REPOSITORY_ROOT, config_copy

from adaptive_qmix.config import ContractError, ScientificRunBlocked, require_scientific_run_allowed, validate_config
from adaptive_qmix.signal_executor import UnsupportedAsynchronousSemantics, validate_synchronous_executor_config


class ConfigAndNetworkTests(unittest.TestCase):
    def test_official_training_is_blocked_by_provisional_yellow(self):
        config = config_copy()
        with self.assertRaises(ScientificRunBlocked):
            require_scientific_run_allowed(config)

    def test_asynchronous_three_plus_five_is_rejected(self):
        config = config_copy()
        executor = config["executor"]
        executor["switch_new_green_s"] = 5
        executor["switch_duration_s"] = 8
        with self.assertRaises(UnsupportedAsynchronousSemantics):
            validate_synchronous_executor_config(executor)
        with self.assertRaises(ContractError):
            validate_config(config)

    def test_budget_and_update_count_are_exact(self):
        training = config_copy()["training"]
        self.assertEqual(training["interaction_budget"], 360000)
        self.assertEqual(training["replay_warmup"], 5000)
        self.assertEqual(
            training["interaction_budget"] - training["replay_warmup"],
            training["learner_events"],
        )
        self.assertEqual(training["learner_events"], 355000)

    def test_network_hash_lane_ids_lengths_and_storage_normalizers(self):
        config = config_copy()
        network_path = os.path.join(REPOSITORY_ROOT, config["network"]["path"])
        with open(network_path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(digest, config["network"]["sha256"])

        root = ET.parse(network_path).getroot()
        actual = {
            lane.attrib["id"]: float(lane.attrib["length"])
            for lane in root.iter("lane") if "id" in lane.attrib
        }
        for lane_id, expected in config["observation"]["expected_lane_lengths_m"].items():
            self.assertIn(lane_id, actual)
            self.assertAlmostEqual(actual[lane_id], float(expected), places=3)

        effective_space = (
            config["observation"]["vehicle_length_m"]
            + config["observation"]["min_gap_m"]
        )
        for intersection in ("J1", "J2"):
            lanes = config["observation"]["lanes"][intersection]
            h_storage = sum(
                int(math.floor(actual[lane_id] / effective_space))
                for lane_id in lanes["H_in"]
            )
            v_storage = sum(
                int(math.floor(actual[lane_id] / effective_space))
                for lane_id in lanes["V_in"]
            )
            self.assertEqual(h_storage, config["observation"]["queue_normalizer_H"])
            self.assertEqual(v_storage, config["observation"]["queue_normalizer_V"])

    def test_elapsed_green_60_is_scaling_not_a_maximum(self):
        scale = config_copy()["observation"]["green_elapsed_scale_s"]
        self.assertEqual(scale, 60.0)
        values = [green / (green + scale) for green in (0.0, 60.0, 600.0)]
        self.assertEqual(values[0], 0.0)
        self.assertEqual(values[1], 0.5)
        self.assertLess(values[2], 1.0)
        self.assertGreater(values[2], values[1])


if __name__ == "__main__":
    unittest.main()

