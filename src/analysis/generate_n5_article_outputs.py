import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


DCHF_BY_SEED = "results/tables/n5_multiseed_scalability_dchf_by_seed.csv"
CONTROLLER_SUMMARY = "results/tables/n5_multiseed_scalability_controller_summary.csv"
FINAL_SUMMARY = "results/tables/n5_multiseed_scalability_summary.csv"

FIG_DIR = "results/figures"
TABLE_DIR = "results/tables"

os.makedirs(FIG_DIR, exist_ok=True)
os.makedirs(TABLE_DIR, exist_ok=True)

df = pd.read_csv(DCHF_BY_SEED)
ctrl = pd.read_csv(CONTROLLER_SUMMARY)
summary = pd.read_csv(FINAL_SUMMARY)

plt.rcParams.update({
    "font.size": 11,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "legend.fontsize": 10,
})


def save_fig(name):
    pdf_path = os.path.join(FIG_DIR, f"{name}.pdf")
    png_path = os.path.join(FIG_DIR, f"{name}.png")
    plt.tight_layout()
    plt.savefig(pdf_path, bbox_inches="tight")
    plt.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved: {pdf_path}")
    print(f"Saved: {png_path}")


# ============================================================
# Figure 1: Mean waiting time by seed and controller
# ============================================================

seeds = sorted(ctrl["seed"].unique())
controllers = [
    "Simultaneous Fixed-Time",
    "Progression Offset 45s",
    "QMIX 5 Agents",
]
labels = [
    "Simultaneous fixed-time",
    "Progression offset 45 s",
    "QMIX 5 agents",
]

x = np.arange(len(seeds))
width = 0.25

plt.figure(figsize=(8.5, 4.8))

for i, controller in enumerate(controllers):
    values = []
    for seed in seeds:
        value = ctrl[
            (ctrl["seed"] == seed) &
            (ctrl["controller"] == controller)
        ]["mean_total_waiting_time"].iloc[0]
        values.append(value)

    plt.bar(x + (i - 1) * width, values, width, label=labels[i])

plt.xticks(x, [str(s) for s in seeds])
plt.xlabel("SUMO random seed")
plt.ylabel("Mean total waiting time (s)")
plt.title("N=5 scalability validation: waiting time by controller")
plt.legend()
plt.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.7)
save_fig("n5_multiseed_waiting_time_by_controller")


# ============================================================
# Figure 2: QMIX approximation gap by seed
# ============================================================

plt.figure(figsize=(8.0, 4.6))

plt.bar(df["seed"].astype(str), df["qmix_gap_percent"])
plt.axhline(0, linestyle="-", linewidth=1)
plt.axhline(5, linestyle="--", linewidth=1, label="Effective threshold: 5%")
plt.axhline(10, linestyle=":", linewidth=1, label="Marginal threshold: 10%")

plt.xlabel("SUMO random seed")
plt.ylabel("QMIX approximation gap (%)")
plt.title("N=5 scalability validation: QMIX gap vs. progression offset")
plt.legend()
plt.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.7)
save_fig("n5_multiseed_qmix_gap")


# ============================================================
# Figure 3: Coordination gain by seed
# ============================================================

plt.figure(figsize=(8.5, 4.8))

x = np.arange(len(df))
width = 0.35

plt.bar(
    x - width / 2,
    df["offset_coordination_gain_percent"],
    width,
    label="Progression offset 45 s",
)

plt.bar(
    x + width / 2,
    df["qmix_coordination_gain_percent"],
    width,
    label="QMIX 5 agents",
)

plt.xticks(x, df["seed"].astype(str))
plt.xlabel("SUMO random seed")
plt.ylabel("Coordination gain (%)")
plt.title("N=5 scalability validation: coordination gain by seed")
plt.legend()
plt.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.7)
save_fig("n5_multiseed_coordination_gain")


