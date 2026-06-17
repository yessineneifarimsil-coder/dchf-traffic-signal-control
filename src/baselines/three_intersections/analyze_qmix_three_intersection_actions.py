import os
import pandas as pd


INPUT_FILE = "results/raw/qmix_three_intersections_per_second.csv"

OUTPUT_ACTIONS = "results/tables/qmix_three_intersection_action_distribution.csv"
OUTPUT_PATTERNS = "results/tables/qmix_three_intersection_action_patterns.csv"
OUTPUT_QUEUE_FAIRNESS = "results/tables/qmix_three_intersection_queue_fairness.csv"
OUTPUT_SUMMARY = "results/tables/qmix_three_intersection_action_fairness_summary.csv"


ACTION_LABELS = {
    0: "side_priority",
    1: "main_priority",
}


EDGE_QUEUE_COLUMNS = {
    "E1_queue_J1_J2": "J1_to_J2",
    "neg_E1_queue_J2_J1": "J2_to_J1",
    "E2_queue_J2_J3": "J2_to_J3",
    "neg_E2_queue_J3_J2": "J3_to_J2",
}


def main():
    os.makedirs("results/tables", exist_ok=True)

    df = pd.read_csv(INPUT_FILE)

    # One row per decision, because the same decision is repeated over many seconds.
    decision_df = df.drop_duplicates(subset=["decision"]).copy()

    # ------------------------------------------------------------
    # 1. Agent-level action distribution
    # ------------------------------------------------------------
    action_rows = []

    for agent_col, agent_name in [
        ("action_j1", "J1"),
        ("action_j2", "J2"),
        ("action_j3", "J3"),
    ]:
        counts = decision_df[agent_col].value_counts().sort_index()
        total = counts.sum()

        for action, count in counts.items():
            action_rows.append(
                {
                    "agent": agent_name,
                    "action": int(action),
                    "action_label": ACTION_LABELS[int(action)],
                    "count_decisions": int(count),
                    "percentage_decisions": (count / total) * 100,
                }
            )

    action_df = pd.DataFrame(action_rows).round(3)
    action_df.to_csv(OUTPUT_ACTIONS, index=False)

    # ------------------------------------------------------------
    # 2. Joint action-pattern distribution
    # ------------------------------------------------------------
    decision_df["action_pattern"] = (
        decision_df["action_j1"].astype(int).astype(str)
        + "-"
        + decision_df["action_j2"].astype(int).astype(str)
        + "-"
        + decision_df["action_j3"].astype(int).astype(str)
    )

    pattern_counts = (
        decision_df["action_pattern"]
        .value_counts()
        .reset_index()
    )

    pattern_counts.columns = ["action_pattern", "count_decisions"]
    pattern_counts["percentage_decisions"] = (
        pattern_counts["count_decisions"] / pattern_counts["count_decisions"].sum()
    ) * 100

    pattern_counts = pattern_counts.round(3)
    pattern_counts.to_csv(OUTPUT_PATTERNS, index=False)

    # ------------------------------------------------------------
    # 3. Queue/fairness on central corridor links
    # ------------------------------------------------------------
    queue_rows = []

    for col, label in EDGE_QUEUE_COLUMNS.items():
        queue_rows.append(
            {
                "link": label,
                "column": col,
                "mean_queue": df[col].mean(),
                "max_queue": df[col].max(),
                "std_queue": df[col].std(),
                "zero_queue_percentage": (df[col] == 0).mean() * 100,
            }
        )

    queue_df = pd.DataFrame(queue_rows).round(3)
    queue_df.to_csv(OUTPUT_QUEUE_FAIRNESS, index=False)

    # ------------------------------------------------------------
    # 4. Simple fairness/imbalance indicators
    # ------------------------------------------------------------
    mean_queues = queue_df["mean_queue"]

    max_mean_queue = mean_queues.max()
    min_mean_queue = mean_queues.min()
    avg_mean_queue = mean_queues.mean()

    queue_imbalance_absolute = max_mean_queue - min_mean_queue
    queue_imbalance_relative = (
        queue_imbalance_absolute / avg_mean_queue if avg_mean_queue > 0 else 0.0
    )

    dominant_pattern = pattern_counts.iloc[0]["action_pattern"]
    dominant_pattern_percentage = pattern_counts.iloc[0]["percentage_decisions"]

    summary = {
        "total_seconds_logged": len(df),
        "total_decisions": len(decision_df),
        "dominant_action_pattern": dominant_pattern,
        "dominant_action_pattern_percentage": dominant_pattern_percentage,
        "mean_total_waiting_time": df["total_waiting_time"].mean(),
        "mean_speed": df["mean_speed"].mean(),
        "mean_total_queue": df["total_queue"].mean(),
        "max_total_queue": df["total_queue"].max(),
        "max_mean_link_queue": max_mean_queue,
        "min_mean_link_queue": min_mean_queue,
        "avg_mean_link_queue": avg_mean_queue,
        "queue_imbalance_absolute": queue_imbalance_absolute,
        "queue_imbalance_relative": queue_imbalance_relative,
    }

    summary_df = pd.DataFrame([summary]).round(3)
    summary_df.to_csv(OUTPUT_SUMMARY, index=False)

    print("\n=== Agent-Level Action Distribution ===")
    print(action_df.to_string(index=False))

    print("\n=== Joint Action Pattern Distribution ===")
    print(pattern_counts.to_string(index=False))

    print("\n=== Central Corridor Queue Fairness ===")
    print(queue_df.to_string(index=False))

    print("\n=== Action/Fairness Summary ===")
    print(summary_df.to_string(index=False))

    print(f"\nSaved action distribution to: {OUTPUT_ACTIONS}")
    print(f"Saved action patterns to: {OUTPUT_PATTERNS}")
    print(f"Saved queue fairness to: {OUTPUT_QUEUE_FAIRNESS}")
    print(f"Saved summary to: {OUTPUT_SUMMARY}")


if __name__ == "__main__":
    main()