"""Probe each trained checkpoint on synthetic observations to test whether the
learned policy is state-dependent or has collapsed to a constant joint action."""
import os, sys, itertools
import numpy as np
sys.path.insert(0, os.path.join(os.getcwd(), "src", "qmix"))
from qmix_agent import QMIXAgent

GRID = [0.0, 0.1, 0.3, 0.6, 1.0]          # normalized queue levels
PHASES = [0.0, 1.0]                        # current green indicator

def probe(path, mixer):
    ag = QMIXAgent(n_agents=2, obs_dim=3, state_dim=6, action_dim=2,
                   mixer_type=mixer, batch_size=64)
    ag.load(path); ag.epsilon = 0.0
    seen = {}
    for s1, m1, p1, s2, m2, p2 in itertools.product(
            GRID, GRID, PHASES, GRID, GRID, PHASES):
        obs = [[s1, m1, p1], [s2, m2, p2]]
        a = tuple(ag.select_actions(obs))
        seen[a] = seen.get(a, 0) + 1
    total = sum(seen.values())
    dist = {k: round(100.0 * v / total, 1) for k, v in sorted(seen.items())}
    return len(seen), dist

for mixer, tag in (("qmix", "qmix"), ("vdn", "vdn")):
    for s in (101, 102, 103, 104, 105):
        p = f"results/raw/{tag}_corridor_model_v2_seed{s}.pth"
        if os.path.exists(p):
            n, d = probe(p, mixer)
            flag = "  <-- COLLAPSED" if n == 1 else ""
            print(f"{tag} seed {s}: {n} distinct joint actions over 100 states  {d}{flag}")
    p = f"results/raw/{tag}_corridor_model_v2.pth"
    if os.path.exists(p):
        n, d = probe(p, mixer)
        print(f"{tag} ORIGINAL : {n} distinct joint actions over 100 states  {d}")