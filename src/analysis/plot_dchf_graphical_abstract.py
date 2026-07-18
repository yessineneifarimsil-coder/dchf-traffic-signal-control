from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from matplotlib.patches import Rectangle, FancyBboxPatch, Circle, Arc


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_PNG = OUT_DIR / "dchf_graphical_abstract.png"
OUT_PDF = OUT_DIR / "dchf_graphical_abstract.pdf"

SPACINGS = [100, 200, 300, 500, 750, 1000]
DEMANDS = [0.5, 1.0, 1.5, 2.0, 2.5]
DEMAND_LABELS = ["0.5×", "1.0×", "1.5×", "2.0×", "2.5×"]

COLORS = {
    1: "#2E9B3E",  # useful effective coordination
    2: "#7B3FA1",  # capacity-constrained effective
    3: "#B0B0B0",  # close/no-gain, unused here
    4: "#F5A623",  # marginal
    5: "#D83A3A",  # outside horizon
}

LABELS = {
    1: "Effective\n(G ≤ 5%)",
    2: "Capacity-constrained\n(capacity-limited)",
    4: "Marginal\n(5–10%)",
    5: "Outside horizon\n(> 10%)",
}

REFERENCE_VALUES = {
    "Optimized\noffset": ("169.8 s", "#0A2F6B"),
    "QMIX V2": ("177.3 s", "#7B3FA1"),
    "Max\nPressure": ("149.9 s", "#0B6B37"),
    "QMIX gap\nvs offset": ("4.42%", "#333333"),
}


def fallback_grid() -> np.ndarray:
    """
    Rows are bottom-to-top demand levels:
    0.5×, 1.0×, 1.5×, 2.0×, 2.5×.

    Columns are:
    100, 200, 300, 500, 750, 1000 m.

    Codes:
    1 = useful effective
    2 = capacity-constrained effective    100, 200, 300, 500, 750, 1000 m.

    Codes:
    1 = useful effective
    2 = capacity-constrained effective
    4 = marginal
    5 = outside horizon
    """
    return np.array(
        [
            [5, 5, 5, 5, 5, 5],  # 0.5×
            [4, 1, 1, 5, 5, 5],  # 1.0×
            [5, 5, 1, 5, 5, 5],  # 1.5×
            [5, 5, 2, 5, 5, 2],  # 2.0×
            [5, 5, 2, 4, 4, 2],  # 2.5×
        ],
        dtype=int,
    )


def load_grid() -> np.ndarray:
    """
    Prefer the corrected CSV, so the graphical abstract stays synchronized
    with Figure 5 and the manuscript. If the CSV is unavailable, use the
    locked fallback grid above.
    """
    csv_path = ROOT / "results" / "tables" / "final_distance_demand_integrated_dchf_classes.csv"

    if not csv_path.exists():
        return fallback_grid()

    df = pd.read_csv(csv_path)
    required = {"distance", "demand_multiplier", "final_integrated_dchf_code"}

    if not required.issubset(df.columns):
        return fallback_grid()

    grid = np.full((len(DEMANDS), len(SPACINGS)), 5, dtype=int)

    for _, row in df.iterrows():
        d = int(row["distance"])
        rho = float(row["demand_multiplier"])

        if d in SPACINGS and rho in DEMANDS:
            i = SPACINGS.index(d)
            j = DEMANDS.index(rho)
            grid[j, i] = int(row["final_integrated_dchf_code"])

    return grid


def add_panel_box(fig, xywh, title=None):
    ax = fig.add_axes(xywh)
    ax.axis("off")

    box = FancyBboxPatch(
        (0, 0),
        1,
        1,
        boxstyle="round,pad=0.012,rounding_size=0.022",
        transform=ax.transAxes,
        facecolor="white",
        edgecolor="#163A6B",
        linewidth=1.2,
        clip_on=False,
    )
    ax.add_patch(box)

    if title:
        ax.text(
            0.5,
            0.965,
            title,
            ha="center",
            va="top",
            fontsize=14,
            fontweight="bold",
            color="black",
            transform=ax.transAxes,
        )

    return ax


