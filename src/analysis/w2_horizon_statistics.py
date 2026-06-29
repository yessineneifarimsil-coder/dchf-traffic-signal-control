"""
W2 — Homogenized statistical testing for the DCHF horizon experiments.

HONEST DESIGN (this is the whole point of W2):
  - Where genuine PAIRED per-seed data exists (offset, QMIX, sim under common
    seeds), run a real paired Wilcoxon signed-rank test + paired bootstrap CI.
    -> This is the case for the multi-seed horizon BOUNDARY validation cases
       (two-intersection spatial d=300m & d=1000m; three-intersection
       third-light d23=500m & d23=1000m), which have 5 paired seeds each.
  - Where only Max Pressure has per-seed data and offset/QMIX are single
    reference outputs (the MP demand & spatial sweeps), report bootstrap /
    normal-approx CIs and label them DIAGNOSTIC, NOT paired tests.

This produces exactly the evidence the paper can defend, and labels each row's
evidence level so no result is overclaimed.

Run from repo root:
    conda activate traffic_rl
    python scripts/w2_horizon_statistics.py
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

RNG = np.random.default_rng(42)
BOOTSTRAP_B = 10000
TABLE_DIR = "results/tables"
OUT_DIR = "results/tables"
os.makedirs(OUT_DIR, exist_ok=True)


def bootstrap_ci(values, statistic=np.mean, b=BOOTSTRAP_B, alpha=0.05):
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) == 0:
        return np.nan, np.nan, np.nan
    if len(values) == 1:
        return float(statistic(values)), np.nan, np.nan
    boot = np.array([statistic(RNG.choice(values, size=len(values), replace=True))
                     for _ in range(b)])
    return (float(statistic(values)),
            float(np.percentile(boot, 100 * alpha / 2)),
            float(np.percentile(boot, 100 * (1 - alpha / 2))))


def classify_gap(gap):
    if gap <= 5:  return "Effective"
    if gap <= 10: return "Marginal"
    return "Outside horizon"


# ============================================================
# PART 1 — GENUINE PAIRED WILCOXON on boundary validation cases
# (offset, QMIX, sim all evaluated under the SAME 5 seeds)
# ============================================================

def analyze_paired_boundary_cases():
    path = f"{TABLE_DIR}/multiseed_horizon_validation_seed_metrics.csv"
    if not os.path.exists(path):
        print(f"[WARN] Missing {path}")
        return pd.DataFrame()

    df = pd.read_csv(path)
    rows = []

    for (block, scenario), g in df.groupby(["validation_block", "scenario"]):
        g = g.sort_values("seed")
        offset = g["optimized_offset_waiting_time"].to_numpy(float)
        qmix   = g["qmix_waiting_time"].to_numpy(float)

        # Paired comparison: optimized offset vs QMIX (both real, common seeds)
        diff = offset - qmix
        diff = diff[~np.isnan(diff)]
        n = len(diff)

        if n >= 2:
            # Wilcoxon needs non-zero differences; guard against all-equal
            try:
                p = float(wilcoxon(diff).pvalue)
            except ValueError:
                p = np.nan
        else:
            p = np.nan

        # HONEST NOTE on n=5: the two-sided Wilcoxon p-value floor is 0.0625,
        # so p<0.05 is mathematically UNREACHABLE with 5 seeds even for a
        # perfectly consistent large effect. The bootstrap CI is therefore the
        # primary inferential statistic; Wilcoxon is reported as a consistency
        # check (a floor p=0.0625 means all 5 seeds agreed in sign).
        wilcoxon_note = ("p floor=0.0625 at n=5; value at floor = all seeds agree in sign"
                         if (not np.isnan(p) and abs(p - 0.0625) < 1e-9)
                         else "")

        mean_diff, ci_low, ci_high = bootstrap_ci(diff)

        # Also CI on the QMIX gap (%) across seeds
        gap_col = "qmix_gap_vs_optimized_offset_percent"
        gap_mean, gap_low, gap_high = bootstrap_ci(g[gap_col].to_numpy(float))

        # The KEY regime-robustness statistic: does the gap CI stay on one side
        # of the 5% / 10% thresholds? That is what makes the classification robust.
        if not np.isnan(gap_high) and gap_high <= 5:
            regime_robust = "Effective (CI entirely <=5%)"
        elif not np.isnan(gap_low) and gap_low > 10:
            regime_robust = "Outside horizon (CI entirely >10%)"
        elif not np.isnan(gap_low) and not np.isnan(gap_high) and gap_low > 5 and gap_high <= 10:
            regime_robust = "Marginal (CI entirely in 5-10%)"
        else:
            regime_robust = "Boundary-straddling (CI crosses a threshold)"

        rows.append({
            "dimension": block,
            "condition": scenario,
            "comparison": "optimized_offset_vs_qmix",
            "n_paired_seeds": n,
            "mean_waiting_diff_offset_minus_qmix": round(mean_diff, 3),
            "diff_ci95_low": round(ci_low, 3) if not np.isnan(ci_low) else np.nan,
            "diff_ci95_high": round(ci_high, 3) if not np.isnan(ci_high) else np.nan,
            "wilcoxon_p": p,
            "wilcoxon_note": wilcoxon_note,
            "qmix_gap_pct_mean": round(gap_mean, 3),
            "qmix_gap_pct_ci95_low": round(gap_low, 3) if not np.isnan(gap_low) else np.nan,
            "qmix_gap_pct_ci95_high": round(gap_high, 3) if not np.isnan(gap_high) else np.nan,
            "qmix_dchf_regime": classify_gap(gap_mean),
            "regime_robustness": regime_robust,
            "evidence_level": "PAIRED Wilcoxon + paired bootstrap CI (common seeds)",
        })

    return pd.DataFrame(rows)


# ============================================================
# PART 2 — DIAGNOSTIC CIs on the MP sweeps
# (MP has 5 seeds; offset/QMIX are single reference outputs -> NOT paired)
# ============================================================

def analyze_mp_sweep(kind):
    """kind = 'demand' or 'spatial'"""
    comp_path = f"{TABLE_DIR}/max_pressure_{kind}_comparison.csv"
    if not os.path.exists(comp_path):
        print(f"[WARN] Missing {comp_path}")
        return pd.DataFrame()

    comp = pd.read_csv(comp_path)
    cond_col = "demand_scenario" if kind == "demand" else "distance_m"
    rows = []

    for _, r in comp.iterrows():
        cond = r[cond_col]
        offset = float(r["offset_waiting"])
        mp_mean = float(r["mp_waiting_mean"])
        mp_std  = float(r["mp_waiting_std"])
        g_mp    = float(r["G_MP_pct"])
        g_qmix  = float(r["G_QMIX_pct"])

        # Normal-approx 95% CI from 5-seed mean +/- std (we have mean & std, not raw)
        n = 5
        half = 1.96 * mp_std / np.sqrt(n) if mp_std > 0 else np.nan
        ci_low = mp_mean - half
        ci_high = mp_mean + half
        gap_low  = (ci_low - offset) / offset * 100 if not np.isnan(half) else np.nan
        gap_high = (ci_high - offset) / offset * 100 if not np.isnan(half) else np.nan

        rows.append({
            "dimension": kind,
            "condition": str(cond),
            "comparison": "max_pressure_vs_offset_reference",
            "n_mp_seeds": n,
            "mp_waiting_mean": round(mp_mean, 3),
            "mp_waiting_ci95_low": round(ci_low, 3) if not np.isnan(ci_low) else np.nan,
            "mp_waiting_ci95_high": round(ci_high, 3) if not np.isnan(ci_high) else np.nan,
            "G_MP_pct_mean": round(g_mp, 3),
            "G_MP_pct_ci95_low": round(gap_low, 3) if not np.isnan(gap_low) else np.nan,
            "G_MP_pct_ci95_high": round(gap_high, 3) if not np.isnan(gap_high) else np.nan,
            "G_QMIX_pct_reference": round(g_qmix, 3),
            "mp_dchf_regime": classify_gap(g_mp),
            "evidence_level": "DIAGNOSTIC: MP 5-seed CI vs single-seed offset/QMIX reference (NOT paired)",
        })

    return pd.DataFrame(rows)


def main():
    paired = analyze_paired_boundary_cases()
    mp_demand = analyze_mp_sweep("demand")
    mp_spatial = analyze_mp_sweep("spatial")

    paired_path = f"{OUT_DIR}/w2_paired_wilcoxon_boundary_cases.csv"
    diag_path = f"{OUT_DIR}/w2_mp_sweep_diagnostic_ci.csv"

    paired.to_csv(paired_path, index=False)
    pd.concat([mp_demand, mp_spatial], ignore_index=True).to_csv(diag_path, index=False)

    print("\n[DONE] W2 outputs written:")
    print(f"  {paired_path}   <- GENUINE paired Wilcoxon (boundary cases)")
    print(f"  {diag_path}     <- DIAGNOSTIC CIs (MP sweeps, not paired)")

    if not paired.empty:
        print("\n=== PAIRED WILCOXON (offset vs QMIX, common 5 seeds) ===")
        for _, r in paired.iterrows():
            print(f"  {r['dimension']} | {r['condition']}")
            print(f"    gap={r['qmix_gap_pct_mean']}% "
                  f"[{r['qmix_gap_pct_ci95_low']}, {r['qmix_gap_pct_ci95_high']}] "
                  f"| Wilcoxon p={r['wilcoxon_p']} | {r['qmix_dchf_regime']}")

    print("\n[INTERPRETATION]")
    print("  - Boundary cases: report as PAIRED Wilcoxon tests (real, common seeds).")
    print("  - MP sweeps: report as 5-seed CIs vs reference; NOT paired Wilcoxon.")
    print("  - This labeling is what makes W2 defensible.")


if __name__ == "__main__":
    main()
