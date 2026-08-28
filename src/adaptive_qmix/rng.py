"""Independent deterministic RNG namespaces for matched comparisons."""

from __future__ import absolute_import

import random

import numpy as np


MASTER_ENTROPY = 20260828
EXPERIMENT_NAMESPACE = 1301

NAMESPACE_CODES = {
    "local_init_J1": 101,
    "local_init_J2": 102,
    "qmix_mixer_init": 110,
    "epsilon_J1": 201,
    "epsilon_J2": 202,
    "replay_sampling": 301,
    "traffic_manifest": 401,
    "sumo_episode": 402,
    "checkpoint_validation": 501,
}


def seed_sequence(training_seed, namespace, index=0):
    if namespace not in NAMESPACE_CODES:
        raise KeyError("Unknown RNG namespace: {}".format(namespace))
    return np.random.SeedSequence(
        [
            MASTER_ENTROPY,
            EXPERIMENT_NAMESPACE,
            int(training_seed),
            NAMESPACE_CODES[namespace],
            int(index),
        ]
    )


def numpy_rng(training_seed, namespace, index=0):
    return np.random.Generator(np.random.PCG64(seed_sequence(training_seed, namespace, index)))


def uint32_seed(training_seed, namespace, index=0):
    state = seed_sequence(training_seed, namespace, index).generate_state(1)
    return int(state[0])


def namespace_manifest(training_seed):
    return {
        name: {
            "master_entropy": MASTER_ENTROPY,
            "experiment_namespace": EXPERIMENT_NAMESPACE,
            "training_seed": int(training_seed),
            "namespace_code": int(code),
        }
        for name, code in sorted(NAMESPACE_CODES.items())
    }


class IndependentEpsilonStreams(object):
    """Draw exactly two random values per agent and joint decision.

    A threshold and candidate random action are consumed even when the greedy
    action is used, keeping RNG consumption identical across algorithms.
    """

    def __init__(self, training_seed, action_dim=2):
        self.action_dim = int(action_dim)
        self._rngs = [
            numpy_rng(training_seed, "epsilon_J1"),
            numpy_rng(training_seed, "epsilon_J2"),
        ]
        self.decisions = 0

    def select(self, greedy_actions, epsilon):
        if len(greedy_actions) != 2:
            raise ValueError("Expected exactly two greedy actions.")
        selected = []
        diagnostics = []
        for agent_id, greedy in enumerate(greedy_actions):
            generator = self._rngs[agent_id]
            threshold = float(generator.random())
            candidate = int(generator.integers(0, self.action_dim))
            explore = threshold < float(epsilon)
            selected.append(candidate if explore else int(greedy))
            diagnostics.append(
                {
                    "agent_id": agent_id,
                    "threshold": threshold,
                    "candidate_action": candidate,
                    "explore": explore,
                }
            )
        self.decisions += 1
        return selected, diagnostics


def configure_python_and_torch(training_seed, deterministic=True):
    """Configure Python and PyTorch without importing torch at package import."""
    python_seed = uint32_seed(training_seed, "local_init_J1", index=999)
    random.seed(python_seed)
    np.random.seed(python_seed)

    import torch

    torch.manual_seed(python_seed)
    torch.use_deterministic_algorithms(bool(deterministic))
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = bool(deterministic)
        torch.backends.cudnn.benchmark = False
    return python_seed