def draw_heatmap(fig, panel_xywh, grid):
    left, bottom, width, height = panel_xywh

    ax = fig.add_axes(
        [
            left + 0.07 * width,
            bottom + 0.36 * height,
            0.86 * width,
            0.48 * height,
        ]
    )

    ax.set_xlim(0, 6)
    ax.set_ylim(0, 5)
    ax.set_aspect("equal")
    ax.axis("off")

    for j, _rho in enumerate(DEMANDS):
        for i, _d in enumerate(SPACINGS):
            code = int(grid[j, i])
            rect = Rectangle(
                (i, j),
                1,
                1,
                facecolor=COLORS[code],
                edgecolor="white",
                linewidth=2.0,
            )
            ax.add_patch(rect)

    # Label the useful cluster.
    cluster = FancyBboxPatch(
        (1.04, 0.98),
        1.90,
        1.05,
        boxstyle="round,pad=0.02,rounding_size=0.05",
        facecolor="none",
        edgecolor="white",
        linewidth=1.8,
        alpha=0.8,
    )
    ax.add_patch(cluster)

    ax.text(
        2.0,
        1.55,
        "effective\npocket",
        color="white",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
    )

    for i, d in enumerate(SPACINGS):
        ax.text(
            i + 0.5,
            -0.26,
            str(d),
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
        )

    for j, label in enumerate(DEMAND_LABELS):
        ax.text(
            -0.23,
            j + 0.5,
            label,
            ha="right",
            va="center",
            fontsize=11,
            fontweight="bold",
        )

    ax.text(
        3.0,
        -0.70,
        "Inter-intersection spacing  $d$  (m)",
        ha="center",
        va="center",
        fontsize=12,
    )

    ax.text(
        -0.95,
        2.5,
        "Demand multiplier",
        ha="center",
        va="center",
        rotation=90,
        fontsize=12,
        fontweight="bold",
    )

    # Legend.
    leg = fig.add_axes(
        [
            left + 0.055 * width,
            bottom + 0.18 * height,
            0.90 * width,
            0.11 * height,
        ]
    )
    leg.axis("off")

    legend_items = [
        (1, LABELS[1]),
        (2, LABELS[2]),
        (4, LABELS[4]),
        (5, LABELS[5]),
    ]
    xs = [0.02, 0.265, 0.57, 0.79]

    for x, (code, text) in zip(xs, legend_items):
        leg.add_patch(
            Rectangle(
                (x, 0.45),
                0.045,
                0.34,
                transform=leg.transAxes,
                facecolor=COLORS[code],
                edgecolor="none",
            )
        )
        leg.text(
            x + 0.065,
            0.62,
            text,
            transform=leg.transAxes,
            va="center",
            ha="left",
            fontsize=9.5,
        )

    # Integrated-map callout.
    call = fig.add_axes(
        [
            left + 0.045 * width,
            bottom + 0.035 * height,
            0.91 * width,
            0.105 * height,
        ]
    )
    call.axis("off")

    call.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor="#F3F8FF",
            edgecolor="#163A6B",
            linewidth=0.9,
        )
    )

    # Small map-pin icon.
    call.plot([0.035, 0.065, 0.095, 0.125], [0.22, 0.34, 0.24, 0.36], color="#0A2F6B", lw=2)
    call.plot([0.035, 0.035], [0.22, 0.70], color="#0A2F6B", lw=2)
    call.plot([0.065, 0.065], [0.34, 0.82], color="#0A2F6B", lw=2)
    call.plot([0.095, 0.095], [0.24, 0.72], color="#0A2F6B", lw=2)
    call.plot([0.125, 0.125], [0.36, 0.84], color="#0A2F6B", lw=2)
    call.add_patch(Circle((0.145, 0.77), 0.035, color="#0A2F6B"))
    call.add_patch(Circle((0.145, 0.77), 0.014, color="white"))

   call.text(0.19, 0.57, "Integrated map:", fontsize=12.0, fontweight="bold", va="center")

call.text(0.385, 0.57, "3 effective", fontsize=12.0, fontweight="bold", color=COLORS[1], va="center")
call.text(0.525, 0.57, "·", fontsize=12.5, color="#444444", va="center")
call.text(0.555, 0.57, "4 capacity-constrained", fontsize=12.0, fontweight="bold", color=COLORS[2], va="center")

