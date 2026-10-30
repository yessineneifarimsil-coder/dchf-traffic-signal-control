"""Inference-time ablation of the two protections on the 30 selected checkpoints (QMIX, VDN, IDQN,
training seeds 101-110), development traffics 9301-9305, arms none | guarantee | min_green | both.

    plan                       print checks, cells and the plan fingerprint (writes nothing)
    prepare --approved-plan F  create the output root, copy + verify checkpoints and manifests
    run --shard i/n            run the new cells of shard i (resumable; never reruns a finished cell)
    progress                   finished / expected
    verify-reuse               re-check the reused cells against the plan

600 cells = 30 models x 5 traffics x 4 arms. The 50 QMIX cells of arm "none" REUSE the min-7 study's
comparison runs (frozen evaluator script, same checkpoints, same manifests, same SUMO seeds); the S1
check (protected_checks_2026-10-24) showed that the protected evaluator in arm "none" writes the same
frozen output files byte for byte. 550 cells are new, run with the protected evaluator of
QMIX_PROTECTED (commit 3611383, frozen code identical to 8c14f32), arm parameters unchanged
(guarantee threshold 120 s, minimum green 7 s), greedy, full lane-state logging, TraCI subscriptions.

Nothing in the frozen repositories or in the existing results is modified. An interrupted cell (directory
without protection_record.json) is renamed <dir>.incomplete<k> and run again once; a scientific failure
(CLEARANCE_FAILURE) is a finished cell and is never rerun.
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")
PROTECTED_COMMIT = "3611383014ef1d6c8d9138a1bd852042eb4da930"
FROZEN_COMMIT = "8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d"
FROZEN_PATHS = ("src/adaptive_qmix", "scripts/adaptive_qmix", "config", "sumo_scenarios")
RESULTS = os.environ.get("QMIX_RESULTS_ROOT", r"D:\QMIX_Results")
SELECTION = os.path.join(RESULTS, "qualification_300m_medium_amendment003", "selection", "selection_records.json")
LEARNERS = os.path.join(RESULTS, "qualification_300m_medium_timing_amendment002r", "learners")
MANIFESTS = os.path.join(RESULTS, "protected_pilot_2026-10-24", "manifests")
MANIFESTS_MIN7 = os.path.join(RESULTS, "fixed_timing_min7_2026-10-28", "comparison", "manifests")
REUSE_RUNS = os.path.join(RESULTS, "fixed_timing_min7_2026-10-28", "comparison", "runs")
METHODS = ("qmix", "vdn", "idqn")
SEEDS = tuple(range(101, 111))
TRAFFIC = tuple(range(9301, 9306))
ARMS = ("none", "guarantee", "min_green", "both")
CONFIG_REL = os.path.join("config", "adaptive_qmix", "qualification_300m_medium.json")
REUSED_FILES = ("episode_summary.csv", "evaluation_metrics.json", "lane_states.csv", "reward_seconds.csv",
                "signal_actions.csv", "signal_phases.csv", "tripinfo.xml", "vehicle_crossings.csv",
                "run_manifest.json")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return None


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True, default=str)
        f.write("\n")


def git(root, *args):
    try:
        return subprocess.check_output(["git", "-C", root] + list(args), stderr=subprocess.STDOUT).decode().strip()
    except (OSError, subprocess.CalledProcessError) as e:
        return "ERROR {}".format(e)


def tag(method, seed, t):
    return "{}_seed{}_t{:06d}".format(method, seed, t)


def manifest_prefix(root, seed):
    return os.path.join(root, "manifests", "development_{}".format(seed))


def reuse_dir(model_tag, traffic):
    return os.path.join(REUSE_RUNS, "C_{}__traffic{}".format(model_tag, traffic))


def build_plan(root):
    checks, problems = [], []
    head, dirty = git(PROTECTED, "rev-parse", "HEAD"), git(PROTECTED, "status", "--porcelain")
    frozen = git(PROTECTED, "diff", "--stat", FROZEN_COMMIT, "--", *FROZEN_PATHS)
    checks += [("QMIX_PROTECTED at {}".format(PROTECTED_COMMIT[:7]), head == PROTECTED_COMMIT, head),
               ("QMIX_PROTECTED clean", dirty == "", dirty or "-"),
               ("frozen code identical to 8c14f32", frozen == "", frozen or "-")]
    sel = (read_json(SELECTION) or {}).get("selection", {})
    models = []
    for m in METHODS:
        for s in SEEDS:
            rec = next((r for r in sel.get(m, []) if int(r["training_seed"]) == s and r.get("selected")), None)
            if rec is None:
                problems.append("{}:{} not selected".format(m, s))
                continue
            t = int(rec["selected"]["transition_index"])
            path = os.path.join(LEARNERS, m, "seed{}".format(s), tag(m, s, t) + ".pth")
            ok = os.path.isfile(path) and sha256_file(path) == rec["selected"]["checkpoint_sha256"]
            checks.append(("{} = selected checkpoint".format(tag(m, s, t)), ok, rec["selected"]["checkpoint_sha256"][:16]))
            if ok:
                models.append({"method": m, "training_seed": s, "transition_index": t, "tag": tag(m, s, t),
                               "source": path, "sha256": rec["selected"]["checkpoint_sha256"]})
    manifests = {}
    for seed in TRAFFIC:
        entry = {}
        for ext in ("csv", "rou.xml", "metadata.json"):
            a = os.path.join(MANIFESTS, "development_{}.{}".format(seed, ext))
            b = os.path.join(MANIFESTS_MIN7, "development_seed{}.{}".format(seed, ext))
            ha, hb = sha256_file(a), sha256_file(b)
            entry[ext] = ha
            checks.append(("manifest {} {} identical in pilot and min-7 study".format(seed, ext), ha == hb, ha[:16]))
        meta = read_json(os.path.join(MANIFESTS, "development_{}.metadata.json".format(seed)))
        entry["sumo_seed"] = int(meta["sumo_seed"])
        entry["scheduled_total"] = int(meta["scheduled_total"])
        manifests[str(seed)] = entry
    cells, reused = [], 0
    for mod in models:
        for seed in TRAFFIC:
            for arm in ARMS:
                c = {"model": mod["tag"], "method": mod["method"], "traffic_seed": seed, "arm": arm,
                     "directory": os.path.join("cells", mod["tag"], "traffic{}".format(seed), arm)}
                if mod["method"] == "qmix" and arm == "none":
                    d = reuse_dir(mod["tag"], seed)
                    rm = read_json(os.path.join(d, "min7_outcome.json")) or {}
                    rman = read_json(os.path.join(d, "run_manifest.json")) or {}
                    ok = (rm.get("cell", {}).get("checkpoint_sha256") == mod["sha256"]
                          and rman.get("checkpoint_sha256") == mod["sha256"]
                          and rman.get("route_manifest_sha256") == manifests[str(seed)]["csv"]
                          and int(rman.get("sumo_seed", -1)) == manifests[str(seed)]["sumo_seed"]
                          and rman.get("git_commit") == FROZEN_COMMIT and rman.get("lane_state_logging") == "full"
                          and rman.get("traci_access_mode") == "subscription"
                          and all(os.path.isfile(os.path.join(d, f)) for f in REUSED_FILES))
                    checks.append(("reuse {} traffic {}".format(mod["tag"], seed), ok, d))
                    if not ok:
                        problems.append("reused cell not verified: {}".format(d))
                    c.update({"reused_from": d, "reused_file_sha256": dict(
                        (f, sha256_file(os.path.join(d, f))) for f in REUSED_FILES if os.path.isfile(os.path.join(d, f))),
                        "reused_evaluator": "frozen scripts/adaptive_qmix/evaluate_checkpoint.py (min-7 study driver 27bc9b68)"})
                    reused += 1
                cells.append(c)
    problems += ["check failed: {} ({})".format(n, d) for n, ok, d in checks if not ok]
    sys.path.insert(0, os.path.join(PROTECTED, "src"))
    from adaptive_qmix.config import load_config
    from adaptive_qmix_protected.protection import ProtectionSpec
    config = load_config(os.path.join(PROTECTED, CONFIG_REL))
    arms = {}
    for arm in ARMS:
        ProtectionSpec(arm).validate(config["executor"])
        arms[arm] = ProtectionSpec(arm).to_dict()
    plan = {"study": "protection_ablation_inference_dev9301_9305", "exploratory": True,
            "label": "development evaluation of checkpoints trained WITHOUT protection; not a final test",
            "protected_commit": head, "frozen_commit": FROZEN_COMMIT, "config_sha256": config["_config_sha256"],
            "arms": arms, "executor": config["executor"], "traffic": {"family": "development", "seeds": list(TRAFFIC),
                                                                        "manifests": manifests},
            "models": models, "cells": cells, "n_cells": len(cells), "n_reused": reused, "n_new": len(cells) - reused,
            "root": os.path.abspath(root), "runner_sha256": sha256_file(os.path.abspath(__file__)),
            "python": sys.executable, "evaluation": {"greedy": True, "lane_state_logging": "full",
                                                    "traci_access_mode": "subscription", "device": "cpu",
                                                    "run_kind": "development_evaluation"},
            "design_change": "user instruction 2026-10-29: traffics 9301-9305 (already inspected) instead of the "
                             "originally planned 9401-9410; 600 instead of 1200 evaluations; QMIX/none reused"}
    plan["fingerprint"] = hashlib.sha256(json.dumps(plan, sort_keys=True, default=str).encode()).hexdigest()
    return plan, checks, problems


def require_plan(root):
    plan, _c, problems = build_plan(root)
    if problems:
        raise SystemExit("REFUSED: {}".format(problems))
    stored = read_json(os.path.join(plan["root"], "plan.json"))
    if not stored or stored["fingerprint"] != plan["fingerprint"]:
        raise SystemExit("REFUSED: root not prepared with this plan (fingerprint differs)")
    return plan


def cmd_prepare(root, approved):
    plan, _c, problems = build_plan(root)
    if problems:
        print("REFUSED:", problems)
        return 2
    if approved != plan["fingerprint"]:
        print("REFUSED: --approved-plan must be", plan["fingerprint"])
        return 2
    if os.path.exists(plan["root"]):
        print("REFUSED: {} already exists".format(plan["root"]))
        return 2
    os.makedirs(os.path.join(plan["root"], "checkpoints"))
    os.makedirs(os.path.join(plan["root"], "manifests"))
    for m in plan["models"]:
        dst = os.path.join(plan["root"], "checkpoints", m["tag"] + ".pth")
        shutil.copyfile(m["source"], dst)
        if sha256_file(dst) != m["sha256"]:
            raise SystemExit("checkpoint copy differs: {}".format(dst))
    for seed in TRAFFIC:
        for ext in ("csv", "rou.xml", "metadata.json"):
            src = os.path.join(MANIFESTS, "development_{}.{}".format(seed, ext))
            dst = manifest_prefix(plan["root"], seed) + "." + ext
            shutil.copyfile(src, dst)
            if sha256_file(dst) != plan["traffic"]["manifests"][str(seed)][ext]:
                raise SystemExit("manifest copy differs: {}".format(dst))
    write_json(os.path.join(plan["root"], "plan.json"), plan)
    print("Prepared {}: {} cells ({} new, {} reused)".format(plan["root"], plan["n_cells"], plan["n_new"], plan["n_reused"]))
    return 0


def cmd_run(root, shard):
    plan = require_plan(root)
    sys.path.insert(0, os.path.join(PROTECTED, "src"))
    import traci
    from adaptive_qmix.config import load_config
    from adaptive_qmix_protected.evaluation import evaluate_protected
    from adaptive_qmix_protected.protection import ProtectionSpec
    config = load_config(os.path.join(PROTECTED, CONFIG_REL))
    i, n = (int(x) for x in shard.split("/"))
    new = [c for c in plan["cells"] if "reused_from" not in c]
    log = open(os.path.join(plan["root"], "run_log_shard{}of{}.jsonl".format(i, n)), "a")
    for pos, c in enumerate(new):
        if pos % n != i:
            continue
        d = os.path.join(plan["root"], c["directory"])
        if os.path.isfile(os.path.join(d, "protection_record.json")):
            continue
        attempt = 1
        if os.path.exists(d):
            k = 1
            while os.path.exists("{}.incomplete{}".format(d, k)):
                k += 1
            if k > 1:
                print("NOT RERUN (already retried once, preserved): {}".format(d))
                continue
            os.rename(d, "{}.incomplete{}".format(d, k))
            attempt = 2
        prefix = manifest_prefix(plan["root"], c["traffic_seed"])
        t0, cpu0 = time.time(), time.process_time()
        metrics, record = evaluate_protected(
            traci, config, PROTECTED, os.path.join(plan["root"], "checkpoints", c["model"] + ".pth"),
            prefix + ".csv", prefix + ".rou.xml", c["traffic_seed"],
            plan["traffic"]["manifests"][str(c["traffic_seed"])]["sumo_seed"], d, ProtectionSpec(c["arm"]),
            run_kind="development_evaluation", lane_state_logging="full")
        entry = {"cell": c["directory"], "attempt": attempt, "status": metrics["clearance_status"],
                 "wall_s": time.time() - t0, "cpu_s": time.process_time() - cpu0,
                 "interventions_guarantee": record["interventions_guarantee"],
                 "interventions_min_green": record["interventions_min_green"]}
        log.write(json.dumps(entry) + "\n")
        log.flush()
        print(c["model"], c["traffic_seed"], c["arm"], metrics["clearance_status"], "%.0fs" % entry["wall_s"], flush=True)
    return 0


def cmd_progress(root):
    plan = require_plan(root)
    new = [c for c in plan["cells"] if "reused_from" not in c]
    done = sum(os.path.isfile(os.path.join(plan["root"], c["directory"], "protection_record.json")) for c in new)
    print("new cells finished {}/{} (+{} reused)".format(done, len(new), plan["n_reused"]))
    return 0 if done == len(new) else 3


def cmd_verify_reuse(root):
    plan = require_plan(root)
    bad = []
    for c in plan["cells"]:
        if "reused_from" in c:
            for f, h in c["reused_file_sha256"].items():
                if sha256_file(os.path.join(c["reused_from"], f)) != h:
                    bad.append((c["reused_from"], f))
    print("reused cells {} | changed files {}".format(plan["n_reused"], len(bad)))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "prepare", "run", "progress", "verify-reuse"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--approved-plan")
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args(argv)
    if a.action == "plan":
        plan, checks, problems = build_plan(a.root)
        for name, ok, detail in checks:
            if not ok or not name.startswith("reuse"):
                print("[{}] {}: {}".format("OK" if ok else "FAIL", name, detail))
        print("reuse checks OK: {}/{}".format(sum(ok for n, ok, _ in checks if n.startswith("reuse")),
                                              sum(1 for n, _o, _d in checks if n.startswith("reuse"))))
        print("cells {} = {} models x {} traffics x {} arms | new {} | reused {}".format(
            plan["n_cells"], len(plan["models"]), len(TRAFFIC), len(ARMS), plan["n_new"], plan["n_reused"]))
        for p in problems:
            print("[PROBLEM]", p)
        print("plan fingerprint:", plan["fingerprint"])
        return 2 if problems else 0
    if a.action == "prepare":
        return cmd_prepare(a.root, a.approved_plan)
    if a.action == "run":
        return cmd_run(a.root, a.shard)
    if a.action == "progress":
        return cmd_progress(a.root)
    return cmd_verify_reuse(a.root)


if __name__ == "__main__":
    sys.exit(main())
