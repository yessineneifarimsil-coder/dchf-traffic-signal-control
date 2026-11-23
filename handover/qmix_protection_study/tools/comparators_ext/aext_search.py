"""Campaign A-ext: actuated gap-out with a 5 s minimum green, tuned per profile (R1, R2, R3). Prepared, not launched.

    python tools/comparators_ext/aext_search.py plan     --root D:\\QMIX_Results\\comparators_actuated_g5 [--a-root <A root>]
    python tools/comparators_ext/aext_search.py prepare  --root ... --approved-plan <fingerprint> [--a-root <A root>]
    python tools/comparators_ext/aext_search.py run      --root ... --stage aext-design|aext-validation --shard i/n
    python tools/comparators_ext/aext_search.py progress --root ... [--stage <stage>]
    python tools/comparators_ext/aext_search.py finalise --root ... --stage aext-design|aext-validation

Why (written in the plan, before any result): campaign A's actuated comparator imposes a 7 s minimum green
whereas QMIX and VDN have none, and its retained settings sit on the edge of its grid (gap 2 s, secondary
maximum green 15 s in all three profiles). This is an EXTENSION of the classical references (one more candidate,
selected by the same frozen rule); a 5 s minimum green does not reproduce the control authority of the learners,
whose greens can end after 2 s.

Grid, declared before any result: gap 1, 2, 3 s x main maximum green 30, 45, 60 s x secondary maximum green
10, 15, 25 s; zone 40 m; minimum green 5 s; yellow 3 s: 27 settings. Design on 8c11-8c15, the 5 best to
validation on 8c21-8c25, selection by the frozen rule of campaign A's actuated stage: mean J, then mean time
loss, then grid order (ranking on design: mean J, then grid order; validity: every run CLEARED with finite J
and time loss; never imputed). 405 + 75 = 480 runs.

Same resume code as comparator_search.py (its functions classify, job, search_jobs, write_order, read_order,
candidate_records are imported, the file itself is not modified), with three corrections:
  (a) the jobs of an order are de-duplicated by run folder BEFORE they are split between processes, so a folder
      can never be in two shards (campaign A's robustness-eval PermissionError);
  (b) every finalise builds its report afresh (campaign A's finalise coarse carried `report` across versions);
  (c) the upper-bound estimate covers every stage.
Compact mode, exit codes 0 / 3 / 5, sealed orders and selections written once: as in campaign A.
"""
from __future__ import absolute_import, print_function

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "comparators"))

import comparator_search as CS  # noqa: E402
import seeds as SD  # noqa: E402

PROFILES = ("R1_sparse_secondary_heavy_main", "R2_single_secondary_trickle", "R3_time_varying")
KIND = "actuated_g5"
GRID = [{"gap_s": g, "max_green_H_s": h, "max_green_V_s": v, "zone_m": 40}
        for g in (1, 2, 3) for h in (30, 45, 60) for v in (10, 15, 25)]
FIXED = {"minimum_green_s": 5, "yellow_s": 3}
RETAINED = 5
STAGES = ["aext-design", "aext-validation"]
CODE_FILES = ("aext_search.py", "controllers_g5.py", "evaluate_ext.py",
              os.path.join("..", "comparators", "comparator_search.py"),
              os.path.join("..", "comparators", "controllers.py"),
              os.path.join("..", "comparators", "evaluate_comparator.py"),
              os.path.join("..", "comparators", "seeds.py"), os.path.join("..", "comparators", "grids.py"),
              os.path.join("..", "robustness", "evaluate_any.py"), os.path.join("..", "robustness", "n_adapter.py"),
              os.path.join("..", "robustness", "scenario_traffic.py"))
DEFAULT_SECONDS = 13.810352563858032       # campaign A measure (plan 03af6200...), used if A's plan is not readable
DEFAULT_BYTES = 82030
WORKERS = 4
RATIONALE = ("campaign A's actuated comparator imposes a 7 s minimum green whereas QMIX and VDN have none, and its "
             "retained settings sit on the edge of its grid (gap 2 s, secondary maximum green 15 s in R1, R2 and R3); "
             "this is an extension of the classical references (one more candidate, selected by the same frozen rule); "
             "a 5 s minimum green does not reproduce the control authority of the learners, whose greens can end after 2 s")


class AextError(RuntimeError):
    pass


def spec(params):
    return {"kind": KIND, "params": dict(params)}


def code_hashes():
    return dict((os.path.basename(f), CS.sha256_file(os.path.join(HERE, f))) for f in CODE_FILES)


def measure_of(a_root):
    path = os.path.join(a_root, "plan.json") if a_root else ""
    if path and os.path.isfile(path):
        m = CS.read_json(path).get("measure") or {}
        if m.get("seconds_per_run"):
            return {"seconds_per_run": m["seconds_per_run"], "bytes_per_run_compact": m["bytes_per_run_compact"],
                    "source": "campaign A plan.json (read only)"}
    return {"seconds_per_run": DEFAULT_SECONDS, "bytes_per_run_compact": DEFAULT_BYTES,
            "source": "campaign A measure recorded in plan 03af6200"}


