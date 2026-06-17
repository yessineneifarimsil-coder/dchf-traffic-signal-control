import pandas as pd


FIXED_TIME_FILE = "results/tables/fixed_time_corridor_turning_summary.csv"
OFFSET_SWEEP_FILE = "results/tables/offset_sweep_turning_summary_0_90_2x2.csv"
QMIX_TRANSFERRED_FILE = "results/tables/qmix_v2_turning_summary.csv"
QMIX_TRAINED_FILE = "results/tables/qmix_v2_turning_trained_summary.csv"

OUTPUT_CSV = "results/tables/scenario_b_controller_comparison.csv"


def main():
    fixed_df = pd.read_csv(FIXED_TIME_FILE)
    offset_df = pd.read_csv(OFFSET_SWEEP_FILE)
    qmix_transferred_df = pd.read_csv(QMIX_TRANSFERRED_FILE)
    qmix_trained_df = pd.read_csv(QMIX_TRAINED_FILE)

    fixed_row = fixed_df.iloc[0].to_dict()
    best_offset = offset_df[offset_df["offset"] == 45].iloc[0].to_dict()
    qmix_transferred_row = qmix_transferred_df.iloc[0].to_dict()
    qmix_trained_row = qmix_trained_df.iloc[0].to_dict()

    rows = [
        {
            "controller": "Simultaneous Fixed-Time",
            "mean_vehicle_count": fixed_row["mean_vehicle_count"],
            "max_vehicle_count": fixed_row["max_vehicle_count"],
            "mean_total_waiting_time": fixed_row["mean_total_waiting_time"],
            "max_total_waiting_time": fixed_row["max_total_waiting_time"],
            "mean_speed": fixed_row["mean_speed"],
            "mean_total_queue": fixed_row["mean_total_queue"],
            "max_total_queue": fixed_row["max_total_queue"],
        },
        {
            "controller": "Best Offset Fixed-Time 45s",
            "mean_vehicle_count": best_offset["vehicle_count_mean"],
            "max_vehicle_count": best_offset["vehicle_count_max"],
            "mean_total_waiting_time": best_offset["total_waiting_time_mean"],
            "max_total_waiting_time": best_offset["total_waiting_time_max"],
            "mean_speed": best_offset["mean_speed_mean"],
            "mean_total_queue": best_offset["total_queue_mean"],
            "max_total_queue": best_offset["total_queue_max"],
        },
        {
            "controller": "QMIX V2 transferred",
            "mean_vehicle_count": qmix_transferred_row["mean_vehicle_count"],
            "max_vehicle_count": qmix_transferred_row["max_vehicle_count"],
            "mean_total_waiting_time": qmix_transferred_row["mean_total_waiting_time"],
            "max_total_waiting_time": qmix_transferred_row["max_total_waiting_time"],
            "mean_speed": qmix_transferred_row["mean_speed"],
            "mean_total_queue": qmix_transferred_row["mean_total_queue"],
            "max_total_queue": qmix_transferred_row["max_total_queue"],
        },
        {
            "controller": "QMIX V2 trained on Scenario B",
            "mean_vehicle_count": qmix_trained_row["mean_vehicle_count"],
            "max_vehicle_count": qmix_trained_row["max_vehicle_count"],
            "mean_total_waiting_time": qmix_trained_row["mean_total_waiting_time"],
            "max_total_waiting_time": qmix_trained_row["max_total_waiting_time"],
            "mean_speed": qmix_trained_row["mean_speed"],
            "mean_total_queue": qmix_trained_row["mean_total_queue"],
            "max_total_queue": qmix_trained_row["max_total_queue"],
        },
    ]

    summary_df = pd.DataFrame(rows).round(3)

    print("\n=== Scenario B Controller Comparison ===")
    print(summary_df.to_string(index=False))

    summary_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved comparison to: {OUTPUT_CSV}")

    base = summary_df[summary_df["controller"] == "Simultaneous Fixed-Time"].iloc[0]

    for controller in summary_df["controller"]:
        if controller == "Simultaneous Fixed-Time":
            continue

        row = summary_df[summary_df["controller"] == controller].iloc[0]

        waiting_improvement = (
            (base["mean_total_waiting_time"] - row["mean_total_waiting_time"])
            / base["mean_total_waiting_time"]
        ) * 100

        speed_improvement = (
            (row["mean_speed"] - base["mean_speed"])
            / base["mean_speed"]
        ) * 100

        queue_improvement = (
            (base["mean_total_queue"] - row["mean_total_queue"])
            / base["mean_total_queue"]
        ) * 100

        print(f"\n=== Improvement of {controller} over Simultaneous Fixed-Time ===")
        print(f"Waiting-time improvement: {waiting_improvement:.2f}%")
        print(f"Mean-speed improvement: {speed_improvement:.2f}%")
        print(f"Queue improvement: {queue_improvement:.2f}%")

    transferred = summary_df[
        summary_df["controller"] == "QMIX V2 transferred"
    ].iloc[0]

    trained = summary_df[
        summary_df["controller"] == "QMIX V2 trained on Scenario B"
    ].iloc[0]

    transfer_vs_trained = (
        (trained["mean_total_waiting_time"] - transferred["mean_total_waiting_time"])
        / trained["mean_total_waiting_time"]
    ) * 100

    print("\n=== Transfer vs Direct Training ===")
    print(
        "Waiting-time advantage of transferred QMIX V2 over directly trained QMIX V2: "
        f"{transfer_vs_trained:.2f}%"
    )


if __name__ == "__main__":
    main()