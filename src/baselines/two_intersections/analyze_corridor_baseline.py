import pandas as pd


INPUT_CSV = "results/raw/fixed_time_corridor_2x2.csv"
OUTPUT_CSV = "results/tables/fixed_time_corridor_summary.csv"


def main():
    df = pd.read_csv(INPUT_CSV)

    summary = {
        "controller": "Simultaneous Fixed-Time",
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

    summary_df = pd.DataFrame([summary]).round(3)

    print("\n=== Fixed-Time Corridor Summary ===")
    print(summary_df.to_string(index=False))

    summary_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved summary to: {OUTPUT_CSV}")

    phase_summary = (
        df.groupby("phase_group")[[
            "vehicle_count",
            "total_waiting_time",
            "mean_speed",
            "total_queue"
        ]]
        .mean()
        .round(3)
    )

    print("\n=== Mean metrics by phase group ===")
    print(phase_summary)


if __name__ == "__main__":
    main()