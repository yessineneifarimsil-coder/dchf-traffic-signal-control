"""Reproducible figures for the manuscript (matplotlib, Agg). Every figure writes its plotted data to
figures/data/<name>.csv; failures are drawn explicitly (red cross in a separate band, never averaged) and
every panel states its counts.

    python figures/make_figures.py --ablation analysis/ablation --min7 D:\\QMIX_Results\\fixed_timing_min7_2026-10-28\\summary\\comparison_runs.csv
"""
import argparse
import csv
import os
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ARM_COLORS = {"none": "#2a78d6", "guarantee": "#eb6834", "min_green": "#1baf7a", "both": "#eda100"}
ARM_MARKERS = {"none": "o", "guarantee": "s", "min_green": "^", "both": "D"}
ARM_LABEL = {"none": "no protection", "guarantee": "guarantee only", "min_green": "minimum green only", "both": "both"}
METHOD_LABEL = {"qmix": "QMIX", "vdn": "VDN", "idqn": "IDQN"}
FAIL = "#d03b3b"
INK, INK2 = "#0b0b0b", "#52514e"
plt.rcParams.update({"font.size": 8, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.6,
                     "axes.axisbelow": True, "savefig.dpi": 300, "font.family": "DejaVu Sans"})


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fnum(x):
    return None if x in (None, "", "None", "nan") else float(x)


def save(fig, name, rows, fields):
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    with open(os.path.join(HERE, "data", name + ".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    fig.savefig(os.path.join(HERE, name + ".pdf"), bbox_inches="tight")
    fig.savefig(os.path.join(HERE, name + ".png"), bbox_inches="tight")
    plt.close(fig)


def fig_same_traffic(cells, fixed):
    groups = [("Old fixed\nplan\nC19 8/5 s", [r for r in fixed if r["arm"] == "A_old_fixed"], None),
              ("Fixed plan,\ngreens ≥7 s\nC25 12/7 s", [r for r in fixed if r["arm"] == "B_min7_fixed"], None)]
    for arm in ("none", "both"):
        for m in ("qmix", "vdn", "idqn"):
            groups.append(("{}\n{}".format(METHOD_LABEL[m], ARM_LABEL[arm]),
                           [r for r in cells if r["method"] == m and r["arm"] == arm], arm))
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    rows, top = [], 0
    for i, (label, rs, arm) in enumerate(groups):
        js = [fnum(r.get("J_primary_s") or r.get("J_primary_s")) for r in rs]
        top = max([top] + [j for j in js if j is not None])
    band = top * 1.12
    for i, (label, rs, arm) in enumerate(groups):
        color = ARM_COLORS[arm] if arm else INK2
        valid, fails = [], 0
        for k, r in enumerate(rs):
            j = fnum(r.get("J_primary_s"))
            status = r.get("status")
            x = i + (k % 10 - 4.5) * 0.035 if arm else i + (k - 2) * 0.06
            if j is None or status != "CLEARED":
                fails += 1
                ax.plot([x], [band], marker="x", color=FAIL, ms=6, mew=1.5)
            else:
                valid.append(j)
                ax.plot([x], [j], marker=ARM_MARKERS.get(arm, "o"), color=color, ms=3.2, alpha=0.75, mec="none")
            rows.append({"group": label.replace("\n", " "), "model": r.get("model", r.get("arm")),
                         "traffic_seed": r.get("traffic_seed"), "status": status, "J_primary_s": j})
        if valid:
            ax.plot([i - 0.25, i + 0.25], [statistics.median(valid)] * 2, color=INK, lw=1.2)
        ax.text(i, band * 1.05, "{}/{}\nvalid".format(len(valid), len(rs)), ha="center", fontsize=6.5, color=INK2)
    ax.axhline(band * 0.985, color="#c9c8c3", lw=0.6)
    ax.text(len(groups) - 0.45, band, "failure\n(J undefined)", color=FAIL, fontsize=6.5, va="center")
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g[0] for g in groups], fontsize=6.5)
    ax.set_ylabel("J: mean waiting burden per scheduled vehicle (s)")
    ax.set_xlim(-0.6, len(groups) - 0.2)
    ax.set_ylim(min(fnum(r["J_primary_s"]) for r in rows if r["J_primary_s"] is not None) * 0.9, band * 1.16)
    ax.set_title("Development traffics 9301–9305: every evaluation shown (bar = median of valid runs)",
                 fontsize=8, color=INK, loc="left")
    save(fig, "fig1_same_traffic_performance", rows, ["group", "model", "traffic_seed", "status", "J_primary_s"])


