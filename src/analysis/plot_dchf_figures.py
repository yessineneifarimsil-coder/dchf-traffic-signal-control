import os
import re
import pandas as pd
import matplotlib.pyplot as plt


TABLE_DIR = "results/tables"
FIG_DIR = "results/figures"

os.makedirs(FIG_DIR, exist_ok=True)


FILES = {
    "distance": f"{TABLE_DIR}/dchf_two_intersection_distance_horizon.csv",
    "demand": f"{TABLE_DIR}/dchf_two_intersection_demand_horizon.csv",
    "d23": f"{TABLE_DIR}/dchf_three_intersection_d23_horizon.csv",
    "threshold": f"{TABLE_DIR}/dchf_horizon_summary_by_threshold.csv",
    "scalability": f"{TABLE_DIR}/dchf_early_scalability_projection.csv",
}


def save_figure(name):
    png_path = os.path.join(FIG_DIR, f"{name}.png")
    pdf_path = os.path.join(FIG_DIR, f"{name}.pdf")

    plt.tight_layout()
    plt.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.savefig(pdf_path, bbox_inches="tight")
    plt.close()

    print(f"Saved: {png_path}")
    print(f"Saved: {pdf_path}")


def read_csv(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing file: {path}")

    return pd.read_csv(path)


def extract_distance_m(scenario):
    match = re.search(r"([\d.]+)\s*m", str(scenario))
    return float(match.group(1)) if match else None


def extract_d23_m(scenario):
    match = re.search(r"d23\s*=\s*([\d.]+)", str(scenario))
    if match:
        return float(match.group(1))

    return extract_distance_m(scenario)


def extract_demand_multiplier(scenario):
    match = re.search(r"\(([\d.]+)x\)", str(scenario))
    return float(match.group(1)) if match else None


def plot_distance_gap_and_gain():
    df = read_csv(FILES["distance"])
    df["distance_m"] = df["scenario"].apply(extract_distance_m)
    df = df.sort_values("distance_m")

    x = df["distance_m"]
    gap = df["qmix_gap_vs_optimized_offset_percent"]
    cg = df["qmix_coordination_gain_percent"]

    plt.figure(figsize=(7.5, 4.8))
    plt.plot(x, gap, marker="o")
    plt.axhline(5, linestyle="--", linewidth=1)
    plt.axhline(10, linestyle="--", linewidth=1)
    plt.xlabel("Inter-intersection distance (m)")
    plt.ylabel("QMIX gap vs optimized offset (%)")
    plt.title("Two-intersection spatial horizon: QMIX approximation gap")
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gap_distance")

    plt.figure(figsize=(7.5, 4.8))
    plt.plot(x, cg, marker="o")
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xlabel("Inter-intersection distance (m)")
    plt.ylabel("QMIX Coordination Gain vs simultaneous fixed-time (%)")
    plt.title("Two-intersection spatial horizon: Coordination Gain")
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gain_distance")


def plot_demand_gap_and_gain():
    df = read_csv(FILES["demand"])
    df["demand_multiplier"] = df["scenario"].apply(extract_demand_multiplier)
    df = df.sort_values("demand_multiplier")

    x_labels = df["scenario"].tolist()
    x_pos = range(len(x_labels))

    gap = df["qmix_gap_vs_optimized_offset_percent"]
    cg = df["qmix_coordination_gain_percent"]

    plt.figure(figsize=(8.2, 4.8))
    plt.plot(x_pos, gap, marker="o")
    plt.axhline(5, linestyle="--", linewidth=1)
    plt.axhline(10, linestyle="--", linewidth=1)
    plt.xticks(x_pos, x_labels, rotation=25, ha="right")
    plt.xlabel("Demand scenario")
    plt.ylabel("QMIX gap vs optimized offset (%)")
    plt.title("Demand horizon: QMIX approximation gap")
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gap_demand")

    plt.figure(figsize=(8.2, 4.8))
    plt.plot(x_pos, cg, marker="o")
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xticks(x_pos, x_labels, rotation=25, ha="right")
    plt.xlabel("Demand scenario")
    plt.ylabel("QMIX Coordination Gain vs simultaneous fixed-time (%)")
    plt.title("Demand horizon: Coordination Gain")
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gain_demand")


def plot_d23_gap_and_gain():
    df = read_csv(FILES["d23"])
    df["d23_m"] = df["scenario"].apply(extract_d23_m)
    df = df.sort_values("d23_m")

    x = df["d23_m"]
    gap = df["qmix_gap_vs_optimized_offset_percent"]
    cg = df["qmix_coordination_gain_percent"]

    plt.figure(figsize=(7.5, 4.8))
    plt.plot(x, gap, marker="o")
    plt.axhline(5, linestyle="--", linewidth=1)
    plt.axhline(10, linestyle="--", linewidth=1)
    plt.xlabel("Third-light distance d23 (m)")
    plt.ylabel("QMIX gap vs optimized offset (%)")
    plt.title("Three-intersection third-light horizon: QMIX approximation gap")
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gap_d23")

    plt.figure(figsize=(7.5, 4.8))
    plt.plot(x, cg, marker="o")
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xlabel("Third-light distance d23 (m)")
    plt.ylabel("QMIX Coordination Gain vs simultaneous fixed-time (%)")
    plt.title("Three-intersection third-light horizon: Coordination Gain")
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gain_d23")


def plot_threshold_sensitivity():
    df = read_csv(FILES["threshold"])

    # Keep only the three main horizon families for readability.
    keep = [
        "Two-intersection spatial horizon",
        "Two-intersection demand horizon",
        "Three-intersection third-light spatial horizon",
        "Three-intersection reference scalability horizon",
    ]
    df = df[df["horizon_type"].isin(keep)].copy()

    pivot = df.pivot(
        index="horizon_type",
        columns="gap_threshold_percent",
        values="number_of_effective_scenarios",
    )

    pivot = pivot[[3, 5, 10]]

    plt.figure(figsize=(8.8, 5.2))
    pivot.plot(kind="bar", ax=plt.gca())
    plt.xlabel("Horizon type")
    plt.ylabel("Number of effective scenarios")
    plt.title("DCHF threshold sensitivity")
    plt.xticks(rotation=25, ha="right")
    plt.grid(True, axis="y", alpha=0.3)
    plt.legend(title="Gap threshold (%)")
    save_figure("dchf_threshold_sensitivity")


def plot_early_scalability():
    df = read_csv(FILES["scalability"])

    x = df["N"]
    gap = df["qmix_gap_vs_optimized_offset_percent"]
    cg = df["qmix_coordination_gain_percent"]

    plt.figure(figsize=(6.8, 4.6))
    plt.plot(x, gap, marker="o")
    plt.axhline(5, linestyle="--", linewidth=1)
    plt.axhline(10, linestyle="--", linewidth=1)
    plt.xlabel("Number of coordinated intersections (N)")
    plt.ylabel("QMIX gap vs optimized offset (%)")
    plt.title("Early scalability projection: QMIX approximation gap")
    plt.xticks(x)
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gap_scalability")

    plt.figure(figsize=(6.8, 4.6))
    plt.plot(x, cg, marker="o")
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xlabel("Number of coordinated intersections (N)")
    plt.ylabel("QMIX Coordination Gain vs simultaneous fixed-time (%)")
    plt.title("Early scalability projection: Coordination Gain")
    plt.xticks(x)
    plt.grid(True, alpha=0.3)
    save_figure("dchf_gain_scalability")


def main():
    plot_distance_gap_and_gain()
    plot_demand_gap_and_gain()
    plot_d23_gap_and_gain()
    plot_threshold_sensitivity()
    plot_early_scalability()

    print("\nAll DCHF figures generated successfully.")
    print(f"Figures folder: {FIG_DIR}")


if __name__ == "__main__":
    main()