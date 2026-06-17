import os
import pandas as pd
import matplotlib.pyplot as plt


TABLE_DIR = "results/tables"
FIG_DIR = "results/figures"

SUMMARY_FILE = f"{TABLE_DIR}/multiseed_horizon_validation_summary.csv"
REGIME_FILE = f"{TABLE_DIR}/multiseed_horizon_regime_stability.csv"

OUT_GAP_PDF = f"{FIG_DIR}/multiseed_horizon_qmix_gap.pdf"
OUT_GAP_PNG = f"{FIG_DIR}/multiseed_horizon_qmix_gap.png"

OUT_STABILITY_PDF = f"{FIG_DIR}/multiseed_horizon_regime_stability.pdf"
OUT_STABILITY_PNG = f"{FIG_DIR}/multiseed_horizon_regime_stability.png"

OUT_GAIN_PDF = f"{FIG_DIR}/multiseed_horizon_coordination_gain.pdf"
OUT_GAIN_PNG = f"{FIG_DIR}/multiseed_horizon_coordination_gain.png"


def short_label(row):
    scenario = str(row["scenario"])

    if "d12 = 300" in scenario and "d23" not in scenario:
        return "2-int.\n300 m"

    if "d12 = 1000" in scenario:
        return "2-int.\n1000 m"

    if "d23 = 500" in scenario:
        return "3-int.\nd23=500 m"

    if "d23 = 1000" in scenario:
        return "3-int.\nd23=1000 m"

    return scenario


def main():
    os.makedirs(FIG_DIR, exist_ok=True)

    if not os.path.exists(SUMMARY_FILE):
        raise FileNotFoundError(f"Missing file: {SUMMARY_FILE}")

    if not os.path.exists(REGIME_FILE):
        raise FileNotFoundError(f"Missing file: {REGIME_FILE}")

    summary = pd.read_csv(SUMMARY_FILE)
    regimes = pd.read_csv(REGIME_FILE)

    summary["label"] = summary.apply(short_label, axis=1)
    regimes["label"] = regimes.apply(short_label, axis=1)

    # =====================================================
    # Figure 1: QMIX gap mean ± std
    # =====================================================
    x = range(len(summary))
    y = summary["qmix_gap_vs_optimized_offset_percent_mean"]
    yerr = summary["qmix_gap_vs_optimized_offset_percent_std"]

    plt.figure(figsize=(8.2, 4.8))
    plt.errorbar(x, y, yerr=yerr, marker="o", capsize=5, linestyle="none")
    plt.axhline(5, linestyle="--", linewidth=1)
    plt.axhline(10, linestyle="--", linewidth=1)
    plt.xticks(x, summary["label"])
    plt.ylabel("QMIX gap vs optimized offset (%)")
    plt.xlabel("Validation scenario")
    plt.title("Multi-seed validation: QMIX approximation gap")
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_GAP_PDF, bbox_inches="tight")
    plt.savefig(OUT_GAP_PNG, dpi=300, bbox_inches="tight")
    plt.close()

    # =====================================================
    # Figure 2: Regime stability
    # =====================================================
    x = range(len(regimes))
    y = regimes["regime_stability_percent"]

    plt.figure(figsize=(8.2, 4.8))
    plt.bar(x, y)
    plt.ylim(0, 105)
    plt.xticks(x, regimes["label"])
    plt.ylabel("Regime stability across seeds (%)")
    plt.xlabel("Validation scenario")
    plt.title("Multi-seed validation: DCHF regime stability")
    plt.grid(True, axis="y", alpha=0.3)

    for i, value in enumerate(y):
        plt.text(i, value + 1.5, f"{value:.0f}%", ha="center", va="bottom")

    plt.tight_layout()
    plt.savefig(OUT_STABILITY_PDF, bbox_inches="tight")
    plt.savefig(OUT_STABILITY_PNG, dpi=300, bbox_inches="tight")
    plt.close()

    # =====================================================
    # Figure 3: QMIX Coordination Gain mean ± std
    # =====================================================
    x = range(len(summary))
    y = summary["qmix_coordination_gain_percent_mean"]
    yerr = summary["qmix_coordination_gain_percent_std"]

    plt.figure(figsize=(8.2, 4.8))
    plt.errorbar(x, y, yerr=yerr, marker="o", capsize=5, linestyle="none")
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.xticks(x, summary["label"])
    plt.ylabel("QMIX Coordination Gain (%)")
    plt.xlabel("Validation scenario")
    plt.title("Multi-seed validation: QMIX Coordination Gain")
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_GAIN_PDF, bbox_inches="tight")
    plt.savefig(OUT_GAIN_PNG, dpi=300, bbox_inches="tight")
    plt.close()

    print("\nGenerated multi-seed validation figures:")
    print(f"- {OUT_GAP_PDF}")
    print(f"- {OUT_GAP_PNG}")
    print(f"- {OUT_STABILITY_PDF}")
    print(f"- {OUT_STABILITY_PNG}")
    print(f"- {OUT_GAIN_PDF}")
    print(f"- {OUT_GAIN_PNG}")


if __name__ == "__main__":
    main()