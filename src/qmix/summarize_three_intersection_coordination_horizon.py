import os
import pandas as pd


INPUT_FILE = "results/tables/three_intersection_d23_best_offset_vs_qmix.csv"

OUTPUT_REGIMES = "results/tables/three_intersection_coordination_horizon_regimes.csv"
OUTPUT_KEY_FINDINGS = "results/tables/three_intersection_coordination_horizon_key_findings.csv"


def classify_best_distance(df):
    best_row = df.loc[df["best_offset_waiting_time"].idxmin()]
    return best_row


def main():
    os.makedirs("results/tables", exist_ok=True)

    df = pd.read_csv(INPUT_FILE)

    regime_rows = []

    for _, row in df.iterrows():
        d23 = int(row["d23"])
        gap = row["qmix_gap_vs_best_offset_percent"]

        if gap <= 5:
            regime = "Effective coordination zone"
        elif gap <= 10:
            regime = "Marginal coordination zone"
        else:
            regime = "Outside coordination horizon"

        regime_rows.append(
            {
                "d23": d23,
                "best_offset_j2": row["best_offset_j2"],
                "best_offset_j3": row["best_offset_j3"],
                "best_offset_waiting_time": row["best_offset_waiting_time"],
                "qmix_waiting_time": row["qmix_waiting_time"],
                "qmix_gap_percent": gap,
                "best_offset_queue": row["best_offset_queue"],
                "qmix_queue": row["qmix_queue"],
                "coordination_regime": regime,
            }
        )

    regimes_df = pd.DataFrame(regime_rows).round(3)
    regimes_df.to_csv(OUTPUT_REGIMES, index=False)

    best_distance = classify_best_distance(df)

    effective_distances = regimes_df[
        regimes_df["coordination_regime"] == "Effective coordination zone"
    ]["d23"].astype(str).tolist()

    marginal_distances = regimes_df[
        regimes_df["coordination_regime"] == "Marginal coordination zone"
    ]["d23"].astype(str).tolist()

    outside_distances = regimes_df[
        regimes_df["coordination_regime"] == "Outside coordination horizon"
    ]["d23"].astype(str).tolist()

    key_findings = [
        {
            "finding": "Best manually optimized d23",
            "value": f"{int(best_distance['d23'])} m",
        },
        {
            "finding": "Best offset pattern at best d23",
            "value": (
                f"J2={int(best_distance['best_offset_j2'])} s, "
                f"J3={int(best_distance['best_offset_j3'])} s"
            ),
        },
        {
            "finding": "Best offset waiting time",
            "value": f"{best_distance['best_offset_waiting_time']:.3f}",
        },
        {
            "finding": "Effective QMIX spatial zone",
            "value": ", ".join(effective_distances) + " m",
        },
        {
            "finding": "Marginal QMIX spatial zone",
            "value": ", ".join(marginal_distances) + " m",
        },
        {
            "finding": "Outside QMIX coordination horizon",
            "value": ", ".join(outside_distances) + " m",
        },
    ]

    key_findings_df = pd.DataFrame(key_findings)
    key_findings_df.to_csv(OUTPUT_KEY_FINDINGS, index=False)

    print("\n=== Three-Intersection Coordination Horizon Regimes ===")
    print(regimes_df.to_string(index=False))

    print("\n=== Three-Intersection Coordination Horizon Key Findings ===")
    print(key_findings_df.to_string(index=False))

    print(f"\nSaved regimes to: {OUTPUT_REGIMES}")
    print(f"Saved key findings to: {OUTPUT_KEY_FINDINGS}")


if __name__ == "__main__":
    main()