def fig_paired(pairs, key, ylabel, name):
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.6), sharey=True)
    rows = []
    for ax, m in zip(axes, ("qmix", "vdn", "idqn")):
        for i, arm in enumerate(("guarantee", "min_green", "both")):
            ps = [p for p in pairs if p["method"] == m and p["arm"] == arm]
            v = [fnum(p[key]) for p in ps if fnum(p[key]) is not None]
            excluded = len(ps) - len(v)
            if v:
                ax.boxplot([v], positions=[i], widths=0.5, showfliers=False,
                           medianprops={"color": INK, "lw": 1.2}, boxprops={"color": INK2},
                           whiskerprops={"color": INK2}, capprops={"color": INK2})
                ax.plot([i + (k % 25 - 12) * 0.012 for k in range(len(v))], v, ARM_MARKERS[arm],
                        color=ARM_COLORS[arm], ms=2.6, alpha=0.6, mec="none")
            ax.text(i, 1.02, "n={}".format(len(v)) + ("\n{} excl.".format(excluded) if excluded else ""),
                    transform=ax.get_xaxis_transform(), ha="center", fontsize=6, color=INK2)
            for p in ps:
                rows.append({"method": m, "arm": arm, "model": p["model"], "traffic_seed": p["traffic_seed"],
                             key: fnum(p[key]), "status_none": p["status_none"], "status_arm": p["status_arm"]})
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_xticks(range(3))
        ax.set_xticklabels(["guarantee\nonly", "min. green\nonly", "both"], fontsize=6.5)
        ax.set_title(METHOD_LABEL[m], fontsize=8, color=INK, pad=16)
    axes[0].set_ylabel(ylabel)
    save(fig, name, rows, ["method", "arm", "model", "traffic_seed", key, "status_none", "status_arm"])


def fig_service(cells):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 2.8), gridspec_kw={"width_ratios": [1, 1.6]})
    rows = []
    arms = ("none", "guarantee", "min_green", "both")
    for j, m in enumerate(("qmix", "vdn", "idqn")):
        for i, arm in enumerate(arms):
            rs = [r for r in cells if r["method"] == m and r["arm"] == arm]
            nf = sum(r["status"] != "CLEARED" for r in rs)
            x = j * 5 + i
            a1.bar([x], [nf], color=ARM_COLORS[arm], width=0.8)
            a1.text(x, nf + 0.1, "{}".format(nf), ha="center", fontsize=6.5, color=INK)
            for k, r in enumerate(rs):
                c = fnum(r["max_counter_s"])
                a2.plot([x + (k % 10 - 4.5) * 0.06], [max(c, 1)], "x" if r["status"] != "CLEARED" else ARM_MARKERS[arm],
                        color=FAIL if r["status"] != "CLEARED" else ARM_COLORS[arm], ms=3, alpha=0.7)
                rows.append({"method": m, "arm": arm, "model": r["model"], "traffic_seed": r["traffic_seed"],
                             "status": r["status"], "max_counter_s": c,
                             "max_wait_to_first_green_s": fnum(r["max_wait_to_first_green_s"]),
                             "max_vehicle_waiting_s": fnum(r["max_vehicle_waiting_s"])})
    for a in (a1, a2):
        a.set_xticks([j * 5 + 1.5 for j in range(3)])
        a.set_xticklabels([METHOD_LABEL[m] for m in ("qmix", "vdn", "idqn")])
    a1.set_ylabel("clearance failures (of 50 runs)")
    a2.set_yscale("log")
    a2.axhline(127, color=INK, lw=0.8, ls="--")
    a2.text(14.6, 127, " 127 s bound\n (guarantee arms)", fontsize=6, va="center", color=INK)
    a2.set_ylabel("max service counter per run (s, log)")
    handles = [plt.Line2D([], [], marker=ARM_MARKERS[a], color=ARM_COLORS[a], ls="", label=ARM_LABEL[a]) for a in arms]
    handles.append(plt.Line2D([], [], marker="x", color=FAIL, ls="", label="failed run"))
    a2.legend(handles=handles, fontsize=6, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False)
    save(fig, "fig3_failures_and_service", rows, ["method", "arm", "model", "traffic_seed", "status", "max_counter_s",
                                                  "max_wait_to_first_green_s", "max_vehicle_waiting_s"])


