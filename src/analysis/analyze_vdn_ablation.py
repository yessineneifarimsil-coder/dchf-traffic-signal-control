import os
import numpy as np
import pandas as pd


# =========================
# Paths
# =========================
VDN_SEED_METRICS = "results/tables/multiseed_vdn_per_second_seed_metrics.csv"
OFFSET_QMIX_RAW = "results/raw/multiseed_offset_qmix_per_second_raw.csv"

OUTPUT_GAP = "results/tables/vdn_ablation_gap.csv"

# NOTE: these two labels MUST match the exact strings in the raw CSV's
# 'controller' column. Verify with the check command before running:
#   python -c "import pandas as pd; df=pd.read_csv(r'results\raw\multiseed_offset_qmix_per_second_raw.csv'); print(df['controller'].drop_duplicates().tolist())"
OFFSET_LABEL = "Best Offset Fixed-Time 45s"
QMIX_LABEL = "QMIX V2"
VDN_LABEL = "VDN"

N_BOOTSTRAP = 10000
BOOTSTRAP_SEED = 12345  # seeds ONLY the post-hoc bootstrap resampling, not the experiment

# Cross-check tolerances against the manuscript reference values
OFFSET_REF = 169.782
QMIX_REF = 177.291
QMIX_GAP_REF = 4.42
WAITING_TOL = 0.5     # absolute seconds
GAP_TOL = 0.5         # absolute percentage points


def per_seed_mean_waiting(raw_df, controller_label):
    """
    Reproduce the per-seed mean_total_waiting_time exactly as the multiseed
    summary was built: for the given controller, group per-second rows by seed
    and take the mean of total_waiting_time. Returns a Series indexed by seed.
    """
    sub = raw_df[raw_df["controller"] == controller_label]
    return sub.groupby("seed")["total_waiting_time"].mean()


def gap_ratio_of_means(learned_by_seed, offset_by_seed, seeds):
    """
    Manuscript gap definition (Eq. 5), seed-averaged:
        G = (mean_s J_learned(s) - mean_s J_off(s)) / mean_s J_off(s) * 100
    Ratio of seed-averaged means, NOT the mean of per-seed ratios.
    """
    j_learned = np.array([learned_by_seed.loc[s] for s in seeds])
    j_off = np.array([offset_by_seed.loc[s] for s in seeds])
    return (j_learned.mean() - j_off.mean()) / j_off.mean() * 100.0


def per_seed_gaps_diagnostic(learned_by_seed, offset_by_seed, seeds):
    """Per-seed percentage gaps, printed as a diagnostic only (not the reported G)."""
    return np.array([
        (learned_by_seed.loc[s] - offset_by_seed.loc[s]) / offset_by_seed.loc[s] * 100.0
        for s in seeds
    ])


def paired_bootstrap_ci_ratio_of_means(learned_by_seed, offset_by_seed, seeds,
                                       n_boot=N_BOOTSTRAP, seed=BOOTSTRAP_SEED):
    """
    Paired bootstrap 95% CI on the ratio-of-means gap.
    Each replicate: resample seed indices with replacement, recompute BOTH
    seed-means over the sampled seeds, then the ratio-of-means gap.
    """
    rng = np.random.RandomState(seed)
    j_learned = np.array([learned_by_seed.loc[s] for s in seeds])
    j_off = np.array([offset_by_seed.loc[s] for s in seeds])
    n = len(seeds)

    boot_gaps = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        m_learned = j_learned[idx].mean()
        m_off = j_off[idx].mean()
        boot_gaps[b] = (m_learned - m_off) / m_off * 100.0

    lo = np.percentile(boot_gaps, 2.5)
    hi = np.percentile(boot_gaps, 97.5)
    return lo, hi


def classify_regime(gap_percent):
    """DCHF gap-based regime (Eq. 6), using G <= delta (not |G|)."""
    if gap_percent <= 5.0:
        return "Effective"
    elif gap_percent <= 10.0:
        return "Marginal"
    else:
        return "Outside horizon"


