import os
import itertools
import numpy as np
import pandas as pd

from scipy.stats import wilcoxon, ttest_rel


OFFSET_QMIX_RAW = "results/raw/multiseed_offset_qmix_per_second_raw.csv"
MAX_PRESSURE_SUMMARY = "results/tables/max_pressure_corridor_2x2_summary.csv"

OUTPUT_SEED_METRICS = "results/tables/scenario_a_seed_level_metrics_with_max_pressure.csv"
OUTPUT_STATS = "results/tables/scenario_a_wilcoxon_ci_tests.csv"

os.makedirs("results/tables", exist_ok=True)


def bootstrap_ci(values, n_boot=10000, alpha=0.05, seed=42):
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=float)

    boot_means = []
    for _ in range(n_boot):
        sample = rng.choice(values, size=len(values), replace=True)
        boot_means.append(np.mean(sample))

    lower = np.percentile(boot_means, 100 * alpha / 2)
    upper = np.percentile(boot_means, 100 * (1 - alpha / 2))
    return lower, upper


def read_offset_qmix_seed_metrics():
    raw = pd.read_csv(OFFSET_QMIX_RAW)

    print("\nAvailable controller names in offset/QMIX raw file:")
    print(raw["controller"].unique())

    seed_metrics = (
        raw.groupby(["controller", "seed"], as_index=False)
        .agg(
            mean_waiting=("total_waiting_time", "mean"),
            mean_speed=("mean_speed", "mean"),
            mean_queue=("total_queue", "mean"),
            mean_vehicles=("vehicle_count", "mean"),
        )
    )

    return seed_metrics


def read_max_pressure_seed_metrics():
    mp = pd.read_csv(MAX_PRESSURE_SUMMARY)
    mp = mp[mp["seed"].astype(str) != "MEAN+-STD"].copy()
    mp["seed"] = mp["seed"].astype(int)
    mp["controller"] = "Max Pressure"

    return mp[["controller", "seed", "mean_waiting", "mean_speed", "mean_queue", "mean_vehicles"]]


def main():
    offset_qmix = read_offset_qmix_seed_metrics()
    max_pressure = read_max_pressure_seed_metrics()

    all_metrics = pd.concat([offset_qmix, max_pressure], ignore_index=True)

    controllers = [
        "Best Offset Fixed-Time 45s",
        "QMIX V2",
        "Max Pressure",
    ]

    available = set(all_metrics["controller"].unique())
    missing = [c for c in controllers if c not in available]
    if missing:
        raise ValueError(
            f"Controller names not found: {missing}\n"
            f"Available names are: {sorted(available)}"
        )

    all_metrics = all_metrics.sort_values(["controller", "seed"]).round(6)
    all_metrics.to_csv(OUTPUT_SEED_METRICS, index=False)

    print("\n=== Seed-level metrics ===")
    print(all_metrics.to_string(index=False))

    rows = []
    metric = "mean_waiting"

    for c1, c2 in itertools.combinations(controllers, 2):
        df1 = all_metrics[all_metrics["controller"] == c1][["seed", metric]].sort_values("seed")
        df2 = all_metrics[all_metrics["controller"] == c2][["seed", metric]].sort_values("seed")

        merged = pd.merge(df1, df2, on="seed", suffixes=("_c1", "_c2"))

        a = merged[f"{metric}_c1"].to_numpy(dtype=float)
        b = merged[f"{metric}_c2"].to_numpy(dtype=float)

        diff = a - b
        percent_diff = (diff / b) * 100.0

        mean_diff = np.mean(diff)
        ci_low, ci_high = bootstrap_ci(diff)

        mean_percent_diff = np.mean(percent_diff)
        pct_ci_low, pct_ci_high = bootstrap_ci(percent_diff)

        w_stat, w_p = wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
        t_stat, t_p = ttest_rel(a, b)

        rows.append({
            "metric": metric,
            "controller_1": c1,
            "controller_2": c2,
            "mean_controller_1": np.mean(a),
            "mean_controller_2": np.mean(b),
            "mean_difference_c1_minus_c2": mean_diff,
            "ci95_low_difference": ci_low,
            "ci95_high_difference": ci_high,
            "mean_percent_difference_vs_c2": mean_percent_diff,
            "ci95_low_percent_difference": pct_ci_low,
            "ci95_high_percent_difference": pct_ci_high,
            "wilcoxon_statistic": w_stat,
            "wilcoxon_p_value": w_p,
            "paired_t_statistic": t_stat,
            "paired_t_p_value": t_p,
            "n_paired_seeds": len(merged),
        })

    stats_df = pd.DataFrame(rows).round(6)
    stats_df.to_csv(OUTPUT_STATS, index=False)

    print("\n=== Scenario A statistical tests ===")
    print(stats_df.to_string(index=False))

    print(f"\nSaved seed-level metrics to: {OUTPUT_SEED_METRICS}")
    print(f"Saved statistical tests to: {OUTPUT_STATS}")


if __name__ == "__main__":
    main()