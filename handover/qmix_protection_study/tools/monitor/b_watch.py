"""Operations helpers for campaigns A-ext and B (read-only, except backup-logs which only COPIES files).

    python tools/monitor/b_watch.py processes   [--b-root <B>] [--aext-root <A-ext>]
    python tools/monitor/b_watch.py backup-logs [--b-root <B>] [--aext-root <A-ext>]
    python tools/monitor/b_watch.py watch       [--b-root <B>] [--aext-root <A-ext>] [--interval 600] [--once]

processes    lists ONLY the python processes of B (b_runner.py) and A-ext (aext_search.py): process id, start time,
             action and shard. The listing process itself is never counted. Exit 0 when none runs, 3 otherwise (use it
             before a relaunch: 3 means "do not relaunch, workers are still running").
backup-logs  copies logs\\b_shard*.log, logs\\aext_*_shard*.log and the run_log_*.jsonl of both roots into
             logs\\backup_<YYYYmmdd_HHMMSS>\\ (a relaunch overwrites the console logs). Nothing is deleted or moved.
watch        every --interval seconds (default 600 = 10 min): finished runs per stage (A-ext design and validation;
             B per profile), runs finished in the last 30 minutes and the resulting rate, a remaining-time estimate
             ("estimation indisponible" with fewer than 2 runs in that window), the active B / A-ext processes and the
             free space of each target volume. "Finished" here = evaluation_metrics.json present (fast count); the
             authoritative states are those of `ETAPES.cmd b-progress` / `aext-progress`.
"""
from __future__ import absolute_import, division, print_function

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

PATTERNS = ("b_runner.py", "aext_search.py")
WINDOW_S = 1800


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def classify_cmdline(cmd):
    words = cmd.replace('"', " ").split()
    script = next((w for w in words if w.endswith(PATTERNS)), "")
    action = ""
    if script:
        rest = words[words.index(script) + 1:]
        action = rest[0] if rest else ""
    shard = ""
    if "--shard" in words:
        shard = words[words.index("--shard") + 1] if words.index("--shard") + 1 < len(words) else ""
    stage = words[words.index("--stage") + 1] if "--stage" in words and words.index("--stage") + 1 < len(words) else ""
    return {"campaign": "B" if script.endswith("b_runner.py") else ("A-ext" if script else ""), "action": action,
            "stage": stage, "shard": shard}


