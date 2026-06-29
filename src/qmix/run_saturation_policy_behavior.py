"""
REVIEW ITEM #5: Policy-behavior diagnostic at saturation demand.

At saturation (2.0x) the QMIX gap is only 0.44% -- the smallest in the demand sweep.
The reviewer asks whether this "effective" label is genuine coordination or an
artifact of both controllers degenerating to the same near-always-main-green
behavior under capacity pressure. To answer, we report QMIX's phase-activation
frequency at saturation and compare it to:
  (a) the optimized fixed-offset benchmark's phase pattern (which is fixed by the
      90 s cycle: each phase gets a deterministic, near-50/50 green share), and
  (b) a degenerate "always-main-green" baseline.

If QMIX's action distribution is heavily skewed toward main-green (e.g. >85% main
priority) and its decisions are nearly constant, that supports the
"capacity-collapsed" reading: the small gap reflects both controllers being forced
toward the same behavior, not genuine coordination. If QMIX still alternates
meaningfully (closer to balanced, like the N=3 reference ~49/51), the small gap is
not purely degenerate.

It REUSES the proven evaluate_qmix_for_distance (which records action_j1, action_j2
per decision and holds full green) at the saturation config, then tabulates the
action distribution exactly like the N=3 policy-behavior analysis.

Run from repo root:
    conda activate traffic_rl
    python scripts/run_saturation_policy_behavior.py
"""
import os, sys
import numpy as np
import pandas as pd

REPO_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "qmix"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "env", "two_intersections"))

import evaluate_qmix_distance_sensitivity as qdist
if not hasattr(qdist, "np"):
    qdist.np = np

# Saturation cell: d=300 m, demand 2.0x. action 0 = side priority, 1 = main priority
# (per action_to_phase: 0 -> SIDE_GREEN, 1 -> MAIN_GREEN... verify against env labels).
SAT_CONFIG = "sumo_scenarios/two_intersections/demand_sensitivity/demand_saturation/corridor_turning.sumocfg"
MED_CONFIG = "sumo_scenarios/two_intersections/demand_sensitivity/demand_medium/corridor_turning.sumocfg"
SEEDS = [0, 1, 2, 3, 4]
OUT = "results/tables/saturation_policy_behavior_summary.csv"


def action_distribution(config, distance, seed):
    """Run QMIX eval, return per-agent action shares from the recorded decisions."""
    rows, _ = qdist.evaluate_qmix_for_distance(
        distance=distance, sumo_seed=seed,
        sumo_config_override=config, scenario_label="satbehav")
    df = pd.DataFrame(rows)
    # One row per simulation second; collapse to per-decision actions.
    # action_j1 / action_j2 are constant within a decision block, so use unique
    # (decision, action) pairs if a 'decision' column exists, else value_counts on
    # the change points.
    if "decision" in df.columns:
        per_dec = df.drop_duplicates(subset=["decision"])
    else:
        per_dec = df
    out = {}
    for col, name in [("action_j1", "J1"), ("action_j2", "J2")]:
        if col not in per_dec.columns:
            continue
        vc = per_dec[col].value_counts(normalize=True)
        out[name] = {
            "main_priority_share": float(vc.get(1, 0.0) * 100),
            "side_priority_share": float(vc.get(0, 0.0) * 100),
            "n_decisions": int(len(per_dec)),
        }
    return out


def main():
    if not os.path.exists(SAT_CONFIG):
        print(f"[ERROR] missing saturation config: {SAT_CONFIG}")
        return
    os.makedirs("results/tables", exist_ok=True)

    print("=== QMIX action distribution: SATURATION (2.0x) vs MEDIUM (1.0x), d=300m ===")
    summary = []
    for label, config in [("saturation", SAT_CONFIG), ("medium", MED_CONFIG)]:
        if not os.path.exists(config):
            print(f"[WARN] missing {label} config, skipping")
            continue
        # Aggregate main-priority share across seeds for each agent.
        j1_main, j2_main = [], []
        for seed in SEEDS:
            dist = action_distribution(config, 300, seed)
            if "J1" in dist:
                j1_main.append(dist["J1"]["main_priority_share"])
            if "J2" in dist:
                j2_main.append(dist["J2"]["main_priority_share"])
            print(f"  [{label}] seed {seed}: "
                  f"J1 main {dist.get('J1', {}).get('main_priority_share', float('nan')):.1f}% | "
                  f"J2 main {dist.get('J2', {}).get('main_priority_share', float('nan')):.1f}%")
        summary.append({
            "demand": label,
            "J1_main_priority_share_mean": round(float(np.mean(j1_main)), 1) if j1_main else None,
            "J1_main_priority_share_std": round(float(np.std(j1_main, ddof=1)), 1) if len(j1_main) > 1 else 0.0,
            "J2_main_priority_share_mean": round(float(np.mean(j2_main)), 1) if j2_main else None,
            "J2_main_priority_share_std": round(float(np.std(j2_main, ddof=1)), 1) if len(j2_main) > 1 else 0.0,
        })

    df = pd.DataFrame(summary)
    df.to_csv(OUT, index=False)
    print("\n========== SATURATION POLICY-BEHAVIOR SUMMARY ==========")
    print(df.to_string(index=False))
    print(f"\nSaved to: {OUT}")
    print("\nINTERPRETATION:")
    print("  If saturation main-priority share is much higher and more skewed than")
    print("  medium (e.g. >85% vs ~50%), QMIX has collapsed toward always-main-green")
    print("  -> the small saturation gap is capacity-collapsed, not coordination.")
    print("  If saturation share stays balanced like medium, the policy still alternates.")
    print("\nSend me this table and I will integrate the correct interpretation.")


if __name__ == "__main__":
    main()
