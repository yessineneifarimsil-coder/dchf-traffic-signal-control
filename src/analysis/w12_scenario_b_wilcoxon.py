"""
W12 bonus: genuine 10-seed paired Wilcoxon for the Scenario B transfer effect.

Reads the per-seed raw log, aggregates to one mean-waiting-time value per
(controller, seed), then runs paired Wilcoxon + bootstrap CI on:
  - transferred vs direct-trained  (the curriculum effect)
  - transferred vs optimized offset (the approximation gap)

At n=10 the two-sided Wilcoxon floor is p=0.002, so a real p<0.05 is attainable
(unlike the n=5 boundary cases).
"""
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

RAW = "results/raw/multiseed_scenario_b_raw.csv"

df = pd.read_csv(RAW)

# Identify the waiting-time column robustly
wait_candidates = [c for c in df.columns if "wait" in c.lower()]
# The per-step total waiting is typically the 4th numeric col; inspect header:
print("Columns:", list(df.columns))

# Expected columns include controller, seed, and a per-step total waiting time.
# We aggregate the per-step waiting to a per-run MEAN (matching the summary CSV).
ctrl_col = [c for c in df.columns if "control" in c.lower()][0]
seed_col = [c for c in df.columns if c.lower() == "seed"][0]

# pick the waiting column: prefer one literally named, else the column the
# summary used (mean_total_waiting_time). Fall back to best guess.
if wait_candidates:
    wcol = wait_candidates[0]
else:
    # 4th column in your snippet was total waiting time
    wcol = df.columns[3]
print(f"Using controller='{ctrl_col}', seed='{seed_col}', waiting='{wcol}'")

# Per (controller, seed) mean waiting time
agg = df.groupby([ctrl_col, seed_col])[wcol].mean().reset_index()

# Pivot: rows=seed, cols=controller
pivot = agg.pivot(index=seed_col, columns=ctrl_col, values=wcol).sort_index()
print("\nPer-seed mean waiting time:")
print(pivot.round(2))

# Map the three controller names (robust to exact strings)
cols = list(pivot.columns)
def find(sub):
    hits = [c for c in cols if sub.lower() in c.lower()]
    return hits[0] if hits else None

offset_c   = find("offset")
transfer_c = find("transfer")
trained_c  = find("trained")

def paired_test(a_name, b_name, label):
    a = pivot[a_name].to_numpy(float)
    b = pivot[b_name].to_numpy(float)
    diff = a - b
    n = len(diff)
    try:
        p = wilcoxon(diff).pvalue
    except ValueError:
        p = float("nan")
    # bootstrap CI on mean difference
    rng = np.random.default_rng(42)
    boot = [np.mean(rng.choice(diff, size=n, replace=True)) for _ in range(10000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"\n=== {label} ===")
    print(f"  n={n} paired seeds")
    print(f"  mean diff ({a_name} - {b_name}) = {diff.mean():.3f} s/veh")
    print(f"  95% bootstrap CI = [{lo:.3f}, {hi:.3f}]")
    print(f"  Wilcoxon p = {p:.5f}  ({'SIGNIFICANT p<0.05' if p<0.05 else 'not <0.05'})")

if trained_c and transfer_c:
    paired_test(trained_c, transfer_c, "Direct-trained vs Transferred (curriculum effect)")
if offset_c and transfer_c:
    paired_test(transfer_c, offset_c, "Transferred vs Optimized offset (approximation gap)")

print("\n[NOTE] At n=10 the Wilcoxon floor is p=0.002, so p<0.05 is attainable.")
