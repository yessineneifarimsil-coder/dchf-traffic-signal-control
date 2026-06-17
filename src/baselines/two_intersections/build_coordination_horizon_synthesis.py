import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


DISTANCE_COMPARISON_FILE = "results/tables/distance_best_offset_vs_qmix.csv"
DEMAND_COMPARISON_FILE = "results/tables/demand_best_offset_vs_qmix.csv"

OUT_DISTANCE_REGIMES = "results/tables/coordination_horizon_distance_regimes.csv"
OUT_DEMAND_REGIMES = "results/tables/coordination_horizon_demand_regimes.csv"
OUT_KEY_FINDINGS = "results/tables/coordination_horizon_key_findings.csv"

FIG_DISTANCE_GAP = "results/figures/coordination_horizon_distance_gap.png"
FIG_DEMAND_GAP = "results/figures/coordination_horizon_demand_gap.png"
FIG_DEMAND_CAPACITY = "results/figures/coordination_horizon_demand_capacity.png"


EFFECTIVE_THRESHOLD = 5.0
MARGINAL_THRESHOLD = 10.0

DEMAND_ORDER = ["low", "medium", "high", "saturation", "oversaturation"]


def classify_coordination_gap(gap_percent):
    if gap_percent <= EFFECTIVE_THRESHOLD:
        return "Effective coordination zone"
    if gap_percent <= MARGINAL_THRESHOLD:
        return "Marginal coordination zone"
    return "Outside coordination horizon"


def classify_capacity_status(buffered_ratio):
    if buffered_ratio < 0.01:
        return "Unconstrained"
    if buffered_ratio < 0.10:
        return "Mild insertion pressure"
    if buffered_ratio < 0.25:
        return "Capacity-limited"
    return "Oversaturated"


def build_distance_regimes():
    df = pd.read_csv(DISTANCE_COMPARISON_FILE)
    df = df.sort_values("distance")

    rows = []

    for _, row in df.iterrows():
        gap = row["qmix_gap_vs_best_offset_percent"]

        rows.append({
            "distance": row["distance"],
            "best_offset": row["best_offset"],
            "best_offset_waiting_time": row["best_offset_waiting_time"],
            "qmix_waiting_time": row["qmix_waiting_time"],
            "qmix_gap_percent": gap,
            "best_offset_queue": row["best_offset_queue"],
            "qmix_queue": row["qmix_queue"],
            "coordination_regime": classify_coordination_gap(gap),
        })

    out_df = pd.DataFrame(rows).round(3)
    out_df.to_csv(OUT_DISTANCE_REGIMES, index=False)

    return out_df


def build_demand_regimes():
    df = pd.read_csv(DEMAND_COMPARISON_FILE)
    df["order"] = df["demand_scenario"].apply(lambda x: DEMAND_ORDER.index(x))
    df = df.sort_values("order")

    rows = []

    for _, row in df.iterrows():
        gap = row["qmix_gap_vs_best_offset_percent"]
        max_buffered_ratio = max(
            row["best_offset_buffered_ratio"],
            row["qmix_buffered_ratio"],
        )

        rows.append({
            "demand_scenario": row["demand_scenario"],
            "demand_multiplier": row["demand_multiplier"],
            "best_offset": row["best_offset"],
            "best_offset_waiting_time": row["best_offset_waiting_time"],
            "qmix_waiting_time": row["qmix_waiting_time"],
            "qmix_gap_percent": gap,
            "best_offset_buffered_ratio": row["best_offset_buffered_ratio"],
            "qmix_buffered_ratio": row["qmix_buffered_ratio"],
            "max_buffered_ratio": max_buffered_ratio,
            "coordination_regime": classify_coordination_gap(gap),
            "capacity_status": classify_capacity_status(max_buffered_ratio),
        })

    out_df = pd.DataFrame(rows).round(3)
    out_df.to_csv(OUT_DEMAND_REGIMES, index=False)

    return out_df


def build_key_findings(distance_df, demand_df):
    effective_distances = distance_df[
        distance_df["coordination_regime"] == "Effective coordination zone"
    ]["distance"].tolist()

    marginal_distances = distance_df[
        distance_df["coordination_regime"] == "Marginal coordination zone"
    ]["distance"].tolist()

    outside_distances = distance_df[
        distance_df["coordination_regime"] == "Outside coordination horizon"
    ]["distance"].tolist()

    effective_demands = demand_df[
        demand_df["coordination_regime"] == "Effective coordination zone"
    ]["demand_scenario"].tolist()

    marginal_demands = demand_df[
        demand_df["coordination_regime"] == "Marginal coordination zone"
    ]["demand_scenario"].tolist()

    outside_demands = demand_df[
        demand_df["coordination_regime"] == "Outside coordination horizon"
    ]["demand_scenario"].tolist()

    rows = [
        {
            "finding": "Spatial effective coordination zone",
            "value": ", ".join([f"{int(d)} m" for d in effective_distances]),
        },
        {
            "finding": "Spatial marginal coordination zone",
            "value": ", ".join([f"{int(d)} m" for d in marginal_distances]),
        },
        {
            "finding": "Distances outside coordination horizon",
            "value": ", ".join([f"{int(d)} m" for d in outside_distances]),
        },
        {
            "finding": "Operational effective demand regimes",
            "value": ", ".join(effective_demands),
        },
        {
            "finding": "Operational marginal demand regimes",
            "value": ", ".join(marginal_demands),
        },
        {
            "finding": "Demand regimes outside coordination horizon",
            "value": ", ".join(outside_demands),
        },
        {
            "finding": "Capacity-limited demand regimes",
            "value": ", ".join(
                demand_df[
                    demand_df["capacity_status"].isin(
                        ["Capacity-limited", "Oversaturated"]
                    )
                ]["demand_scenario"].tolist()
            ),
        },
    ]

    out_df = pd.DataFrame(rows)
    out_df.to_csv(OUT_KEY_FINDINGS, index=False)

    return out_df


