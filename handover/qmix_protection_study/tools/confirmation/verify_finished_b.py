"""READ-ONLY check that every FINISHED cell of B ran its own SUMO (incident of 2026-11-25).

    python tools/confirmation/verify_finished_b.py --root <BCONF> [--out logs\\verify_finished_B.json]

It writes nothing in <BCONF> (only the --out report) and never modifies a cell.

What a finished cell records, and what is checked
-------------------------------------------------
SUMO writes, at the top of tripinfo.xml, an XML comment with the options of its own command line. b_runner gzips the
file into the cell folder (tripinfo.xml.gz). For each finished cell (complete or scientific_failure):

1. header: present; ``route-files`` is the cell's own manifest ``<BCONF>/manifests/<profile>_<seed>.rou.xml``;
   ``tripinfo-output`` is the cell's own work folder ``<cell>.tmp/tripinfo.xml``; ``seed`` is the manifest's
   ``sumo_seed``; ``remote-port`` and the start time ("generated on") are read;
2. vehicles: the tripinfo ids are exactly the vehicle ids of the manifest, once each, and their number is the
   manifest's ``scheduled_total`` (``--tripinfo-output.write-unfinished`` lists the unfinished ones too);
3. cell_summary.json (recomputed by b_runner from the gzip traces): N, tripinfo_rows, no problem; learned arms:
   ``sumo_mismatch_s`` = 0 (commanded signal = SUMO signal, every second);
4. ports: two cells whose SUMO used the same remote port at overlapping times (start from the header, end from the
   run logs) are reported. With the default traci.start the port comes from the dynamic range, so a reuse at different
   times is normal; an OVERLAP is what a cross-connection would need.

Why this is enough: a SUMO started with --remote-port does not advance without its TraCI client. A finished cell has, in
its own folder, a tripinfo written by a SUMO that loaded its own routes and wrote to its own work folder (1), drove all
its vehicles to the end (2), under a controller whose commands are the signals that SUMO applied (3) and whose J equals
the J recomputed from that tripinfo (b_runner re-read). A client connected to another cell's SUMO would leave its own
folder without such a tripinfo.

Exit codes: 0 every finished cell verified; 1 at least one problem; 4 some cells cannot be verified (no header).
"""
from __future__ import absolute_import, division, print_function

import argparse
import datetime
import glob
import gzip
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import b_runner as BR  # noqa: E402

OPTION = re.compile(r'<([A-Za-z0-9_.\-]+) value="([^"]*)"\s*/>')
GENERATED = re.compile(r"generated on (.+?) by ")


def norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path))) if path else path


def read_header(handle):
    """Options and start time from the leading comment of a SUMO output (None when there is no header)."""
    text = ""
    for _ in range(400):
        line = handle.readline()
        if not line:
            break
        line = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
        text += line
        if "-->" in line or "<tripinfos" in line:
            break
    if "<!--" not in text:
        return None
    head = text.split("-->", 1)[0]
    opts = dict(OPTION.findall(head))
    m = GENERATED.search(head)
    opts["_generated_on"] = m.group(1) if m else None
    return opts


def epoch(stamp):
    if not stamp:
        return None
    s = stamp.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*[+-]\d\d):?(\d\d)$", s)
    if m and "T" in s:
        s = m.group(1) + ":" + m.group(2)
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")          # older SUMO headers: local time
        except ValueError:
            return None
    if d.tzinfo is None:
        return time.mktime(d.timetuple()) + d.microsecond / 1e6       # naive: the local time of this machine
    return (d - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)).total_seconds()


def tripinfo_ids(path):
    ids = []
    with gzip.open(path, "rb") as f:
        for _event, el in ET.iterparse(f, events=("end",)):
            if el.tag == "tripinfo":
                ids.append(el.get("id"))
            el.clear()
    return ids


def manifest_ids(rou):
    ids = []
    for _event, el in ET.iterparse(rou, events=("end",)):
        if el.tag == "vehicle":
            ids.append(el.get("id"))
        el.clear()
    return ids


