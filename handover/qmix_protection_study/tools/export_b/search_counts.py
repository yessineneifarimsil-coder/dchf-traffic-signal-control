"""search_counts.csv: exact counts of the classical searches of campaign A and A-ext, read-only (2026-11-26).

    python tools/export_b/search_counts.py --cmp D:\\QMIX_Results\\comparators_robustness_profiles
        --aext D:\\QMIX_Results\\comparators_actuated_g5 --out <EXPORT>

From the code (tools/comparators/comparator_search.py, tools/comparators_ext/aext_search.py):
- every stage has one sealed order <root>/orders/<stage>.json, written once by write_order; its "jobs" are the tasks
  requested; each job names its run folder "runs/<profile>/<seed>/<kind>_<spec sha256[:16]>[_full]" (job()):
  the identity of a simulation is (profile, traffic seed, full spec sha256, full/compact);
- comparator_search.run skips a job whose folder already holds a finished result: a job whose folder was
  already requested by an EARLIER stage is a reuse (same specification, same traffic), not a new simulation.
Counted per stage, in the stage order of the plan: tasks; distinct folders within the stage; folders first requested
by this stage (new); tasks reusing a folder of an earlier stage; repeats inside the stage; folders present on disk
and finished (evaluation_metrics.json whose comparator_spec_sha256, scenario and traffic_seed are those of the job).
Conflicts: one folder named by jobs with different identities (spec sha256, profile, seed, full flag), or a folder
on disk whose metrics name another identity. Folders on disk under runs/ that no order names are listed as orphans.
Order seals are checked (comparator_search.read_order). Nothing is written in the roots.
"""
from __future__ import absolute_import, division, print_function

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (HERE, os.path.join(TOOLS, "comparators"), os.path.join(TOOLS, "comparators_ext"), os.path.join(TOOLS, "robustness")):
    if p not in sys.path:
        sys.path.insert(0, p)

import common as C  # noqa: E402

FIELDS = ["root", "stage", "tasks_in_order", "distinct_folders_in_stage", "new_folders", "reused_from_earlier_stage",
          "repeated_within_stage", "folders_present", "folders_finished", "conflicting_identities", "reused_from_stages"]


def stage_order(root, known):
    names = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(root, "orders", "*.json"))]
    ordered = [s for s in known if s in names]
    return ordered + sorted(s for s in names if s not in ordered)


def norm_dir(d):
    return d.replace("\\", "/")


def identity(j):
    return (j["profile"], int(j["seed"]), j["spec_sha256"], bool(j.get("full")))


def disk_state(root, j):
    d = os.path.join(root, *norm_dir(j["directory"]).split("/"))
    if not os.path.isdir(d):
        return "absent", None
    path = os.path.join(d, "evaluation_metrics.json")
    if not os.path.isfile(path):
        return "present", None
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (ValueError, OSError, UnicodeDecodeError) as error:
        return "present", "unreadable evaluation_metrics.json: {}".format(error)
    if (m.get("comparator_spec_sha256") != j["spec_sha256"] or m.get("scenario") != j["profile"]
            or str(m.get("traffic_seed")) != str(j["seed"])):
        return "present", "metrics name another identity ({}, {}, {})".format(
            m.get("scenario"), m.get("traffic_seed"), str(m.get("comparator_spec_sha256"))[:16])
    if m.get("clearance_status") not in ("CLEARED", "CLEARANCE_FAILURE"):
        return "present", None
    return "finished", None