call.text(0.44, 0.28, "·", fontsize=12.5, color="#444444", va="center")
call.text(0.475, 0.28, "3 marginal", fontsize=12.0, fontweight="bold", color=COLORS[4], va="center")
call.text(0.620, 0.28, "·", fontsize=12.5, color="#444444", va="center")
call.text(0.655, 0.28, "20 outside", fontsize=12.0, fontweight="bold", color=COLORS[5], va="center")


def draw_regime_schematic(fig, panel_xywh):
    left, bottom, width, height = panel_xywh

    ax = fig.add_axes(
        [
            left + 0.08 * width,
            bottom + 0.16 * height,
            0.86 * width,
            0.72 * height,
        ]
    )

    ax.set_xlim(80, 1040)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(Rectangle((100, 0.08), 300, 0.78, facecolor="#EAF4FF", edgecolor="none"))
    ax.add_patch(Rectangle((400, 0.08), 120, 0.78, facecolor="#F0F0F0", edgecolor="none"))
    ax.add_patch(Rectangle((520, 0.08), 480, 0.78, facecolor="#ECF7ED", edgecolor="none"))

    for x in [400, 520]:
        ax.plot([x, x], [0.08, 0.86], color="#666666", lw=1.0, ls="--")

    ax.annotate("", xy=(1030, 0.08), xytext=(88, 0.08), arrowprops=dict(arrowstyle="-|>", lw=1.4, color="black"))
    ax.annotate("", xy=(88, 0.90), xytext=(88, 0.08), arrowprops=dict(arrowstyle="-|>", lw=1.4, color="black"))

    ax.text(60, 0.77, "Demand\nmultiplier", ha="center", va="center", fontsize=9.5, fontweight="bold")
    ax.text(70, 0.63, "High", ha="right", va="center", fontsize=10)
    ax.text(70, 0.43, "Medium", ha="right", va="center", fontsize=10)
    ax.text(70, 0.22, "Low", ha="right", va="center", fontsize=10)

    for x in [100, 200, 300, 400, 500, 750, 1000]:
        ax.plot([x, x], [0.06, 0.08], color="black", lw=1)
        ax.text(x, 0.015, str(x), ha="center", va="top", fontsize=9.5)

    ax.text(
        565,
        -0.08,
        "Inter-intersection spacing  $d$  (m)",
        ha="center",
        va="top",
        fontsize=10.5,
    )

    ax.text(250, 0.78, "Short spacing\n(≤300 m)", ha="center", va="center", fontsize=11.5, fontweight="bold", color="#0A2F6B")
    ax.text(250, 0.23, "Max Pressure\nbest", ha="center", va="center", fontsize=12, fontweight="bold", color="#0A2F6B")

    ax.text(
        460,
        0.78,
        "Transition\nzone\n(450–500 m)",
        ha="center",
        va="center",
        fontsize=10.5,
        fontweight="bold",
        color="#444444",
    )
    ax.text(
        460,
        0.40,
        "controller-\nfamily\ntransition",
        ha="center",
        va="center",
        fontsize=9.5,
        fontstyle="italic",
        color="#444444",
    )

    ax.text(760, 0.78, "Long spacing\n(≥500 m)", ha="center", va="center", fontsize=11.5, fontweight="bold", color="#0B6B37")
    ax.text(760, 0.46, "Optimized\noffset best", ha="center", va="center", fontsize=12.5, fontweight="bold", color="#0B6B37")

    qmix_box = FancyBboxPatch(
        (175, 0.35),
        180,
        0.30,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        facecolor="none",
        edgecolor=COLORS[2],
        linewidth=1.6,
    )
    ax.add_patch(qmix_box)

    ax.text(
        265,
        0.50,
        "QMIX useful\n(≈200–300 m)\nunder medium–high\ndemand",
        ha="center",
        va="center",
        fontsize=9.5,
        color=COLORS[2],
        fontweight="bold",
    )


