import pandas as pd


INPUT_CSV = "results/raw/qmix_corridor_v2_turning_trained_per_second.csv"
OUTPUT_CSV = "results/tables/qmix_v2_turning_trained_summary.csv"


def main():
    df = pd.read_csv(INPUT_CSV)

    summary = {
        "controller": "QMIX V2 trained on Scenario B",
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

    summary_df = pd.DataFrame([summary]).round(3)

    print("\n=== QMIX V2 Trained on Scenario B Summary ===")
    print(summary_df.to_string(index=False))

    summary_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved summary to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()