def build_plan(root, a_root=None):
    SD.check_disjoint()
    measure = measure_of(a_root)
    stages = {"aext-design": len(PROFILES) * len(GRID) * 5, "aext-validation": len(PROFILES) * RETAINED * 5}
    total = sum(stages.values())
    estimate = {"runs": total, "wall_h_4_workers": round(total * measure["seconds_per_run"] / WORKERS / 3600.0, 2),
                "disk_bytes": int(total * measure["bytes_per_run_compact"])}
    plan = {"study": "campaign_A_ext_actuated_min_green_5", "root": os.path.abspath(root), "profiles": list(PROFILES),
            "rationale": RATIONALE, "grid": GRID, "fixed_parameters": FIXED, "retained_for_validation": RETAINED,
            "selection_rule": "design: mean J then grid order (top 5); validation: mean J, mean time loss, grid order",
            "seeds": dict((p, {"design": list(SD.seeds(p, "comparator_design")),
                               "validation": list(SD.seeds(p, "comparator_validation"))}) for p in PROFILES),
            "stages": STAGES, "runs_by_stage": stages, "runs_upper_bound": total, "estimate": estimate,
            "estimate_upper_bound": estimate, "measure": measure, "code_sha256": code_hashes(),
            "scenario_spec_sha256": CS.st.load_spec()["_sha256"]}
    plan["fingerprint"] = CS.sha_obj(plan)
    return plan


def load_plan(root):
    plan = CS.read_json(os.path.join(root, "plan.json"))
    if plan["code_sha256"] != code_hashes():
        raise AextError("code differs from the code fixed in plan.json")
    return plan


def prepare(root, approved, a_root=None):
    plan = build_plan(root, a_root)
    if approved != plan["fingerprint"]:
        print("REFUSED: --approved-plan must be", plan["fingerprint"])
        return 2
    if os.path.exists(os.path.join(root, "plan.json")):
        print("REFUSED: already prepared")
        return 2
    CS.write_manifests(root, ("comparator_design", "comparator_validation"), PROFILES)
    if a_root and os.path.isdir(os.path.join(a_root, "manifests")):
        differ = [n for n in sorted(os.listdir(os.path.join(root, "manifests")))
                  if not os.path.isfile(os.path.join(a_root, "manifests", n))
                  or CS.sha256_file(os.path.join(root, "manifests", n)) != CS.sha256_file(os.path.join(a_root, "manifests", n))]
        if differ:
            raise AextError("manifests differ from campaign A: {}".format(differ[:5]))
        print("manifests identical to campaign A's ({} files, read only)".format(len(os.listdir(os.path.join(root, "manifests")))))
    with open(os.path.join(root, "plan.json"), "w") as f:
        json.dump(plan, f, indent=1, sort_keys=True)
    jobs = []
    for profile in PROFILES:
        jobs += CS.search_jobs(profile, "comparator_design", [spec(p) for p in GRID])
    CS.write_order(root, "aext-design", jobs, {"settings": len(GRID)})
    print("prepared", root)
    return 0


def unique_jobs(jobs):
    """(a) one job per run folder, in order of first appearance, BEFORE sharding."""
    seen, out = set(), []
    for j in jobs:
        if j["directory"] not in seen:
            seen.add(j["directory"])
            out.append(j)
    return out


def shard_jobs(jobs, shard):
    i, n = (int(x) for x in shard.split("/"))
    if not 0 <= i < n:
        raise AextError("bad shard {}".format(shard))
    return [j for pos, j in enumerate(unique_jobs(jobs)) if pos % n == i]


def run(root, stage, shard, evaluator=None):
    load_plan(root)
    order = CS.read_order(root, stage)
    if evaluator is None:
        import evaluate_ext
        evaluator = evaluate_ext.evaluate
    corrupted, unfinished = [], []
    i, n = shard.split("/")
    log = open(os.path.join(root, "run_log_{}_shard{}of{}.jsonl".format(stage, i, n)), "a")
    for j in shard_jobs(order["jobs"], shard):
        SD.assert_search_seed(j["profile"], j["seed"])
        state, why = CS.classify(root, j)
        if state in CS.FINISHED:
            continue
        if state == "corrupted":
            print("CORRUPTED, preserved, NOT rerun: {} ({})".format(j["directory"], "; ".join(why)))
            corrupted.append(j["directory"])
            continue
        d = os.path.join(root, j["directory"])
        if state == "interrupted":
            if os.path.exists(d + ".incomplete1"):
                print("INTERRUPTED TWICE, preserved, NOT rerun: {}".format(j["directory"]))
                unfinished.append(j["directory"])
                continue
            os.rename(d, d + ".incomplete1")
        t0 = time.time()
        try:
            evaluator(j["spec"], CS.manifest_prefix(root, j["profile"], j["seed"]), d, counters=False, compact=True)
        except Exception as error:  # noqa: BLE001 - technical interruption
            print("INTERRUPTED: {} ({!r})".format(j["directory"], error))
        state, why = CS.classify(root, j)
        log.write(json.dumps({"stage": stage, "dir": j["directory"], "state": state, "problems": why,
                              "wall_s": time.time() - t0}) + "\n")
        log.flush()
        if state == "corrupted":
            corrupted.append(j["directory"])
        elif state not in CS.FINISHED:
            unfinished.append(j["directory"])
    log.close()
    print("stage {} shard {}: {} corrupted, {} not finished".format(stage, shard, len(corrupted), len(unfinished)))
    return 5 if corrupted else (3 if unfinished else 0)


