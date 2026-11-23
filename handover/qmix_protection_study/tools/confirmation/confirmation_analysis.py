"""Pre-registered analysis of the confirmation study (plan B). Written before any confirmation run.

    python tools/confirmation/confirmation_analysis.py --cells <confirmation cells.csv> ^
        --margins <margins.json> --statistics <statistics.py of A004> --out analysis/confirmation

Input cells.csv: one row per evaluation with scenario, seed, controller (learned:<arm> or the comparator name of
the plan), model ('' for comparators), method, status, J_primary_s, open_wait_at_end_s. margins.json: the
validation J of each profile's primary comparator, written at the freeze. The decision rules, their order, the
margin rule delta = max(0.05 x J_val, 0.10 s), the intervals and the bootstrap are those of confirmation_plan.json,
whose fingerprint is checked. The bootstrap is paired_crossed_bootstrap of the A004 module (statistics-1.2),
loaded from --statistics and refused unless its file SHA-256 equals --statistics-sha256 (recorded in B's
freeze.json); it is never copied. b_runner.py analyse calls this module with the frozen values.
"""
from __future__ import absolute_import, division, print_function

import argparse
import csv
import hashlib
import importlib.util
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


class PlanError(RuntimeError):
    pass


def plan_fingerprint(plan):
    return hashlib.sha256(json.dumps(dict((k, v) for k, v in plan.items() if k != "fingerprint"),
                                     sort_keys=True).encode()).hexdigest()


def check_plan(plan):
    if plan.get("fingerprint") != plan_fingerprint(plan):
        raise PlanError("confirmation_plan.json differs from its fingerprint")
    return True


