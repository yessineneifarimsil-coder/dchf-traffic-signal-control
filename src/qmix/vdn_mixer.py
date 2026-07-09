import torch
import torch.nn as nn


class VDNMixer(nn.Module):
    """
    VDN (Value-Decomposition Network) mixer.

    Controlled ablation of the QMIX MixingNetwork: the monotonic
    hypernetwork mixer is replaced by a plain sum of agent Q-values,
        Q_tot = sum_i Q_i,
    with no learnable parameters and no dependence on the global state.

    Signature-compatible drop-in for MixingNetwork:
        forward(agent_qs, global_state) -> [batch_size, 1]

    global_state is accepted for interface compatibility and deliberately
    ignored. This lets QMIXAgent reuse its training/eval code path unchanged
    except for the mixer object itself, isolating the effect of the QMIX
    mixing network from every other component (local networks, observations,
    actions, replay, reward, training budget, decentralized execution).
    """

    def __init__(self, n_agents=2, state_dim=6):
        super(VDNMixer, self).__init__()
        self.n_agents = n_agents
        self.state_dim = state_dim

    def forward(self, agent_qs, global_state):
        # agent_qs:     [batch_size, n_agents]
        # global_state: [batch_size, state_dim]  (ignored by VDN)
        return agent_qs.sum(dim=1, keepdim=True)