"""Pre-registered analysis of the confirmation study (plan B). Written before any confirmation run.

    python tools/confirmation/confirmation_analysis.py --cells <confirmation cells.csv> ^
        --margins <margins.json> --plan tools/confirmation/confirmation_plan.json --out analysis/confirmation

Input cells.csv: one row per evaluation with scenario, seed, controller (learned:<arm> or the comparator name of
the plan), model ('' for comparators), method, status, J_primary_s, open_wait_at_end_s. margins.json: the
validation J of each profile's selected primary comparator (from the sealed A selections), written at the freeze.
The decision rules, their order, the margin rule, the intervals and the bootstrap are those of
confirmation_plan.json; the bootstrap is the frozen adaptive_qmix.protocol.statistics.paired_crossed_bootstrap
(official=False), imported, never copied.
"""
from __future__ import absolute_import, division, print_function

import argparse
import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")
sys.path.insert(0, os.path.join(PROTECTED, "src"))
sys.path.insert(0, os.path.join(HERE, "..", "article_analyses"))

METHODS = ("qmix", "vdn")
PRIMARY_ARM = "guarantee"


def finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def model_seed(tag):
    return int(tag.split("_seed")[1].split("_")[0])


def classify(low, high, delta, service_failure=False, not_estimable=False):
    """Decision category, in the pre-registered order."""
    if service_failure:
        return "SERVICE FAILURE"
    if not_estimable:
        return "NOT ESTIMABLE"
    if high < -delta:
        return "SUPERIOR BEYOND MARGIN"
    if high < 0:
        return "SUPERIOR"
    if -delta < low and high < delta:
        return "EQUIVALENT"
    if low > delta:
        return "INFERIOR BEYOND MARGIN"
    if low > 0:
        return "INFERIOR"
    return "INCONCLUSIVE"


def learned_panel(cells, profile, method, arm):
    rows = [c for c in cells if c["scenario"] == profile and c.get("method") == method
            and c["controller"] == "learned:" + arm]
    panel, failures, open_waits = {}, [], []
    for r in rows:
        if r["status"] != "CLEARED" or not finite(r["J_primary_s"]):
            failures.append((r["model"], int(r["seed"])))
            if r.get("open_wait_at_end_s") not in (None, "", "None"):
                open_waits.append((r["model"], int(r["seed"])))
            continue
        panel.setdefault(model_seed(r["model"]), {})[int(r["seed"])] = float(r["J_primary_s"])
    return rows, panel, failures, open_waits


def comparator_values(cells, profile, comparator):
    rows = [c for c in cells if c["scenario"] == profile and c["controller"] == comparator]
    values, failures = {}, []
    for r in rows:
        if r["status"] != "CLEARED" or not finite(r["J_primary_s"]):
            failures.append(int(r["seed"]))
        else:
            values[int(r["seed"])] = float(r["J_primary_s"])
    return rows, values, failures


def check_design(plan, profile, rows, comparator_rows, method):
    expected_models = set(model_seed(t) for t in plan["learned_policies"][method])
    expected_seeds = set(plan["traffic_seeds"][profile])
    got = set((model_seed(r["model"]), int(r["seed"])) for r in rows)
    want = set((m, s) for m in expected_models for s in expected_seeds)
    problems = []
    if got != want:
        problems.append("learned cells missing {} / unexpected {}".format(len(want - got), len(got - want)))
    if set(int(r["seed"]) for r in comparator_rows) != expected_seeds or len(comparator_rows) != len(expected_seeds):
        problems.append("comparator cells do not cover exactly the {} confirmation traffics".format(len(expected_seeds)))
    return problems


def compare(plan, cells, profile, method, arm, comparator, confidence, delta, decide):
    from adaptive_qmix.protocol import statistics as ST
    rows, panel, failures, open_waits = learned_panel(cells, profile, method, arm)
    crow, cvalues, cfail = comparator_values(cells, profile, comparator)
    problems = check_design(plan, profile, rows, crow, method)
    out = {"profile": profile, "method": method, "arm": arm, "comparator": comparator,
           "learned_evaluations": len(rows), "learned_failures": len(failures), "open_wait_failures": len(open_waits),
           "comparator_failures": cfail, "design_problems": problems, "confidence": confidence, "delta": delta}
    if problems:
        out["category"] = "INCOMPLETE (design not met: no decision)"
        return out
    service_failure = decide and bool(open_waits)
    not_estimable = bool(failures) or bool(cfail)
    if not not_estimable:
        b = ST.paired_crossed_bootstrap(panel, cvalues, replicates=plan["statistics"]["replicates"],
                                        confidence=confidence, comparator_kind=ST.COMPARATOR_DETERMINISTIC)
        out.update({"mean_difference": b["observed_mean_difference"], "ci": [b["ci_low"], b["ci_high"]],
                    "comparator_mean_J": sum(cvalues.values()) / len(cvalues),
                    "per_model_difference": dict(zip(b["training_seeds"], b["per_training_seed_difference"]))})
    else:
        bad_models = set(model_seed(m) for m, _s in failures)
        keep = dict((m, v) for m, v in panel.items() if m not in bad_models and len(v) == len(plan["traffic_seeds"][profile]))
        cols = [s for s in plan["traffic_seeds"][profile] if s not in cfail]
        if keep and cols:
            sub = dict((m, dict((s, v[s]) for s in cols)) for m, v in keep.items())
            b = ST.paired_crossed_bootstrap(sub, dict((s, cvalues[s]) for s in cols), replicates=plan["statistics"]["replicates"],
                                            confidence=plan["statistics"]["descriptive_confidence"],
                                            comparator_kind=ST.COMPARATOR_DETERMINISTIC)
            out["sensitivity_descriptive_only"] = {"models_kept": sorted(keep), "traffics_kept": cols,
                                                   "mean_difference": b["observed_mean_difference"],
                                                   "ci_95": [b["ci_low"], b["ci_high"]]}
    if decide:
        low, high = out.get("ci", [float("nan"), float("nan")])
        out["category"] = classify(low, high, delta, service_failure, not_estimable)
    return out


