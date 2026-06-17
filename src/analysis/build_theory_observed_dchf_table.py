import os
import pandas as pd

TABLE_DIR = "results/tables"
os.makedirs(TABLE_DIR, exist_ok=True)

OUT_CSV = f"{TABLE_DIR}/theory_observed_dchf_interpretation.csv"
OUT_TEX = f"{TABLE_DIR}/theory_observed_dchf_interpretation.tex"

rows = [
    {
        "DCHF dimension": "Low-demand coordination limit",
        "Theory-based expectation": (
            "Under low demand, platoons are weak and vehicle interactions are sparse; "
            "therefore, the benefit of coordinated signal control is expected to be limited."
        ),
        "Observed result": (
            "Most low-demand cases fall outside the useful coordination horizon, even when "
            "the network is unconstrained."
        ),
        "Interpretation": (
            "The lower demand horizon is confirmed: coordination is not always useful when "
            "traffic pressure is too weak."
        ),
    },
    {
        "DCHF dimension": "Intermediate spacing",
        "Theory-based expectation": (
            "Classical progression theory suggests that coordination is most useful when "
            "intersections are close enough to preserve platoon structure but not so close "
            "that storage interference dominates."
        ),
        "Observed result": (
            "The strongest useful coordination region is concentrated around 200--300 m, "
            "especially around 300 m."
        ),
        "Interpretation": (
            "The observed spatial horizon supports a non-monotonic coordination effect, "
            "with an intermediate favorable spacing region."
        ),
    },
    {
        "DCHF dimension": "Very short spacing",
        "Theory-based expectation": (
            "Very short spacing may increase interaction between signals but can also create "
            "queue spillback, limited storage, and rapid interference between intersections."
        ),
        "Observed result": (
            "At 100 m, medium demand is marginal, while higher demand regimes mostly fall "
            "outside the useful coordination horizon."
        ),
        "Interpretation": (
            "Short distance alone does not guarantee useful coordination; storage and "
            "interference effects can dominate."
        ),
    },
    {
        "DCHF dimension": "Long-distance coordination decay",
        "Theory-based expectation": (
            "As distance increases, platoons disperse and the temporal coupling between "
            "upstream and downstream signals weakens."
        ),
        "Observed result": (
            "At 500 m and 750 m, QMIX performance deteriorates in many demand regimes. "
            "At 1000 m, several cases are outside the coordination horizon."
        ),
        "Interpretation": (
            "The spatial coordination horizon is bounded; long links weaken useful learned "
            "coordination."
        ),
    },
    {
        "DCHF dimension": "Capacity and oversaturation",
        "Theory-based expectation": (
            "Under saturation and oversaturation, physical capacity constraints may dominate "
            "controller differences."
        ),
        "Observed result": (
            "Several saturation and oversaturation cases have high buffered ratios. Some cases "
            "are algorithmically close to the optimized offset benchmark but capacity-limited."
        ),
        "Interpretation": (
            "A small QMIX gap is not sufficient to claim useful coordination; capacity state "
            "must also be considered."
        ),
    },
    {
        "DCHF dimension": "Integrated distance--demand diagnosis",
        "Theory-based expectation": (
            "Coordination effectiveness should emerge from the joint interaction between "
            "spacing, demand, and capacity rather than from a single threshold."
        ),
        "Observed result": (
            "Only 4 of 30 distance--demand cases are useful effective coordination cases; "
            "2 are algorithmically effective but capacity-limited; 1 is close but has no "
            "practical gain; 3 are marginal; and 20 are outside the horizon."
        ),
        "Interpretation": (
            "The coordination horizon is a surface, not a fixed distance or demand threshold."
        ),
    },
    {
        "DCHF dimension": "Scalability to three intersections",
        "Theory-based expectation": (
            "Adding a downstream signal increases coordination complexity and may reduce "
            "the transferability of a learned policy."
        ),
        "Observed result": (
            "The three-intersection reference case remains effective with a QMIX gap of "
            "4.455%, while the third-light distance experiment is effective only at "
            "300 m and 500 m, marginal at 750 m, and outside at 100 m, 200 m, and 1000 m."
        ),
        "Interpretation": (
            "Early scalability is possible, but it remains bounded by downstream spacing "
            "and network structure."
        ),
    },
    {
        "DCHF dimension": "Robustness across seeds",
        "Theory-based expectation": (
            "If the DCHF regimes are meaningful, selected effective and outside-horizon "
            "cases should remain stable under stochastic vehicle insertion."
        ),
        "Observed result": (
            "Multi-seed validation confirms 100% regime stability for selected effective "
            "and outside-horizon cases."
        ),
        "Interpretation": (
            "The observed horizon classifications are not artifacts of a single SUMO seed."
        ),
    },
]

df = pd.DataFrame(rows)
df.to_csv(OUT_CSV, index=False)

latex = r"""\begin{table}[H]
\centering
\caption{Theory-based interpretation of the observed DCHF horizons.}
\label{tab:theory_observed_dchf_interpretation}
\small
\begin{tabular}{p{0.21\textwidth}p{0.25\textwidth}p{0.25\textwidth}p{0.21\textwidth}}
\toprule
\textbf{DCHF dimension} & \textbf{Theory-based expectation} & \textbf{Observed result} & \textbf{Interpretation} \\
\midrule
"""

for _, row in df.iterrows():
    latex += (
        row["DCHF dimension"]
        + " & "
        + row["Theory-based expectation"]
        + " & "
        + row["Observed result"]
        + " & "
        + row["Interpretation"]
        + r" \\"
        + "\n\\midrule\n"
    )

latex = latex.replace("\\midrule\n\\end", "\\bottomrule\n\\end")

latex += r"""\bottomrule
\end{tabular}
\end{table}
"""

with open(OUT_TEX, "w", encoding="utf-8") as f:
    f.write(latex)

print("Theory vs observed DCHF table generated.")
print(f"Saved CSV: {OUT_CSV}")
print(f"Saved LaTeX: {OUT_TEX}")

print("\nPreview:")
print(df.to_string(index=False))