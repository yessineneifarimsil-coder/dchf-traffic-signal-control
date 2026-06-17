import torch
import torch.nn as nn


class DQNNetwork(nn.Module):
    """
    Simple neural network for DQN.

    Input:
        state = [queue_phase_0, queue_phase_3, current_green]

    Output:
        Q-values for two actions:
            action 0 -> choose phase 0
            action 1 -> choose phase 3
    """

    def __init__(self, state_dim=3, action_dim=2):
        super(DQNNetwork, self).__init__()

        self.network = nn.Sequential(
            nn.Linear(state_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, action_dim),
        )

    def forward(self, x):
        return self.network(x)