def guarantee_minus_none(plan, cells, profile, method):
    from adaptive_qmix.protocol import statistics as ST
    gr, g, gf, _o = learned_panel(cells, profile, method, "guarantee")
    nr, n, nf, _o = learned_panel(cells, profile, method, "none")
    seeds = plan["traffic_seeds"][profile]
    want = set((model_seed(t), s) for t in plan["learned_policies"][method] for s in seeds)
    for rows in (gr, nr):
        if set((model_seed(r["model"]), int(r["seed"])) for r in rows) != want or len(rows) != len(want):
            return {"profile": profile, "method": method, "contrast": "guarantee - none",
                    "category": "INCOMPLETE (design not met: no estimate)"}
    if gf or nf:
        return {"profile": profile, "method": method, "contrast": "guarantee - none", "category": "NOT ESTIMABLE",
                "failures_guarantee": len(gf), "failures_none": len(nf)}
    b = ST.paired_crossed_bootstrap(g, n, replicates=plan["statistics"]["replicates"],
                                    confidence=plan["statistics"]["descriptive_confidence"],
                                    comparator_kind=ST.COMPARATOR_LEARNED)
    return {"profile": profile, "method": method, "contrast": "guarantee - none (effect of the guarantee alone)",
            "mean_difference": b["observed_mean_difference"], "ci_95": [b["ci_low"], b["ci_high"]]}


def service(cells, plan):
    import clopper_pearson as CP
    out = []
    for method in METHODS:
        for arm in ("guarantee", "none"):
            rows = [c for c in cells if c.get("method") == method and c["controller"] == "learned:" + arm]
            if not rows:
                continue
            opens = sum(1 for r in rows if r["status"] != "CLEARED" and r.get("open_wait_at_end_s") not in (None, "", "None"))
            fails = sum(1 for r in rows if r["status"] != "CLEARED")
            n = len(rows)
            out.append({"method": method, "arm": arm, "n": n, "failures": fails, "open_wait_failures": opens,
                        "open_wait_cp95": list(CP.clopper_pearson(opens, n)),
                        "open_wait_one_sided_upper_if_zero": CP.one_sided_upper_zero(n) if opens == 0 else None,
                        "service_claim_allowed": arm == "guarantee" and opens == 0
                        and n == len(plan["learned_policies"][method]) * sum(len(v) for v in plan["traffic_seeds"].values())})
    return out


def analyse(plan, cells, margins):
    st = plan["statistics"]
    primary, secondary = [], []
    for profile in plan["profiles"]:
        delta = st["equivalence_margin"]["relative"] * float(margins[profile])
        for method in METHODS:
            primary.append(compare(plan, cells, profile, method, PRIMARY_ARM, plan["comparators"]["primary"],
                                   st["decision_confidence"], delta, decide=True))
            for comparator in sorted(set(c["controller"] for c in cells if c["scenario"] == profile
                                         and not c["controller"].startswith("learned:")
                                         and c["controller"] != plan["comparators"]["primary"])):
                for arm in ("guarantee", "none"):
                    secondary.append(compare(plan, cells, profile, method, arm, comparator,
                                             st["descriptive_confidence"], delta, decide=False))
            secondary.append(compare(plan, cells, profile, method, "none", plan["comparators"]["primary"],
                                     st["descriptive_confidence"], delta, decide=False))
            secondary.append(guarantee_minus_none(plan, cells, profile, method))
    return {"primary": primary, "secondary_descriptive": secondary, "service": service(cells, plan)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cells", required=True)
    ap.add_argument("--margins", required=True)
    ap.add_argument("--plan", default=os.path.join(HERE, "confirmation_plan.json"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    with open(a.plan) as f:
        plan = json.load(f)
    with open(a.cells) as f:
        cells = list(csv.DictReader(f))
    with open(a.margins) as f:
        margins = json.load(f)
    result = analyse(plan, cells, margins)
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    with open(os.path.join(a.out, "confirmation_results.json"), "w") as f:
        json.dump(result, f, indent=1, default=str)
    for r in result["primary"]:
        print("{:32} {:5} vs {:8} {:28} {}".format(r["profile"], r["method"], r["comparator"], r["category"],
                                                  r.get("ci")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
