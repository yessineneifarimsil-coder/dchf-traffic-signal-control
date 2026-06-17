import os
import pandas as pd


FILES = {
    "QMIX V1": {
        "per_second": "results/raw/qmix_corridor_per_second.csv",
        "training": "results/raw/qmix_corridor_training.csv",
    },
    "QMIX V2": {
        "per_second": "results/raw/qmix_corridor_v2_per_second.csv",
        "training": "results/raw/qmix_corridor_training_v2.csv",
    },
    "QMIX V3": {
        "per_second": "results/raw/qmix_corridor_v3_per_second.csv",
        "training": "results/raw/qmix_corridor_training_v3.csv",
    },
}

OUTPUT_COMPARISON = "results/tables/qmix_v1_v2_v3_comparison.csv"
OUTPUT_TRAINING = "results/tables/qmix_v1_v2_v3_training_tail_summary.csv"


def safe_mean(df, col):
    return df[col].mean() if col in df.columns else None


def safe_max(df, col):
    return df[col].max() if col in df.columns else None


def safe_min(df, col):
    return df[col].min() if col in df.columns else None


def main():
    os.makedirs("results/tables", exist_ok=True)

    comparison_rows = []
    training_rows = []

    for controller, paths in FILES.items():
        per_second_path = paths["per_second"]
        training_path = paths["training"]

        if not os.path.exists(per_second_path):
            print(f"Missing per-second file for {controller}: {per_second_path}")
            continue

        df = pd.read_csv(per_second_path)

        row = {
            "controller": controller,
            "rows": len(df),
            "mean_vehicle_count": safe_mean(df, "vehicle_count"),
            "max_vehicle_count": safe_max(df, "vehicle_count"),
            "mean_total_waiting_time": safe_mean(df, "total_waiting_time"),
            "max_total_waiting_time": safe_max(df, "total_waiting_time"),
            "mean_speed": safe_mean(df, "mean_speed"),
            "min_mean_speed": safe_min(df, "mean_speed"),
            "mean_total_queue": safe_mean(df, "total_queue"),
            "max_total_queue": safe_max(df, "total_queue"),
        }

        comparison_rows.append(row)

        if os.path.exists(training_path):
            train_df = pd.read_csv(training_path)
            last = train_df.tail(20)

            training_rows.append({
                "controller": controller,
                "training_rows": len(train_df),
                "last20_mean_episode_reward": safe_mean(last, "episode_reward"),
                "last20_mean_loss": safe_mean(last, "avg_loss"),
                "last20_mean_final_waiting": safe_mean(last, "final_total_waiting_time"),
                "last20_mean_final_speed": safe_mean(last, "final_mean_speed"),
                "last20_mean_final_queue": safe_mean(last, "final_total_queue"),
                "last_epsilon": train_df["epsilon"].iloc[-1] if "epsilon" in train_df.columns else None,
            })

    comparison_df = pd.DataFrame(comparison_rows).round(3)
    training_df = pd.DataFrame(training_rows).round(3)

    comparison_df.to_csv(OUTPUT_COMPARISON, index=False)
    training_df.to_csv(OUTPUT_TRAINING, index=False)

    print("\n=== QMIX V1 / V2 / V3 Evaluation Comparison ===")
    print(comparison_df.to_string(index=False))

    print("\n=== QMIX V1 / V2 / V3 Training Tail Summary ===")
    print(training_df.to_string(index=False))

    print(f"\nSaved evaluation comparison to: {OUTPUT_COMPARISON}")
    print(f"Saved training summary to: {OUTPUT_TRAINING}")


if __name__ == "__main__":
    main()