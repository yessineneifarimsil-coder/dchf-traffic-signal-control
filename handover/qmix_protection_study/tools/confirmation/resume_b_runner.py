"""Resumption of campaign B after the TraCI incident of 2026-11-25 (worker 2/4 lost its connection label).

    python tools/confirmation/resume_b_runner.py check    --root <BCONF> [--workers 4]
    python tools/confirmation/resume_b_runner.py assign   --root <BCONF> [--workers 4]
    python tools/confirmation/resume_b_runner.py preflight --root <BCONF>
    python tools/confirmation/resume_b_runner.py run      --root <BCONF> --worker <k>

What it is
----------
A launcher around the FROZEN ``b_runner.run``. It changes neither the plan, nor its fingerprint, nor the seeds, the
jobs, the controllers, the guarantee, the criteria or the statistics: every job is executed by ``b_runner.run`` itself,
with its own freeze checks (code, margins, statistics), its classification, its resume rule (one retry, the partial
folder kept as ``<cell>.incomplete1``, a second interruption preserved and never rerun) and its run log. Two things are
added, in the worker process only:

1. the distribution: ``assign`` writes once, in ``<BCONF>/resume/assignment_NN.json``, the jobs not finished
   (interrupted or not started; corrupted jobs are preserved and never rerun), dealt round-robin in plan order over
   the workers. Each worker runs exactly its list, whatever shard of the first launch the jobs belonged to;
2. the TraCI guard (``traci_guard.py``): robust start, at most 3 new start attempts on another port, cleanup of the
   connection label and of the SUMO process after any failure. An error during the simulation stays INTERRUPTED.

Safeguards
----------
- ``assign`` and ``preflight`` refuse (code 3) while any process of B or A-ext is running (``b_watch.list_processes``,
  the same listing as ``ETAPES.cmd b-processes``): the first launch must be over.
- ``preflight`` and ``run`` refuse when this file or traci_guard.py differ from the ones recorded in the assignment,
  when the plan fingerprint differs, or when the start path of the frozen environment is not the one the guard covers.
- Nothing is deleted. Finished cells are never touched (b_runner.run skips them).

Exit codes: 0 done; 1 STOP (message); 3 processes still running (assign/preflight) or jobs not finished (run);
5 a corrupted result (as b_runner.run).
"""
from __future__ import absolute_import, division, print_function

import argparse
import glob
import hashlib
import inspect
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (HERE, os.path.join(TOOLS, "monitor")):
    if p not in sys.path:
        sys.path.insert(0, p)

import b_runner as BR  # noqa: E402
import traci_guard as TG  # noqa: E402

WORKERS = 4
RESUMABLE = ("interrupted", "not_started")
GUARD_FILES = (os.path.join(HERE, "resume_b_runner.py"), os.path.join(HERE, "traci_guard.py"))
# Calls that would bypass the guard (it replaces traci.start and traci.main.start only).
BYPASS = (re.compile(r"\btraci\.init\s*\("), re.compile(r"\btraci\.connect\s*\("), re.compile(r"from\s+traci\s+import"),
          re.compile(r"\btraci\.connection\.Connection\s*\("))


class ResumeError(Exception):
    pass


class GuardBypassed(BaseException):
    """A cell ran without any guarded start: stop the worker before the next cell (never caught by b_runner.run)."""


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def guard_hashes():
    return dict((os.path.basename(p), sha256_file(p)) for p in GUARD_FILES)


def resume_dir(root):
    return os.path.join(root, "resume")


