"""Read-only storage audit before campaign B (nothing is written except --out).

    python tools/disk/audit_storage.py --out logs\\storage_audit.json

Reports:
  * free space on C: and D: (shutil.disk_usage);
  * the size of every first-level folder of D:\\QMIX_Results;
  * for campaign A (D:\\QMIX_Results\\comparators_robustness_profiles): the size of runs\\ per stage, the stage of
    each run folder being read from orders\\<stage>.json (a folder listed by several stages is counted once, under
    the first stage of comparator_search.STAGES); runs folders listed by no order are reported apart;
  * D:\\IEV_Results: TOTAL size only (its content is neither listed nor reported);
  * the estimated need of campaign B and of A-ext, read from their plan.json when they exist, else from the
    defaults below, and the B start threshold (need + 4 GB, the rule of the B runner).
"""
from __future__ import absolute_import, division, print_function

import argparse
import json
import os
import shutil
import sys
import time

A_STAGES = ["coarse", "fine-g5", "fine-min7", "validation-g5", "validation-min7", "actuated-design",
            "actuated-validation", "tod-design-g5", "tod-design-min7", "tod-validation-g5", "tod-validation-min7",
            "robustness-eval"]
# Defaults used only when the B / A-ext plans do not exist yet (both are replaced by measure.json once measured).
DEFAULT_B_EVALUATIONS = 2470                           # 2,000 QMIX/VDN + 200 IDQN (R0) + 270 comparators
DEFAULT_B_BYTES_PER_RUN = int(2712403 * 1.25)          # campaign A full-log measure x 1.25 (counters), before gzip
DEFAULT_AEXT_RUNS = 480
DEFAULT_AEXT_BYTES_PER_RUN = 82030                     # campaign A compact measure
SAFETY_BYTES = 4 * 1024 ** 3


def tree_size(path):
    total, files = 0, 0
    for directory, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(directory, name))
                files += 1
            except OSError:
                pass
    return total, files


def existing_ancestor(path):
    path = os.path.abspath(path)
    while not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    return path


def free(drive):
    try:
        usage = shutil.disk_usage(drive)
        return {"total_bytes": usage.total, "free_bytes": usage.free, "free_gb": round(usage.free / 1e9, 2)}
    except OSError as error:
        return {"error": str(error)}


def read_json(path):
    with open(path) as handle:
        return json.load(handle)


def campaign_a(root):
    out = {"root": root, "exists": os.path.isdir(root)}
    if not out["exists"]:
        return out
    stage_of = {}
    for stage in A_STAGES:
        path = os.path.join(root, "orders", stage + ".json")
        if not os.path.isfile(path):
            continue
        for job in read_json(path)["jobs"]:
            stage_of.setdefault(os.path.normpath(job["directory"]), stage)
    per_stage = dict((s, {"folders": 0, "bytes": 0, "files": 0}) for s in A_STAGES)
    unlisted = {"folders": 0, "bytes": 0, "files": 0}
    runs = os.path.join(root, "runs")
    for profile in sorted(os.listdir(runs)) if os.path.isdir(runs) else []:
        for seed in sorted(os.listdir(os.path.join(runs, profile))):
            for name in sorted(os.listdir(os.path.join(runs, profile, seed))):
                rel = os.path.normpath(os.path.join("runs", profile, seed, name))
                size, files = tree_size(os.path.join(root, rel))
                bucket = per_stage[stage_of[rel]] if rel in stage_of else unlisted
                bucket["folders"] += 1
                bucket["bytes"] += size
                bucket["files"] += files
    for v in list(per_stage.values()) + [unlisted]:
        v["gb"] = round(v["bytes"] / 1e9, 3)
    out["runs_by_stage"] = per_stage
    out["runs_not_in_any_order"] = unlisted
    out["runs_total_gb"] = round(sum(v["bytes"] for v in per_stage.values()) / 1e9 + unlisted["gb"], 3)
    return out


def need(plan_path, default_runs, default_bytes):
    if os.path.isfile(plan_path):
        plan = read_json(plan_path)
        estimate = plan.get("estimate", {})
        if "disk_bytes" in estimate:
            return {"source": plan_path, "runs": estimate.get("runs"), "bytes": int(estimate["disk_bytes"])}
    return {"source": "default (plan not written yet)", "runs": default_runs, "bytes": default_runs * default_bytes,
            "bytes_per_run": default_bytes}


