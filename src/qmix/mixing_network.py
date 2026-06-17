import torch
import torch.nn as nn
import torch.nn.functional as F


class MixingNetwork(nn.Module):
    """
    QMIX mixing network.

    It combines individual agent Q-values into a global Q_total.

    Inputs:
        agent_qs: tensor of shape [batch_size, n_agents]
        global_state: tensor of shape [batch_size, state_dim]

    Output:
        q_total: tensor of shape [batch_size, 1]

    Important QMIX principle:
        Q_total must be monotonic with respect to individual agent Q-values.
        This is enforced by using absolute values for hypernetwork-generated weights.
    """

    def __init__(self, n_agents=2, state_dim=6, mixing_hidden_dim=32, hypernet_hidden_dim=64):
        super(MixingNetwork, self).__init__()

        self.n_agents = n_agents
        self.state_dim = state_dim
        self.mixing_hidden_dim = mixing_hidden_dim

        # Hypernetwork for first-layer weights
        self.hyper_w1 = nn.Sequential(
            nn.Linear(state_dim, hypernet_hidden_dim),
            nn.ReLU(),
            nn.Linear(hypernet_hidden_dim, n_agents * mixing_hidden_dim),
        )

        # Hypernetwork for first-layer bias
        self.hyper_b1 = nn.Linear(state_dim, mixing_hidden_dim)

        # Hypernetwork for second-layer weights
        self.hyper_w2 = nn.Sequential(
            nn.Linear(state_dim, hypernet_hidden_dim),
            nn.ReLU(),
            nn.Linear(hypernet_hidden_dim, mixing_hidden_dim),
        )

        # State-dependent value function bias
        self.hyper_b2 = nn.Sequential(
            nn.Linear(state_dim, mixing_hidden_dim),
            nn.ReLU(),
            nn.Linear(mixing_hidden_dim, 1),
        )

    def forward(self, agent_qs, global_state):
        batch_size = agent_qs.size(0)

        # agent_qs: [batch, n_agents] -> [batch, 1, n_agents]
        agent_qs = agent_qs.view(batch_size, 1, self.n_agents)

        # First layer weights and bias
        w1 = torch.abs(self.hyper_w1(global_state))
        w1 = w1.view(batch_size, self.n_agents, self.mixing_hidden_dim)

        b1 = self.hyper_b1(global_state)
        b1 = b1.view(batch_size, 1, self.mixing_hidden_dim)

        hidden = F.elu(torch.bmm(agent_qs, w1) + b1)

        # Second layer weights and bias
        w2 = torch.abs(self.hyper_w2(global_state))
        w2 = w2.view(batch_size, self.mixing_hidden_dim, 1)

        b2 = self.hyper_b2(global_state)
        b2 = b2.view(batch_size, 1, 1)

        q_total = torch.bmm(hidden, w2) + b2

        return q_total.view(batch_size, 1)