def list_processes():
    """python processes whose command line runs b_runner.py or aext_search.py, excluding this process."""
    me = os.getpid()
    rows = []
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*.exe' -and "
              "($_.CommandLine -like '*b_runner.py*' -or $_.CommandLine -like '*aext_search.py*') } | "
              "Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=120).stdout.decode("utf-8", "replace").strip()
        except (OSError, subprocess.SubprocessError) as error:
            return None, "process listing unavailable: {!r}".format(error)
        data = json.loads(out) if out else []
        data = [data] if isinstance(data, dict) else data
        for p in data:
            rows.append({"pid": int(p["ProcessId"]), "ppid": int(p.get("ParentProcessId") or 0),
                         "started": str(p.get("CreationDate")), "cmd": p.get("CommandLine") or ""})
    else:
        for d in glob.glob("/proc/[0-9]*"):
            try:
                with open(os.path.join(d, "cmdline"), "rb") as handle:
                    cmd = handle.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                started = os.stat(d).st_mtime
            except OSError:
                continue
            if "python" in cmd.split(" ")[0] and any(p in cmd for p in PATTERNS):
                rows.append({"pid": int(os.path.basename(d)), "ppid": 0,
                             "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)), "cmd": cmd})
    out = []
    for r in rows:
        if r["pid"] == me or "b_watch.py" in r["cmd"]:
            continue                                     # never count the monitor itself
        info = classify_cmdline(r["cmd"])
        if info["campaign"]:
            out.append(dict(r, **info))
    return sorted(out, key=lambda r: (r["campaign"], r["shard"], r["pid"])), None


def b_jobs(b_root):
    path = os.path.join(b_root, "plan.json")
    return read_json(path)["jobs"] if os.path.isfile(path) else None


def aext_orders(aext_root):
    out = {}
    for stage in ("aext-design", "aext-validation"):
        path = os.path.join(aext_root, "orders", stage + ".json")
        if os.path.isfile(path):
            jobs, seen = [], set()
            for j in read_json(path)["jobs"]:
                if j["directory"] not in seen:
                    seen.add(j["directory"])
                    jobs.append(j)
            out[stage] = jobs
    return out


def finished(root, directory):
    return os.path.isfile(os.path.join(root, directory, "evaluation_metrics.json"))


def recent(root_logs, now):
    """(count in the last 30 min, count of entries with a time stamp) from run_log_*.jsonl."""
    n, stamped = 0, 0
    for path in root_logs:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        t = json.loads(line).get("t_end")
                    except ValueError:
                        continue
                    if t is None:
                        continue
                    stamped += 1
                    if now - float(t) <= WINDOW_S and json.loads(line).get("state") in ("complete", "scientific_failure"):
                        n += 1
        except OSError:
            continue
    return n, stamped


def free_gb(path):
    path = os.path.abspath(path)
    while not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    try:
        return round(shutil.disk_usage(path).free / 1e9, 2)
    except OSError:
        return None


def snapshot(b_root, aext_root, now=None):
    now = time.time() if now is None else now
    lines = ["=== {} ===".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))]
    remaining = 0
    logs = []
    for stage, jobs in sorted(aext_orders(aext_root).items()):
        done = sum(1 for j in jobs if finished(aext_root, j["directory"]))
        remaining += len(jobs) - done
        lines.append("A-ext {:16} {:4}/{:<4} finished".format(stage, done, len(jobs)))
    logs += glob.glob(os.path.join(aext_root, "run_log_*.jsonl"))
    jobs = b_jobs(b_root)
    if jobs is None:
        lines.append("B: not prepared (no plan.json in {})".format(b_root))
    else:
        by = {}
        for j in jobs:
            t = by.setdefault(j["profile"], [0, 0])
            t[1] += 1
            t[0] += 1 if finished(b_root, j["directory"]) else 0
        for p, (d, n) in sorted(by.items()):
            lines.append("B {:34} {:4}/{:<4} finished".format(p, d, n))
            remaining += n - d
        logs += glob.glob(os.path.join(b_root, "run_log_shard*.jsonl"))
    n, stamped = recent(logs, now)
    if n >= 2:
        rate = n / (WINDOW_S / 3600.0)
        lines.append("last 30 min: {} runs finished -> {:.1f} runs/h; remaining {} -> about {:.1f} h (estimate)".format(
            n, rate, remaining, remaining / rate))
    else:
        lines.append("last 30 min: {} runs finished -> estimation indisponible (remaining {})".format(n, remaining))
    procs, error = list_processes()
    if error:
        lines.append(error)
    else:
        lines.append("active processes: {}".format(len(procs)))
        for p in procs:
            lines.append("  pid {:6} {:5} {:9} {:16} shard {:6} started {}".format(p["pid"], p["campaign"], p["action"],
                                                                                   p["stage"], p["shard"], p["started"]))
    for name, root in (("B", b_root), ("A-ext", aext_root)):
        lines.append("free space on the volume of {} ({}): {} GB".format(name, root, free_gb(root)))
    return "\n".join(lines)


def backup_logs(b_root, aext_root, logs_dir="logs"):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(logs_dir, "backup_" + stamp)
    sources = (glob.glob(os.path.join(logs_dir, "b_shard*.log")) + glob.glob(os.path.join(logs_dir, "aext_*_shard*.log")))
    roots = [("B", b_root, "run_log_shard*.jsonl"), ("A-ext", aext_root, "run_log_*.jsonl")]
    copied = []
    os.makedirs(dest)
    for src in sources:
        shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
        copied.append(src)
    for name, root, pattern in roots:
        for src in glob.glob(os.path.join(root, pattern)):
            sub = os.path.join(dest, name)
            os.makedirs(sub, exist_ok=True)
            shutil.copy2(src, os.path.join(sub, os.path.basename(src)))
            copied.append(src)
    return dest, copied


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("processes", "backup-logs", "watch"))
    ap.add_argument("--b-root", default=r"D:\QMIX_Results\confirmation_B")
    ap.add_argument("--aext-root", default=r"D:\QMIX_Results\comparators_actuated_g5")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    if a.action == "processes":
        procs, error = list_processes()
        if error:
            print(error)
            return 1
        for p in procs:
            print("pid {:6} {:5} {:9} {:16} shard {:6} started {}".format(p["pid"], p["campaign"], p["action"], p["stage"],
                                                                         p["shard"], p["started"]))
        print("{} B / A-ext process(es) running{}".format(len(procs), "" if procs else ": a relaunch is possible"))
        return 3 if procs else 0
    if a.action == "backup-logs":
        dest, copied = backup_logs(a.b_root, a.aext_root)
        print("copied {} file(s) to {} (nothing deleted)".format(len(copied), dest))
        return 0
    while True:
        print(snapshot(a.b_root, a.aext_root))
        sys.stdout.flush()
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
