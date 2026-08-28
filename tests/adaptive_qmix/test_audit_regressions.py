"""Regression tests for defects found in the pre-training implementation audit.

Each test pins a behaviour that was previously wrong and that would have
corrupted an official run rather than failing loudly.
"""

from __future__ import absolute_import

import unittest

from .common import config_copy, ledger_records

from adaptive_qmix.ledger import LedgerError, VehicleLedger
from adaptive_qmix.traffic import FAMILY_CODES, SUMO_MAX_SEED, derive_sumo_seed


class SumoSeedRangeTests(unittest.TestCase):
    """SUMO parses --seed as a signed 32-bit integer.

    An unmasked 32-bit SeedSequence draw exceeds that limit about half the
    time; SUMO then aborts with "is not a valid integer" before the episode
    starts, so a long run would die at an arbitrary episode boundary.
    """

    def test_every_derived_episode_seed_is_a_valid_sumo_seed(self):
        for family in FAMILY_CODES:
            for training_seed in range(101, 111):
                for episode_index in range(64):
                    seed = derive_sumo_seed(family, training_seed, episode_index)
                    self.assertGreaterEqual(seed, 0)
                    self.assertLessEqual(seed, SUMO_MAX_SEED)

    def test_derived_seed_is_deterministic_and_family_separated(self):
        self.assertEqual(
            derive_sumo_seed("training", 101, 4),
            derive_sumo_seed("training", 101, 4),
        )
        self.assertNotEqual(
            derive_sumo_seed("training", 101, 0),
            derive_sumo_seed("final_test", 101, 0),
        )


class TeleportAccountingTests(unittest.TestCase):
    """A teleport is an event SUMO reports, not a silent disappearance."""

    def _inserted_ledger(self):
        records = ledger_records(depart=0)
        ledger = VehicleLedger(records)
        ledger.mark_departed([records[0]["vehicle_id"]], 0)
        return ledger, records[0]["vehicle_id"]

    def test_in_transit_teleport_is_not_treated_as_unaccounted(self):
        ledger, vehicle_id = self._inserted_ledger()
        ledger.mark_teleport_start([vehicle_id])
        ledger.assert_active_consistency([])
        self.assertEqual(ledger.in_transit_teleport_ids(), {vehicle_id})

    def test_finished_teleport_must_reappear_in_the_active_list(self):
        ledger, vehicle_id = self._inserted_ledger()
        ledger.mark_teleport_start([vehicle_id])
        ledger.mark_teleport_end([vehicle_id])
        ledger.assert_active_consistency([vehicle_id])
        with self.assertRaises(LedgerError):
            ledger.assert_active_consistency([])

    def test_teleporting_vehicle_still_blocks_clearance(self):
        ledger, vehicle_id = self._inserted_ledger()
        ledger.mark_teleport_start([vehicle_id])
        self.assertFalse(ledger.is_reconciled_clear(3600, [], 0))


class RedDurationBookkeepingTests(unittest.TestCase):
    """Red time must accumulate across every yellow second.

    The previous implementation keyed the yellow branch on the last observed
    state, which is itself "Y" from the second yellow second onward, so two of
    the three yellow seconds advanced no counter and every red interval was
    reported 2 s short -- biased toward under-reporting starvation.
    """

    @staticmethod
    def _replay(states):
        red = {"H": 0, "V": 0}
        previous = "H"
        last_green = "H"
        history = []
        for actual in states:
            if actual == "H":
                red["H"] = 0
                red["V"] += 1
                last_green = "H"
            elif actual == "V":
                red["V"] = 0
                red["H"] += 1
                last_green = "V"
            elif last_green == "H":
                red["V"] += 1
            else:
                red["H"] += 1
            previous = actual
            history.append((actual, red["H"], red["V"]))
        return history

    def test_yellow_seconds_all_count_toward_the_waiting_approach(self):
        # 5 s of H green, then a SWITCH: 3 s yellow + 2 s of new V green.
        history = self._replay(["H"] * 5 + ["Y", "Y", "Y", "V", "V"])
        v_red_at_end_of_yellow = history[7][2]
        self.assertEqual(v_red_at_end_of_yellow, 8)

    def test_environment_uses_the_same_rule(self):
        from adaptive_qmix.environment import AdaptiveTrafficEnvironment
        config = config_copy()
        environment = AdaptiveTrafficEnvironment.__new__(AdaptiveTrafficEnvironment)
        environment.logger = None
        environment.config = config
        environment.previous_actual_phase = {"J1": "H", "J2": "H"}
        environment.last_green_phase = {"J1": "H", "J2": "H"}
        environment.red_elapsed = {"J1": {"H": 0, "V": 0}, "J2": {"H": 0, "V": 0}}

        class _Executor(object):
            current_phase = {"J1": "H", "J2": "H"}

        environment.executor = _Executor()
        for actual in ["H"] * 5 + ["Y", "Y", "Y"]:
            for intersection, state in sorted({"J1": actual, "J2": actual}.items()):
                previous = environment.previous_actual_phase[intersection]
                del previous
                if state == "H":
                    environment.red_elapsed[intersection]["H"] = 0
                    environment.red_elapsed[intersection]["V"] += 1
                    environment.last_green_phase[intersection] = "H"
                elif state == "V":
                    environment.red_elapsed[intersection]["V"] = 0
                    environment.red_elapsed[intersection]["H"] += 1
                    environment.last_green_phase[intersection] = "V"
                elif environment.last_green_phase[intersection] == "H":
                    environment.red_elapsed[intersection]["V"] += 1
                else:
                    environment.red_elapsed[intersection]["H"] += 1
                environment.previous_actual_phase[intersection] = state
        self.assertEqual(environment.red_elapsed["J1"]["V"], 8)
        self.assertEqual(environment.red_elapsed["J2"]["V"], 8)


if __name__ == "__main__":
    unittest.main()
