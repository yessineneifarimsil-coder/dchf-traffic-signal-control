"""Independent re-estimation of the 12 confirmatory contrasts of campaign B from B_episodes.csv (public export).

    python reestimate_B.py --episodes B_episodes.csv --margins B_margins.json --statistics <frozen statistics.py>
                           --out <folder> [--frozen-decisions <analysis\\confirmation\\decisions.csv>] [--sensitivity]

Inputs. The values come ONLY from B_episodes.csv. B_margins.json is the verbatim copy of <BCONF>/margins.json (sealed
by freeze.json): per profile, the validation J of the primary comparator, delta and the primary label. The bootstrap
is the function ``paired_crossed_bootstrap`` of the frozen statistics module (statistics-1.1, file ed133bb2... once
line endings are normalised), IMPORTED from --statistics, never copied. Python 3.7, numpy; nothing else.

Same procedure as the frozen analysis (b_runner.analyse -> confirmation_analysis.analyse), re-implemented here
independently of that code:
- family of 12: QMIX and VDN with the guarantee minus the primary comparator of each of the 5 profiles (deterministic
  comparator, broadcast per traffic), and QMIX and VDN with the guarantee minus IDQN with the guarantee on R0
  (learned comparator, paired by training-seed number and traffic);
- decision intervals at 1 - 0.05/12, descriptive intervals at 95 %, 10 000 replicates, percentile intervals;
- random seed: the default ``rng_seed`` of paired_crossed_bootstrap, BOOTSTRAP_RNG_NAMESPACE = 0x53544154
  (1398030676), defined in statistics.py (line 78 of the frozen file); the generator is
  PCG64(SeedSequence([rng_seed, rows, columns])). The frozen analysis does not pass rng_seed (confirmation_analysis.py
  calls paired_crossed_bootstrap without it): the seed is the module default; it is not written in results.json;
- delta = max(0.05 x J_val, 0.10 s); the two contrasts against IDQN use the delta of R0;
- rules, in order: SERVICE FAILURE (an open-wait failure in a guarantee arm of the contrast), NOT ESTIMABLE (any
  failure in the contrast), SUPERIOR BEYOND MARGIN (U < -delta), SUPERIOR (U < 0), EQUIVALENT (-delta < L and
  U < delta), INFERIOR BEYOND MARGIN (L > delta), INFERIOR (L > 0), INCONCLUSIVE.

--sensitivity (NOT DECISIONAL: the decisions of B are those of the frozen analysis) writes sensitivity_B.csv:
 a) the same contrasts with 100 000 replicates (default seed), and with 10 000 replicates for 5 other seeds
    (rng_seed = 1398030676 + k, k = 1..5), to measure the numerical stability of the 99.58 % bounds;
 b) QMIX - IDQN and VDN - IDQN with the training seeds resampled INDEPENDENTLY for the two methods (instead of
    pairing them by number), the traffics still crossed and shared: implemented here (the frozen module has no such
    option), 10 000 and 100 000 replicates, generator PCG64(SeedSequence([1398030676, 10, 10, 0x554E50]))
    ("UNP").
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

import numpy as np

REFERENCE_LF_SHA256 = "ed133bb26705f9f6ad245e45d9eaef2c1dd464de8bfa0c46e1c4f68e88aa9a7a"
PROFILES = ("R0_reference", "R1_sparse_secondary_heavy_main", "R2_single_secondary_trickle", "R3_time_varying",
            "R4_isolated_tail")
METHODS = ("qmix", "vdn")
ARM = "guarantee"
REFERENCE = "idqn"
JOINT_PROFILE = "R0_reference"
FAMILY_SIZE, FAMILY_ALPHA = 12, 0.05
DECISION = 1.0 - FAMILY_ALPHA / FAMILY_SIZE
DESCRIPTIVE = 0.95
REPLICATES = 10000
SENSITIVITY_REPLICATES = 100000
SENSITIVITY_SEEDS = (1, 2, 3, 4, 5)
RELATIVE, FLOOR_S = 0.05, 0.10
TRAINING_SEEDS = tuple(range(101, 111))
FIELDS = ["question", "profile", "method", "against", "mean_difference_s", "ci_decision_low", "ci_decision_high",
          "decision_confidence", "family", "ci_95_low", "ci_95_high", "delta_s", "decision"]
NUMERIC = ("mean_difference_s", "ci_decision_low", "ci_decision_high", "decision_confidence", "ci_95_low",
           "ci_95_high", "delta_s")
Q_CLASSICAL, Q_JOINT = "learned vs classical", "joint vs independent (IDQN)"
FAMILY_TEXT = "Bonferroni over 12 (1 - 0.05/12)"


class ReestimationError(Exception):
    pass


def load_statistics(path):
    with open(path, "rb") as f:
        raw = f.read()
    lf = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    if lf != REFERENCE_LF_SHA256:
        raise ReestimationError("{} is not the frozen statistics module (sha256 after CRLF->LF {}, expected {})".format(
            path, lf, REFERENCE_LF_SHA256))
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("frozen_statistics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, hashlib.sha256(raw).hexdigest()


def read_episodes(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def classify(low, high, delta, service_failure=False, not_estimable=False):
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


def is_failure(r):
    return r["status"] != "CLEARED" or not finite(r["J_s"])


def learned_panel(rows, profile, method, arm):
    sel = [r for r in rows if r["profile"] == profile and r["controller_kind"] == "learned" and r["method"] == method
           and r["arm"] == arm]
    panel, failures, open_waits = {}, [], []
    for r in sel:
        key = (int(r["training_seed"]), int(r["traffic_seed"]))
        if is_failure(r):
            failures.append(key)
            if r["open_wait_at_end"] not in ("", "None"):
                open_waits.append(key)
            continue
        panel.setdefault(key[0], {})[key[1]] = float(r["J_s"])
    return sel, panel, failures, open_waits


def comparator_values(rows, profile, label):
    sel = [r for r in rows if r["profile"] == profile and r["controller_kind"] != "learned"
           and label in r["comparator_labels"].split(";")]
    values, failures = {}, []
    for r in sel:
        if is_failure(r):
            failures.append(int(r["traffic_seed"]))
        else:
            values[int(r["traffic_seed"])] = float(r["J_s"])
    return sel, values, failures


def traffic_seeds(rows, profile):
    return sorted(set(int(r["traffic_seed"]) for r in rows if r["profile"] == profile))


def design_problems(sel, profile_seeds, expected_rows=None):
    want = set((m, s) for m in TRAINING_SEEDS for s in profile_seeds)
    got = [(int(r["training_seed"]), int(r["traffic_seed"])) for r in sel]
    problems = []
    if set(got) != want or len(got) != len(want):
        problems.append("cells missing {} / unexpected {} / duplicated {}".format(
            len(want - set(got)), len(set(got) - want), len(got) - len(set(got))))
    return problems


def margins_of(path):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    out = {}
    for p in PROFILES:
        j_val = float(m[p]["validation_J"])
        delta = max(RELATIVE * j_val, FLOOR_S)
        if "delta_s" in m[p] and abs(float(m[p]["delta_s"]) - delta) > 1e-12:
            raise ReestimationError("delta of {} in margins.json ({}) differs from the rule ({})".format(
                p, m[p]["delta_s"], delta))
        out[p] = {"delta": delta, "primary": m[p]["primary"], "validation_J": j_val}
    return out


def bootstrap(ST, a, b, kind, replicates=None, rng_seed=None):
    replicates = REPLICATES if replicates is None else replicates
    kw = {} if rng_seed is None else {"rng_seed": rng_seed}
    d = ST.paired_crossed_bootstrap(a, b, replicates=replicates, confidence=DECISION, comparator_kind=kind, **kw)
    d95 = ST.paired_crossed_bootstrap(a, b, replicates=replicates, confidence=DESCRIPTIVE, comparator_kind=kind, **kw)
    return d["observed_mean_difference"], (d["ci_low"], d["ci_high"]), (d95["ci_low"], d95["ci_high"])


def contrasts(rows, margins):
    """The 12 contrasts: (question, profile, method, against, kind, data) with the data needed by the bootstrap."""
    out = []
    for profile in PROFILES:
        seeds = traffic_seeds(rows, profile)
        label = margins[profile]["primary"]
        for method in METHODS:
            sel, panel, fails, opens = learned_panel(rows, profile, method, ARM)
            csel, cvalues, cfails = comparator_values(rows, profile, label)
            problems = design_problems(sel, seeds)
            if sorted(int(r["traffic_seed"]) for r in csel) != seeds:
                problems.append("comparator {} does not cover the {} traffics once each".format(label, len(seeds)))
            out.append({"question": Q_CLASSICAL, "profile": profile, "method": method, "against": label,
                        "kind": "deterministic", "a": panel, "b": cvalues, "delta": margins[profile]["delta"],
                        "service_failure": bool(opens), "not_estimable": bool(fails or cfails), "problems": problems,
                        "failures": len(fails) + len(cfails)})
    seeds = traffic_seeds(rows, JOINT_PROFILE)
    ref_sel, ref_panel, ref_fails, ref_opens = learned_panel(rows, JOINT_PROFILE, REFERENCE, ARM)
    for method in METHODS:
        sel, panel, fails, opens = learned_panel(rows, JOINT_PROFILE, method, ARM)
        problems = design_problems(sel, seeds) + ["IDQN: " + p for p in design_problems(ref_sel, seeds)]
        out.append({"question": Q_JOINT, "profile": JOINT_PROFILE, "method": method, "against": REFERENCE,
                    "kind": "learned", "a": panel, "b": ref_panel, "delta": margins[JOINT_PROFILE]["delta"],
                    "service_failure": bool(opens or ref_opens), "not_estimable": bool(fails or ref_fails),
                    "problems": problems, "failures": len(fails) + len(ref_fails)})
    return out


def kind_constant(ST, kind):
    return ST.COMPARATOR_LEARNED if kind == "learned" else ST.COMPARATOR_DETERMINISTIC


def estimate(rows, margins, ST):
    results = []
    for c in contrasts(rows, margins):
        r = dict((k, c[k]) for k in ("question", "profile", "method", "against"))
        r.update({"decision_confidence": DECISION, "family": FAMILY_TEXT, "delta_s": c["delta"]})
        if c["problems"]:
            r.update({"decision": "INCOMPLETE (design not met: no decision)", "problems": "; ".join(c["problems"])})
        elif c["not_estimable"]:
            r["decision"] = classify(float("nan"), float("nan"), c["delta"], c["service_failure"], True)
        else:
            mean, ci, ci95 = bootstrap(ST, c["a"], c["b"], kind_constant(ST, c["kind"]))
            r.update({"mean_difference_s": mean, "ci_decision_low": ci[0], "ci_decision_high": ci[1],
                      "ci_95_low": ci95[0], "ci_95_high": ci95[1],
                      "decision": classify(ci[0], ci[1], c["delta"], c["service_failure"], False)})
        results.append(r)
    return results


def unpaired(c, replicates, extra=0x554E50, namespace=0x53544154):
    """Sensitivity b: training seeds of the two methods resampled independently; traffics shared and crossed."""
    seeds = sorted(c["a"])
    traffics = sorted(next(iter(c["a"].values())))
    A = np.array([[c["a"][m][t] for t in traffics] for m in seeds], dtype=np.float64)
    B = np.array([[c["b"][m][t] for t in traffics] for m in sorted(c["b"])], dtype=np.float64)
    rows, cols = A.shape
    gen = np.random.Generator(np.random.PCG64(np.random.SeedSequence([namespace, rows, cols, extra])))
    means = np.empty(int(replicates))
    for i in range(int(replicates)):
        ra = gen.integers(0, rows, size=rows)
        rb = gen.integers(0, B.shape[0], size=B.shape[0])
        cc = gen.integers(0, cols, size=cols)
        means[i] = A[np.ix_(ra, cc)].mean() - B[np.ix_(rb, cc)].mean()

    def ci(level):
        alpha = (1.0 - level) / 2.0
        return float(np.percentile(means, 100 * alpha)), float(np.percentile(means, 100 * (1 - alpha)))
    return float(A.mean() - B.mean()), ci(DECISION), ci(DESCRIPTIVE)


def sensitivity(rows, margins, ST):
    out = []
    base = ST.BOOTSTRAP_RNG_NAMESPACE
    big, seeds_k = SENSITIVITY_REPLICATES, SENSITIVITY_SEEDS
    for c in contrasts(rows, margins):
        if c["problems"] or c["not_estimable"]:
            continue
        runs = [("a_replicates_{}".format(big), big, base)] + [("a_seed_+{}".format(k), REPLICATES, base + k) for k in seeds_k]
        for name, reps, seed in runs:
            mean, ci, ci95 = bootstrap(ST, c["a"], c["b"], kind_constant(ST, c["kind"]), reps, seed)
            out.append(dict(analysis=name, replicates=reps, rng_seed=seed, mean=mean, ci=ci, ci95=ci95, c=c))
        if c["kind"] == "learned":
            for reps in (REPLICATES, big):
                mean, ci, ci95 = unpaired(c, reps)
                out.append(dict(analysis="b_unpaired_training_seeds", replicates=reps,
                                rng_seed="SeedSequence([{}, 10, 10, 0x554E50])".format(base), mean=mean, ci=ci,
                                ci95=ci95, c=c))
    rows_out = []
    for s in out:
        c = s["c"]
        rows_out.append({"analysis": s["analysis"], "status": "NOT DECISIONAL (sensitivity)", "question": c["question"],
                         "profile": c["profile"], "method": c["method"], "against": c["against"],
                         "replicates": s["replicates"], "rng_seed": s["rng_seed"], "mean_difference_s": s["mean"],
                         "ci_decision_low": s["ci"][0], "ci_decision_high": s["ci"][1], "ci_95_low": s["ci95"][0],
                         "ci_95_high": s["ci95"][1], "delta_s": c["delta"],
                         "category_if_these_bounds_were_used": classify(s["ci"][0], s["ci"][1], c["delta"])})
    return rows_out


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def compare(mine, frozen):
    """Text report: max |difference| per numeric column and decision identity, keyed by question/profile/method/against."""
    key = lambda r: (r["question"], r["profile"], r["method"], r["against"])  # noqa: E731
    fz = dict((key(r), r) for r in frozen)
    me = dict((key(r), r) for r in mine)
    lines = ["Re-estimation from B_episodes.csv versus the frozen analysis\\confirmation\\decisions.csv", ""]
    lines.append("contrasts: re-estimated {}, frozen {}, in both {}".format(len(me), len(fz), len(set(me) & set(fz))))
    for k in sorted(set(me) ^ set(fz)):
        lines.append("  ONLY IN {}: {}".format("re-estimation" if k in me else "frozen", " / ".join(k)))
    worst = {}
    for k in sorted(set(me) & set(fz)):
        for col in NUMERIC:
            a, b = me[k].get(col, ""), fz[k].get(col, "")
            if a in ("", None) and b in ("", None):
                continue
            try:
                d = abs(float(a) - float(b))
            except (TypeError, ValueError):
                d = float("inf")
            if d > worst.get(col, (-1.0,))[0]:
                worst[col] = (d, k)
    lines.append("")
    lines.append("maximum absolute difference per column:")
    for col in NUMERIC:
        if col in worst:
            lines.append("  {:20} {!r}  ({})".format(col, worst[col][0], " / ".join(worst[col][1])))
        else:
            lines.append("  {:20} no value in either file".format(col))
    same = [k for k in set(me) & set(fz) if me[k]["decision"] == fz[k]["decision"]]
    lines.append("")
    lines.append("decisions identical: {}/{}".format(len(same), len(set(me) & set(fz))))
    for k in sorted(set(me) & set(fz)):
        flag = "same" if me[k]["decision"] == fz[k]["decision"] else "DIFFERENT"
        lines.append("  {:9} {} | re-estimated {} | frozen {}".format(flag, " / ".join(k), me[k]["decision"], fz[k]["decision"]))
    ok = len(same) == len(fz) == len(me) == FAMILY_SIZE and all(worst.get(c, (0,))[0] <= 1e-9 for c in NUMERIC)
    lines.append("")
    lines.append("VERDICT: {}".format("IDENTICAL (12 decisions, numbers equal to within 1e-9)" if ok else
                                      "DIFFERENCES FOUND (reported above, nothing corrected)"))
    return "\n".join(lines) + "\n", ok


def write_csv(path, fields, rows):
    with open(path, "x", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(dict((k, repr(v) if isinstance(v, float) else v) for k, v in r.items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--margins", required=True)
    ap.add_argument("--statistics", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frozen-decisions")
    ap.add_argument("--sensitivity", action="store_true")
    a = ap.parse_args(argv)
    try:
        ST, raw_sha = load_statistics(a.statistics)
        rows = read_episodes(a.episodes)
        margins = margins_of(a.margins)
        results = estimate(rows, margins, ST)
        write_csv(os.path.join(a.out, "reestimate_B.csv"), FIELDS + ["problems"], results)
        for r in results:
            print("[family of 12] {:28} {:32} {:5} vs {:24} {}".format(r["question"], r["profile"], r["method"],
                                                                     r["against"], r["decision"]))
        code = 0
        if a.frozen_decisions:
            text, ok = compare(results, read_csv(a.frozen_decisions))
            text = ("statistics module: raw sha256 {}, identical to the reference {} after CRLF->LF\n"
                    "bootstrap seed: default rng_seed of paired_crossed_bootstrap = BOOTSTRAP_RNG_NAMESPACE = {} "
                    "(0x53544154), replicates {}\n\n").format(raw_sha, REFERENCE_LF_SHA256, ST.BOOTSTRAP_RNG_NAMESPACE,
                                                            REPLICATES) + text
            with open(os.path.join(a.out, "reestimation_vs_frozen.txt"), "x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(text.strip().splitlines()[-1])
            code = 0 if ok else 4
        if a.sensitivity:
            srows = sensitivity(rows, margins, ST)
            write_csv(os.path.join(a.out, "sensitivity_B.csv"),
                      ["analysis", "status", "question", "profile", "method", "against", "replicates", "rng_seed",
                       "mean_difference_s", "ci_decision_low", "ci_decision_high", "ci_95_low", "ci_95_high", "delta_s",
                       "category_if_these_bounds_were_used"], srows)
            print("sensitivity_B.csv: {} rows (NOT DECISIONAL)".format(len(srows)))
        return code
    except (ReestimationError, OSError, KeyError, ValueError) as error:
        print("STOP:", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