def count_root(root, label, known_stages, read_order):
    rows, seen, conflicts = [], {}, []           # folder -> (identity, first stage)
    on_disk_named = set()
    for stage in stage_order(root, known_stages):
        order = read_order(root, stage)
        jobs = order["jobs"]
        dirs_here, new, reused, repeated, present, finished = set(), 0, 0, 0, 0, 0
        from_stages = {}
        for j in jobs:
            d = norm_dir(j["directory"])
            ident = identity(j)
            if d in dirs_here:
                repeated += 1
                if seen[d][0] != ident:
                    conflicts.append({"root": label, "stage": stage, "folder": d, "identities": [seen[d][0], ident]})
                continue
            dirs_here.add(d)
            if d in seen:
                if seen[d][0] != ident:
                    conflicts.append({"root": label, "stage": stage, "folder": d, "identities": [seen[d][0], ident]})
                reused += 1
                from_stages[seen[d][1]] = from_stages.get(seen[d][1], 0) + 1
            else:
                seen[d] = (ident, stage)
                new += 1
            state, problem = disk_state(root, j)
            if problem:
                conflicts.append({"root": label, "stage": stage, "folder": d, "on_disk": problem})
            present += state != "absent"
            finished += state == "finished"
            on_disk_named.add(d)
        rows.append({"root": label, "stage": stage, "tasks_in_order": len(jobs), "distinct_folders_in_stage": len(dirs_here),
                     "new_folders": new, "reused_from_earlier_stage": reused, "repeated_within_stage": repeated,
                     "folders_present": present, "folders_finished": finished,
                     "conflicting_identities": sum(1 for c in conflicts if c["stage"] == stage and c["root"] == label),
                     "reused_from_stages": ";".join("{}:{}".format(k, v) for k, v in sorted(from_stages.items()))})
    disk = set()
    runs = os.path.join(root, "runs")
    for profile in (sorted(os.listdir(runs)) if os.path.isdir(runs) else []):
        for seed in sorted(os.listdir(os.path.join(runs, profile))):
            base = os.path.join(runs, profile, seed)
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                if os.path.isdir(os.path.join(base, name)):
                    disk.add("runs/{}/{}/{}".format(profile, seed, name))
    total = {"root": label, "stage": "TOTAL", "tasks_in_order": sum(r["tasks_in_order"] for r in rows),
             "distinct_folders_in_stage": len(seen), "new_folders": sum(r["new_folders"] for r in rows),
             "reused_from_earlier_stage": sum(r["reused_from_earlier_stage"] for r in rows),
             "repeated_within_stage": sum(r["repeated_within_stage"] for r in rows),
             "folders_present": len(disk & set(seen)), "folders_finished": "",
             "conflicting_identities": len([c for c in conflicts if c["root"] == label]),
             "reused_from_stages": "folders on disk not named by any order: {}".format(len(disk - set(seen)))}
    return rows + [total], conflicts, sorted(disk - set(seen))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmp", required=True)
    ap.add_argument("--aext", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import comparator_search as CS
    import aext_search as AX
    scrub = C.Scrubber(export=a.out, extra=((a.cmp, "<CMP>"), (a.aext, "<AEXT>")))
    all_rows, all_conflicts, orphans = [], [], {}
    for root, label, stages in ((a.cmp, "A (comparators_robustness_profiles)", CS.STAGES),
                                (a.aext, "A-ext (comparators_actuated_g5)", AX.STAGES)):
        if not os.path.isdir(os.path.join(root, "orders")):
            all_rows.append({"root": label, "stage": "NOT AVAILABLE", "reused_from_stages": "no orders folder in the root"})
            continue
        rows, conflicts, orph = count_root(root, label, stages, CS.read_order)
        all_rows += rows
        all_conflicts += conflicts
        orphans[label] = orph
    grand = {"root": "A + A-ext", "stage": "TOTAL"}
    for k in ("tasks_in_order", "distinct_folders_in_stage", "new_folders", "reused_from_earlier_stage",
              "repeated_within_stage", "folders_present", "conflicting_identities"):
        grand[k] = sum(int(r[k]) for r in all_rows if r.get("stage") == "TOTAL" and r.get(k) not in ("", None))
    all_rows.append(grand)
    C.write_csv_once(os.path.join(a.out, "search_counts.csv"), FIELDS, all_rows, scrub)
    hyp = {"tasks": 34500, "distinct": 29785, "reused_fine_min7": 4685, "reused_validation": 30}
    a_rows = [r for r in all_rows if r["root"].startswith("A (")]
    a_total = next((r for r in a_rows if r["stage"] == "TOTAL"), {})
    by = dict((r["stage"], r) for r in a_rows)
    observed = {"tasks": a_total.get("tasks_in_order"), "distinct": a_total.get("distinct_folders_in_stage"),
                "reused_fine_min7": by.get("fine-min7", {}).get("reused_from_earlier_stage"),
                "reused_validation": sum(int(r["reused_from_earlier_stage"]) for s, r in by.items() if "validation" in s)}
    C.write_json_once(os.path.join(a.out, "search_counts_details.json"), {
        "hypothesis_checked": dict((k, {"stated_about": hyp[k], "observed": observed[k]}) for k in hyp),
        "note": "campaign A only (the A-ext root is counted separately); 'validation' sums every stage whose name "
                "contains 'validation'", "conflicts": all_conflicts, "orphan_folders": orphans}, scrub)
    for r in all_rows:
        print("{:40} {:22} tasks {:>6} distinct {:>6} new {:>6} reused {:>5} repeated {:>4} present {:>6} conflicts {}".format(
            r["root"], r["stage"], r.get("tasks_in_order", ""), r.get("distinct_folders_in_stage", ""), r.get("new_folders", ""),
            r.get("reused_from_earlier_stage", ""), r.get("repeated_within_stage", ""), r.get("folders_present", ""),
            r.get("conflicting_identities", "")))
    for k in hyp:
        print("hypothesis {:18} stated ~{:<6} observed {}".format(k, hyp[k], observed[k]))
    return 1 if all_conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