def draw_icon_clock(ax, cx, cy, color):
    ax.add_patch(Circle((cx, cy), 0.045, transform=ax.transAxes, fill=False, edgecolor=color, lw=2))
    ax.plot([cx, cx], [cy, cy + 0.025], transform=ax.transAxes, color=color, lw=2)
    ax.plot([cx, cx + 0.022], [cy, cy - 0.012], transform=ax.transAxes, color=color, lw=2)
    ax.plot([cx - 0.025, cx + 0.025], [cy + 0.06, cy + 0.06], transform=ax.transAxes, color=color, lw=2)


def draw_icon_network(ax, cx, cy, color):
    pts = [
        (cx - 0.035, cy + 0.02),
        (cx, cy + 0.05),
        (cx + 0.035, cy + 0.02),
        (cx - 0.02, cy - 0.035),
        (cx + 0.03, cy - 0.035),
    ]

    for a, b in [(0, 1), (1, 2), (0, 3), (2, 4), (3, 4), (1, 4)]:
        ax.plot([pts[a][0], pts[b][0]], [pts[a][1], pts[b][1]], transform=ax.transAxes, color=color, lw=1.5)

    for x, y in pts:
        ax.add_patch(Circle((x, y), 0.011, transform=ax.transAxes, color="white", ec=color, lw=1.5))


def draw_icon_gauge(ax, cx, cy, color):
    ax.add_patch(Arc((cx, cy - 0.005), 0.09, 0.09, theta1=20, theta2=160, transform=ax.transAxes, color=color, lw=2))
    ax.plot([cx, cx + 0.028], [cy - 0.005, cy + 0.025], transform=ax.transAxes, color=color, lw=2)
    ax.add_patch(Circle((cx, cy - 0.005), 0.006, transform=ax.transAxes, color=color))

    for ang in [35, 90, 145]:
        rad = np.deg2rad(ang)
        ax.plot(
            [cx + 0.035 * np.cos(rad), cx + 0.045 * np.cos(rad)],
            [cy - 0.005 + 0.035 * np.sin(rad), cy - 0.005 + 0.045 * np.sin(rad)],
            transform=ax.transAxes,
            color=color,
            lw=1.5,
        )


def draw_icon_bars(ax, cx, cy, color):
    heights = [0.025, 0.04, 0.06, 0.08]

    for k, h in enumerate(heights):
        x = cx - 0.045 + k * 0.027
        ax.add_patch(
            Rectangle(
                (x, cy - 0.045),
                0.011,
                h,
                transform=ax.transAxes,
                facecolor="none",
                edgecolor=color,
                lw=1.6,
            )
        )


def draw_scorecard(fig, panel_xywh):
    left, bottom, width, height = panel_xywh

    ax = fig.add_axes(
        [
            left + 0.035 * width,
            bottom + 0.18 * height,
            0.93 * width,
            0.66 * height,
        ]
    )
    ax.axis("off")

    ax.add_patch(Rectangle((0, 0.34), 1, 0.58, transform=ax.transAxes, facecolor="white", edgecolor="#888888", lw=0.9))

    for k in range(1, 4):
        ax.plot([k / 4, k / 4], [0.34, 0.92], transform=ax.transAxes, color="#AAAAAA", lw=0.8)

    ax.plot([0, 1], [0.56, 0.56], transform=ax.transAxes, color="#AAAAAA", lw=0.8)

    icon_funcs = [draw_icon_clock, draw_icon_network, draw_icon_gauge, draw_icon_bars]

    for idx, ((label, (value, color)), icon_func) in enumerate(zip(REFERENCE_VALUES.items(), icon_funcs)):
        x0 = idx / 4 + 0.125

        icon_func(ax, x0, 0.82, color)

        ax.text(
            x0,
            0.66,
            label,
            ha="center",
            va="center",
            fontsize=11.5,
            fontweight="bold",
            color=color,
            transform=ax.transAxes,
        )

        ax.add_patch(
            Rectangle(
                (idx / 4, 0.34),
                0.25,
                0.22,
                transform=ax.transAxes,
                facecolor=color,
                alpha=0.08,
                edgecolor="none",
            )
        )

        ax.text(
            x0,
            0.445,
            value,
            ha="center",
            va="center",
            fontsize=15.5,
            fontweight="bold",
            color=color,
            transform=ax.transAxes,
        )

    # Target icon and takeaway.
    ax.add_patch(Circle((0.06, 0.17), 0.045, transform=ax.transAxes, fill=False, ec="#0A2F6B", lw=2))
    ax.add_patch(Circle((0.06, 0.17), 0.024, transform=ax.transAxes, fill=False, ec="#0A2F6B", lw=2))
    ax.add_patch(Circle((0.06, 0.17), 0.006, transform=ax.transAxes, color="#0A2F6B"))
    ax.plot([0.06, 0.105], [0.17, 0.22], transform=ax.transAxes, color="#0A2F6B", lw=2)

    ax.text(
        0.13,
        0.20,
        "QMIX remains close to the benchmark,",
        ha="left",
        va="center",
        fontsize=11.5,
        transform=ax.transAxes,
        fontstyle="italic",
    )
    ax.text(
        0.13,
        0.105,
        "but Max Pressure is best at the reference condition.",
        ha="left",
        va="center",
        fontsize=11.5,
        transform=ax.transAxes,
        fontstyle="italic",
    )


