"""Neural networks frozen for the N=2 qualification experiment."""

from __future__ import absolute_import

import copy

import torch
import torch.nn as nn
import torch.nn.functional as functional

from .rng import uint32_seed


class LocalQNetwork(nn.Module):
    """Shared architecture (not shared weights): 8 -> 128 -> 128 -> 2."""

    def __init__(self, observation_dim=8, hidden_dim=128, action_dim=2):
        super(LocalQNetwork, self).__init__()
        self.fc1 = nn.Linear(int(observation_dim), int(hidden_dim))
        self.fc2 = nn.Linear(int(hidden_dim), int(hidden_dim))
        self.output = nn.Linear(int(hidden_dim), int(action_dim))

    def forward(self, observations):
        hidden = functional.relu(self.fc1(observations))
        hidden = functional.relu(self.fc2(hidden))
        return self.output(hidden)


class QMixer(nn.Module):
    """Monotonic QMIX mixer conditioned on the 16-D global state."""

    def __init__(self, n_agents=2, state_dim=16, mixing_dim=32, hyper_dim=64):
        super(QMixer, self).__init__()
        self.n_agents = int(n_agents)
        self.state_dim = int(state_dim)
        self.mixing_dim = int(mixing_dim)

        self.hyper_w1 = nn.Sequential(
            nn.Linear(self.state_dim, int(hyper_dim)),
            nn.ReLU(),
            nn.Linear(int(hyper_dim), self.n_agents * self.mixing_dim),
        )
        self.hyper_b1 = nn.Linear(self.state_dim, self.mixing_dim)
        self.hyper_w_final = nn.Sequential(
            nn.Linear(self.state_dim, int(hyper_dim)),
            nn.ReLU(),
            nn.Linear(int(hyper_dim), self.mixing_dim),
        )
        self.value = nn.Sequential(
            nn.Linear(self.state_dim, self.mixing_dim),
            nn.ReLU(),
            nn.Linear(self.mixing_dim, 1),
        )

    def forward(self, local_q_values, global_state):
        if local_q_values.dim() != 2 or local_q_values.size(1) != self.n_agents:
            raise ValueError("Expected local Q tensor with shape [batch, n_agents].")
        if global_state.dim() != 2 or global_state.size(1) != self.state_dim:
            raise ValueError("Expected global state tensor with shape [batch, state_dim].")

        batch_size = local_q_values.size(0)
        agent_q = local_q_values.view(batch_size, 1, self.n_agents)
        weight_1 = torch.abs(self.hyper_w1(global_state)).view(
            batch_size, self.n_agents, self.mixing_dim
        )
        bias_1 = self.hyper_b1(global_state).view(batch_size, 1, self.mixing_dim)
        hidden = functional.elu(torch.bmm(agent_q, weight_1) + bias_1)

        weight_final = torch.abs(self.hyper_w_final(global_state)).view(
            batch_size, self.mixing_dim, 1
        )
        value = self.value(global_state).view(batch_size, 1, 1)
        total_q = torch.bmm(hidden, weight_final) + value
        return total_q.view(batch_size)


def _construct_with_isolated_torch_seed(seed_value, constructor):
    """Construct a module without consuming the caller's torch RNG stream."""
    cpu_state = torch.get_rng_state()
    cuda_states = None
    if torch.cuda.is_available():
        cuda_states = torch.cuda.get_rng_state_all()
    try:
        torch.manual_seed(int(seed_value))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(seed_value))
        return constructor()
    finally:
        torch.set_rng_state(cpu_state)
        if cuda_states is not None:
            torch.cuda.set_rng_state_all(cuda_states)


def build_local_networks(training_seed, device):
    """Build algorithm-independent J1/J2 initial local networks."""
    networks = []
    for agent_index, namespace in enumerate(("local_init_J1", "local_init_J2")):
        seed_value = uint32_seed(training_seed, namespace)
        network = _construct_with_isolated_torch_seed(
            seed_value, lambda: LocalQNetwork(8, 128, 2)
        )
        networks.append(network.to(device))
    return nn.ModuleList(networks)


def build_qmixer(training_seed, device):
    seed_value = uint32_seed(training_seed, "qmix_mixer_init")
    mixer = _construct_with_isolated_torch_seed(
        seed_value, lambda: QMixer(2, 16, 32, 64)
    )
    return mixer.to(device)


def exact_target_copy(module):
    target = copy.deepcopy(module)
    target.eval()
    for parameter in target.parameters():
        parameter.requires_grad_(False)
    return target


def hard_update(target, online):
    target.load_state_dict(online.state_dict())

