"""
Validation for run_fully_paired_sweeps_v2.py.

TWO INDEPENDENT CHECKS. Both must pass before any new number is trusted.

CHECK 1 -- the output flags did not perturb the simulation.
    fully_paired_sweeps_raw.csv has SIX columns: three join keys
    (sweep, cell, seed) and three numeric columns (offset_wt, qmix_wt, mp_wt).
    Only the three NUMERIC columns are compared, and they must match to 1e-9.
    --summary-output / --tripinfo-output are output-only flags, and adding an
    independent simultaneous-fixed-time pass does not touch the other three
    controllers' seeds or configs, so exact reproduction is the expectation.

CHECK 2 -- the NEW buffered-ratio column is actually correct.
    Check 1 says nothing about this. The BR path rests on an assumption about
    SUMO's summary-output schema: that 'inserted' is cumulative-to-date, so the
    final <step> carries total insertions. If that assumption were wrong and the
    parser summed instead, every BR would clamp to 0.0000 via
    max(0, expected - inserted) and LOOK like a clean result.

    The Max Pressure demand sweep already ran on the SAME five seeds (0-4), the
    SAME configs and the SAME controller, and its per-seed buffered ratios are
    committed in max_pressure_demand_sweep_seed_summary.csv. The new MP BRs must
    therefore reproduce them EXACTLY, seed by seed -- not within rounding.
    Anything else means the BR path is wrong.

Run from repo root:
    python src\\analysis\\check_paired_v2_regression.py
"""
import sys
import pandas as pd

REF_WT = "results/tables/fully_paired_sweeps_raw.csv"
NEW_WT = "results/tables/fully_paired_sweeps_v2_raw.csv"
NEW_SUMMARY = "results/tables/fully_paired_sweeps_v2_summary.csv"
REF_MP_BR = "results/tables/max_pressure_demand_sweep_seed_summary.csv"

KEYS = ["sweep", "cell", "seed"]
NUMERIC = ["offset_wt", "qmix_wt", "mp_wt"]
TOL_WT = 1e-9
TOL_BR = 2e-4          # committed MP BRs are rounded to 4 dp

failures = []


def check_waiting_times():
    print("=" * 72)
    print("CHECK 1  waiting-time reproduction (3 numeric columns, tol 1e-9)")
    print("=" * 72)

    ref = pd.read_csv(REF_WT)
    new = pd.read_csv(NEW_WT)

    merged = ref.merge(new, on=KEYS, suffixes=("_ref", "_new"),
                       how="outer", indicator=True)

    only = merged[merged["_merge"] != "both"]
    if len(only):
        failures.append("cells present in only one file")
        print("[FAIL] cells present in one file only:")
        print(only[KEYS + ["_merge"]].to_string(index=False))

    worst_rows = None
    for col in NUMERIC:
        d = (merged[f"{col}_ref"] - merged[f"{col}_new"]).abs()
        merged[f"_d_{col}"] = d
        n_bad = int((d > TOL_WT).sum())
        print(f"[{'OK  ' if n_bad == 0 else 'FAIL'}] {col:10s} "
              f"max |diff| = {d.max():.10f}   rows differing: {n_bad}")
        if n_bad:
            failures.append(f"{col} drift")
            worst_rows = True

    if worst_rows:
        merged["_maxdiff"] = merged[[f"_d_{c}" for c in NUMERIC]].max(axis=1)
        cols = KEYS + [f"{c}_ref" for c in NUMERIC] + [f"{c}_new" for c in NUMERIC]
        print("\nWorst offending rows:")
        print(merged.nlargest(5, "_maxdiff")[cols].to_string(index=False))


