import random
from collections import deque
import numpy as np


class QMIXReplayBuffer:
    """
    Replay buffer for QMIX.

    Stores joint multi-agent transitions:
        global_state
        observations for all agents
        joint actions
        global reward
        next_global_state
        next observations
        done
    """

    def __init__(self, capacity=50_000):
        self.buffer = deque(maxlen=capacity)

    def push(
        self,
        global_state,
        observations,
        actions,
        reward,
        next_global_state,
        next_observations,
        done,
    ):
        self.buffer.append((
            np.array(global_state, dtype=np.float32),
            np.array(observations, dtype=np.float32),
            np.array(actions, dtype=np.int64),
            reward,
            np.array(next_global_state, dtype=np.float32),
            np.array(next_observations, dtype=np.float32),
            done,
        ))

    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)

        (
            global_states,
            observations,
            actions,
            rewards,
            next_global_states,
            next_observations,
            dones,
        ) = zip(*batch)

        return (
            np.array(global_states, dtype=np.float32),
            np.array(observations, dtype=np.float32),
            np.array(actions, dtype=np.int64),
            np.array(rewards, dtype=np.float32),
            np.array(next_global_states, dtype=np.float32),
            np.array(next_observations, dtype=np.float32),
            np.array(dones, dtype=np.float32),
        )

    def __len__(self):
        return len(self.buffer)