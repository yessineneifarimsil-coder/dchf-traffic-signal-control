from __future__ import absolute_import

import copy
import unittest

import numpy as np

from .common import config_copy

try:
    import torch
    import torch.nn as nn
    from adaptive_qmix.learner import MultiAgentLearner
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    nn = None
    MultiAgentLearner = None
    TORCH_AVAILABLE = False


def synthetic_batch(batch_size=8):
    generator = np.random.Generator(np.random.PCG64(1234))
    return {
        "states": generator.normal(size=(batch_size, 16)).astype(np.float32),
        "observations": generator.normal(size=(batch_size, 2, 8)).astype(np.float32),
        "actions": generator.integers(0, 2, size=(batch_size, 2), dtype=np.int64),
        "rewards": generator.normal(size=batch_size).astype(np.float32),
        "next_states": generator.normal(size=(batch_size, 16)).astype(np.float32),
        "next_observations": generator.normal(size=(batch_size, 2, 8)).astype(np.float32),
        "terminated": np.asarray([False] * (batch_size - 1) + [True]),
        "elapsed_seconds": np.asarray([5.0] * (batch_size - 1) + [8.0], dtype=np.float32),
    }


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch is required for learner contract tests")
class LearnerTests(unittest.TestCase):
    def setUp(self):
        self.training = config_copy()["training"]

    def _parameters_equal(self, first, second):
        return all(
            torch.equal(left, right)
            for left, right in zip(first.parameters(), second.parameters())
        )

    def test_local_architecture_and_initial_weights_match_across_methods(self):
        qmix = MultiAgentLearner("qmix", 101, self.training)
        vdn = MultiAgentLearner("vdn", 101, self.training)
        idqn = MultiAgentLearner("idqn", 101, self.training)
        for agent_index in range(2):
            self.assertEqual(qmix.online_locals[agent_index].fc1.in_features, 8)
            self.assertEqual(qmix.online_locals[agent_index].fc1.out_features, 128)
            self.assertEqual(qmix.online_locals[agent_index].fc2.out_features, 128)
            self.assertEqual(qmix.online_locals[agent_index].output.out_features, 2)
            self.assertTrue(self._parameters_equal(
                qmix.online_locals[agent_index], vdn.online_locals[agent_index]
            ))
            self.assertTrue(self._parameters_equal(
                qmix.online_locals[agent_index], idqn.online_locals[agent_index]
            ))

    def test_target_networks_are_exact_initial_copies(self):
        for method in ("qmix", "vdn", "idqn"):
            learner = MultiAgentLearner(method, 101, self.training)
            self.assertTrue(self._parameters_equal(
                learner.online_locals, learner.target_locals
            ))
            if method == "qmix":
                self.assertTrue(self._parameters_equal(
                    learner.online_mixer, learner.target_mixer
                ))

    def test_double_dqn_selects_online_and_evaluates_target(self):
        class FixedNetwork(nn.Module):
            def __init__(self, values):
                super(FixedNetwork, self).__init__()
                self.register_buffer("values", torch.tensor(values, dtype=torch.float32))

            def forward(self, observations):
                return self.values.unsqueeze(0).expand(observations.size(0), -1)

        learner = MultiAgentLearner("vdn", 101, self.training)
        learner.online_locals = nn.ModuleList([
            FixedNetwork([1.0, 2.0]), FixedNetwork([3.0, 1.0])
        ])
        learner.target_locals = nn.ModuleList([
            FixedNetwork([10.0, 5.0]), FixedNetwork([7.0, 9.0])
        ])
        tensors = learner._tensor_batch(synthetic_batch(4))
        values = learner._double_dqn_target_local_q(tensors)
        self.assertTrue(torch.equal(values[:, 0], torch.full((4,), 5.0)))
        self.assertTrue(torch.equal(values[:, 1], torch.full((4,), 7.0)))

    def test_discount_uses_elapsed_seconds_and_only_environment_terminal_masks(self):
        learner = MultiAgentLearner("vdn", 101, self.training)
        tensors = {
            "elapsed_seconds": torch.tensor([5.0, 8.0, 8.0]),
            "terminated": torch.tensor([0.0, 0.0, 1.0]),
        }
        mask = learner._discount_and_mask(tensors)
        self.assertAlmostEqual(float(mask[0]), 0.99, places=7)
        self.assertAlmostEqual(float(mask[1]), 0.99 ** (8.0 / 5.0), places=7)
        self.assertEqual(float(mask[2]), 0.0)

    def test_idqn_sum_loss_preserves_each_network_gradient(self):
        batch = synthetic_batch()
        first_only = MultiAgentLearner("idqn", 101, self.training)
        summed = MultiAgentLearner("idqn", 101, self.training)

        tensors = first_only._tensor_batch(batch)
        first_only.optimizer.zero_grad()
        losses, _target = first_only._losses(tensors)
        losses[0].backward()
        first_grads = [parameter.grad.detach().clone()
                       for parameter in first_only.online_locals[0].parameters()]

        tensors = summed._tensor_batch(batch)
        summed.optimizer.zero_grad()
        losses, _target = summed._losses(tensors)
        (losses[0] + losses[1]).backward()
        summed_grads = [parameter.grad.detach().clone()
                        for parameter in summed.online_locals[0].parameters()]
        for expected, actual in zip(first_grads, summed_grads):
            self.assertTrue(torch.equal(expected, actual))

        second_only = MultiAgentLearner("idqn", 101, self.training)
        tensors = second_only._tensor_batch(batch)
        second_only.optimizer.zero_grad()
        losses, _target = second_only._losses(tensors)
        losses[1].backward()
        second_grads = [parameter.grad.detach().clone()
                        for parameter in second_only.online_locals[1].parameters()]
        summed_second_grads = [parameter.grad.detach().clone()
                               for parameter in summed.online_locals[1].parameters()]
        for expected, actual in zip(second_grads, summed_second_grads):
            self.assertTrue(torch.equal(expected, actual))

    def test_idqn_clipping_is_independent_per_agent(self):
        learner = MultiAgentLearner("idqn", 101, self.training)
        for parameter in learner.online_locals[0].parameters():
            parameter.grad = torch.full_like(parameter, 1000.0)
        before_j2 = []
        for parameter in learner.online_locals[1].parameters():
            parameter.grad = torch.full_like(parameter, 0.001)
            before_j2.append(parameter.grad.detach().clone())
        norms = learner._clip_gradients()
        self.assertGreater(norms[0], 10.0)
        self.assertLess(norms[1], 10.0)
        for before, parameter in zip(before_j2, learner.online_locals[1].parameters()):
            self.assertTrue(torch.equal(before, parameter.grad))

    def test_cooperative_clipping_uses_one_global_group(self):
        for method in ("qmix", "vdn"):
            learner = MultiAgentLearner(method, 101, self.training)
            for network in learner.online_locals:
                for parameter in network.parameters():
                    parameter.grad = torch.ones_like(parameter)
            if method == "qmix":
                for parameter in learner.online_mixer.parameters():
                    parameter.grad = torch.ones_like(parameter)
            norms = learner._clip_gradients()
            self.assertEqual(len(norms), 1)

    def test_target_copy_occurs_exactly_at_event_500(self):
        learner = MultiAgentLearner("qmix", 101, self.training)
        with torch.no_grad():
            next(learner.target_locals.parameters()).add_(10.0)
        learner.learner_events = 498
        result_499 = learner.update(synthetic_batch())
        self.assertFalse(result_499["target_hard_copied"])
        self.assertFalse(self._parameters_equal(
            learner.online_locals, learner.target_locals
        ))
        result_500 = learner.update(synthetic_batch())
        self.assertTrue(result_500["target_hard_copied"])
        self.assertTrue(self._parameters_equal(
            learner.online_locals, learner.target_locals
        ))
        self.assertTrue(self._parameters_equal(
            learner.online_mixer, learner.target_mixer
        ))

    def test_huber_beta_and_reduction_are_exact(self):
        learner = MultiAgentLearner("qmix", 101, self.training)
        self.assertEqual(learner.loss_function.beta, 1.0)
        self.assertEqual(learner.loss_function.reduction, "mean")

    def test_bitwise_reproducibility_is_same_runtime_device_scoped(self):
        first = MultiAgentLearner("qmix", 101, self.training, device="cpu")
        second = MultiAgentLearner("qmix", 101, self.training, device="cpu")
        result_first = first.update(copy.deepcopy(synthetic_batch()))
        result_second = second.update(copy.deepcopy(synthetic_batch()))
        self.assertEqual(result_first["loss"], result_second["loss"])
        self.assertTrue(self._parameters_equal(first.online_locals, second.online_locals))
        self.assertTrue(self._parameters_equal(first.online_mixer, second.online_mixer))


if __name__ == "__main__":
    unittest.main()

