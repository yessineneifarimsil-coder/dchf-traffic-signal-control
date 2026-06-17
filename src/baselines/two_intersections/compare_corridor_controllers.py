import pandas as pd


SIMULTANEOUS_FILE = "results/raw/fixed_time_corridor_2x2.csv"
OFFSET_SWEEP_FILE = "results/raw/offset_sweep_raw_0_90_2x2.csv"
QUEUE_BASED_FILE = "results/raw/queue_based_corridor_2x2.csv"
INDEPENDENT_DQN_FILE = "results/raw/independent_dqn_corridor_per_second.csv"
QMIX_V1_FILE = "results/raw/qmix_corridor_per_second.csv"
QMIX_V2_FILE = "results/raw/qmix_corridor_v2_per_second.csv"
QMIX_V3_FILE = "results/raw/qmix_corridor_v3_per_second.csv"

OUTPUT_CSV = "results/tables/corridor_controller_comparison_with_qmix_v2.csv"


def summarize_regular_file(name, path):
    df = pd.read_csv(path)

    return {
        "controller": name,
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
    }


def summarize_offset(name, path, offset_value):
    df = pd.read_csv(path)
    df = df[df["offset"] == offset_value]

    return {
        "controller": name,
        "rows": len(df),
        "mean_vehicle_count": df["vehicle_count"].mean(),
        "max_vehicle_count": df["vehicle_count"].max(),
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "max_total_waiting_time": df["total_waiting_time"].max(),
        "mean_speed": df["mean_speed"].mean(),
        "min_mean_speed": df["mean_speed"].min(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
    }


def main():
    rows = []

    rows.append(
        summarize_regular_file(
            "Simultaneous Fixed-Time",
            SIMULTANEOUS_FILE
        )
    )

    rows.append(
        summarize_offset(
            "Best Offset Fixed-Time 45s",
            OFFSET_SWEEP_FILE,
            offset_value=45
        )
    )

    rows.append(
        summarize_regular_file(
            "Queue-Based Corridor",
            QUEUE_BASED_FILE
        )
    )

    rows.append(
        summarize_regular_file(
            "Independent DQN",
            INDEPENDENT_DQN_FILE
        )
    )

    rows.append(
        summarize_regular_file(
            "QMIX V1",
            QMIX_V1_FILE
        )
    )

    rows.append(
        summarize_regular_file(
            "QMIX V2",
            QMIX_V2_FILE
        )
    )
    rows.append(
        summarize_regular_file(
            "QMIX V3",
             QMIX_V3_FILE
        )
    )

    summary_df = pd.DataFrame(rows).round(3)

    print("\n=== Corridor Controller Comparison with QMIX V2 ===")
    print(summary_df.to_string(index=False))

    summary_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved comparison table to: {OUTPUT_CSV}")

    base = summary_df[summary_df["controller"] == "Simultaneous Fixed-Time"].iloc[0]

    for controller_name in summary_df["controller"]:
        if controller_name == "Simultaneous Fixed-Time":
            continue

        ctrl = summary_df[summary_df["controller"] == controller_name].iloc[0]

        waiting_improvement = (
            (base["mean_total_waiting_time"] - ctrl["mean_total_waiting_time"])
            / base["mean_total_waiting_time"]
        ) * 100

        speed_improvement = (
            (ctrl["mean_speed"] - base["mean_speed"])
            / base["mean_speed"]
        ) * 100

        queue_improvement = (
            (base["mean_total_queue"] - ctrl["mean_total_queue"])
            / base["mean_total_queue"]
        ) * 100

        print(f"\n=== Improvement of {controller_name} over Simultaneous Fixed-Time ===")
        print(f"Waiting-time improvement: {waiting_improvement:.2f}%")
        print(f"Mean-speed improvement: {speed_improvement:.2f}%")
        print(f"Queue improvement: {queue_improvement:.2f}%")


if __name__ == "__main__":
    main()