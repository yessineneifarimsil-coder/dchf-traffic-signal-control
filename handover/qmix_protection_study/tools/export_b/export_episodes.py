"""B_episodes.csv: one row per FINISHED cell of B, read-only (2026-11-26).

    python tools/export_b/export_episodes.py --root <BCONF> --out <EXPORT> [--recheck]

Where the values come from (read in the code, nothing assumed):
- identity of the cell: <BCONF>/plan.json, "jobs" (built by b_runner.build_jobs): kind, profile, seed, model, method,
  arm, checkpoint_sha256 (learned) or spec, spec_sha256, labels (comparator), directory. plan.json is loaded by
  b_runner.load_plan, which checks it against its own fingerprint and against freeze.json (code, margins, statistics);
- state: b_runner.classify (complete / scientific_failure / ...), read-only;
- values: <BCONF>/<cell>/cell_summary.json, written at the end of the cell by b_runner.finalize_cell from
  robustness_analysis.cell_metrics (the same file b_runner.cell_rows reads for the analysis: J_primary_s, status,
  open_wait_at_end_s, D_bar_s, mean_completed_time_loss_s, ...);
- N_scheduled is also compared with <BCONF>/manifests/<profile>_<seed>.metadata.json (scheduled_total).
With --recheck, every cell is re-read from its gzip traces by b_runner.recheck_cell (as b-analyse does; it unpacks
into a temporary folder outside <BCONF>) and a difference is reported. Nothing is written in <BCONF>.

J_s is empty when the run did not clear (never imputed), exactly as b_runner.cell_rows passes it to the analysis.
Numbers are written with repr() so that the analysis values are reproduced exactly.
"""
from __future__ import absolute_import, division, print_function

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common as C  # noqa: E402
import b_runner as BR  # noqa: E402

COLUMNS = ["cell_id", "profile", "traffic_seed", "controller_kind", "method", "training_seed", "checkpoint",
           "checkpoint_sha256", "comparator_spec", "comparator_spec_sha256", "arm", "status", "N_scheduled", "J_s",
           "D_bar_s", "mean_time_loss_s", "max_vehicle_wait_s", "vehicles_wait_ge_300s", "open_wait_at_end",
           "interventions_guarantee_demand", "interventions_guarantee_after", "max_counter_s", "shortest_green_s",
           "sumo_mismatch_s", "end_time_s"]
EXTRA = ["cell_state", "comparator_labels", "comparator_variant", "model_tag"]
# column -> key of cell_summary.json
SUMMARY = {"status": "status", "N_scheduled": "N", "J_s": "J_primary_s", "D_bar_s": "D_bar_s",
           "mean_time_loss_s": "mean_completed_time_loss_s", "max_vehicle_wait_s": "max_vehicle_waiting_s",
           "vehicles_wait_ge_300s": "vehicles_waiting_ge_300s", "open_wait_at_end": "open_wait_at_end_s",
           "interventions_guarantee_demand": "interventions_guarantee_demand",
           "interventions_guarantee_after": "interventions_guarantee_after", "max_counter_s": "max_counter_s",
           "shortest_green_s": "shortest_green_s", "sumo_mismatch_s": "sumo_mismatch_s", "end_time_s": "end_time_s"}
KIND = {"fixed": "fixed", "actuated": "actuated", "actuated_g5": "actuated", "tod": "tod", "canonical_mp": "max_pressure"}
LEARNED_ONLY = ("interventions_guarantee_demand", "interventions_guarantee_after", "sumo_mismatch_s")


