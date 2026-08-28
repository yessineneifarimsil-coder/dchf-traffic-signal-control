"""Exact Double-DQN update rules for QMIX, VDN and Independent DQN."""

from __future__ import absolute_import

import os

import numpy as np
import torch
import torch.nn as nn

from .models import build_local_networks, build_qmixer, exact_target_copy, hard_update


METHODS = ("qmix", "vdn", "idqn")


def epsilon_at_transition(transition_index, start=1.0, end=0.05, decay=250000):
    position = min(max(int(transition_index), 0), int(decay))
    fraction = float(position) / float(decay)
    return float(start) + fraction * (float(end) - float(start))


class MultiAgentLearner(object):
    """Matched learner implementation; only value decomposition differs."""

    def __init__(self, method, training_seed, training_config, device="cpu"):
        method = str(method).lower()
        if method not in METHODS:
            raise ValueError("Unknown learned controller: {}".format(method))
        self.method = method
        self.device = torch.device(device)
        self.training_config = dict(training_config)
        self.gamma = float(training_config["gamma_per_5s"])
        self.gradient_max_norm = float(training_config["gradient_max_l2_norm"])
        self.target_update_frequency = int(
            training_config["target_hard_update_events"]
        )
        self.huber_beta = float(training_config["huber_beta"])
        if self.huber_beta != 1.0:
            raise ValueError("Qualification Huber beta must equal 1.0.")

        self.online_locals = build_local_networks(training_seed, self.device)
        self.target_locals = exact_target_copy(self.online_locals).to(self.device)
        self.online_mixer = None
        self.target_mixer = None
        if self.method == "qmix":
            self.online_mixer = build_qmixer(training_seed, self.device)
            self.target_mixer = exact_target_copy(self.online_mixer).to(self.device)

        parameter_groups = []
        for network in self.online_locals:
            parameter_groups.extend(list(network.parameters()))
        if self.online_mixer is not None:
            parameter_groups.extend(list(self.online_mixer.parameters()))
        self.optimizer = torch.optim.Adam(
            parameter_groups, lr=float(training_config["learning_rate"])
        )
        self.loss_function = nn.SmoothL1Loss(beta=1.0, reduction="mean")
        self.learner_events = 0

    def _tensor_batch(self, batch):
        converted = {}
        float_names = (
            "states", "observations", "rewards", "next_states",
            "next_observations", "elapsed_seconds",
        )
        for name in float_names:
            converted[name] = torch.as_tensor(
                batch[name], dtype=torch.float32, device=self.device
            )
        converted["actions"] = torch.as_tensor(
            batch["actions"], dtype=torch.long, device=self.device
        )
        converted["terminated"] = torch.as_tensor(
            batch["terminated"], dtype=torch.float32, device=self.device
        )
        return converted

    def greedy_actions(self, observations):
        obs = torch.as_tensor(observations, dtype=torch.float32, device=self.device)
        if obs.shape != (2, 8):
            raise ValueError("Greedy action selection expects observations [2, 8].")
        with torch.no_grad():
            return [
                int(self.online_locals[index](obs[index]).argmax(dim=-1).item())
                for index in range(2)
            ]

    def local_q_values(self, observations):
        obs = torch.as_tensor(observations, dtype=torch.float32, device=self.device)
        if obs.shape != (2, 8):
            raise ValueError("Q-value logging expects observations [2, 8].")
        with torch.no_grad():
            return [
                self.online_locals[index](obs[index]).detach().cpu().numpy().copy()
                for index in range(2)
            ]

    def _chosen_online_local_q(self, tensors):
        chosen = []
        for agent_index in range(2):
            all_q = self.online_locals[agent_index](
                tensors["observations"][:, agent_index, :]
            )
            action = tensors["actions"][:, agent_index].unsqueeze(1)
            chosen.append(all_q.gather(1, action).squeeze(1))
        return torch.stack(chosen, dim=1)

    def _double_dqn_target_local_q(self, tensors):
        """Online argmax selection, target-network evaluation for each agent."""
        targets = []
        with torch.no_grad():
            for agent_index in range(2):
                next_observation = tensors["next_observations"][:, agent_index, :]
                online_next = self.online_locals[agent_index](next_observation)
                next_action = online_next.argmax(dim=1, keepdim=True)
                target_next = self.target_locals[agent_index](next_observation)
                targets.append(target_next.gather(1, next_action).squeeze(1))
        return torch.stack(targets, dim=1)

    def _discount_and_mask(self, tensors):
        # Truncation flags deliberately do not appear in this mask.
        discount = torch.pow(
            torch.full_like(tensors["elapsed_seconds"], self.gamma),
            tensors["elapsed_seconds"] / 5.0,
        )
        return (1.0 - tensors["terminated"]) * discount

    def _losses(self, tensors):
        chosen_local = self._chosen_online_local_q(tensors)
        target_local = self._double_dqn_target_local_q(tensors)
        bootstrap_mask = self._discount_and_mask(tensors)
        reward = tensors["rewards"]

        if self.method == "qmix":
            current_total = self.online_mixer(chosen_local, tensors["states"])
            with torch.no_grad():
                # The target mixer receives target local values and s_{t+1}.
                next_total = self.target_mixer(target_local, tensors["next_states"])
                target = reward + bootstrap_mask * next_total
            return [self.loss_function(current_total, target)], target

        if self.method == "vdn":
            current_total = chosen_local.sum(dim=1)
            with torch.no_grad():
                next_total = target_local.sum(dim=1)
                target = reward + bootstrap_mask * next_total
            return [self.loss_function(current_total, target)], target

        losses = []
        targets = []
        for agent_index in range(2):
            with torch.no_grad():
                target_i = reward + bootstrap_mask * target_local[:, agent_index]
            losses.append(
                self.loss_function(chosen_local[:, agent_index], target_i)
            )
            targets.append(target_i)
        return losses, torch.stack(targets, dim=1)

    def _clip_gradients(self):
        if self.method == "idqn":
            # Each independent learner gets its own L2 clipping factor.
            return [
                float(
                    torch.nn.utils.clip_grad_norm_(
                        self.online_locals[index].parameters(), self.gradient_max_norm
                    )
                )
                for index in range(2)
            ]

        parameters = []
        for network in self.online_locals:
            parameters.extend(list(network.parameters()))
        if self.method == "qmix":
            parameters.extend(list(self.online_mixer.parameters()))
        # Frozen rule: one global L2 norm for all online parameters participating
        # in the cooperative QMIX/VDN loss.
        return [
            float(torch.nn.utils.clip_grad_norm_(parameters, self.gradient_max_norm))
        ]

    def update(self, batch):
        tensors = self._tensor_batch(batch)
        self.optimizer.zero_grad()
        losses, target = self._losses(tensors)
        if self.method == "idqn":
            total_loss = losses[0] + losses[1]
        else:
            total_loss = losses[0]
        total_loss.backward()
        preclip_norms = self._clip_gradients()
        self.optimizer.step()

        self.learner_events += 1
        target_copied = False
        if self.learner_events % self.target_update_frequency == 0:
            self.hard_update_targets()
            target_copied = True
        return {
            "method": self.method,
            "learner_event": self.learner_events,
            "loss": float(total_loss.detach().cpu().item()),
            "component_losses": [
                float(loss.detach().cpu().item()) for loss in losses
            ],
            "target_mean": float(target.detach().mean().cpu().item()),
            "preclip_gradient_norms": preclip_norms,
            "target_hard_copied": target_copied,
        }

    def hard_update_targets(self):
        hard_update(self.target_locals, self.online_locals)
        if self.method == "qmix":
            hard_update(self.target_mixer, self.online_mixer)

    def checkpoint_payload(self, transition_index, config_hash, rng_manifest):
        payload = {
            "method": self.method,
            "transition_index": int(transition_index),
            "learner_events": int(self.learner_events),
            "config_sha256": str(config_hash),
            "rng_namespaces": rng_manifest,
            "online_locals": self.online_locals.state_dict(),
            "target_locals": self.target_locals.state_dict(),
            "optimizer": self.optimizer.state_dict(),
        }
        if self.method == "qmix":
            payload["online_mixer"] = self.online_mixer.state_dict()
            payload["target_mixer"] = self.target_mixer.state_dict()
        return payload

    def save_checkpoint(self, path, transition_index, config_hash, rng_manifest):
        directory = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(directory):
            os.makedirs(directory)
        torch.save(
            self.checkpoint_payload(transition_index, config_hash, rng_manifest), path
        )


def batch_from_replay_sample(sample):
    """Explicit compatibility hook for tests and runners."""
    required = (
        "states", "observations", "actions", "rewards", "next_states",
        "next_observations", "terminated", "elapsed_seconds",
    )
    missing = [name for name in required if name not in sample]
    if missing:
        raise KeyError("Replay sample missing fields: {}".format(missing))
    return {name: np.asarray(value) for name, value in sample.items()}
