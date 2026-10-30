"""Engineering smoke check of the robustness evaluator (4 short SUMO runs in a scratch root; not results).

    python tools/robustness/smoke.py --root D:\\QMIX_Results\\robustness_smoke_<date> --checkpoint <qmix .pth>

Checks per run: completes, J denominator = manifest N, service_counters.csv has one row per second and
intersection, the reconstruction from logs (when per-second lanes exist) is not required here.
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evaluate_any as ea  # noqa: E402
import scenario_traffic as st  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--checkpoint", required=True)
    a = ap.parse_args()
    if os.path.exists(a.root):
        raise SystemExit("root exists")
    sys.path.insert(0, os.path.join(ea.PROTECTED, "src"))
    from adaptive_qmix.config import load_config
    config = load_config(os.path.join(ea.PROTECTED, ea.CONFIG_REL))
    spec = st.load_spec()
    prefixes = {}
    for sc, seed in (("R2_single_secondary_trickle", 8201), ("R4_isolated_tail", 8401)):
        p = os.path.join(a.root, "manifests", "{}_{}".format(sc, seed))
        st.write(spec, sc, seed, st.generate(spec, sc, seed), p, config["demand"]["vehicle_type"])
        prefixes[sc] = p
    runs = [("fixed:min7_C25_12_7_D0", "R2_single_secondary_trickle", None),
            ("canonical_mp", "R2_single_secondary_trickle", None),
            ("p5:both", "R4_isolated_tail", None),
            ("learned:both", "R2_single_secondary_trickle", a.checkpoint)]
    report = []
    for ctrl, sc, ck in runs:
        d = os.path.join(a.root, "runs", sc, ctrl.replace(":", "__"))
        m = ea.evaluate(ctrl, prefixes[sc], d, checkpoint=ck)
        meta = json.load(open(prefixes[sc] + ".metadata.json"))
        rows = list(csv.DictReader(open(os.path.join(d, "service_counters.csv"))))
        end = float(list(csv.DictReader(open(os.path.join(d, "episode_summary.csv"))))[0]["end_time"])
        r = {"controller": ctrl, "scenario": sc, "status": m["clearance_status"], "N": meta["scheduled_total"],
             "scheduled_count": m["scheduled_count"], "J": m["J_primary_mean_scheduled_waiting_burden_s"],
             "J_total": m["J_primary_total_scheduled_waiting_burden_vehicle_s"], "end_time": end,
             "counter_rows": len(rows), "counter_rows_expected": int(2 * end), "wall_s": round(m["wall_s"], 1)}
        r["ok"] = (r["scheduled_count"] == r["N"] and r["counter_rows"] == r["counter_rows_expected"]
                   and (r["J"] is None or r["status"] != "CLEARED" or abs(r["J"] - r["J_total"] / r["N"]) < 1e-9))
        report.append(r)
        print(json.dumps(r))
    with open(os.path.join(a.root, "smoke_report.json"), "w") as f:
        json.dump(report, f, indent=1)
    return 0 if all(r["ok"] for r in report) else 1


if __name__ == "__main__":
    sys.exit(main())
