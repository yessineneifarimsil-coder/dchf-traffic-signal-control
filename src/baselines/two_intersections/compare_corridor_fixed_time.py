import pandas as pd


FILES = {
    "Simultaneous Fixed-Time": "results/raw/fixed_time_corridor_2x2.csv",
    "Offset Fixed-Time 20s": "results/raw/fixed_time_corridor_offset_20s_2x2.csv",
}

OUTPUT_CSV = "results/tables/corridor_fixed_time_comparison.csv"


def summarize(name, path):
    df = pd.read_csv(path)

    return {
        "controller": name,
        "simulation_steps": len(df),
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

    for name, path in FILES.items():
        rows.append(summarize(name, path))

    summary_df = pd.DataFrame(rows).round(3)

    print("\n=== Corridor Fixed-Time Comparison ===")
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