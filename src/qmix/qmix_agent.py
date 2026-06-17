import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from q_network import AgentQNetwork
from mixing_network import MixingNetwork
from replay_buffer import QMIXReplayBuffer


class QMIXAgent:
    """
    QMIX agent for two traffic-light agents.

    n_agents = 2:
        agent 0 controls J1
        agent 1 controls J2

    Each local agent observes:
        [side_queue, main_queue, current_green]

    Global state:
        [J1_side_queue, J1_main_queue, J1_phase,
         J2_side_queue, J2_main_queue, J2_phase]
    """

    def __init__(
        self,
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
        learning_rate=1e-3,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_min=0.10,
        epsilon_decay=0.999,
        buffer_capacity=50_000,
        batch_size=64,
        target_update_freq=100,
        device=None,
    ):
        self.n_agents = n_agents
        self.obs_dim = obs_dim
        self.state_dim = state_dim
        self.action_dim = action_dim

        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay

        self.batch_size = batch_size
        self.target_update_freq = target_update_freq
        self.learn_step = 0

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        # Local agent networks
        self.agent_networks = nn.ModuleList([
            AgentQNetwork(obs_dim, action_dim).to(self.device)
            for _ in range(n_agents)
        ])

        self.target_agent_networks = nn.ModuleList([
            AgentQNetwork(obs_dim, action_dim).to(self.device)
            for _ in range(n_agents)
        ])

        # Mixing networks
        self.mixer = MixingNetwork(
            n_agents=n_agents,
            state_dim=state_dim,
        ).to(self.device)

        self.target_mixer = MixingNetwork(
            n_agents=n_agents,
            state_dim=state_dim,
        ).to(self.device)

        self.update_target_networks()

        parameters = list(self.agent_networks.parameters()) + list(self.mixer.parameters())
        self.optimizer = optim.Adam(parameters, lr=learning_rate)
        self.loss_fn = nn.MSELoss()

        self.memory = QMIXReplayBuffer(capacity=buffer_capacity)

    def select_actions(self, observations):
        """
        observations shape:
            list/array of shape [n_agents, obs_dim]

        returns:
            list of actions, one per agent
        """
        actions = []

        for agent_id in range(self.n_agents):
            obs = observations[agent_id]

            if random.random() < self.epsilon:
                action = random.randrange(self.action_dim)
                actions.append(action)
                continue

            obs_tensor = torch.tensor(
                np.array([obs], dtype=np.float32),
                device=self.device,
            )

            with torch.no_grad():
                q_values = self.agent_networks[agent_id](obs_tensor)

            action = int(torch.argmax(q_values, dim=1).item())
            actions.append(action)

        return actions

    def store_transition(
        self,
        global_state,
        observations,
        actions,
        reward,
        next_global_state,
        next_observations,
        done,
    ):
        self.memory.push(
            global_state,
            observations,
            actions,
            reward,
            next_global_state,
            next_observations,
            done,
        )

    def learn(self):
        if len(self.memory) < self.batch_size:
            return None

        (
            global_states,
            observations,
            actions,
            rewards,
            next_global_states,
            next_observations,
            dones,
        ) = self.memory.sample(self.batch_size)

        global_states = torch.tensor(global_states, device=self.device)
        observations = torch.tensor(observations, device=self.device)
        actions = torch.tensor(actions, device=self.device)
        rewards = torch.tensor(rewards, device=self.device).unsqueeze(1)
        next_global_states = torch.tensor(next_global_states, device=self.device)
        next_observations = torch.tensor(next_observations, device=self.device)
        dones = torch.tensor(dones, device=self.device).unsqueeze(1)

        # Current selected Q-values for each agent
        current_agent_qs = []

        for agent_id in range(self.n_agents):
            agent_obs = observations[:, agent_id, :]
            agent_actions = actions[:, agent_id].unsqueeze(1)

            q_values = self.agent_networks[agent_id](agent_obs)
            selected_q = q_values.gather(1, agent_actions)

            current_agent_qs.append(selected_q)

        current_agent_qs = torch.cat(current_agent_qs, dim=1)

        q_total = self.mixer(current_agent_qs, global_states)

        # Target max Q-values for next state
        with torch.no_grad():
            target_agent_qs = []

            for agent_id in range(self.n_agents):
                next_agent_obs = next_observations[:, agent_id, :]
                next_q_values = self.target_agent_networks[agent_id](next_agent_obs)
                max_next_q = next_q_values.max(dim=1, keepdim=True)[0]
                target_agent_qs.append(max_next_q)

            target_agent_qs = torch.cat(target_agent_qs, dim=1)

            target_q_total = self.target_mixer(target_agent_qs, next_global_states)
            y = rewards + self.gamma * target_q_total * (1 - dones)

        loss = self.loss_fn(q_total, y)

        self.optimizer.zero_grad()
        loss.backward()

        torch.nn.utils.clip_grad_norm_(
            list(self.agent_networks.parameters()) + list(self.mixer.parameters()),
            max_norm=10.0,
        )

        self.optimizer.step()

        self.learn_step += 1

        if self.learn_step % self.target_update_freq == 0:
            self.update_target_networks()

        self.decay_epsilon()

        return loss.item()

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def update_target_networks(self):
        for target_net, net in zip(self.target_agent_networks, self.agent_networks):
            target_net.load_state_dict(net.state_dict())

        self.target_mixer.load_state_dict(self.mixer.state_dict())

    def save(self, path):
        torch.save({
            "agent_networks": [net.state_dict() for net in self.agent_networks],
            "target_agent_networks": [net.state_dict() for net in self.target_agent_networks],
            "mixer": self.mixer.state_dict(),
            "target_mixer": self.target_mixer.state_dict(),
            "epsilon": self.epsilon,
        }, path)

    def load(self, path):
        checkpoint = torch.load(path, map_location=self.device)

        for net, state_dict in zip(self.agent_networks, checkpoint["agent_networks"]):
            net.load_state_dict(state_dict)

        for net, state_dict in zip(self.target_agent_networks, checkpoint["target_agent_networks"]):
            net.load_state_dict(state_dict)

        self.mixer.load_state_dict(checkpoint["mixer"])
        self.target_mixer.load_state_dict(checkpoint["target_mixer"])
        self.epsilon = checkpoint["epsilon"]