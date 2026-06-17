import os
import pandas as pd

TABLE_DIR = "results/tables"
os.makedirs(TABLE_DIR, exist_ok=True)

INPUT = f"{TABLE_DIR}/scenario_b_controller_comparison.csv"
MULTISEED = f"{TABLE_DIR}/multiseed_scenario_b_summary.csv"

OUT = f"{TABLE_DIR}/scenario_b_dchf_summary.csv"

df = pd.read_csv(INPUT)

sim = df[df["controller"] == "Simultaneous Fixed-Time"].iloc[0]
offset = df[df["controller"] == "Best Offset Fixed-Time 45s"].iloc[0]
qmix_transfer = df[df["controller"] == "QMIX V2 transferred"].iloc[0]
qmix_trained = df[df["controller"] == "QMIX V2 trained on Scenario B"].iloc[0]

def cg(sim_wait, ctrl_wait):
    return ((sim_wait - ctrl_wait) / sim_wait) * 100

def gap(ctrl_wait, best_wait):
    return ((ctrl_wait - best_wait) / best_wait) * 100

def regime(g):
    if g <= 5:
        return "Effective coordination zone"
    if g <= 10:
        return "Marginal coordination zone"
    return "Outside coordination horizon"

sim_wait = sim["mean_total_waiting_time"]
best_wait = offset["mean_total_waiting_time"]
transfer_wait = qmix_transfer["mean_total_waiting_time"]
trained_wait = qmix_trained["mean_total_waiting_time"]

rows = [
    {
        "scenario": "Scenario B turning movements",
        "controller": "Best Offset Fixed-Time 45s",
        "mean_waiting_time": best_wait,
        "mean_speed": offset["mean_speed"],
        "mean_queue": offset["mean_total_queue"],
        "coordination_gain_percent": cg(sim_wait, best_wait),
        "gap_vs_best_offset_percent": 0.0,
        "regime": "Optimized benchmark",
    },
    {
        "scenario": "Scenario B turning movements",
        "controller": "QMIX V2 transferred",
        "mean_waiting_time": transfer_wait,
        "mean_speed": qmix_transfer["mean_speed"],
        "mean_queue": qmix_transfer["mean_total_queue"],
        "coordination_gain_percent": cg(sim_wait, transfer_wait),
        "gap_vs_best_offset_percent": gap(transfer_wait, best_wait),
        "regime": regime(gap(transfer_wait, best_wait)),
    },
    {
        "scenario": "Scenario B turning movements",
        "controller": "QMIX V2 trained on Scenario B",
        "mean_waiting_time": trained_wait,
        "mean_speed": qmix_trained["mean_speed"],
        "mean_queue": qmix_trained["mean_total_queue"],
        "coordination_gain_percent": cg(sim_wait, trained_wait),
        "gap_vs_best_offset_percent": gap(trained_wait, best_wait),
        "regime": regime(gap(trained_wait, best_wait)),
    },
]

out_df = pd.DataFrame(rows).round(3)
out_df.to_csv(OUT, index=False)

print("Scenario B DCHF summary generated:")
print(out_df.to_string(index=False))
print(f"\nSaved: {OUT}")

if os.path.exists(MULTISEED):
    ms = pd.read_csv(MULTISEED)
    best_ms = ms[ms["controller"] == "Best Offset Fixed-Time 45s"].iloc[0]
    transfer_ms = ms[ms["controller"] == "QMIX V2 transferred"].iloc[0]
    trained_ms = ms[ms["controller"] == "QMIX V2 trained on Scenario B"].iloc[0]

    best_wait_ms = best_ms["mean_total_waiting_time_mean"]
    transfer_wait_ms = transfer_ms["mean_total_waiting_time_mean"]
    trained_wait_ms = trained_ms["mean_total_waiting_time_mean"]

    print("\nMulti-seed Scenario B interpretation:")
    print(f"Best offset WT: {best_wait_ms:.3f}")
    print(f"Transferred QMIX WT: {transfer_wait_ms:.3f}")
    print(f"Trained QMIX WT: {trained_wait_ms:.3f}")
    print(f"Transferred QMIX gap vs best offset: {gap(transfer_wait_ms, best_wait_ms):.3f}%")
    print(f"Trained QMIX gap vs best offset: {gap(trained_wait_ms, best_wait_ms):.3f}%")