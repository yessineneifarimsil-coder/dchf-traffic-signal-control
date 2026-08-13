"""Classify each checkpoint's greedy policy by anti-phase share.

This version checks whether the anti-phase / synchronized mode classification
is stable across multiple SUMO traffic seeds.

Hypothesis:
Effective checkpoints hold the two agents in opposite phase priorities
(offset-emulating / anti-phase pattern), while failing checkpoints synchronize
them (zero-offset / simultaneous pattern).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "src", "qmix"))
sys.path.insert(0, os.path.join(os.getcwd(), "src", "env", "two_intersections"))

from qmix_agent import QMIXAgent
from two_intersection_env import TwoIntersectionEnv


GAPS = {
    ("qmix", 101): 4.428,
    ("qmix", 102): 4.428,
    ("qmix", 103): 4.428,
    ("qmix", 104): 34.394,
    ("qmix", 105): 42.096,
    ("vdn", 101): 40.928,
    ("vdn", 102): 39.472,
    ("vdn", 103): 4.777,
    ("vdn", 104): 35.129,
    ("vdn", 105): 34.394,
}

TRAFFIC_SEEDS = (0, 1, 2, 3, 4)


def norm(s):
    return [
        s[0] / 100.0,
        s[1] / 100.0,
        s[2],
        s[3] / 100.0,
        s[4] / 100.0,
        s[5],
    ]


def run(path, mixer, seed=0):
    env = TwoIntersectionEnv(
        sumo_binary="sumo",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
        sumo_seed=seed,
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


def anti_phase_share(actions):
    return 100.0 * sum(1 for x in actions if x[0] != x[1]) / len(actions)


print(
    f"{'checkpoint':12s} "
    f"{'gap%':>7s} "
    f"{'anti_mean%':>11s} "
    f"{'anti_min%':>10s} "
    f"{'anti_max%':>10s} "
    f"{'sync_mean%':>10s} "
    f"regime"
)

rows = []

for (mixer, train_seed), gap in GAPS.items():
    path = f"results/raw/{mixer}_corridor_model_v2_seed{train_seed}.pth"

    if not os.path.exists(path):
        print(f"[missing] {path}")
        continue

    shares = []

    for traffic_seed in TRAFFIC_SEEDS:
        actions = run(path, mixer, seed=traffic_seed)
        shares.append(anti_phase_share(actions))

    anti_mean = sum(shares) / len(shares)
    anti_min = min(shares)
    anti_max = max(shares)
    sync_mean = 100.0 - anti_mean

    rows.append(
        (
            f"{mixer}_{train_seed}",
            gap,
            anti_mean,
            anti_min,
            anti_max,
            sync_mean,
        )
    )


for mixer in ("qmix", "vdn"):
    path = f"results/raw/{mixer}_corridor_model_v2.pth"

    if not os.path.exists(path):
        continue

    shares = []

    for traffic_seed in TRAFFIC_SEEDS:
        actions = run(path, mixer, seed=traffic_seed)
        shares.append(anti_phase_share(actions))

    anti_mean = sum(shares) / len(shares)
    anti_min = min(shares)
    anti_max = max(shares)
    sync_mean = 100.0 - anti_mean

    rows.append(
        (
            f"{mixer}_ORIG",
            None,
            anti_mean,
            anti_min,
            anti_max,
            sync_mean,
        )
    )


for name, gap, anti_mean, anti_min, anti_max, sync_mean in sorted(
    rows, key=lambda r: (r[1] is None, r[1] or 0)
):
    gap_text = f"{gap:7.3f}" if gap is not None else "      -"

    if gap is not None and gap <= 5:
        regime = "Effective"
    elif gap is None:
        regime = "published"
    else:
        regime = "Outside"

    print(
        f"{name:12s} "
        f"{gap_text} "
        f"{anti_mean:10.1f}% "
        f"{anti_min:9.1f}% "
        f"{anti_max:9.1f}% "
        f"{sync_mean:9.1f}% "
        f"{regime}"
    )