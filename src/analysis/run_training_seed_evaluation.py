"""
Training-seed replication campaign -- EVALUATION stage.

Reviewer item #1: every learned configuration in the manuscript is represented
by ONE trained network, so the published confidence intervals characterize
traffic-realization variability only. This script closes that gap for the
two-intersection reference condition and the mixer ablation.

WHAT IT DOES
    For each of the 10 checkpoints produced by the seeded training campaign
    (QMIX 101-105, VDN 101-105), evaluate the FROZEN policy across the same
    10 common SUMO traffic seeds used in the published Scenario A comparison,
    and compute the approximation gap against the published optimized 45 s
    fixed-offset benchmark.

    100 evaluation episodes total (10 checkpoints x 10 traffic seeds).

WHAT IT DELIBERATELY DOES NOT DO
    * It does not re-run the fixed-offset benchmark. The offset controller is
      deterministic given the seed and was already evaluated over these ten
      seeds; its per-seed waiting values are read from the committed
      multiseed_offset_qmix_per_second_raw.csv so the gap denominators are
      IDENTICAL to the published ones.
    * It does not touch the validated evaluation loops. run_qmix_v2_per_second
      and run_vdn_v2_per_second are imported and reused as-is; only the
      module-level checkpoint constant is redirected per checkpoint.
    * It does not fold in the ORIGINAL unseeded checkpoint. That policy is
      reported separately as the selected reference policy, shown as a labelled
      point against the seeded distribution -- never averaged into it.

OUTPUT
    results/tables/training_seed_eval_raw.csv
        one row per (algorithm, train_seed, traffic_seed)
    results/tables/training_seed_eval_summary.csv
        one row per (algorithm, train_seed): mean gap over traffic seeds
    results/tables/training_seed_eval_distribution.csv
        one row per algorithm: mean and spread ACROSS TRAINING SEEDS -- this is
        the table that answers the reviewer.

Run from repo root:
    conda activate traffic_rl
    python src\\analysis\\run_training_seed_evaluation.py
"""
import os
import sys
import csv

import numpy as np
import pandas as pd

REPO_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "baselines", "two_intersections"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "qmix"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "env", "two_intersections"))

import evaluate_multiseed_offset_qmix_per_second as qeval
import evaluate_multiseed_vdn_per_second as veval

TRAIN_SEEDS = [101, 102, 103, 104, 105]
TRAFFIC_SEEDS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

QMIX_CKPT = "results/raw/qmix_corridor_model_v2_seed{}.pth"
VDN_CKPT = "results/raw/vdn_corridor_model_v2_seed{}.pth"

# Published per-seed optimized-offset waiting values (ten-seed Scenario A).
OFFSET_REF_RAW = "results/raw/multiseed_offset_qmix_per_second_raw.csv"

# Published reference numbers, for the labelled comparison point.
PUBLISHED_OFFSET_MEAN = 169.782
PUBLISHED_QMIX_MEAN = 177.291
PUBLISHED_QMIX_GAP = 4.42
PUBLISHED_VDN_MEAN = 241.235
PUBLISHED_VDN_GAP = 42.09

OUT_RAW = "results/tables/training_seed_eval_raw.csv"
OUT_SUMMARY = "results/tables/training_seed_eval_summary.csv"
OUT_DIST = "results/tables/training_seed_eval_distribution.csv"


def load_offset_reference():
    """Per-traffic-seed optimized-offset waiting values from the committed
    published campaign, so gap denominators match the paper exactly."""
    if not os.path.exists(OFFSET_REF_RAW):
        raise FileNotFoundError(
            f"{OFFSET_REF_RAW} not found. The gap denominators must come from "
            "the published offset campaign, not be recomputed."
        )
    df = pd.read_csv(OFFSET_REF_RAW)
    controllers = df["controller"].drop_duplicates().tolist()
    offset_names = [c for c in controllers
                    if "offset" in str(c).lower() or "fixed" in str(c).lower()]
    if not offset_names:
        raise ValueError(f"No offset controller found. Controllers: {controllers}")
    name = offset_names[0]
    sub = df[df["controller"] == name]
    ref = sub.groupby("seed")["total_waiting_time"].mean().to_dict()
    print(f"Offset reference controller: '{name}'")
    print(f"Offset per-seed means: "
          f"{ {k: round(v, 3) for k, v in sorted(ref.items())} }")
    mean_all = float(np.mean(list(ref.values())))
    print(f"Offset mean over seeds: {mean_all:.3f} "
          f"(published {PUBLISHED_OFFSET_MEAN})")
    if abs(mean_all - PUBLISHED_OFFSET_MEAN) > 0.05:
        print("[WARN] offset mean does not match the published value. "
              "Check the controller label before trusting any gap.")
    return ref


def evaluate_checkpoint(algorithm, train_seed, offset_ref):
    """Evaluate one frozen checkpoint over the ten traffic seeds."""
    if algorithm == "QMIX":
        path = QMIX_CKPT.format(train_seed)
        module, runner, const = qeval, qeval.run_qmix_v2_per_second, "QMIX_V2_MODEL"
    else:
        path = VDN_CKPT.format(train_seed)
        module, runner, const = veval, veval.run_vdn_v2_per_second, "VDN_V2_MODEL"

    if not os.path.exists(path):
        raise FileNotFoundError(path)

    original = getattr(module, const)
    setattr(module, const, path)
    print(f"\n===== {algorithm} train_seed {train_seed} -> {path} =====")

    rows = []
    try:
        for ts in TRAFFIC_SEEDS:
            _, summary = runner(ts)
            wt = float(summary["mean_total_waiting_time"])
            off = offset_ref[ts]
            gap = (wt - off) / off * 100
            rows.append({
                "algorithm": algorithm,
                "train_seed": train_seed,
                "traffic_seed": ts,
                "offset_wt": round(off, 3),
                "learned_wt": round(wt, 3),
                "gap_pct": round(gap, 4),
            })
            print(f"  traffic seed {ts}: wt={wt:.3f} offset={off:.3f} "
                  f"gap={gap:+.3f}%")
    finally:
        setattr(module, const, original)

    return rows