def fig_tradeoff(cells, fixed):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 2.9), sharey=True)
    rows = []
    for m, mk in (("qmix", "o"), ("vdn", "s"), ("idqn", "^")):
        for arm in ("none", "guarantee", "min_green", "both"):
            for model in sorted({r["model"] for r in cells if r["method"] == m}):
                rs = [r for r in cells if r["model"] == model and r["arm"] == arm]
                if any(r["status"] != "CLEARED" for r in rs):
                    rows.append({"controller": model, "arm": arm, "J_mean": None, "time_loss_mean": None,
                                 "D_bar_mean": None, "note": "excluded: {} failed run(s) of {}".format(
                                     sum(r["status"] != "CLEARED" for r in rs), len(rs))})
                    continue
                J = statistics.mean(fnum(r["J_primary_s"]) for r in rs)
                TL = statistics.mean(fnum(r["mean_completed_time_loss_s"]) for r in rs)
                D = statistics.mean(fnum(r["D_bar_s"]) for r in rs)
                style = ({"mfc": "none", "mec": ARM_COLORS[arm], "ms": 6, "mew": 0.9} if arm == "none" else
                         {"color": ARM_COLORS[arm], "ms": 3.5, "alpha": 0.8, "mec": "none"})
                a1.plot([TL], [J], mk, **style)
                a2.plot([D], [J], mk, **style)
                rows.append({"controller": model, "arm": arm, "J_mean": J, "time_loss_mean": TL, "D_bar_mean": D,
                             "note": "5/5 cleared"})
    for arm_key, label, mk, off in (("A_old_fixed", "old fixed plan", "*", (8, -3)),
                                    ("B_min7_fixed", "fixed plan, greens ≥7 s", "P", (6, 6))):
        rs = [r for r in fixed if r["arm"] == arm_key]
        J = statistics.mean(fnum(r["J_primary_s"]) for r in rs)
        TL = statistics.mean(fnum(r["mean_time_loss_s"]) for r in rs)
        a1.plot([TL], [J], mk, color=INK, ms=8)
        a1.annotate(label, (TL, J), xytext=off, textcoords="offset points", fontsize=6.5, color=INK)
        rows.append({"controller": label, "arm": "-", "J_mean": J, "time_loss_mean": TL, "D_bar_mean": None,
                     "note": "5/5 cleared (D not available in the summary file)"})
    a1.set_xscale("log")
    from matplotlib.ticker import FixedLocator, NullLocator, ScalarFormatter
    a1.xaxis.set_major_locator(FixedLocator([10, 15, 20, 30, 60]))
    a1.xaxis.set_minor_locator(NullLocator())
    a1.xaxis.set_major_formatter(ScalarFormatter())
    a1.set_xlabel("mean time loss, completed vehicles (s, log scale)")
    a2.set_xlabel("D/N: waiting burden during the demand (s)")
    fig.subplots_adjust(wspace=0.12)
    a1.set_ylabel("J (s), mean over 5 traffics")
    handles = [plt.Line2D([], [], marker="o", color=ARM_COLORS[a], ls="", label=ARM_LABEL[a],
                          **({"mfc": "none"} if a == "none" else {})) for a in ARM_COLORS]
    handles += [plt.Line2D([], [], marker=mk, color=INK2, ls="", label=METHOD_LABEL[m])
                for m, mk in (("qmix", "o"), ("vdn", "s"), ("idqn", "^"))]
    a2.legend(handles=handles, fontsize=6, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False)
    a1.set_title("Models with 5/5 clearances only (excluded ones listed in the data file);\n"
                 "hollow = no protection, often hidden under an identical guarantee-only point", fontsize=6.5,
                 color=INK2, loc="left")
    save(fig, "fig4_metric_tradeoff", rows, ["controller", "arm", "J_mean", "time_loss_mean", "D_bar_mean", "note"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ablation", required=True)
    ap.add_argument("--min7", required=True)
    a = ap.parse_args()
    cells = read(os.path.join(a.ablation, "cells.csv"))
    pairs = read(os.path.join(a.ablation, "pairs.csv"))
    fixed = [r for r in read(a.min7) if r["arm"] in ("A_old_fixed", "B_min7_fixed")]
    for r in fixed:
        r["status"] = r["status"]
    fig_same_traffic(cells, fixed)
    fig_paired(pairs, "dJ_s", "ΔJ vs no protection (s)\nsame model and traffic, both cleared", "fig2a_paired_dJ")
    fig_paired(pairs, "dD_veh_s", "ΔD vs no protection (veh·s)\nwindow [0, 3600) s, all pairs", "fig2b_paired_dD")
    fig_service(cells)
    fig_tradeoff(cells, fixed)
    print("figures written to", HERE)


if __name__ == "__main__":
    main()
