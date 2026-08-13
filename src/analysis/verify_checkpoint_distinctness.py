"""Decide between redirect failure and distinct weights inducing the same
greedy policy. Tests both QMIX and VDN checkpoints.

Test 1: tensor fingerprints.
Test 2: greedy action traces on the realized SUMO trajectory.
"""
import os
import sys
import hashlib
import numpy as np
import torch

sys.path.insert(0, os.path.join(os.getcwd(), "src", "qmix"))
sys.path.insert(0, os.path.join(os.getcwd(), "src", "env", "two_intersections"))

from qmix_agent import QMIXAgent
from two_intersection_env import TwoIntersectionEnv


CKPTS = []

for s in (101, 102, 103, 104, 105):
    CKPTS.append(("qmix", s, f"results/raw/qmix_corridor_model_v2_seed{s}.pth"))

for s in (101, 102, 103, 104, 105):
    CKPTS.append(("vdn", s, f"results/raw/vdn_corridor_model_v2_seed{s}.pth"))

CKPTS.append(("qmix", "ORIG", "results/raw/qmix_corridor_model_v2.pth"))
CKPTS.append(("vdn", "ORIG", "results/raw/vdn_corridor_model_v2.pth"))


def weight_fingerprint(path):
    c = torch.load(path, map_location="cpu")
    h = hashlib.sha256()

    def visit(name, obj):
        if torch.is_tensor(obj):
            h.update(name.encode())
            h.update(str(tuple(obj.shape)).encode())
            h.update(np.ascontiguousarray(obj.detach().cpu().numpy()).tobytes())

        elif isinstance(obj, dict):
            for k in sorted(obj.keys()):
                visit(f"{name}/{k}", obj[k])

        elif isinstance(obj, (list, tuple)):
            for i, item in enumerate(obj):
                visit(f"{name}[{i}]", item)

        elif isinstance(obj, (int, float, str, bool, type(None))):
            h.update(name.encode())
            h.update(str(obj).encode())

    visit("checkpoint", c)
    return h.hexdigest()[:16]


def norm(st):
    return [
        st[0] / 100.0,
        st[1] / 100.0,
        st[2],
        st[3] / 100.0,
        st[4] / 100.0,
        st[5],
    ]


def trace(path, mixer, traffic_seed=0):
    env = TwoIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
        sumo_seed=traffic_seed,
    )

    ag = QMIXAgent(
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
        mixer_type=mixer,
        batch_size=64,
    )

    ag.load(path)
    ag.epsilon = 0.0

    g = norm(env.reset())
    obs = [g[0:3], g[3:6]]

    acts = []

    try:
        while env.step_count < 3600:
            a = tuple(ag.select_actions(obs))
            acts.append(a)

            env.step(list(a))

            g = norm(env.get_state())
            obs = [g[0:3], g[3:6]]
    finally:
        env.close()

    return acts


print("=== TEST 1: weight tensor fingerprints ===")
seen = {}

for mixer, seed, path in CKPTS:
    if os.path.exists(path):
        fp = weight_fingerprint(path)
        key = f"{mixer}_{seed}"
        seen[key] = fp
        print(f"{key:12s}: {fp}")
    else:
        print(f"{mixer}_{seed:>5}: missing")


print("\nDuplicate fingerprints:")
for a in seen:
    for b in seen:
        if a < b and seen[a] == seen[b]:
            print(f"  DUPLICATE: {a} == {b} ({seen[a]})")


print("\n=== TEST 2: greedy action traces, traffic seed 0 ===")
traces = {}

for mixer, seed, path in CKPTS:
    if os.path.exists(path):
        key = f"{mixer}_{seed}"
        acts = trace(path, mixer, traffic_seed=0)
        traces[key] = acts
        unique = sorted(set(acts))
        print(f"{key:12s}: {len(acts)} decisions, unique={unique}, first12={acts[:12]}")


print("\n=== Pairwise action-sequence comparison, traffic seed 0 ===")
keys = list(traces.keys())

for i in range(len(keys)):
    for j in range(i + 1, len(keys)):
        a = traces[keys[i]]
        b = traces[keys[j]]
        same = sum(1 for x, y in zip(a, b) if x == y)
        if a == b:
            verdict = "IDENTICAL"
        else:
            verdict = f"{same}/{min(len(a), len(b))} match"
        print(f"{keys[i]:12s} vs {keys[j]:12s}: {verdict}")