def regime(gap):
    return "Effective" if gap <= 5 else ("Marginal" if gap <= 10 else "Outside horizon")


def bootstrap_ci(vals, n=10000, seed=42):
    rng = np.random.default_rng(seed)
    a = np.array(vals, float)
    if len(a) < 2:
        return float("nan"), float("nan")
    b = [np.mean(rng.choice(a, size=len(a), replace=True)) for _ in range(n)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def write(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Saved: {path}  ({len(rows)} rows)")


def main():
    offset_ref = load_offset_reference()

    raw = []
    for algorithm in ("QMIX", "VDN"):
        for ts in TRAIN_SEEDS:
            raw += evaluate_checkpoint(algorithm, ts, offset_ref)

    df = pd.DataFrame(raw)

    # Per-checkpoint summary: mean over traffic seeds.
    summary = []
    for (alg, tseed), g in df.groupby(["algorithm", "train_seed"]):
        gaps = g["gap_pct"].tolist()
        lo, hi = bootstrap_ci(gaps)
        summary.append({
            "algorithm": alg,
            "train_seed": tseed,
            "n_traffic_seeds": len(gaps),
            "mean_wt": round(g["learned_wt"].mean(), 3),
            "std_wt": round(g["learned_wt"].std(ddof=1), 3),
            "mean_gap_pct": round(float(np.mean(gaps)), 3),
            "gap_ci_low": round(lo, 3),
            "gap_ci_high": round(hi, 3),
            "regime": regime(float(np.mean(gaps))),
        })
    summary = sorted(summary, key=lambda r: (r["algorithm"], r["train_seed"]))

    # THE reviewer-facing table: spread ACROSS training seeds.
    dist = []
    for alg in ("QMIX", "VDN"):
        per_ckpt = [r["mean_gap_pct"] for r in summary if r["algorithm"] == alg]
        per_wt = [r["mean_wt"] for r in summary if r["algorithm"] == alg]
        lo, hi = bootstrap_ci(per_ckpt)
        n_eff = sum(1 for g in per_ckpt if g <= 5)
        dist.append({
            "algorithm": alg,
            "n_training_seeds": len(per_ckpt),
            "mean_wt_across_training_seeds": round(float(np.mean(per_wt)), 3),
            "std_wt_across_training_seeds": round(float(np.std(per_wt, ddof=1)), 3),
            "mean_gap_across_training_seeds": round(float(np.mean(per_ckpt)), 3),
            "std_gap_across_training_seeds": round(float(np.std(per_ckpt, ddof=1)), 3),
            "min_gap": round(min(per_ckpt), 3),
            "max_gap": round(max(per_ckpt), 3),
            "gap_ci_low": round(lo, 3),
            "gap_ci_high": round(hi, 3),
            "n_seeds_effective": n_eff,
            "effective_stability_pct": round(100.0 * n_eff / len(per_ckpt), 1),
            "published_single_checkpoint_gap": (
                PUBLISHED_QMIX_GAP if alg == "QMIX" else PUBLISHED_VDN_GAP),
        })

    write(OUT_RAW, raw)
    write(OUT_SUMMARY, summary)
    write(OUT_DIST, dist)

    print("\n" + "=" * 72)
    print("PER-CHECKPOINT (mean over 10 traffic seeds)")
    print("=" * 72)
    print(pd.DataFrame(summary).to_string(index=False))

    print("\n" + "=" * 72)
    print("ACROSS TRAINING SEEDS -- the reviewer-facing result")
    print("=" * 72)
    print(pd.DataFrame(dist).to_string(index=False))

    print("\n" + "=" * 72)
    print("SEPARATION CHECK (the VDN ablation claim)")
    print("=" * 72)
    q = [r["mean_gap_pct"] for r in summary if r["algorithm"] == "QMIX"]
    v = [r["mean_gap_pct"] for r in summary if r["algorithm"] == "VDN"]
    print(f"QMIX gaps by training seed: {[round(x, 2) for x in q]}")
    print(f"VDN  gaps by training seed: {[round(x, 2) for x in v]}")
    if max(q) < min(v):
        print(f"\nSEPARATED: worst QMIX ({max(q):.2f}%) beats best VDN "
              f"({min(v):.2f}%). The mixer conclusion survives training-seed "
              "replication.")
    else:
        print(f"\nOVERLAP: worst QMIX ({max(q):.2f}%) vs best VDN "
              f"({min(v):.2f}%). The mixer claim must be softened -- report "
              "the overlap explicitly rather than the point comparison.")

    print("\nPublished single-checkpoint values for the labelled reference "
          f"point: QMIX {PUBLISHED_QMIX_GAP}%, VDN {PUBLISHED_VDN_GAP}%.")
    print("Report the original checkpoint as a labelled point against this "
          "distribution. Do NOT average it in.")


if __name__ == "__main__":
    main()
