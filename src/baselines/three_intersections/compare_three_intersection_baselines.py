import os
import pandas as pd


FIXED_FILE = "results/tables/fixed_time_three_intersections_summary.csv"
OFFSET_BEST_FILE = "results/tables/three_intersection_offset_best_summary.csv"

OUTPUT_CSV = "results/tables/three_intersection_baseline_comparison.csv"


def improvement_lower_is_better(base, new):
    return ((base - new) / base) * 100


def improvement_higher_is_better(base, new):
    return ((new - base) / base) * 100


def main():
    os.makedirs("results/tables", exist_ok=True)

    fixed_df = pd.read_csv(FIXED_FILE)
    offset_df = pd.read_csv(OFFSET_BEST_FILE)

    fixed = fixed_df.iloc[0]

    best_waiting = offset_df[offset_df["criterion"] == "minimum_waiting_time"].iloc[0]
    best_speed = offset_df[offset_df["criterion"] == "maximum_mean_speed"].iloc[0]
    best_queue = offset_df[offset_df["criterion"] == "minimum_mean_queue"].iloc[0]

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
            "controller": "Best Offset - Minimum Waiting",
            "offset_j2": best_waiting["offset_j2"],
            "offset_j3": best_waiting["offset_j3"],
            "mean_total_waiting_time": best_waiting["mean_total_waiting_time"],
            "mean_speed": best_waiting["mean_speed"],
            "mean_total_queue": best_waiting["mean_total_queue"],
            "max_total_queue": best_waiting["max_total_queue"],
            "total_departed": best_waiting["total_departed"],
            "total_arrived": best_waiting["total_arrived"],
            "final_active": best_waiting["final_active"],
            "final_buffered": best_waiting["final_buffered"],
            "buffered_ratio": best_waiting["buffered_ratio"],
        },
        {
            "controller": "Best Offset - Maximum Speed",
            "offset_j2": best_speed["offset_j2"],
            "offset_j3": best_speed["offset_j3"],
            "mean_total_waiting_time": best_speed["mean_total_waiting_time"],
            "mean_speed": best_speed["mean_speed"],
            "mean_total_queue": best_speed["mean_total_queue"],
            "max_total_queue": best_speed["max_total_queue"],
            "total_departed": best_speed["total_departed"],
            "total_arrived": best_speed["total_arrived"],
            "final_active": best_speed["final_active"],
            "final_buffered": best_speed["final_buffered"],
            "buffered_ratio": best_speed["buffered_ratio"],
        },
        {
            "controller": "Best Offset - Minimum Queue",
            "offset_j2": best_queue["offset_j2"],
            "offset_j3": best_queue["offset_j3"],
            "mean_total_waiting_time": best_queue["mean_total_waiting_time"],
            "mean_speed": best_queue["mean_speed"],
            "mean_total_queue": best_queue["mean_total_queue"],
            "max_total_queue": best_queue["max_total_queue"],
            "total_departed": best_queue["total_departed"],
            "total_arrived": best_queue["total_arrived"],
            "final_active": best_queue["final_active"],
            "final_buffered": best_queue["final_buffered"],
            "buffered_ratio": best_queue["buffered_ratio"],
        },
    ]

    comparison_df = pd.DataFrame(rows).round(3)
    comparison_df.to_csv(OUTPUT_CSV, index=False)

    print("\n=== Three-Intersection Baseline Comparison ===")
    print(comparison_df.to_string(index=False))

    base_waiting = fixed["mean_total_waiting_time"]
    base_speed = fixed["mean_speed"]
    base_queue = fixed["mean_total_queue"]

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
        print(f"Offset pattern: J1=0 | J2={row['offset_j2']} | J3={row['offset_j3']}")
        print(f"Waiting-time improvement: {waiting_imp:.2f}%")
        print(f"Mean-speed improvement: {speed_imp:.2f}%")
        print(f"Queue improvement: {queue_imp:.2f}%")

    print(f"\nSaved comparison to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()