def plot_distance_gap(distance_df):
    plt.figure(figsize=(10, 6))

    plt.plot(
        distance_df["distance"],
        distance_df["qmix_gap_percent"],
        marker="o",
    )

    plt.axhline(
        y=EFFECTIVE_THRESHOLD,
        linestyle="--",
        label="Effective threshold: 5%",
    )
    plt.axhline(
        y=MARGINAL_THRESHOLD,
        linestyle=":",
        label="Marginal threshold: 10%",
    )

    plt.xlabel("Inter-Intersection Distance (m)")
    plt.ylabel("QMIX Gap vs Best Offset (%)")
    plt.title("Spatial Coordination Horizon of QMIX V2")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()

    for x, y in zip(distance_df["distance"], distance_df["qmix_gap_percent"]):
        plt.text(
            x,
            y,
            f"{y:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.tight_layout()
    os.makedirs(os.path.dirname(FIG_DISTANCE_GAP), exist_ok=True)
    plt.savefig(FIG_DISTANCE_GAP, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {FIG_DISTANCE_GAP}")


def plot_demand_gap(demand_df):
    plt.figure(figsize=(10, 6))

    plt.plot(
        demand_df["demand_scenario"],
        demand_df["qmix_gap_percent"],
        marker="o",
    )

    plt.axhline(
        y=EFFECTIVE_THRESHOLD,
        linestyle="--",
        label="Effective threshold: 5%",
    )
    plt.axhline(
        y=MARGINAL_THRESHOLD,
        linestyle=":",
        label="Marginal threshold: 10%",
    )

    plt.xlabel("Demand Scenario")
    plt.ylabel("QMIX Gap vs Best Offset (%)")
    plt.title("Operational Coordination Horizon of QMIX V2")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()

    for x, y in zip(demand_df["demand_scenario"], demand_df["qmix_gap_percent"]):
        plt.text(
            x,
            y,
            f"{y:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.tight_layout()
    os.makedirs(os.path.dirname(FIG_DEMAND_GAP), exist_ok=True)
    plt.savefig(FIG_DEMAND_GAP, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {FIG_DEMAND_GAP}")


def plot_demand_capacity(demand_df):
    x = np.arange(len(demand_df))
    width = 0.35

    plt.figure(figsize=(11, 6))

    plt.bar(
        x - width / 2,
        demand_df["best_offset_buffered_ratio"] * 100,
        width,
        label="Best offset fixed-time",
    )

    plt.bar(
        x + width / 2,
        demand_df["qmix_buffered_ratio"] * 100,
        width,
        label="QMIX V2 transferred",
    )

    plt.xlabel("Demand Scenario")
    plt.ylabel("Buffered Vehicles Ratio (%)")
    plt.title("Capacity Limitation across Demand Regimes")
    plt.xticks(x, demand_df["demand_scenario"])
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    os.makedirs(os.path.dirname(FIG_DEMAND_CAPACITY), exist_ok=True)
    plt.savefig(FIG_DEMAND_CAPACITY, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved figure to: {FIG_DEMAND_CAPACITY}")


def main():
    os.makedirs("results/tables", exist_ok=True)
    os.makedirs("results/figures", exist_ok=True)

    distance_df = build_distance_regimes()
    demand_df = build_demand_regimes()
    findings_df = build_key_findings(distance_df, demand_df)

    print("\n=== Spatial Coordination Horizon Regimes ===")
    print(distance_df.to_string(index=False))

    print("\n=== Operational Coordination Horizon Regimes ===")
    print(demand_df.to_string(index=False))

    print("\n=== Key Findings ===")
    print(findings_df.to_string(index=False))

    plot_distance_gap(distance_df)
    plot_demand_gap(demand_df)
    plot_demand_capacity(demand_df)

    print(f"\nSaved distance regimes to: {OUT_DISTANCE_REGIMES}")
    print(f"Saved demand regimes to: {OUT_DEMAND_REGIMES}")
    print(f"Saved key findings to: {OUT_KEY_FINDINGS}")


if __name__ == "__main__":
    main()