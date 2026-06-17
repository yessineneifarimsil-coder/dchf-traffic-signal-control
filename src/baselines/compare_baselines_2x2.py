import pandas as pd


FILES = {
    "Safe Fixed-Time": "results/raw/safe_fixed_time_2x2.csv",
    "Queue-Based Adaptive V1": "results/raw/queue_based_2x2.csv",
    "Queue-Based Adaptive V2": "results/raw/queue_based_v2_2x2.csv",
    "Queue-Based Adaptive V3": "results/raw/queue_based_v3_2x2.csv",
    "DQN V2 Per-Second": "results/raw/dqn_v2_per_second_2x2.csv",
}

OUTPUT_CSV = "results/tables/controller_comparison_2x2_with_dqn_v2.csv"


def summarize_controller(name, path):
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
    }


def main():
    summaries = []

    for name, path in FILES.items():
        summaries.append(summarize_controller(name, path))

    summary_df = pd.DataFrame(summaries).round(3)

    print("\n=== Controller Comparison: 2x2 Single Intersection ===")
    print(summary_df.to_string(index=False))

    summary_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved comparison table to: {OUTPUT_CSV}")

    fixed = summary_df[summary_df["controller"] == "Safe Fixed-Time"].iloc[0]

    for controller_name in summary_df["controller"]:
        if controller_name == "Safe Fixed-Time":
            continue

        ctrl = summary_df[summary_df["controller"] == controller_name].iloc[0]

        waiting_improvement = (
            (fixed["mean_total_waiting_time"] - ctrl["mean_total_waiting_time"])
            / fixed["mean_total_waiting_time"]
        ) * 100

        speed_improvement = (
            (ctrl["mean_speed"] - fixed["mean_speed"])
            / fixed["mean_speed"]
        ) * 100

        print(f"\n=== Improvement of {controller_name} over Safe Fixed-Time ===")
        print(f"Waiting-time improvement: {waiting_improvement:.2f}%")
        print(f"Mean-speed improvement: {speed_improvement:.2f}%")


if __name__ == "__main__":
    main()