import pandas as pd

INPUT_CSV = "results/raw/fixed_time_single_intersection.csv"
OUTPUT_CSV = "results/tables/fixed_time_summary.csv"

df = pd.read_csv(INPUT_CSV)

summary = {
    "simulation_steps": len(df),
    "mean_vehicle_count": df["vehicle_count"].mean(),
    "max_vehicle_count": df["vehicle_count"].max(),
    "mean_total_waiting_time": df["total_waiting_time"].mean(),
    "max_total_waiting_time": df["total_waiting_time"].max(),
    "mean_speed": df["mean_speed"].mean(),
    "min_mean_speed": df["mean_speed"].min(),
}

summary_df = pd.DataFrame([summary]).round(3)

print("\n=== Fixed-Time Controller Summary ===")
print(summary_df.to_string(index=False))

summary_df.to_csv(OUTPUT_CSV, index=False)
print(f"\nSaved summary to: {OUTPUT_CSV}")