def rows_of(root, plan, recheck=False):
    rows, not_finished, absent, recheck_diffs, n_mismatch = [], [], {}, [], []
    meta_cache = {}
    for j in BR.unique_jobs(plan["jobs"]):
        state, why = BR.classify(root, j)
        if state not in BR.FINISHED:
            not_finished.append({"cell": j["directory"], "state": state, "why": why})
            continue
        if recheck:
            diff = BR.recheck_cell(root, j, os.path.join(root, "manifests"))
            if diff:
                recheck_diffs.append({"cell": j["directory"], "differences": diff})
        s = BR.read_json(os.path.join(root, j["directory"], "cell_summary.json"))
        key = (j["profile"], j["seed"])
        if key not in meta_cache:
            meta_cache[key] = BR.read_json(os.path.join(root, "manifests", "{}_{}.metadata.json".format(*key)))
        if int(s.get("N", -1)) != int(meta_cache[key]["scheduled_total"]):
            n_mismatch.append(j["directory"])
        learned = j["kind"] == "learned"
        r = {"cell_id": j["directory"].replace("\\", "/"), "profile": j["profile"], "traffic_seed": str(j["seed"]),
             "cell_state": state}
        if learned:
            r.update({"controller_kind": "learned", "method": j["method"], "model_tag": j["model"],
                      "training_seed": str(int(j["model"].split("_seed")[1].split("_")[0])),
                      "checkpoint": "<BCONF>/checkpoints/{}.pth".format(j["model"]),
                      "checkpoint_sha256": j["checkpoint_sha256"], "arm": j["arm"],
                      "comparator_spec": "", "comparator_spec_sha256": "", "comparator_labels": "",
                      "comparator_variant": ""})
        else:
            kind = j["spec"]["kind"]
            r.update({"controller_kind": KIND.get(kind, "unknown:" + kind), "method": ";".join(j["labels"]),
                      "model_tag": "", "training_seed": "", "checkpoint": "", "checkpoint_sha256": "", "arm": "",
                      "comparator_spec": json.dumps(j["spec"], sort_keys=True, separators=(",", ":")),
                      "comparator_spec_sha256": j["spec_sha256"], "comparator_labels": ";".join(j["labels"]),
                      "comparator_variant": kind})
        for col, k in SUMMARY.items():
            if k not in s:
                if not (col in LEARNED_ONLY and not learned):
                    absent.setdefault(col, []).append(j["directory"])
                r[col] = ""
                continue
            v = s[k]
            if col == "J_s":
                r[col] = "" if (v is None or s.get("status") != "CLEARED") else repr(float(v))
            elif col == "open_wait_at_end":
                r[col] = "" if v is None else str(v)
            else:
                r[col] = C.fnum(v)
        rows.append(r)
    return rows, {"not_finished": not_finished, "absent_columns": absent, "recheck_differences": recheck_diffs,
                  "N_differs_from_manifest": n_mismatch}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--recheck", action="store_true")
    a = ap.parse_args(argv)
    try:
        C.ensure_export_dir(a.out, must_be_new=True)
        plan = BR.load_plan(a.root)                                    # fingerprint and freeze checks
        scrub = C.Scrubber(a.root, a.out)
        rows, report = rows_of(a.root, plan, recheck=a.recheck)
        C.write_csv_once(os.path.join(a.out, "B_episodes.csv"), COLUMNS + EXTRA, rows, scrub)
        margins_path = os.path.join(a.root, "margins.json")
        fr = BR.read_json(os.path.join(a.root, "freeze.json"))
        if C.sha256_file(margins_path) != fr["margins_sha256"]:
            raise C.ExportError("margins.json differs from the freeze")
        with open(margins_path, "rb") as f:
            margins_bytes = f.read()
        with open(os.path.join(a.out, "B_margins.json"), "xb") as f:   # verbatim copy (sealed by the freeze)
            f.write(margins_bytes)
        summary = {"plan_fingerprint": plan["fingerprint"], "jobs_in_plan": len(BR.unique_jobs(plan["jobs"])),
                   "rows_written": len(rows), "recheck_from_gzip_traces": a.recheck,
                   "margins_sha256": fr["margins_sha256"], "statistics_module_sha256": fr["statistics_module_sha256"],
                   "statistics_module_path": fr["statistics_module_path"],
                   "columns": COLUMNS, "extra_columns": EXTRA, "sources": {
                       "identity": "<BCONF>/plan.json jobs", "values": "<BCONF>/<cell_id>/cell_summary.json",
                       "N check": "<BCONF>/manifests/<profile>_<seed>.metadata.json scheduled_total"}}
        summary.update(report)
        C.write_json_once(os.path.join(a.out, "B_episodes_report.json"), summary, scrub)
    except (C.ExportError, BR.BError, OSError, ValueError) as error:
        print("STOP:", error)
        return 1
    print("B_episodes.csv: {} rows ({} jobs in the plan, {} not finished) | absent columns: {} | N differing from "
          "the manifest: {} | recheck differences: {}".format(
              len(rows), summary["jobs_in_plan"], len(report["not_finished"]),
              dict((k, len(v)) for k, v in report["absent_columns"].items()) or "none",
              len(report["N_differs_from_manifest"]),
              len(report["recheck_differences"]) if a.recheck else "not rechecked"))
    return 0 if len(rows) == summary["jobs_in_plan"] and not report["recheck_differences"] else 3


if __name__ == "__main__":
    sys.exit(main())