def progress(root, stage=None):
    code = 0
    for s in ([stage] if stage else STAGES):
        if not os.path.isfile(CS.order_path(root, s)):
            print("{:18} order not written yet".format(s))
            code = max(code, 3)
            continue
        order = CS.read_order(root, s)
        states = {}
        for j in unique_jobs(order["jobs"]):
            states.setdefault(CS.classify(root, j)[0], []).append(j["directory"])
        total = sum(len(v) for v in states.values())
        done = sum(len(states.get(x, [])) for x in CS.FINISHED)
        print("{:18} finished {}/{} (scientific failures {}) | corrupted {} | interrupted {} | not started {}".format(
            s, done, total, len(states.get("scientific_failure", [])), len(states.get("corrupted", [])),
            len(states.get("interrupted", [])), len(states.get("not_started", []))))
        if states.get("corrupted"):
            code = 5
        elif done < total:
            code = max(code, 3)
    return code


def grid_index(record):
    return GRID.index(record["spec"]["params"])


def rank(records):
    valid = [r for r in records.values() if r["valid"]]
    if len(valid) < RETAINED:
        raise AextError("only {} valid settings for a shortlist of {}; never padded".format(len(valid), RETAINED))
    return sorted(valid, key=lambda r: (r["mean_J"], grid_index(r)))[:RETAINED]


def select(records):
    valid = [r for r in records.values() if r["valid"]]
    if not valid:
        raise AextError("every validation setting failed: nothing may be selected")
    return sorted(valid, key=lambda r: (r["mean_J"], r["mean_time_loss"], grid_index(r)))[0]


def finalise(root, stage):
    load_plan(root)
    order = CS.read_order(root, stage)
    pending = [j["directory"] for j in unique_jobs(order["jobs"]) if CS.classify(root, j)[0] not in CS.FINISHED]
    if pending:
        raise AextError("{} runs of {} are not finished, e.g. {}".format(len(pending), stage, pending[:3]))
    report = {}                                                            # (b) fresh for every finalise
    if stage == "aext-design":
        jobs = []
        for profile in PROFILES:
            top = rank(CS.candidate_records(root, [j for j in unique_jobs(order["jobs"]) if j["profile"] == profile]))
            report[profile] = [t["spec"]["params"] for t in top]
            jobs += CS.search_jobs(profile, "comparator_validation", [t["spec"] for t in top])
        CS.write_order(root, "aext-validation", jobs, {"design_order": order["sha256"], "top5": report})
        return 0
    if stage == "aext-validation":
        for profile in PROFILES:
            recs = CS.candidate_records(root, [j for j in unique_jobs(order["jobs"]) if j["profile"] == profile])
            chosen = select(recs)
            CS.write_selection(root, "{}__actuated_g5".format(profile),
                               {"profile": profile, "stage": stage, "order": order["sha256"], "selected": chosen,
                                "candidates": sorted(recs.values(), key=grid_index)})
        return 0
    raise AextError("unknown stage {}".format(stage))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "prepare", "run", "progress", "finalise"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--a-root")
    ap.add_argument("--approved-plan")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args(argv)
    try:
        if a.action == "plan":
            plan = build_plan(a.root, a.a_root)
            print(json.dumps({k: plan[k] for k in ("profiles", "runs_by_stage", "runs_upper_bound", "estimate",
                                                   "measure")}, indent=1))
            print("rationale:", plan["rationale"])
            print("plan fingerprint:", plan["fingerprint"])
            return 0
        if a.action == "prepare":
            return prepare(a.root, a.approved_plan, a.a_root)
        if a.action == "progress":
            return progress(a.root, a.stage)
        if not a.stage:
            raise AextError("--stage is required")
        if a.action == "run":
            return run(a.root, a.stage, a.shard)
        return finalise(a.root, a.stage)
    except (AextError, CS.SearchError, SD.SeedError) as error:
        print("STOP:", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
