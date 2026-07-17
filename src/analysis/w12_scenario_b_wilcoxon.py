"""
W12 bonus: genuine 10-seed paired Wilcoxon tests for the
Scenario B transfer effect.

Reads the per-second Scenario B raw results, aggregates them to one
mean network-waiting value per (controller, seed), and evaluates:

1. Direct-trained QMIX versus transferred QMIX.
2. Transferred QMIX versus the optimized fixed offset.

The script saves both the paired seed-level values and the statistical
test results used by the manuscript.
"""

import os

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon


RAW = "results/raw/multiseed_scenario_b_raw.csv"

OUT_SEEDS = (
    "results/tables/"
    "scenario_b_paired_seed_mean_waiting.csv"
)

OUT_TESTS = (
    "results/tables/"
    "scenario_b_paired_wilcoxon_tests.csv"
)

BOOTSTRAP_REPLICATIONS = 10_000
BOOTSTRAP_SEED = 42

os.makedirs("results/tables", exist_ok=True)

df = pd.read_csv(RAW)

print("Columns:", list(df.columns))

# Identify required columns.
ctrl_candidates = [
    c for c in df.columns
    if "control" in c.lower()
]

seed_candidates = [
    c for c in df.columns
    if c.lower() == "seed"
]

wait_candidates = [
    c for c in df.columns
    if "wait" in c.lower()
]

if not ctrl_candidates:
    raise ValueError(
        "No controller column found in the Scenario B raw file."
    )

if not seed_candidates:
    raise ValueError(
        "No seed column found in the Scenario B raw file."
    )

if not wait_candidates:
    raise ValueError(
        "No waiting-time column found in the Scenario B raw file."
    )

ctrl_col = ctrl_candidates[0]
seed_col = seed_candidates[0]

# Preserve the historical selection rule used by the original script:
# use the first column whose name contains "wait".
wcol = wait_candidates[0]

print(
    f"Using controller='{ctrl_col}', "
    f"seed='{seed_col}', waiting='{wcol}'"
)

# Aggregate the per-second records to one mean value per
# controller and traffic seed.
agg = (
    df.groupby(
        [ctrl_col, seed_col],
        as_index=False,
    )[wcol]
    .mean()
)

# Rows = seed, columns = controller.
pivot = (
    agg.pivot(
        index=seed_col,
        columns=ctrl_col,
        values=wcol,
    )
    .sort_index()
)

print("\nPer-seed mean waiting time:")
print(pivot.round(3))

# Save the paired seed-level values.
pivot.reset_index().to_csv(
    OUT_SEEDS,
    index=False,
)


controller_names = list(pivot.columns)


def find_controller(substring):
    """Return the first controller name containing substring."""
    matches = [
        name
        for name in controller_names
        if substring.lower() in name.lower()
    ]

    if not matches:
        return None

    return matches[0]


offset_controller = find_controller("offset")
transfer_controller = find_controller("transfer")
trained_controller = find_controller("trained")

required_controllers = {
    "optimized offset": offset_controller,
    "transferred QMIX": transfer_controller,
    "direct-trained QMIX": trained_controller,
}

missing_controllers = [
    label
    for label, name in required_controllers.items()
    if name is None
]

if missing_controllers:
    raise ValueError(
        "Could not identify the following controllers: "
        + ", ".join(missing_controllers)
        + ". Available controllers: "
        + ", ".join(map(str, controller_names))
    )


test_results = []


def paired_test(
    controller_a,
    controller_b,
    comparison_label,
):
    """
    Test paired differences defined as controller A minus controller B.
    """
    values_a = pivot[controller_a].to_numpy(dtype=float)
    values_b = pivot[controller_b].to_numpy(dtype=float)

    if len(values_a) != len(values_b):
        raise ValueError(
            f"Unequal paired sample sizes for {comparison_label}."
        )

    differences = values_a - values_b
    n_seeds = len(differences)

    try:
        p_value = float(
            wilcoxon(
                differences,
                alternative="two-sided",
            ).pvalue
        )
    except ValueError:
        p_value = float("nan")

    rng = np.random.default_rng(BOOTSTRAP_SEED)

    bootstrap_means = np.empty(
        BOOTSTRAP_REPLICATIONS,
        dtype=float,
    )

    for index in range(BOOTSTRAP_REPLICATIONS):
        bootstrap_sample = rng.choice(
            differences,
            size=n_seeds,
            replace=True,
        )

        bootstrap_means[index] = (
            bootstrap_sample.mean()
        )

    ci_low, ci_high = np.percentile(
        bootstrap_means,
        [2.5, 97.5],
    )

    mean_difference = float(differences.mean())

    result = {
        "comparison": comparison_label,
        "controller_a": controller_a,
        "controller_b": controller_b,
        "difference_definition": (
            "controller_a_minus_controller_b"
        ),
        "n_paired_seeds": n_seeds,
        "mean_difference_seconds": mean_difference,
        "bootstrap_ci_low_seconds": float(ci_low),
        "bootstrap_ci_high_seconds": float(ci_high),
        "wilcoxon_p_value": p_value,
        "wilcoxon_alternative": "two-sided",
        "bootstrap_replications": BOOTSTRAP_REPLICATIONS,
        "bootstrap_seed": BOOTSTRAP_SEED,
    }

    test_results.append(result)

    print(f"\n=== {comparison_label} ===")
    print(f"  n = {n_seeds} paired seeds")
    print(
        f"  mean difference "
        f"({controller_a} - {controller_b}) "
        f"= {mean_difference:.3f} s"
    )
    print(
        f"  95% bootstrap CI "
        f"= [{ci_low:.3f}, {ci_high:.3f}]"
    )
    print(
        f"  Wilcoxon p = {p_value:.5f} "
        f"({'SIGNIFICANT p<0.05' if p_value < 0.05 else 'not <0.05'})"
    )


paired_test(
    trained_controller,
    transfer_controller,
    "Direct-trained versus transferred QMIX",
)

paired_test(
    transfer_controller,
    offset_controller,
    "Transferred QMIX versus optimized offset",
)

test_df = pd.DataFrame(test_results)

test_df.to_csv(
    OUT_TESTS,
    index=False,
)

print("\nSaved statistical evidence:")
print(f"  {OUT_SEEDS}")
print(f"  {OUT_TESTS}")

print(
    "\n[NOTE] At n=10, the minimum attainable "
    "two-sided Wilcoxon p-value is approximately 0.002."
)