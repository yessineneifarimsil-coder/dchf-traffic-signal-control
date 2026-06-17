import os
import pandas as pd


TABLE_DIR = "results/tables"

OUT_PLAN = f"{TABLE_DIR}/multiseed_horizon_validation_plan.csv"
OUT_LATEX = f"{TABLE_DIR}/multiseed_horizon_validation_plan_latex.txt"


def main():
    os.makedirs(TABLE_DIR, exist_ok=True)

    plan = pd.DataFrame([
        {
            "validation_block": "Two-intersection spatial horizon",
            "case_type": "Effective case",
            "scenario": "d12 = 300 m",
            "reason_for_selection": "Reference effective spatial case; QMIX gap was below 5%.",
            "controllers_to_compare": "Simultaneous fixed-time; optimized offset; QMIX V2",
            "seeds": "0, 1, 2, 3, 4",
            "metrics": "mean waiting time; mean speed; mean queue; Coordination Gain; QMIX gap",
            "expected_interpretation": "Should remain effective across seeds if the horizon classification is robust."
        },
        {
            "validation_block": "Two-intersection spatial horizon",
            "case_type": "Outside-horizon case",
            "scenario": "d12 = 1000 m",
            "reason_for_selection": "Long-distance outside-horizon case; QMIX gap was far above 10%.",
            "controllers_to_compare": "Simultaneous fixed-time; optimized offset; QMIX V2",
            "seeds": "0, 1, 2, 3, 4",
            "metrics": "mean waiting time; mean speed; mean queue; Coordination Gain; QMIX gap",
            "expected_interpretation": "Should remain outside the horizon across seeds if long-distance coordination collapse is robust."
        },
        {
            "validation_block": "Three-intersection third-light horizon",
            "case_type": "Effective case",
            "scenario": "d12 = 300 m, d23 = 500 m",
            "reason_for_selection": "Best tested third-light distance; QMIX gap was below 5%.",
            "controllers_to_compare": "Simultaneous fixed-time; optimized offset; three-agent QMIX",
            "seeds": "0, 1, 2, 3, 4",
            "metrics": "mean waiting time; mean speed; mean queue; Coordination Gain; QMIX gap",
            "expected_interpretation": "Should remain effective across seeds if the d23 = 500 m horizon result is robust."
        },
        {
            "validation_block": "Three-intersection third-light horizon",
            "case_type": "Outside-horizon case",
            "scenario": "d12 = 300 m, d23 = 1000 m",
            "reason_for_selection": "Long-distance third-light case; QMIX gap was far above 10%.",
            "controllers_to_compare": "Simultaneous fixed-time; optimized offset; three-agent QMIX",
            "seeds": "0, 1, 2, 3, 4",
            "metrics": "mean waiting time; mean speed; mean queue; Coordination Gain; QMIX gap",
            "expected_interpretation": "Should remain outside the horizon across seeds if the downstream distance limit is robust."
        },
    ])

    plan.to_csv(OUT_PLAN, index=False)

    latex = r"""
\subsection{Multi-Seed Validation of Horizon Stability}

To verify that the DCHF classifications are not artifacts of a single stochastic simulation run, a targeted multi-seed validation is conducted on selected effective and outside-horizon cases. Four representative scenarios are retained: a two-intersection effective case, a two-intersection outside-horizon case, a three-intersection effective third-light case, and a three-intersection outside-horizon third-light case. For each scenario, the same controller comparison is repeated over five SUMO random seeds, while the network geometry, demand level, signal timing structure, and controller configuration remain fixed.

\begin{table}[H]
\centering
\caption{Planned multi-seed validation cases for DCHF horizon stability.}
\label{tab:multiseed_horizon_validation_plan}
\begin{tabular}{L{3.5cm}L{3.0cm}L{3.2cm}L{4.0cm}}
\toprule
\textbf{Validation block} & \textbf{Case type} & \textbf{Scenario} & \textbf{Purpose} \\
\midrule
Two-intersection spatial horizon & Effective & $d_{12}=300$ m & Test whether an effective spatial case remains effective across seeds. \\
Two-intersection spatial horizon & Outside horizon & $d_{12}=1000$ m & Test whether long-distance coordination collapse remains outside the horizon. \\
Three-intersection third-light horizon & Effective & $d_{12}=300$ m, $d_{23}=500$ m & Test robustness of the best tested third-light distance. \\
Three-intersection third-light horizon & Outside horizon & $d_{12}=300$ m, $d_{23}=1000$ m & Test robustness of the downstream distance limit. \\
\bottomrule
\end{tabular}
\end{table}
"""

    with open(OUT_LATEX, "w", encoding="utf-8") as f:
        f.write(latex)

    print("\n=== Multi-seed horizon validation plan ===")
    print(plan.to_string(index=False))

    print(f"\nSaved plan to: {OUT_PLAN}")
    print(f"Saved LaTeX block to: {OUT_LATEX}")


if __name__ == "__main__":
    main()