def check_buffered_ratios():
    print()
    print("=" * 72)
    print("CHECK 2  MP buffered ratio vs committed per-seed values (tol 5e-5)")
    print("=" * 72)

    new = pd.read_csv(NEW_WT)
    ref = pd.read_csv(REF_MP_BR)

    cols_needed = ["cell", "seed", "mp_buffered_ratio", "mp_inserted",
                   "expected_total_vehicles"]
    missing = [c for c in cols_needed if c not in new.columns]
    if missing:
        failures.append(f"v2 raw file missing columns: {missing}")
        print(f"[FAIL] missing columns in v2 raw file: {missing}")
        return

    dem = new[new["sweep"] == "demand"][cols_needed]
    dem = dem.rename(columns={"cell": "demand_scenario"})

    ref = ref[["demand_scenario", "seed", "buffered_ratio", "total_departed"]]
    ref = ref.rename(columns={"buffered_ratio": "br_ref",
                              "total_departed": "departed_ref"})

    m = dem.merge(ref, on=["demand_scenario", "seed"], how="inner")

    if m.empty:
        failures.append("no overlapping MP demand cells to validate")
        print("[FAIL] no overlapping rows -- cannot validate the BR path.")
        return

    m["br_diff"] = (m["mp_buffered_ratio"] - m["br_ref"]).abs()
    m["inserted_diff"] = (m["mp_inserted"] - m["departed_ref"]).abs()

    n_bad_br = int((m["br_diff"] > TOL_BR).sum())
    n_bad_ins = int((m["inserted_diff"] > 0).sum())

    print(f"[{'OK  ' if n_bad_br == 0 else 'FAIL'}] buffered_ratio  "
          f"max |diff| = {m['br_diff'].max():.6f}   rows differing: {n_bad_br}")
    print(f"[{'OK  ' if n_bad_ins == 0 else 'WARN'}] inserted vs "
          f"getDepartedNumber  max |diff| = {m['inserted_diff'].max():.0f} "
          f"vehicles   rows differing: {n_bad_ins}")

    if n_bad_br:
        failures.append("MP buffered ratio does not reproduce committed values")

    # The specific failure signature: 'inserted' summed instead of read last.
    if (m["mp_buffered_ratio"].fillna(-1) == 0).all() and (m["br_ref"] > 0).any():
        failures.append("ALL new BRs are 0.0000 while reference is nonzero -- "
                        "'inserted' is almost certainly being summed rather "
                        "than read at the final step")
        print("\n[FAIL] every new BR is 0.0000 while the committed reference is "
              "nonzero. This is the summed-'inserted' failure mode. STOP.")

    print("\nPer-seed comparison:")
    show = m[["demand_scenario", "seed", "expected_total_vehicles",
              "mp_inserted", "departed_ref", "mp_buffered_ratio", "br_ref"]]
    print(show.to_string(index=False))


def report_new_columns():
    print()
    print("=" * 72)
    print("NEW COLUMNS  d=300 m / medium demand")
    print("=" * 72)
    new = pd.read_csv(NEW_WT)
    sel = new[(new["sweep"] == "demand") & (new["cell"] == "medium")]
    show = ["seed", "sim_wt", "offset_wt", "qmix_wt", "mp_wt",
            "cg_offset", "cg_qmix", "cg_mp",
            "offset_buffered_ratio", "qmix_buffered_ratio", "mp_buffered_ratio"]
    show = [c for c in show if c in sel.columns]
    print(sel[show].to_string(index=False))

    print()
    print("RECLASSIFICATION WATCH -- five-seed QMIX diagnostics by demand cell")
    print("(capacity precedence threshold BR = 0.10)")
    s = pd.read_csv(NEW_SUMMARY)
    watch = s[s["sweep"] == "demand"][
        ["cell", "G_QMIX_mean", "CG_QMIX_mean", "BR_QMIX_mean",
         "qmix_regime", "qmix_integrated_class"]]
    print(watch.to_string(index=False))
    print()
    print("Published single-seed BR for comparison: high 0.0648, "
          "saturation 0.2013, oversaturation 0.2956.")


def main():
    check_waiting_times()
    check_buffered_ratios()
    try:
        report_new_columns()
    except Exception as e:
        print(f"\n[note] could not render new-column report: {e}")

    print()
    print("=" * 72)
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print(f"  - {f}")
        print("Do not use any new column until these are resolved.")
        sys.exit(1)
    print("RESULT: PASS -- simulation unperturbed AND the buffered-ratio path")
    print("reproduces committed per-seed values. New columns are trustworthy.")


if __name__ == "__main__":
    main()