def write_json_once(path, payload):
    with open(path, "x", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------------------------------------------

def running_processes():
    """(rows, error) of the processes of B / A-ext, this one excluded (b_watch.list_processes)."""
    import b_watch
    return b_watch.list_processes()


def refuse_if_running(lister=None):
    rows, error = (lister or running_processes)()
    if error:
        raise ResumeError("cannot list the processes, so the resumption is refused: {}".format(error))
    me = os.getpid()
    rows = [r for r in rows or [] if r.get("pid") != me]
    if rows:
        raise ResumeError("{} B / A-ext process(es) still running: {}. Wait for the end of the first launch "
                          "(ETAPES.cmd b-processes must say 0).".format(
                              len(rows), ", ".join("pid {} {} {}".format(r["pid"], r.get("action", ""), r.get("shard", ""))
                                                   for r in rows)))


# ---------------------------------------------------------------------------------------------------------------
# Start path of the frozen environment
# ---------------------------------------------------------------------------------------------------------------

def package_dirs():
    """Directories of the code that runs a B cell: the frozen environment, the protected package, the evaluators."""
    __import__("evaluate_any")                    # puts the protected src on sys.path, as for a real cell
    dirs = []
    for name in ("adaptive_qmix", "adaptive_qmix_protected"):
        try:
            module = __import__(name)
            dirs.append(os.path.dirname(os.path.abspath(module.__file__)))
        except ImportError as error:
            dirs.append("MISSING {}: {}".format(name, error))
    return dirs


def start_path_report(dirs=None, reset_source=None):
    """problems, notes: the frozen reset must call self.traci.start, and no code of the B path may start TraCI in a
    way the guard does not cover (traci.init / traci.connect / from traci import ...)."""
    problems, notes = [], []
    if reset_source is None:
        try:
            from adaptive_qmix.environment import AdaptiveTrafficEnvironment
            reset_source = inspect.getsource(AdaptiveTrafficEnvironment.reset)
        except Exception as error:  # noqa: BLE001
            problems.append("frozen environment not importable: {!r}".format(error))
            reset_source = ""
    if reset_source and "self.traci.start(" not in reset_source:
        problems.append("AdaptiveTrafficEnvironment.reset does not call self.traci.start: the guard would not apply")
    elif reset_source:
        notes.append("AdaptiveTrafficEnvironment.reset calls self.traci.start (covered by the guard)")
    tool_files = [os.path.join(TOOLS, "robustness", "evaluate_any.py"), os.path.join(TOOLS, "robustness", "n_adapter.py"),
                  os.path.join(TOOLS, "comparators", "evaluate_comparator.py"),
                  os.path.join(TOOLS, "comparators_ext", "evaluate_ext.py"), os.path.join(HERE, "b_runner.py")]
    files = list(tool_files)
    for d in (package_dirs() if dirs is None else dirs):
        if d.startswith("MISSING"):
            problems.append(d)
            continue
        for base, sub, names in os.walk(d):
            sub[:] = sorted(x for x in sub if x != "__pycache__")
            files += [os.path.join(base, n) for n in sorted(names) if n.endswith(".py")]
    starts = 0
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError) as error:
            problems.append("cannot read {}: {!r}".format(path, error))
            continue
        for n, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if ".start(" in code and "traci" in code:
                starts += 1
            for pattern in BYPASS:
                if pattern.search(code):
                    problems.append("{}:{}: {} (not covered by the guard)".format(path, n, line.strip()))
    notes.append("{} files scanned, {} traci start call(s) found, all through the module attribute".format(len(files), starts))
    return problems, notes


# ---------------------------------------------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------------------------------------------

def states(root, plan):
    out = {}
    for j in BR.unique_jobs(plan["jobs"]):
        out.setdefault(BR.classify(root, j)[0], []).append(j)
    return out


def assignments(root):
    return sorted(glob.glob(os.path.join(resume_dir(root), "assignment_[0-9][0-9].json")))


def assign(root, workers=WORKERS, lister=None):
    refuse_if_running(lister)
    plan = BR.load_plan(root)                                     # frozen checks of b_runner
    by_state = states(root, plan)
    todo = [j for j in BR.unique_jobs(plan["jobs"]) if BR.classify(root, j)[0] in RESUMABLE]
    if not todo:
        raise ResumeError("nothing to resume: every job is finished or corrupted")
    os.makedirs(resume_dir(root), exist_ok=True)
    number = len(assignments(root)) + 1
    lists = [[] for _ in range(workers)]
    for pos, j in enumerate(todo):
        lists[pos % workers].append(j["directory"])
    twice = [j["directory"] for j in todo if os.path.exists(os.path.join(root, j["directory"] + ".incomplete1"))
             and BR.classify(root, j)[0] == "interrupted"]
    payload = {"number": number, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "plan_fingerprint": plan["fingerprint"],
               "workers": workers, "jobs": lists, "port_ranges": [TG.worker_range(k) for k in range(workers)],
               "start_retries": TG.RETRIES, "guard_sha256": guard_hashes(),
               "states_at_assignment": dict((s, len(v)) for s, v in sorted(by_state.items())),
               "corrupted_not_rerun": [j["directory"] for j in by_state.get("corrupted", [])],
               "already_interrupted_once_will_be_preserved_if_interrupted": twice}
    path = os.path.join(resume_dir(root), "assignment_{:02d}.json".format(number))
    write_json_once(path, payload)
    return path, payload


def load_assignment(root, path=None):
    paths = assignments(root)
    path = path or (paths[-1] if paths else None)
    if not path or not os.path.isfile(path):
        raise ResumeError("no assignment in {}: run `assign` first".format(resume_dir(root)))
    a = read_json(path)
    if a["guard_sha256"] != guard_hashes():
        raise ResumeError("resume_b_runner.py / traci_guard.py differ from the assignment {}: assign again".format(path))
    return path, a


def check_assignment(root, a, plan):
    if a["plan_fingerprint"] != plan["fingerprint"]:
        raise ResumeError("assignment fingerprint {} differs from the plan {}".format(a["plan_fingerprint"],
                                                                                     plan["fingerprint"]))
    known = set(j["directory"] for j in plan["jobs"])
    flat = [d for lst in a["jobs"] for d in lst]
    if len(flat) != len(set(flat)) or not set(flat) <= known:
        raise ResumeError("assignment lists a job twice or a job outside the plan")


# ---------------------------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------------------------