def audit(qmix_results, iev, a_root, b_root, aext_root, drives):
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "free_space": dict((d, free(d)) for d in drives)}
    folders = {}
    if os.path.isdir(qmix_results):
        for name in sorted(os.listdir(qmix_results)):
            path = os.path.join(qmix_results, name)
            if os.path.isdir(path):
                size, files = tree_size(path)
                folders[name] = {"gb": round(size / 1e9, 3), "files": files}
    report["qmix_results_folders"] = folders
    report["campaign_A"] = campaign_a(a_root)
    if os.path.isdir(iev):
        size, _files = tree_size(iev)
        report["iev_results_total_gb"] = round(size / 1e9, 3)
    else:
        report["iev_results_total_gb"] = None
    b = need(os.path.join(b_root, "plan.json"), DEFAULT_B_EVALUATIONS, DEFAULT_B_BYTES_PER_RUN)
    x = need(os.path.join(aext_root, "plan.json"), DEFAULT_AEXT_RUNS, DEFAULT_AEXT_BYTES_PER_RUN)
    report["need"] = {"campaign_B": dict(b, gb=round(b["bytes"] / 1e9, 2),
                                         threshold_gb=round((b["bytes"] + SAFETY_BYTES) / 1e9, 2)),
                      "A_ext": dict(x, gb=round(x["bytes"] / 1e9, 3))}
    report["B_can_start_on_free_space"] = None
    report["A_ext_can_start_on_free_space"] = None
    for key, root, n in (("B", b_root, b), ("A_ext", aext_root, x)):
        anc = existing_ancestor(root)
        drive = os.path.splitdrive(os.path.abspath(root))[0] or os.path.sep
        usage = free(anc)
        report["{}_target".format(key)] = {"root": root, "existing_ancestor": anc,
                                           "volume_exists": os.path.isdir(drive + os.sep) if drive != os.path.sep else True,
                                           "free": usage}
        if "free_bytes" in usage:
            report["{}_can_start_on_free_space".format(key)] = usage["free_bytes"] >= n["bytes"] + SAFETY_BYTES
    report["notes"] = ["read-only audit: nothing is deleted or moved",
                       "an archive COPY does not free the space of its originals; this delivery deletes nothing",
                       "set BCONF (or AEXT) to a root on another existing volume when the target volume lacks space"]
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qmix-results", default=r"D:\QMIX_Results")
    ap.add_argument("--iev", default=r"D:\IEV_Results")
    ap.add_argument("--a-root", default=r"D:\QMIX_Results\comparators_robustness_profiles")
    ap.add_argument("--b-root", default=r"D:\QMIX_Results\confirmation_B")
    ap.add_argument("--aext-root", default=r"D:\QMIX_Results\comparators_actuated_g5")
    ap.add_argument("--drives", nargs="*", default=["C:\\", "D:\\"])
    ap.add_argument("--out", default=os.path.join("logs", "storage_audit.json"))
    a = ap.parse_args(argv)
    report = audit(a.qmix_results, a.iev, a.a_root, a.b_root, a.aext_root, a.drives)
    if os.path.dirname(a.out) and not os.path.isdir(os.path.dirname(a.out)):
        os.makedirs(os.path.dirname(a.out))
    with open(a.out, "w") as handle:
        json.dump(report, handle, indent=1)
    for drive, v in report["free_space"].items():
        print("free {}: {}".format(drive, "{} GB".format(v["free_gb"]) if "free_gb" in v else v.get("error")))
    for name, v in sorted(report["qmix_results_folders"].items()):
        print("  {:55} {:>9.3f} GB".format(name, v["gb"]))
    if report["campaign_A"].get("runs_by_stage"):
        print("campaign A runs by stage:")
        for stage, v in report["campaign_A"]["runs_by_stage"].items():
            print("  {:22} {:>6} folders {:>8.3f} GB".format(stage, v["folders"], v["gb"]))
        print("  not in any order: {} folders".format(report["campaign_A"]["runs_not_in_any_order"]["folders"]))
    print("IEV_Results total: {} GB".format(report["iev_results_total_gb"]))
    print("need B: {gb} GB ({source}); threshold to start B: {threshold_gb} GB".format(**report["need"]["campaign_B"]))
    print("need A-ext: {gb} GB ({source})".format(**report["need"]["A_ext"]))
    print("B can start on current free space:", report["B_can_start_on_free_space"])
    print("written:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
