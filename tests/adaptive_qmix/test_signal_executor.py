from __future__ import absolute_import

import unittest

from .common import config_copy

from adaptive_qmix.signal_executor import EXTEND, SWITCH, SynchronousSignalExecutor


class FakeTrafficLight(object):
    def __init__(self):
        self.phase_calls = []
        self.duration_calls = []

    def setPhase(self, traffic_light, phase):
        self.phase_calls.append((traffic_light, phase))

    def setPhaseDuration(self, traffic_light, duration):
        self.duration_calls.append((traffic_light, duration))


class FakeTraci(object):
    def __init__(self):
        self.trafficlight = FakeTrafficLight()
        self.steps = 0

    def simulationStep(self):
        self.steps += 1


class SignalExecutorTests(unittest.TestCase):
    def setUp(self):
        self.traci = FakeTraci()
        self.executor = SynchronousSignalExecutor(self.traci, config_copy())
        self.executor.initialize()

    def test_initial_state_is_h_h_zero_and_first_action_at_zero(self):
        self.assertEqual(self.executor.current_phase, {"J1": "H", "J2": "H"})
        self.assertEqual(self.executor.green_elapsed, {"J1": 0, "J2": 0})
        self.assertEqual(self.executor.decision_index, 0)

    def test_extend_is_five_green_seconds(self):
        result = self.executor.execute([EXTEND, EXTEND])
        self.assertEqual(result["elapsed_seconds"], 5)
        self.assertEqual(self.traci.steps, 5)
        self.assertEqual([row["states"]["J1"] for row in result["trace"]], ["H"] * 5)
        self.assertEqual(result["green_elapsed"], {"J1": 5, "J2": 5})

    def test_switch_is_three_yellow_plus_two_new_green(self):
        result = self.executor.execute([SWITCH, SWITCH])
        self.assertEqual([row["states"]["J1"] for row in result["trace"]],
                         ["Y", "Y", "Y", "V", "V"])
        self.assertEqual(result["current_phase"], {"J1": "V", "J2": "V"})
        self.assertEqual(result["green_elapsed"], {"J1": 2, "J2": 2})
        self.assertIn(("J1", 3), self.traci.trafficlight.phase_calls)
        self.assertIn(("J1", 0), self.traci.trafficlight.phase_calls)
        self.assertIn(("J1", 3), self.traci.trafficlight.duration_calls)
        self.assertIn(("J1", 2), self.traci.trafficlight.duration_calls)

    def test_mixed_actions_still_share_one_next_decision_time(self):
        result = self.executor.execute([EXTEND, SWITCH])
        self.assertEqual(result["elapsed_seconds"], 5)
        self.assertEqual(result["green_elapsed"]["J1"], 5)
        self.assertEqual(result["green_elapsed"]["J2"], 2)
        self.assertEqual(self.executor.decision_index, 1)

    def test_no_implicit_minimum_or_maximum_green(self):
        for _index in range(50):
            self.executor.execute([EXTEND, EXTEND])
        self.assertEqual(self.executor.green_elapsed["J1"], 250)


if __name__ == "__main__":
    unittest.main()