def run_log_ends(root):
    """directory -> t_end of its last FINISHED record in the run logs (first launch and resumptions)."""
    ends = {}
    for path in sorted(glob.glob(os.path.join(root, "run_log_shard*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("state") in BR.FINISHED and r.get("t_end"):
                    ends[r["dir"]] = (float(r["t_end"]), float(r.get("wall_s") or 0.0))
    return ends


def verify(root, plan=None):
    plan = plan or BR.load_plan(root)
    jobs = BR.unique_jobs(plan["jobs"])
    ends = run_log_ends(root)
    manifests, problems, unverifiable, ports = {}, [], [], []
    counts = {"finished": 0, "verified": 0, "header": 0, "ids_match": 0, "summary_ok": 0, "learned_signal_ok": 0}
    for j in jobs:
        state = BR.classify(root, j)[0]
        if state not in BR.FINISHED:
            continue
        counts["finished"] += 1
        d = os.path.join(root, j["directory"])
        key = (j["profile"], str(j["seed"]))
        if key not in manifests:
            prefix = os.path.join(root, "manifests", "{}_{}".format(*key))
            meta = BR.read_json(prefix + ".metadata.json")
            manifests[key] = {"rou": prefix + ".rou.xml", "ids": manifest_ids(prefix + ".rou.xml"),
                              "n": int(meta["scheduled_total"]), "sumo_seed": str(meta.get("sumo_seed"))}
        man = manifests[key]
        mine = []
        trip = os.path.join(d, "tripinfo.xml.gz")
        try:
            with gzip.open(trip, "rb") as f:
                head = read_header(f)
        except (OSError, EOFError) as error:
            head = None
            mine.append("tripinfo.xml.gz unreadable: {!r}".format(error))
        if head is None:
            unverifiable.append(j["directory"])
        else:
            counts["header"] += 1
            if norm(head.get("route-files")) != norm(man["rou"]):
                mine.append("route-files {} is not the cell's manifest {}".format(head.get("route-files"), man["rou"]))
            want = os.path.join(d + ".tmp", "tripinfo.xml")
            if norm(head.get("tripinfo-output")) != norm(want):
                mine.append("tripinfo-output {} is not the cell's work folder {}".format(head.get("tripinfo-output"), want))
            if man["sumo_seed"] not in (None, "None") and head.get("seed") != man["sumo_seed"]:
                mine.append("SUMO seed {} differs from the manifest {}".format(head.get("seed"), man["sumo_seed"]))
            start = epoch(head.get("_generated_on"))
            end = ends.get(j["directory"], (None, 0))[0]
            ports.append({"dir": j["directory"], "port": head.get("remote-port"), "start": start, "end": end})
        try:
            ids = tripinfo_ids(trip)
        except (ET.ParseError, OSError, EOFError) as error:
            ids = None
            mine.append("tripinfo unreadable: {!r}".format(error))
        if ids is None:
            pass
        elif sorted(ids) != sorted(man["ids"]) or len(ids) != man["n"]:
            extra = sorted(set(ids) - set(man["ids"]))[:3]
            missing = sorted(set(man["ids"]) - set(ids))[:3]
            mine.append("tripinfo has {} rows ({} distinct) for N = {}; foreign ids {}; missing ids {}".format(
                len(ids), len(set(ids)), man["n"], extra, missing))
        else:
            counts["ids_match"] += 1
        s = BR.read_json(os.path.join(d, "cell_summary.json"))
        sp = list(s.get("problems") or [])
        if int(s.get("N") or -1) != man["n"] or int(s.get("tripinfo_rows") or -1) != man["n"] or sp:
            mine.append("cell_summary: N {} tripinfo_rows {} problems {}".format(s.get("N"), s.get("tripinfo_rows"), sp[:3]))
        else:
            counts["summary_ok"] += 1
        if j["kind"] == "learned":
            if s.get("sumo_mismatch_s") != 0:
                mine.append("learned arm: sumo_mismatch_s = {!r}".format(s.get("sumo_mismatch_s")))
            else:
                counts["learned_signal_ok"] += 1
        if mine:
            problems.append({"dir": j["directory"], "problems": mine})
        elif head is not None:
            counts["verified"] += 1
    overlaps = []
    by_port = {}
    for p in ports:
        by_port.setdefault(p["port"], []).append(p)
    for port, rows in by_port.items():
        rows = sorted(rows, key=lambda r: r["start"] or 0)
        for a, b in zip(rows, rows[1:]):
            if None in (a["start"], a["end"], b["start"]):
                continue
            if b["start"] < a["end"]:
                overlaps.append({"port": port, "cells": [a["dir"], b["dir"]], "start_b": b["start"], "end_a": a["end"]})
    timing_known = sum(1 for p in ports if p["start"] is not None and p["end"] is not None)
    verdict = "PROBLEMS" if problems or overlaps else ("NOT VERIFIABLE FOR SOME CELLS" if unverifiable else "VERIFIED")
    return {"plan_fingerprint": plan["fingerprint"], "verdict": verdict, "counts": counts,
            "port_overlaps": overlaps, "cells_with_port_and_timing": timing_known,
            "distinct_ports": len(by_port), "problems": problems, "without_header": unverifiable}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default=os.path.join("logs", "verify_finished_B.json"))
    a = ap.parse_args(argv)
    try:
        report = verify(a.root)
    except (BR.BError, OSError, ValueError) as error:
        print("STOP:", error)
        return 1
    if a.out:
        d = os.path.dirname(a.out)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, sort_keys=True)
    c = report["counts"]
    print("finished cells {} | verified {} | header {} | ids = manifest {} | summary ok {} | learned signal ok {}".format(
        c["finished"], c["verified"], c["header"], c["ids_match"], c["summary_ok"], c["learned_signal_ok"]))
    print("ports: {} distinct, {} cells with port and timing, {} overlap(s)".format(
        report["distinct_ports"], report["cells_with_port_and_timing"], len(report["port_overlaps"])))
    for p in report["problems"][:20]:
        print("  PROBLEM {}: {}".format(p["dir"], "; ".join(p["problems"])))
    for o in report["port_overlaps"][:20]:
        print("  OVERLAP port {}: {}".format(o["port"], " / ".join(o["cells"])))
    if report["without_header"]:
        print("  {} cell(s) without a SUMO header in tripinfo: not verifiable this way".format(len(report["without_header"])))
    print("{} (report: {})".format(report["verdict"], a.out))
    if report["verdict"] == "PROBLEMS":
        return 1
    return 4 if report["without_header"] else 0


if __name__ == "__main__":
    sys.exit(main())