# ============================================================
# LaTeX table 1: DCHF by seed
# ============================================================

table_seed_path = os.path.join(TABLE_DIR, "table_n5_scalability_by_seed.tex")

with open(table_seed_path, "w", encoding="utf-8") as f:
    f.write("\\begin{table}[htbp]\n")
    f.write("\\centering\n")
    f.write("\\caption{Multi-seed scalability validation for the five-intersection corridor.}\n")
    f.write("\\label{tab:n5_scalability_by_seed}\n")
    f.write("\\resizebox{\\textwidth}{!}{%\n")
    f.write("\\begin{tabular}{ccccccccc}\n")
    f.write("\\hline\n")
    f.write("Seed & Sim. WT & Offset WT & QMIX WT & Offset CG (\\%) & QMIX CG (\\%) & QMIX gap (\\%) & BR & Teleports \\\\\n")
    f.write("\\hline\n")

    for _, row in df.iterrows():
        f.write(
            f"{int(row['seed'])} & "
            f"{row['simultaneous_waiting_time']:.3f} & "
            f"{row['best_offset_waiting_time']:.3f} & "
            f"{row['qmix_waiting_time']:.3f} & "
            f"{row['offset_coordination_gain_percent']:.3f} & "
            f"{row['qmix_coordination_gain_percent']:.3f} & "
            f"{row['qmix_gap_percent']:.3f} & "
            f"{row['qmix_buffered_ratio']:.3f} & "
            f"{int(row['qmix_total_teleports'])} \\\\\n"
        )

    f.write("\\hline\n")
    f.write("\\end{tabular}%\n")
    f.write("}\n")
    f.write("\\end{table}\n")

print(f"Saved: {table_seed_path}")


# ============================================================
# LaTeX table 2: Final summary
# ============================================================

s = summary.iloc[0]
table_summary_path = os.path.join(TABLE_DIR, "table_n5_scalability_summary.tex")

with open(table_summary_path, "w", encoding="utf-8") as f:
    f.write("\\begin{table}[htbp]\n")
    f.write("\\centering\n")
    f.write("\\caption{Summary of the five-intersection scalability validation.}\n")
    f.write("\\label{tab:n5_scalability_summary}\n")
    f.write("\\begin{tabular}{lc}\n")
    f.write("\\hline\n")
    f.write("Indicator & Value \\\\\n")
    f.write("\\hline\n")
    f.write(f"Number of seeds & {int(s['seeds'])} \\\\\n")
    f.write(f"Mean QMIX gap (\\%) & {s['qmix_gap_mean']:.3f} \\\\\n")
    f.write(f"Std. QMIX gap (\\%) & {s['qmix_gap_std']:.3f} \\\\\n")
    f.write(f"Mean QMIX coordination gain (\\%) & {s['qmix_gain_mean']:.3f} \\\\\n")
    f.write(f"Std. QMIX coordination gain (\\%) & {s['qmix_gain_std']:.3f} \\\\\n")
    f.write(f"Mean buffered ratio & {s['qmix_buffered_ratio_mean']:.3f} \\\\\n")
    f.write(f"Mean teleports & {s['qmix_total_teleports_mean']:.3f} \\\\\n")
    f.write(f"Effective-regime stability (\\%) & {s['effective_regime_stability_percent']:.1f} \\\\\n")
    f.write("\\hline\n")
    f.write("\\end{tabular}\n")
    f.write("\\end{table}\n")

print(f"Saved: {table_summary_path}")


print("\nArticle outputs generated successfully.")
print("Figures:")
print(" - results/figures/n5_multiseed_waiting_time_by_controller.pdf")
print(" - results/figures/n5_multiseed_qmix_gap.pdf")
print(" - results/figures/n5_multiseed_coordination_gain.pdf")
print("Tables:")
print(" - results/tables/table_n5_scalability_by_seed.tex")
print(" - results/tables/table_n5_scalability_summary.tex")