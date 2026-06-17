import os
import pandas as pd
import matplotlib.pyplot as plt


ACTION_FILE = "results/tables/qmix_three_intersection_action_distribution.csv"
PATTERN_FILE = "results/tables/qmix_three_intersection_action_patterns.csv"
QUEUE_FILE = "results/tables/qmix_three_intersection_queue_fairness.csv"

OUT_ACTIONS = "results/figures/qmix_three_action_distribution.png"
OUT_PATTERNS = "results/figures/qmix_three_action_patterns.png"
OUT_QUEUES = "results/figures/qmix_three_queue_fairness.png"


def plot_action_distribution():
    df = pd.read_csv(ACTION_FILE)

    agents = df["agent"].unique()
    side_values = []
    main_values = []

    for agent in agents:
        sub = df[df["agent"] == agent]

        side = sub[sub["action"] == 0]["percentage_decisions"].iloc[0]
        main = sub[sub["action"] == 1]["percentage_decisions"].iloc[0]

        side_values.append(side)
        main_values.append(main)

    x = range(len(agents))
    width = 0.35

    plt.figure(figsize=(9, 6))
    plt.bar([i - width / 2 for i in x], side_values, width, label="Side priority")
    plt.bar([i + width / 2 for i in x], main_values, width, label="Main priority")

    plt.xlabel("Agent")
    plt.ylabel("Decision Frequency (%)")
    plt.title("QMIX 3-Agent Action Distribution")
    plt.xticks(list(x), agents)
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_ACTIONS), exist_ok=True)
    plt.savefig(OUT_ACTIONS, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_ACTIONS}")


def plot_action_patterns():
    df = pd.read_csv(PATTERN_FILE)

    plt.figure(figsize=(9, 6))
    plt.bar(df["action_pattern"], df["percentage_decisions"])

    plt.xlabel("Joint Action Pattern [J1-J2-J3]")
    plt.ylabel("Decision Frequency (%)")
    plt.title("QMIX 3-Agent Joint Action Patterns")
    plt.grid(axis="y", linestyle="--", alpha=0.5)

    for i, value in enumerate(df["percentage_decisions"]):
        plt.text(i, value, f"{value:.1f}%", ha="center", va="bottom", fontsize=9)

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_PATTERNS), exist_ok=True)
    plt.savefig(OUT_PATTERNS, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_PATTERNS}")


def plot_queue_fairness():
    df = pd.read_csv(QUEUE_FILE)

    plt.figure(figsize=(10, 6))
    plt.bar(df["link"], df["mean_queue"])

    plt.xlabel("Central Corridor Link")
    plt.ylabel("Mean Queue")
    plt.title("QMIX 3-Agent Central-Link Queue Fairness")
    plt.grid(axis="y", linestyle="--", alpha=0.5)

    for i, value in enumerate(df["mean_queue"]):
        plt.text(i, value, f"{value:.2f}", ha="center", va="bottom", fontsize=9)

    plt.tight_layout()
    os.makedirs(os.path.dirname(OUT_QUEUES), exist_ok=True)
    plt.savefig(OUT_QUEUES, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {OUT_QUEUES}")


def main():
    plot_action_distribution()
    plot_action_patterns()
    plot_queue_fairness()


if __name__ == "__main__":
    main()