def main():
    grid = load_grid()

    counts = {code: int((grid == code).sum()) for code in [1, 2, 3, 4, 5]}
    expected = {1: 3, 2: 4, 3: 0, 4: 3, 5: 20}

    if counts != expected:
        raise ValueError(
            f"Integrated class counts do not match expected 3/4/0/3/20 split: {counts}"
        )

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    fig = plt.figure(figsize=(16, 9), dpi=220, facecolor="white")

    fig.text(
        0.5,
        0.965,
        "Dynamic Coordination Horizon Framework (DCHF)",
        ha="center",
        va="top",
        fontsize=27,
        fontweight="bold",
        color="#0A2F6B",
    )

    fig.text(
        0.5,
        0.925,
        "A diagnostic that asks not whether cooperative MARL wins, but when and where coordination is worth deploying.",
        ha="center",
        va="top",
        fontsize=13.5,
        fontstyle="italic",
        color="black",
    )

    left_panel = [0.035, 0.165, 0.49, 0.725]
    right_top_panel = [0.545, 0.505, 0.42, 0.385]
    right_bottom_panel = [0.545, 0.165, 0.42, 0.315]

    add_panel_box(fig, left_panel, "Coordination usefulness is a surface, not a verdict")
    draw_heatmap(fig, left_panel, grid)

    add_panel_box(fig, right_top_panel, "Different controller families own different regimes")
    draw_regime_schematic(fig, right_top_panel)

    add_panel_box(fig, right_bottom_panel, "Reference corridor (300 m, 10 seeds)")
    draw_scorecard(fig, right_bottom_panel)

    footer_ax = fig.add_axes([0.035, 0.045, 0.93, 0.08])
    footer_ax.axis("off")

    footer_ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.012,rounding_size=0.02",
            facecolor="#F3F8FF",
            edgecolor="#163A6B",
            linewidth=1.2,
            transform=footer_ax.transAxes,
            clip_on=False,
        )
    )

    footer_ax.add_patch(Circle((0.045, 0.50), 0.060, transform=footer_ax.transAxes, color="#0A2F6B"))
footer_ax.text(
    0.045,
    0.50,
    "★",
    color="white",
    ha="center",
    va="center",
    fontsize=16,
    transform=footer_ax.transAxes,
)

footer_ax.text(
    0.095,
    0.50,
    "Key message:",
    color="#0A2F6B",
    ha="left",
    va="center",
    fontsize=14.5,
    fontweight="bold",
    transform=footer_ax.transAxes,
)

footer_ax.text(
    0.245,
    0.50,
    "coordination usefulness is regime-dependent; no single controller family dominates the full operating space.",
    color="black",
    ha="left",
    va="center",
    fontsize=13.2,
    fontstyle="italic",
    fontweight="bold",
    transform=footer_ax.transAxes,
)

    fig.savefig(OUT_PNG, dpi=400, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT_PDF, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print("Generated:")
    print(OUT_PNG)
    print(OUT_PDF)
    print("Verified class counts:", counts)


if __name__ == "__main__":
    main()