def load_statistics(path, plan, expected_sha256=None):
    """Load the frozen statistics module by path, refused unless its file SHA-256 is the expected one.

    The plan's reference protocol_hash (8b6413a9...) is amendment003.protocol_hashes()['statistics_1_2'], a hash of
    a canonical JSON, not of a file (PROTOCOL_AMENDMENT_B.md section 4). The file SHA-256 is recorded in B's
    freeze.json; it is given here as expected_sha256 (b_runner passes it), or read from the plan's
    reference.module_file_sha256 when that holds a 64-hex digest."""
    expected = expected_sha256 or plan["statistics"]["reference"].get("module_file_sha256", "")
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise PlanError("no file SHA-256 for the statistics module (it is recorded in freeze.json; pass it)")
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != expected:
        raise PlanError("statistics module {} has SHA-256 {}, expected {} ({})".format(
            path, digest, expected, plan["statistics"]["reference"]["name"]))
    spec = importlib.util.spec_from_file_location("a004_statistics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def margin(plan, j_val):
    rule = plan["statistics"]["equivalence_margin"]
    return max(rule["relative"] * float(j_val), rule["floor_s"])


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


def compare(plan, cells, profile, method, arm, comparator, confidence, delta, decide, ST):
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
        if decide:
            b95 = ST.paired_crossed_bootstrap(panel, cvalues, replicates=plan["statistics"]["replicates"],
                                              confidence=plan["statistics"]["descriptive_confidence"],
                                              comparator_kind=ST.COMPARATOR_DETERMINISTIC)
            out["ci_95"] = [b95["ci_low"], b95["ci_high"]]
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


def guarantee_minus_none(plan, cells, profile, method, ST):
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


UNIT_ASSUMPTIONS = (
    "Counts are reported for every group, stratified by profile, with the expected count of the plan. Evaluations "
    "are NOT independent: the same models are evaluated on the same traffics, so no interval is computed on pooled "
    "evaluations. Two units are used instead, each with its own denominator and assumption. Model level: k = models "
    "with at least one event out of the models of the group (10); the 10 training seeds are treated as independent "
    "draws of the training procedure, conditional on these traffics. Traffic level: k = traffics with at least one "
    "event out of the traffics of the group (10 per profile); the traffics are treated as independent draws of the "
    "profile generator, conditional on these models. Exact Clopper-Pearson: a TWO-SIDED 95 % interval and, "
    "separately, a ONE-SIDED 95 % upper bound. They bound the share of models (or traffics) with at least one event, "
    "not a per-vehicle or per-run failure probability. Neither is a reliability guarantee, and zero observed events "
    "never establish a zero risk.")


def unit_counts(rows, event, learned=True, intervals=True):
    """Counts of an event at the evaluation, model and traffic levels; unit-level intervals when asked."""
    import clopper_pearson as CP
    out = {"evaluations": len(rows), "events": sum(1 for r in rows if event(r))}
    units = [("traffics", lambda r: (r["scenario"], int(r["seed"])))]
    if learned:
        units.insert(0, ("models", lambda r: r["model"]))
    for name, key in units:
        every = set(key(r) for r in rows)
        hit = set(key(r) for r in rows if event(r))
        unit = {"units": len(every), "units_with_event": len(hit)}
        if every and intervals:
            unit["cp95_two_sided"] = list(CP.clopper_pearson(len(hit), len(every)))
            unit["upper95_one_sided"] = (CP.one_sided_upper_zero(len(every)) if not hit
                                         else CP.clopper_pearson(len(hit), len(every), confidence=0.90)[1])
        out[name] = unit
    return out


def open_wait(r):
    return r["status"] != "CLEARED" and r.get("open_wait_at_end_s") not in (None, "", "None")


def service(cells, plan):
    """Service events of the learned arms, all profiles together: counts at the evaluation / model / traffic levels."""
    out = []
    for method in sorted(set(c.get("method") for c in cells if c["controller"].startswith("learned:"))):
        for arm in ("guarantee", "none"):
            rows = [c for c in cells if c.get("method") == method and c["controller"] == "learned:" + arm]
            if not rows:
                continue
            # the whole design: every policy of the method on all the traffics of the plan (50)
            full = len(rows) == len(plan["learned_policies"].get(method) or []) * sum(
                len(v) for v in plan["traffic_seeds"].values())
            # all profiles together: COUNTS ONLY (intervals are given per profile, never on pooled cells)
            entry = {"method": method, "arm": arm, "profiles": sorted(set(r["scenario"] for r in rows)),
                     "failure": unit_counts(rows, lambda r: r["status"] != "CLEARED", intervals=False),
                     "open_wait_failure": unit_counts(rows, open_wait, intervals=False),
                     "wait_ge_300s": unit_counts(rows, lambda r: int(r.get("vehicles_waiting_ge_300s") or 0) > 0,
                                                 intervals=False),
                     "assumptions": UNIT_ASSUMPTIONS}
            entry["n"] = entry["failure"]["evaluations"]
            entry["failures"] = entry["failure"]["events"]
            entry["open_wait_failures"] = entry["open_wait_failure"]["events"]
            # Observational statement only: "no open-wait failure observed on the whole design" (never "zero risk").
            entry["service_claim_allowed"] = arm == "guarantee" and entry["open_wait_failures"] == 0 and full
            out.append(entry)
    return out


def cleared_pairs(panel_a, panel_b, plan, profile, method):
    """J difference over the (training seed, traffic) pairs where BOTH runs cleared: descriptive and conditional.
    Excluding failures can change the comparison (a method that fails more often loses its hardest traffics)."""
    seeds = sorted(model_seed(t) for t in plan["learned_policies"].get(method) or [])
    traffics = plan["traffic_seeds"][profile]
    diffs = [panel_a[k][j] - panel_b[k][j] for k in seeds for j in traffics
             if j in panel_a.get(k, {}) and j in panel_b.get(k, {})]
    return {"pairs_used": len(diffs), "pairs_expected": len(seeds) * len(traffics),
            "mean_difference": (sum(diffs) / len(diffs)) if diffs else None,
            "status": "descriptive, conditional on both runs clearing; no decision; excluding failures can change "
                      "the comparison"}


def learned_contrast(plan, cells, profile, method, reference, arm, confidence, delta, decide, ST):
    """Joint learner minus independent learner (QMIX - IDQN, VDN - IDQN): crossed bootstrap with a learned
    comparator, paired by training-seed number (statistics-1.1 convention) and by traffic."""
    out = {"profile": profile, "method": method, "reference": reference, "arm": arm, "contrast":
           "{} - {}".format(method, reference), "confidence": confidence, "delta": delta}
    panels, fails, opens, problems = {}, {}, {}, []
    for m in (method, reference):
        rows, panel, failures, open_waits = learned_panel(cells, profile, m, arm)
        tags = plan["learned_policies"].get(m) or []
        if len(tags) != 10:
            problems.append("{}: {} policies in the plan, 10 required (IDQN tags are fixed at the freeze)".format(m, len(tags)))
        want = set((model_seed(t), s) for t in tags for s in plan["traffic_seeds"][profile])
        got = set((model_seed(r["model"]), int(r["seed"])) for r in rows)
        if got != want or len(rows) != len(want):
            problems.append("{}: cells missing {} / unexpected {}".format(m, len(want - got), len(got - want)))
        panels[m], fails[m], opens[m] = panel, failures, open_waits
        out["{}_failures".format(m)] = len(failures)
        out["{}_open_wait_failures".format(m)] = len(open_waits)
    if set(model_seed(t) for t in plan["learned_policies"].get(method) or []) != set(
            model_seed(t) for t in plan["learned_policies"].get(reference) or []):
        problems.append("training seeds of {} and {} differ: no pairing".format(method, reference))
    out["design_problems"] = problems
    if problems:
        out["category"] = "INCOMPLETE (design not met: no decision)"
        return out
    not_estimable = bool(fails[method] or fails[reference])
    if not not_estimable:
        reps = plan["statistics"]["replicates"]
        b = ST.paired_crossed_bootstrap(panels[method], panels[reference], replicates=reps, confidence=confidence,
                                        comparator_kind=ST.COMPARATOR_LEARNED)
        b95 = ST.paired_crossed_bootstrap(panels[method], panels[reference], replicates=reps,
                                          confidence=plan["statistics"]["descriptive_confidence"],
                                          comparator_kind=ST.COMPARATOR_LEARNED)
        out.update({"mean_difference": b["observed_mean_difference"], "ci": [b["ci_low"], b["ci_high"]],
                    "ci_95": [b95["ci_low"], b95["ci_high"]],
                    "per_training_seed_difference": dict(zip(b["training_seeds"], b["per_training_seed_difference"]))})
    out["conditional_descriptive_cleared_pairs"] = cleared_pairs(panels[method], panels[reference], plan, profile, method)
    if decide:
        low, high = out.get("ci", [float("nan"), float("nan")])
        service_failure = bool(opens[method] or opens[reference])
        out["category"] = classify(low, high, delta, service_failure, not_estimable)
    return out


def check_family(plan):
    """One confirmatory family of 12 contrasts, every decision at the same Bonferroni level 1 - 0.05/12."""
    fam = plan["statistics"]["confirmatory_family"]
    level = 1.0 - fam["familywise_alpha"] / float(fam["size"])
    lc = plan.get("learned_contrasts") or {}
    got = [plan["statistics"]["decision_confidence"]] + ([lc["decision_confidence"]] if lc else [])
    if fam["size"] != 12 or any(abs(g - level) > 1e-12 for g in got):
        raise PlanError("decision levels {} differ from the family level {} (size {})".format(got, level, fam["size"]))
    return level


def analyse(plan, cells, margins, ST):
    check_plan(plan)
    check_family(plan)
    st = plan["statistics"]
    primary, secondary = [], []
    for profile in plan["profiles"]:
        delta = margin(plan, margins[profile])
        main = plan["comparators"]["primary_controller_label"][profile]
        if main.startswith("auto"):
            raise PlanError("primary comparator of {} not resolved (B1 is resolved at the freeze)".format(profile))
        for method in METHODS:
            primary.append(compare(plan, cells, profile, method, PRIMARY_ARM, main,
                                   st["decision_confidence"], delta, True, ST))
            for comparator in sorted(set(c["controller"] for c in cells if c["scenario"] == profile
                                         and not c["controller"].startswith("learned:") and c["controller"] != main)):
                for arm in ("guarantee", "none"):
                    secondary.append(compare(plan, cells, profile, method, arm, comparator,
                                             st["descriptive_confidence"], delta, False, ST))
            secondary.append(compare(plan, cells, profile, method, "none", main,
                                     st["descriptive_confidence"], delta, False, ST))
            secondary.append(guarantee_minus_none(plan, cells, profile, method, ST))
    joint = []
    lc = plan.get("learned_contrasts")
    if lc:
        for profile in lc["profiles"]:
            delta = margin(plan, margins[profile])
            for method in lc["methods"]:
                joint.append(learned_contrast(plan, cells, profile, method, lc["reference"], lc["arm"],
                                              lc["decision_confidence"], delta, True, ST))
    return {"primary": primary, "joint_learning": joint, "secondary_descriptive": secondary,
            "service": service(cells, plan)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cells", required=True)
    ap.add_argument("--margins", required=True)
    ap.add_argument("--statistics", required=True, help="frozen statistics.py, hash-checked")
    ap.add_argument("--statistics-sha256", required=True, help="its file SHA-256 from freeze.json")
    ap.add_argument("--plan", default=os.path.join(HERE, "confirmation_plan.json"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    with open(a.plan) as f:
        plan = json.load(f)
    with open(a.cells) as f:
        cells = list(csv.DictReader(f))
    with open(a.margins) as f:
        margins = json.load(f)
    try:
        result = analyse(plan, cells, margins, load_statistics(a.statistics, plan, a.statistics_sha256))
    except PlanError as error:
        print("STOP:", error)
        return 1
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
