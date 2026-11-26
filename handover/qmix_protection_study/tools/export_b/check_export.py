"""Check of the export before delivery (read-only on the export; writes check_export.txt only).

    python tools/export_b/check_export.py --export <EXPORT> --bconf <BCONF> [--rows 2470] [--scientific-failures 30]
        [--guarantee-failures 0] [--guarantee-rows 1100]

Checks, each reported PASS / FAIL with the observed value:
1. B_episodes.csv has the expected number of rows, one per distinct cell_id;
2. scientific failures (cell_state scientific_failure) = the expected number;
3. failures in the guarantee arms = 0, and the number of guarantee evaluations = the expected number;
4. reestimation_vs_frozen.txt ends with VERDICT: IDENTICAL, and reestimate_B.csv has 12 decisions equal to the frozen
   decisions.csv (the comparison of reestimate_B.py itself);
5. no exported text file contains a personal path (C:\\Users\\..., the home folder) or the absolute BCONF path;
6. the expected files are present.
The expected numbers are those stated for B; a difference is reported, never corrected.
"""
from __future__ import absolute_import, division, print_function

import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FILES = ("B_episodes.csv", "B_episodes_report.json", "B_margins.json", "reestimate_B.py", "reestimate_B.csv",
         "reestimation_vs_frozen.txt", "sensitivity_B.csv", "search_counts.csv", "search_counts_details.json",
         "network_facts.json", "training_facts.json")
TEXT = (".csv", ".json", ".txt", ".md", ".py")
PERSONAL = re.compile(r"[A-Za-z]:(\\\\|\\|/)+Users(\\\\|\\|/)+(?!<)", re.I)


def check(export, bconf, rows_expected=2470, sci_expected=30, gfail_expected=0, grows_expected=1100):
    results = []

    def add(name, ok, observed):
        results.append(("PASS" if ok else "FAIL", name, observed))

    with open(os.path.join(export, "B_episodes.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    ids = set(r["cell_id"] for r in rows)
    add("rows = {}".format(rows_expected), len(rows) == rows_expected, len(rows))
    add("one row per cell_id", len(ids) == len(rows), "{} distinct".format(len(ids)))
    sci = sum(1 for r in rows if r["cell_state"] == "scientific_failure")
    add("scientific failures = {}".format(sci_expected), sci == sci_expected, sci)
    g = [r for r in rows if r["controller_kind"] == "learned" and r["arm"] == "guarantee"]
    gf = sum(1 for r in g if r["status"] != "CLEARED")
    add("failures in the guarantee arms = {}".format(gfail_expected), gf == gfail_expected, gf)
    add("guarantee evaluations = {}".format(grows_expected), len(g) == grows_expected, len(g))
    blank_j_cleared = sum(1 for r in rows if r["status"] == "CLEARED" and r["J_s"] == "")
    filled_j_failed = sum(1 for r in rows if r["status"] != "CLEARED" and r["J_s"] != "")
    add("J empty exactly for the runs not cleared", blank_j_cleared == 0 and filled_j_failed == 0,
        "cleared without J {}, not cleared with J {}".format(blank_j_cleared, filled_j_failed))
    path = os.path.join(export, "reestimation_vs_frozen.txt")
    text = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
    add("reestimation identical to the frozen decisions", "VERDICT: IDENTICAL" in text,
        (text.strip().splitlines() or ["absent"])[-1])
    m = re.search(r"decisions identical: (\d+)/(\d+)", text)
    add("12 decisions identical", bool(m) and m.group(1) == m.group(2) == "12", m.group(0) if m else "absent")
    missing = [n for n in FILES if not os.path.isfile(os.path.join(export, n))]
    add("expected files present", not missing, missing or "all")
    leaks = []
    targets = [bconf.rstrip("\\/"), bconf.rstrip("\\/").replace("\\", "/"), os.path.abspath(bconf)] if bconf else []
    for base, _sub, names in os.walk(export):
        for n in names:
            if not n.endswith(TEXT):
                continue
            p = os.path.join(base, n)
            with open(p, encoding="utf-8", errors="replace") as f:
                body = f.read()
            low = body.lower()
            hit = bool(PERSONAL.search(body)) or any(t.lower() in low for t in targets)
            if hit:
                leaks.append(os.path.relpath(p, export))
    add("no personal or BCONF path in the exported text", not leaks, leaks or "none")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", required=True)
    ap.add_argument("--bconf", required=True)
    ap.add_argument("--rows", type=int, default=2470)
    ap.add_argument("--scientific-failures", type=int, default=30)
    ap.add_argument("--guarantee-failures", type=int, default=0)
    ap.add_argument("--guarantee-rows", type=int, default=1100)
    a = ap.parse_args(argv)
    results = check(a.export, a.bconf, a.rows, a.scientific_failures, a.guarantee_failures, a.guarantee_rows)
    lines = ["{:4}  {}  ->  {}".format(*r) for r in results]
    fails = sum(1 for r in results if r[0] == "FAIL")
    lines.append("{} check(s), {} failed".format(len(results), fails))
    text = "\n".join(lines) + "\n"
    with open(os.path.join(a.export, "check_export.txt"), "x", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(text, end="")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
