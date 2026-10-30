"""Robustness validation on NEW traffics (prepared, not launched in this task).

    python tools/robustness/robustness_runner.py plan --root D:\\QMIX_Results\\robustness_<date>
    python tools/robustness/robustness_runner.py prepare --root ... --approved-plan <fingerprint>
    python tools/robustness/robustness_runner.py run --root ... --shard i/n
    python tools/robustness/robustness_runner.py progress --root ...

Cells: 5 scenarios x 5 traffics x (5 classical/diagnostic controllers + 30 selected checkpoints x 3 arms).
A finished cell (evaluation_metrics.json) is never rerun; an interrupted one is renamed .incompleteN and run once
more; a clearance failure is a finished result.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import scenario_traffic as st  # noqa: E402

CLASSICAL = ["fixed:old_C19_8_5_D9", "fixed:min7_C25_12_7_D0", "canonical_mp", "p5:none", "p5:both"]
LEARNED_ARMS = ["none", "guarantee", "both"]
SECONDS_PER_RUN = 14.0          # measured in the protection ablation (mean wall per cleared evaluation, 4 parallel)
FAILURE_FACTOR = 2.0


def sha256_file(p):
    return st.sha256_file(p)


def build_plan(root):
    import ablation_runner as ar
    spec = st.load_spec()
    aplan, checks, problems = ar.build_plan(os.path.join(root, "_unused"))
    models = aplan["models"]
    cells = []
    for sc in sorted(spec["scenarios"]):
        for seed in spec["scenarios"][sc]["seeds"]:
            for c in CLASSICAL:
                cells.append({"scenario": sc, "seed": seed, "controller": c,
                              "directory": os.path.join("cells", sc, str(seed), c.replace(":", "__"))})
            for m in models:
                for arm in LEARNED_ARMS:
                    cells.append({"scenario": sc, "seed": seed, "controller": "learned:" + arm, "model": m["tag"],
                                  "directory": os.path.join("cells", sc, str(seed), m["tag"], arm)})
    n = len(cells)
    plan = {"study": "robustness_validation", "scenario_spec_sha256": spec["_sha256"], "classical": CLASSICAL,
            "learned_arms": LEARNED_ARMS, "models": models, "cells": cells, "n_cells": n, "root": os.path.abspath(root),
            "runner_sha256": sha256_file(os.path.abspath(__file__)),
            "evaluator_sha256": sha256_file(os.path.join(HERE, "evaluate_any.py")),
            "adapter_sha256": sha256_file(os.path.join(HERE, "n_adapter.py")),
            "generator_sha256": sha256_file(os.path.join(HERE, "scenario_traffic.py")),
            # The analysis is fixed with the plan: approving the fingerprint approves it too.
            "analysis_sha256": sha256_file(os.path.join(HERE, "robustness_analysis.py")),
            "estimated_cpu_h": round(n * SECONDS_PER_RUN * 1.4 / 3600.0, 1),
            "estimated_wall_h_4_workers": round(n * SECONDS_PER_RUN / 4 / 3600.0, 1),
            "estimated_wall_h_4_workers_if_10pct_fail": round(n * SECONDS_PER_RUN * (0.9 + 0.1 * FAILURE_FACTOR) / 4 / 3600.0, 1),
            "estimated_disk_gb": round(n * 4.0 / 1024.0, 1)}
    plan["fingerprint"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan, checks, problems


def prepare(root, approved):
    plan, _c, problems = build_plan(root)
    if problems:
        print("REFUSED", problems)
        return 2
    if approved != plan["fingerprint"]:
        print("REFUSED: --approved-plan must be", plan["fingerprint"])
        return 2
    if os.path.exists(plan["root"]):
        print("REFUSED: root exists")
        return 2
    sys.path.insert(0, os.path.join(st.os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED"), "src"))
    from adaptive_qmix.config import load_config
    import evaluate_any as ea
    config = load_config(os.path.join(ea.PROTECTED, ea.CONFIG_REL))
    spec = st.load_spec()
    os.makedirs(os.path.join(plan["root"], "checkpoints"))
    for m in plan["models"]:
        dst = os.path.join(plan["root"], "checkpoints", m["tag"] + ".pth")
        shutil.copyfile(m["source"], dst)
        if sha256_file(dst) != m["sha256"]:
            raise SystemExit("checkpoint copy differs")
    for sc in sorted(spec["scenarios"]):
        for seed in spec["scenarios"][sc]["seeds"]:
            st.write(spec, sc, seed, st.generate(spec, sc, seed),
                     os.path.join(plan["root"], "manifests", "{}_{}".format(sc, seed)), config["demand"]["vehicle_type"])
    hashes = {}
    for name in sorted(os.listdir(os.path.join(plan["root"], "manifests"))):
        hashes[name] = sha256_file(os.path.join(plan["root"], "manifests", name))
    with open(os.path.join(plan["root"], "manifests_sha256.json"), "w") as f:
        json.dump(hashes, f, indent=2, sort_keys=True)
    with open(os.path.join(plan["root"], "plan.json"), "w") as f:
        json.dump(plan, f, indent=2, sort_keys=True)
    print("prepared", plan["root"], plan["n_cells"], "cells")
    return 0


def run(root, shard):
    plan, _c, problems = build_plan(root)
    with open(os.path.join(plan["root"], "plan.json")) as f:
        stored = json.load(f)
    if problems or stored["fingerprint"] != plan["fingerprint"]:
        raise SystemExit("REFUSED: plan mismatch or problems {}".format(problems))
    import evaluate_any as ea
    i, n = (int(x) for x in shard.split("/"))
    log = open(os.path.join(plan["root"], "run_log_shard{}of{}.jsonl".format(i, n)), "a")
    for pos, c in enumerate(plan["cells"]):
        if pos % n != i:
            continue
        d = os.path.join(plan["root"], c["directory"])
        if os.path.isfile(os.path.join(d, "evaluation_metrics.json")):
            continue
        if os.path.exists(d):
            k = 1
            while os.path.exists("{}.incomplete{}".format(d, k)):
                k += 1
            if k > 1:
                print("NOT RERUN (retried once):", d)
                continue
            os.rename(d, "{}.incomplete{}".format(d, k))
        prefix = os.path.join(plan["root"], "manifests", "{}_{}".format(c["scenario"], c["seed"]))
        ck = os.path.join(plan["root"], "checkpoints", c["model"] + ".pth") if "model" in c else None
        t0 = time.time()
        m = ea.evaluate(c["controller"], prefix, d, checkpoint=ck)
        log.write(json.dumps({"cell": c["directory"], "status": m["clearance_status"], "wall_s": time.time() - t0}) + "\n")
        log.flush()
    return 0


def progress(root):
    plan = json.load(open(os.path.join(root, "plan.json")))
    done = sum(os.path.isfile(os.path.join(root, c["directory"], "evaluation_metrics.json")) for c in plan["cells"])
    print("finished {}/{}".format(done, plan["n_cells"]))
    return 0 if done == plan["n_cells"] else 3


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "prepare", "run", "progress"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--approved-plan")
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args(argv)
    if a.action == "plan":
        plan, checks, problems = build_plan(a.root)
        print("cells", plan["n_cells"], "| est. CPU h", plan["estimated_cpu_h"], "| est. wall h (4 workers)",
              plan["estimated_wall_h_4_workers"], "(", plan["estimated_wall_h_4_workers_if_10pct_fail"],
              "if 10% fail) | disk GB", plan["estimated_disk_gb"])
        for p in problems:
            print("[PROBLEM]", p)
        print("plan fingerprint:", plan["fingerprint"])
        return 2 if problems else 0
    return {"prepare": lambda: prepare(a.root, a.approved_plan), "run": lambda: run(a.root, a.shard),
            "progress": lambda: progress(a.root)}[a.action]()


if __name__ == "__main__":
    sys.exit(main())
