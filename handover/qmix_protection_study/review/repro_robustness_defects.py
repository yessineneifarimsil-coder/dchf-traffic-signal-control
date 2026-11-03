"""Reproduce review points 2-4 on the robustness tools of a given version (synthetic data, no SUMO).

    python repro_robustness_defects.py <dir holding robustness_analysis.py and robustness_runner.py> <study dir>

<study dir> provides tools/ablation_metrics.py, tools/robustness/scenario_traffic.py and the synthetic World of
tests/test_robustness_analysis.py. Prints REPRODUIT / NON REPRODUIT per point.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import types
from contextlib import redirect_stdout

VERSION, STUDY = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path[:0] = [VERSION, os.path.join(STUDY, "tools", "robustness"), os.path.join(STUDY, "tools"),
                os.path.join(STUDY, "tests")]
import robustness_analysis as ra  # noqa: E402
import robustness_runner as rr  # noqa: E402
import test_robustness_analysis as T  # noqa: E402
assert os.path.dirname(os.path.abspath(ra.__file__)) == VERSION, ra.__file__
assert os.path.dirname(os.path.abspath(rr.__file__)) == VERSION, rr.__file__

results = {}
base = tempfile.mkdtemp()

# Point 2: one "both" cell declared missing; S1 must not conclude for that scenario.
w = T.World(os.path.join(base, "p2"))
gone = ("R0_reference", 8001, "learned:both", "qmix_seed101_t350000")
w.fill({gone: "skip"})
directory = os.path.join("cells", "R0_reference", "8001", "qmix_seed101_t350000", "both")
out = os.path.join(base, "p2_out")
summary2 = ra.analyse(w.root, out, declared_missing=[directory])
checks = json.load(open(os.path.join(out, "technical_checks.json")))
s1 = json.load(open(os.path.join(out, "s1_service.json")))
report = open(os.path.join(out, "REPORT.md")).read()
allowed = s1["R0_reference"]["S1_statement_allowed"]
print("2. cellule 'both' declaree manquante : all_ok={}, S1_statement_allowed(R0)={}, rapport INCOMPLET={}".format(
    checks.get("all_ok"), allowed, "INCOMPLET" in report or "INCOMPLETE" in report))
results[2] = bool(checks.get("all_ok")) and bool(allowed)

# Point 3: two truncated evaluation_metrics.json counted as finished; run skips them.
root = os.path.join(base, "p3")
cells = [{"scenario": "R0_reference", "seed": 8001, "controller": "fixed:old_C19_8_5_D9",
          "directory": os.path.join("cells", "R0_reference", "8001", "fixed__old_C19_8_5_D9")},
         {"scenario": "R0_reference", "seed": 8002, "controller": "fixed:old_C19_8_5_D9",
          "directory": os.path.join("cells", "R0_reference", "8002", "fixed__old_C19_8_5_D9")}]
plan = {"fingerprint": "f" * 64, "cells": cells, "n_cells": 2, "root": root, "models": []}
for c in cells:
    os.makedirs(os.path.join(root, c["directory"]))
    with open(os.path.join(root, c["directory"], "evaluation_metrics.json"), "w") as h:
        h.write('{"clearance_status": "CLEA')
with open(os.path.join(root, "plan.json"), "w") as h:
    json.dump(plan, h)
buf = io.StringIO()
with redirect_stdout(buf):
    code = rr.progress(root)
evaluated = []
sys.modules["evaluate_any"] = types.SimpleNamespace(
    evaluate=lambda *a, **k: evaluated.append(a) or {"clearance_status": "CLEARED"})
saved = rr.build_plan
rr.build_plan = lambda r: (dict(plan), [], [])
try:
    with redirect_stdout(io.StringIO()) as run_out:
        run_code = rr.run(root, "0/1")
except Exception as error:  # noqa: BLE001
    run_code = "exception {!r}".format(error)
finally:
    rr.build_plan = saved
print("3. deux metriques tronquees : progress -> {!r} code {} ; run -> code {}, evaluations relancees {}".format(
    buf.getvalue().strip(), code, run_code, len(evaluated)))
results[3] = code == 0

# Point 4: a guarantee intervention during the demand in a "both" run labels the guarantee cost EVALUATED.
w = T.World(os.path.join(base, "p4"))
key = ("R0_reference", 8001, "learned:both", "qmix_seed101_t350000")
w.fill({key: {"interventions": [(1200, "guarantee"), (1250, "min_green")]}})
out = os.path.join(base, "p4_out")
ra.analyse(w.root, out)
s3 = json.load(open(os.path.join(out, "s3_costs.json")))
row = [r for r in s3 if r["scenario"] == "R0_reference" and r["method"] == "qmix" and r["arm"] == "both"][0]
print("4. bras 'both' avec garantie active pendant la demande : guarantee_cost_during_demand = {!r}".format(
    row["guarantee_cost_during_demand"]))
results[4] = row["guarantee_cost_during_demand"].startswith("EVALUATED")

shutil.rmtree(base)
print("")
for k in (2, 3, 4):
    print("point {} : {}".format(k, "REPRODUIT" if results[k] else "NON REPRODUIT"))