def check(root, workers=WORKERS, lister=None, dirs=None, reset_source=None):
    plan = BR.load_plan(root)
    by_state = states(root, plan)
    print("plan {} | {}".format(plan["fingerprint"], " | ".join("{} {}".format(s, len(v)) for s, v in sorted(by_state.items()))))
    problems, notes = start_path_report(dirs, reset_source)
    dyn = TG.dynamic_range_windows()
    p2, n2 = TG.check_ranges(workers, dyn, TG.excluded_ranges_windows())
    problems += p2
    notes += n2 + ["worker port ranges {} (dynamic range {})".format(
        [TG.worker_range(k) for k in range(workers)], dyn or "default 49152-65535, not queried on this system")]
    rows, error = (lister or running_processes)()
    if error:
        problems.append(error)
    running = [r for r in rows or [] if r.get("pid") != os.getpid()]
    for n in notes:
        print("  note: " + n)
    for p in problems:
        print("  PROBLEM: " + p)
    print("{} B / A-ext process(es) running{}".format(len(running), "" if running else ": a resumption is possible"))
    print("guard files: {}".format(guard_hashes()))
    if problems:
        return 1
    return 3 if running else 0


def preflight(root, lister=None, free=None, dirs=None, reset_source=None):
    refuse_if_running(lister)
    plan = BR.load_plan(root)
    path, a = load_assignment(root)
    check_assignment(root, a, plan)
    problems, _notes = start_path_report(dirs, reset_source)
    p2, _n2 = TG.check_ranges(a["workers"], TG.dynamic_range_windows())
    if problems + p2:
        raise ResumeError("; ".join(problems + p2))
    flat = set(d for lst in a["jobs"] for d in lst)
    remaining = [j for j in BR.unique_jobs(plan["jobs"]) if j["directory"] in flat
                 and BR.classify(root, j)[0] not in BR.FINISHED]
    need = BR.check_disk(root, len(remaining), plan["estimate"]["bytes_per_run"], free)
    print("resume preflight OK: {} | {} job(s) to run on {} worker(s), {:.2f} GB required with the 4 GB margin, plan {}"
          .format(os.path.basename(path), len(remaining), a["workers"], need / 1e9, plan["fingerprint"]))
    return 0


def run(root, worker, assignment=None, evaluator=None, traci_module=None, free=None, dirs=None, reset_source=None,
        popen=None):
    plan = BR.load_plan(root)
    path, a = load_assignment(root, assignment)
    check_assignment(root, a, plan)
    worker = int(worker)
    if not 0 <= worker < a["workers"]:
        raise ResumeError("worker {} outside 0..{}".format(worker, a["workers"] - 1))
    problems, _notes = start_path_report(dirs, reset_source)
    if problems:
        raise ResumeError("; ".join(problems))
    if traci_module is None:
        import traci as traci_module
    log = os.path.join(resume_dir(root), "traci_guard_r{:02d}_w{}.jsonl".format(a["number"], worker))
    guard = TG.Guard(traci_module, worker, log, port_range=tuple(a["port_ranges"][worker]), retries=a["start_retries"],
                     popen=popen).install()
    mine = set(a["jobs"][worker])
    inner = evaluator or BR.default_evaluator
    state = {"bypassed": None}

    def guarded(root_, j, prefix, work):
        if state["bypassed"]:
            raise GuardBypassed("cell {} ran without a guarded TraCI start: worker stopped".format(state["bypassed"]))
        guard.begin_cell(j["directory"])
        ok = False
        try:
            inner(root_, j, prefix, work)
            ok = True
        finally:
            info = guard.end_cell(ok)
            guard.log("cell_end", ok=ok, **info)
        if ok and info["starts"] == 0 and evaluator is None:
            state["bypassed"] = j["directory"]

    saved_shard = BR.shard
    BR.shard = lambda jobs, spec: [j for j in BR.unique_jobs(jobs) if j["directory"] in mine]
    try:
        return BR.run(root, "r{:02d}w{}/{}".format(a["number"], worker, a["workers"]), evaluator=guarded, free=free)
    finally:
        BR.shard = saved_shard
        guard.release("default", reason="end of worker")
        guard.uninstall()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("check", "assign", "preflight", "run"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--worker", type=int)
    ap.add_argument("--assignment")
    a = ap.parse_args(argv)
    try:
        if a.action == "check":
            return check(a.root, a.workers)
        if a.action == "assign":
            path, payload = assign(a.root, a.workers)
            print("written {} (nothing else changed)".format(path))
            for k, lst in enumerate(payload["jobs"]):
                print("  worker {}: {} job(s), ports {}-{}".format(k, len(lst), *payload["port_ranges"][k]))
            print("  states at assignment: {}".format(payload["states_at_assignment"]))
            if payload["corrupted_not_rerun"]:
                print("  corrupted, preserved, NOT rerun: {}".format(len(payload["corrupted_not_rerun"])))
            return 0
        if a.action == "preflight":
            return preflight(a.root)
        if a.worker is None:
            raise ResumeError("run needs --worker")
        return run(a.root, a.worker, a.assignment)
    except ResumeError as error:
        print("STOP:", error)
        return 3 if "still running" in str(error) else 1
    except (BR.BError, BR.SD.SeedError) as error:
        print("STOP:", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
