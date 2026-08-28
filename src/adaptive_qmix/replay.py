"""Preallocated joint replay buffer with explicit terminal/truncation fields."""

from __future__ import absolute_import

import numpy as np


class JointReplayBuffer(object):
    def __init__(self, capacity=200000, n_agents=2, obs_dim=8, state_dim=16):
        self.capacity = int(capacity)
        self.n_agents = int(n_agents)
        self.obs_dim = int(obs_dim)
        self.state_dim = int(state_dim)
        self.position = 0
        self.size = 0

        self.states = np.empty((self.capacity, self.state_dim), dtype=np.float32)
        self.observations = np.empty(
            (self.capacity, self.n_agents, self.obs_dim), dtype=np.float32
        )
        self.actions = np.empty((self.capacity, self.n_agents), dtype=np.int64)
        self.rewards = np.empty(self.capacity, dtype=np.float32)
        self.next_states = np.empty((self.capacity, self.state_dim), dtype=np.float32)
        self.next_observations = np.empty(
            (self.capacity, self.n_agents, self.obs_dim), dtype=np.float32
        )
        self.terminated = np.empty(self.capacity, dtype=np.bool_)
        self.budget_truncated = np.empty(self.capacity, dtype=np.bool_)
        self.timeout_truncated = np.empty(self.capacity, dtype=np.bool_)
        self.failure_truncated = np.empty(self.capacity, dtype=np.bool_)
        self.elapsed_seconds = np.empty(self.capacity, dtype=np.float32)

    def push(
        self,
        state,
        observations,
        actions,
        reward,
        next_state,
        next_observations,
        terminated,
        elapsed_seconds,
        budget_truncated=False,
        timeout_truncated=False,
        failure_truncated=False,
    ):
        if failure_truncated:
            raise ValueError("Transitions without a valid next observation cannot enter replay.")
        index = self.position
        self.states[index] = np.asarray(state, dtype=np.float32)
        self.observations[index] = np.asarray(observations, dtype=np.float32)
        self.actions[index] = np.asarray(actions, dtype=np.int64)
        self.rewards[index] = float(reward)
        self.next_states[index] = np.asarray(next_state, dtype=np.float32)
        self.next_observations[index] = np.asarray(next_observations, dtype=np.float32)
        self.terminated[index] = bool(terminated)
        self.budget_truncated[index] = bool(budget_truncated)
        self.timeout_truncated[index] = bool(timeout_truncated)
        self.failure_truncated[index] = bool(failure_truncated)
        self.elapsed_seconds[index] = float(elapsed_seconds)

        self.position = (self.position + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size, generator):
        batch_size = int(batch_size)
        if self.size < batch_size:
            raise ValueError("Replay contains fewer entries than the requested batch.")
        indices = generator.choice(self.size, size=batch_size, replace=False)
        return {
            "indices": indices,
            "states": self.states[indices].copy(),
            "observations": self.observations[indices].copy(),
            "actions": self.actions[indices].copy(),
            "rewards": self.rewards[indices].copy(),
            "next_states": self.next_states[indices].copy(),
            "next_observations": self.next_observations[indices].copy(),
            "terminated": self.terminated[indices].copy(),
            "budget_truncated": self.budget_truncated[indices].copy(),
            "timeout_truncated": self.timeout_truncated[indices].copy(),
            "failure_truncated": self.failure_truncated[indices].copy(),
            "elapsed_seconds": self.elapsed_seconds[indices].copy(),
        }

    def estimated_bytes(self):
        arrays = [
            self.states,
            self.observations,
            self.actions,
            self.rewards,
            self.next_states,
            self.next_observations,
            self.terminated,
            self.budget_truncated,
            self.timeout_truncated,
            self.failure_truncated,
            self.elapsed_seconds,
        ]
        return int(sum(array.nbytes for array in arrays))

    def __len__(self):
        return self.size

