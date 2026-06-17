import os
import pandas as pd


FIXED_FILE = "results/tables/fixed_time_three_intersections_summary.csv"
OFFSET_FILE = "results/tables/three_intersection_baseline_comparison.csv"
QMIX_FILE = "results/tables/qmix_three_intersections_summary.csv"

OUTPUT_CSV = "results/tables/three_intersection_qmix_comparison.csv"


def improvement_lower_is_better(base, new):
    return ((base - new) / base) * 100


def improvement_higher_is_better(base, new):
    return ((new - base) / base) * 100


def main():
    os.makedirs("results/tables", exist_ok=True)

    fixed_df = pd.read_csv(FIXED_FILE)
    offset_df = pd.read_csv(OFFSET_FILE)
    qmix_df = pd.read_csv(QMIX_FILE)

    fixed = fixed_df.iloc[0]

    best_offset = offset_df[
        offset_df["controller"] == "Best Offset - Minimum Waiting"
    ].iloc[0]

    qmix = qmix_df.iloc[0]

    rows = [
        {
            "controller": "Simultaneous Fixed-Time",
            "offset_j2": 0,
            "offset_j3": 0,
            "mean_total_waiting_time": fixed["mean_total_waiting_time"],
            "mean_speed": fixed["mean_speed"],
            "mean_total_queue": fixed["mean_total_queue"],
            "max_total_queue": fixed["max_total_queue"],
            "total_departed": fixed["total_departed"],
            "total_arrived": fixed["total_arrived"],
            "final_active": fixed["final_active"],
            "final_buffered": fixed["final_buffered"],
            "buffered_ratio": fixed["buffered_ratio"],
        },
        {
            "controller": "Best Offset Pattern",
            "offset_j2": best_offset["offset_j2"],
            "offset_j3": best_offset["offset_j3"],
            "mean_total_waiting_time": best_offset["mean_total_waiting_time"],
            "mean_speed": best_offset["mean_speed"],
            "mean_total_queue": best_offset["mean_total_queue"],
            "max_total_queue": best_offset["max_total_queue"],
            "total_departed": best_offset["total_departed"],
            "total_arrived": best_offset["total_arrived"],
            "final_active": best_offset["final_active"],
            "final_buffered": best_offset["final_buffered"],
            "buffered_ratio": best_offset["buffered_ratio"],
        },
        {
            "controller": "QMIX 3 Agents",
            "offset_j2": None,
            "offset_j3": None,
            "mean_total_waiting_time": qmix["mean_total_waiting_time"],
            "mean_speed": qmix["mean_speed"],
            "mean_total_queue": qmix["mean_total_queue"],
            "max_total_queue": qmix["max_total_queue"],
            "total_departed": qmix["total_departed"],
            "total_arrived": qmix["total_arrived"],
            "final_active": qmix["final_active"],
            "final_buffered": qmix["final_buffered"],
            "buffered_ratio": qmix["buffered_ratio"],
        },
    ]

    comparison_df = pd.DataFrame(rows).round(3)
    comparison_df.to_csv(OUTPUT_CSV, index=False)

    print("\n=== Three-Intersection QMIX Comparison ===")
    print(comparison_df.to_string(index=False))

    base_waiting = fixed["mean_total_waiting_time"]
    base_speed = fixed["mean_speed"]
    base_queue = fixed["mean_total_queue"]

    best_waiting = best_offset["mean_total_waiting_time"]
    qmix_waiting = qmix["mean_total_waiting_time"]

    qmix_gap_vs_best_offset = (
        (qmix_waiting - best_waiting) / best_waiting
    ) * 100

    print("\n=== Improvements over Simultaneous Fixed-Time ===")

    for _, row in comparison_df.iterrows():
        if row["controller"] == "Simultaneous Fixed-Time":
            continue

        waiting_imp = improvement_lower_is_better(
            base_waiting,
            row["mean_total_waiting_time"],
        )

        speed_imp = improvement_higher_is_better(
            base_speed,
            row["mean_speed"],
        )

        queue_imp = improvement_lower_is_better(
            base_queue,
            row["mean_total_queue"],
        )

        print(f"\n{row['controller']}")
        print(f"Waiting-time improvement: {waiting_imp:.2f}%")
        print(f"Mean-speed improvement: {speed_imp:.2f}%")
        print(f"Queue improvement: {queue_imp:.2f}%")

    print("\n=== QMIX Gap versus Best Offset Pattern ===")
    print(f"QMIX waiting-time gap: {qmix_gap_vs_best_offset:.2f}%")

    if qmix_gap_vs_best_offset <= 5:
        regime = "Effective coordination zone"
    elif qmix_gap_vs_best_offset <= 10:
        regime = "Marginal coordination zone"
    else:
        regime = "Outside coordination horizon"

    print(f"Coordination regime: {regime}")

    print(f"\nSaved comparison to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()