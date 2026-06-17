import torch
import torch.nn as nn


class AgentQNetwork(nn.Module):
    """
    Local Q-network for each traffic-light agent.

    Input:
        local observation of one intersection:
        [side_queue, main_queue, current_green]

    Output:
        Q-values for two actions:
        0 -> side green
        1 -> main green
    """

    def __init__(self, obs_dim=3, action_dim=2, hidden_dim=64):
        super(AgentQNetwork, self).__init__()

        self.network = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim),
        )

    def forward(self, obs):
        return self.network(obs)