def main():
    os.makedirs("results/tables", exist_ok=True)

    # ---- Load VDN per-seed ----
    vdn_seed = pd.read_csv(VDN_SEED_METRICS)
    vdn_by_seed = vdn_seed.set_index("seed")["mean_total_waiting_time"]

    # ---- Load offset + QMIX per-seed from raw ----
    raw = pd.read_csv(OFFSET_QMIX_RAW)

    controllers_present = raw["controller"].drop_duplicates().tolist()
    assert OFFSET_LABEL in controllers_present, (
        "OFFSET_LABEL '{}' not in raw CSV. Present: {}".format(OFFSET_LABEL, controllers_present)
    )
    assert QMIX_LABEL in controllers_present, (
        "QMIX_LABEL '{}' not in raw CSV. Present: {}".format(QMIX_LABEL, controllers_present)
    )

    offset_by_seed = per_seed_mean_waiting(raw, OFFSET_LABEL)
    qmix_by_seed = per_seed_mean_waiting(raw, QMIX_LABEL)

    # ---- Assertions: seed counts and identical seed sets ----
    offset_seeds = set(offset_by_seed.index.tolist())
    qmix_seeds = set(qmix_by_seed.index.tolist())
    vdn_seeds = set(vdn_by_seed.index.tolist())

    assert len(offset_seeds) == 10, "offset seeds != 10: {}".format(sorted(offset_seeds))
    assert len(qmix_seeds) == 10, "qmix seeds != 10: {}".format(sorted(qmix_seeds))
    assert len(vdn_seeds) == 10, "vdn seeds != 10: {}".format(sorted(vdn_seeds))
    assert offset_seeds == qmix_seeds == vdn_seeds, (
        "seed sets differ: offset={}, qmix={}, vdn={}".format(
            sorted(offset_seeds), sorted(qmix_seeds), sorted(vdn_seeds)
        )
    )

    seeds = sorted(offset_seeds)

    # ---- Cross-check recomputed means against manuscript ----
    offset_mean = offset_by_seed.mean()
    qmix_mean = qmix_by_seed.mean()

    assert abs(offset_mean - OFFSET_REF) < WAITING_TOL, (
        "offset mean {:.3f} != manuscript {:.3f}".format(offset_mean, OFFSET_REF)
    )
    assert abs(qmix_mean - QMIX_REF) < WAITING_TOL, (
        "qmix mean {:.3f} != manuscript {:.3f}".format(qmix_mean, QMIX_REF)
    )

    # ---- QMIX gap cross-check (ratio-of-means) ----
    qmix_gap = gap_ratio_of_means(qmix_by_seed, offset_by_seed, seeds)
    qmix_gap_diag = per_seed_gaps_diagnostic(qmix_by_seed, offset_by_seed, seeds)
    qmix_lo, qmix_hi = paired_bootstrap_ci_ratio_of_means(qmix_by_seed, offset_by_seed, seeds)

    assert abs(qmix_gap - QMIX_GAP_REF) < GAP_TOL, (
        "qmix gap {:.3f}% != manuscript {:.3f}%".format(qmix_gap, QMIX_GAP_REF)
    )

    # ---- VDN gap (ratio-of-means) ----
    vdn_mean = vdn_by_seed.mean()
    vdn_gap = gap_ratio_of_means(vdn_by_seed, offset_by_seed, seeds)
    vdn_gap_diag = per_seed_gaps_diagnostic(vdn_by_seed, offset_by_seed, seeds)
    vdn_lo, vdn_hi = paired_bootstrap_ci_ratio_of_means(vdn_by_seed, offset_by_seed, seeds)

    # ---- Report ----
    print("Seeds:", seeds)
    print()
    print("Offset per-seed mean waiting:")
    print(offset_by_seed.round(3).to_string())
    print(f"Offset seed-averaged mean: {offset_mean:.3f}  (manuscript {OFFSET_REF})")
    print(f"QMIX   seed-averaged mean: {qmix_mean:.3f}  (manuscript {QMIX_REF})")
    print(f"VDN    seed-averaged mean: {vdn_mean:.3f}")
    print()
    print("=== QMIX V2 cross-check (ratio-of-means gap) ===")
    print(f"Per-seed gaps (diagnostic, %): {np.round(qmix_gap_diag, 3).tolist()}")
    print(f"Reported gap (ratio of means): {qmix_gap:.3f}%  95% CI [{qmix_lo:.3f}, {qmix_hi:.3f}]")
    print(f"Regime: {classify_regime(qmix_gap)}  (manuscript ~4.42%, Effective)")
    print()
    print("=== VDN ablation result (ratio-of-means gap) ===")
    print(f"Per-seed gaps (diagnostic, %): {np.round(vdn_gap_diag, 3).tolist()}")
    print(f"Reported gap (ratio of means): {vdn_gap:.3f}%  95% CI [{vdn_lo:.3f}, {vdn_hi:.3f}]")
    print(f"Regime: {classify_regime(vdn_gap)}")
    print()

    out = pd.DataFrame([
        {
            "controller": "QMIX V2",
            "n_seeds": len(seeds),
            "offset_mean_waiting": round(offset_mean, 3),
            "learned_mean_waiting": round(qmix_mean, 3),
            "gap_percent": round(qmix_gap, 3),
            "gap_ci_low": round(qmix_lo, 3),
            "gap_ci_high": round(qmix_hi, 3),
            "dchf_regime": classify_regime(qmix_gap),
        },
        {
            "controller": "VDN",
            "n_seeds": len(seeds),
            "offset_mean_waiting": round(offset_mean, 3),
            "learned_mean_waiting": round(vdn_mean, 3),
            "gap_percent": round(vdn_gap, 3),
            "gap_ci_low": round(vdn_lo, 3),
            "gap_ci_high": round(vdn_hi, 3),
            "dchf_regime": classify_regime(vdn_gap),
        },
    ])

    out.to_csv(OUTPUT_GAP, index=False)
    print(f"Gap table saved to: {OUTPUT_GAP}")
    print()
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()