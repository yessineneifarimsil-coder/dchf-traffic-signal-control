"""Exact Clopper-Pearson intervals for the service-failure ("starvation") counts (no simulation, stdlib only).

    python tools/article_analyses/clopper_pearson.py --ablation analysis/ablation/cells.csv --out analysis/cp_ablation
    python tools/article_analyses/clopper_pearson.py --robustness analysis/robustness/cells.csv --out analysis/cp_robustness

Events per evaluation (definitions fixed here, applied identically to every group):
  failure        clearance failure (status != CLEARED);
  open_wait      clearance failure with a service counter still open at the end (indefinite denial of service);
  wait_ge_300s   at least one vehicle with waitingTime >= 300 s (robustness: vehicles_waiting_ge_300s > 0;
                 ablation: max_vehicle_waiting_s >= 300).
Groups: ablation (method, arm); robustness (scenario, method or controller, arm). For each group and event:
k/n, two-sided 95 % Clopper-Pearson interval, and for k = 0 the one-sided 95 % upper bound 1 - 0.05^(1/n).
Evaluations of one model on several traffics are not independent: the interval treats the n evaluations as
independent Bernoulli trials and is therefore a descriptive bound, not an inference on models.
"""
from __future__ import absolute_import, division, print_function

import argparse
import csv
import json
import math
import os
import sys

EVENTS = ("failure", "open_wait", "wait_ge_300s")


def _betacf(a, b, x):
    """Continued fraction of the regularized incomplete beta (modified Lentz)."""
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    raise ArithmeticError("incomplete beta did not converge")


def betainc(a, b, x):
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(p, a, b):
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if betainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson(k, n, confidence=0.95):
    k, n = int(k), int(n)
    if n <= 0 or not 0 <= k <= n:
        raise ValueError("need 0 <= k <= n, n > 0")
    alpha = 1.0 - confidence
    lower = 0.0 if k == 0 else beta_ppf(alpha / 2.0, k, n - k + 1)
    upper = 1.0 if k == n else beta_ppf(1.0 - alpha / 2.0, k + 1, n - k)
    return lower, upper


def one_sided_upper_zero(n, confidence=0.95):
    return 1.0 - (1.0 - confidence) ** (1.0 / int(n))


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def events_of(row, source):
    failure = row.get("status") != "CLEARED"
    open_wait = failure and row.get("open_wait_at_end_s") not in (None, "", "None")
    if source == "robustness":
        wait = (_float(row.get("vehicles_waiting_ge_300s")) or 0) > 0
    else:
        wait = (_float(row.get("max_vehicle_waiting_s")) or 0) >= 300
    return {"failure": failure, "open_wait": open_wait, "wait_ge_300s": wait}


def group_of(row, source):
    if source == "ablation":
        return (row["method"], row["arm"])
    who = row.get("method") or row.get("controller")
    return (row["scenario"], who, row.get("arm") or "")


def table(rows, source, confidence=0.95):
    groups = {}
    for row in rows:
        groups.setdefault(group_of(row, source), []).append(events_of(row, source))
    out = []
    for key in sorted(groups):
        evs = groups[key]
        n = len(evs)
        for event in EVENTS:
            k = sum(1 for e in evs if e[event])
            lo, hi = clopper_pearson(k, n, confidence)
            out.append({"group": " / ".join(str(x) for x in key), "event": event, "k": k, "n": n,
                        "rate": k / float(n), "cp_low": lo, "cp_high": hi,
                        "one_sided_upper_if_zero": one_sided_upper_zero(n, confidence) if k == 0 else None})
    return out


def pooled(rows, source, predicate, label, confidence=0.95):
    evs = [events_of(r, source) for r in rows if predicate(r)]
    out = []
    for event in EVENTS:
        k = sum(1 for e in evs if e[event])
        lo, hi = clopper_pearson(k, len(evs), confidence) if evs else (None, None)
        out.append({"group": label, "event": event, "k": k, "n": len(evs), "cp_low": lo, "cp_high": hi})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ablation")
    ap.add_argument("--robustness")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if bool(a.ablation) == bool(a.robustness):
        ap.error("give exactly one of --ablation / --robustness")
    source = "ablation" if a.ablation else "robustness"
    with open(a.ablation or a.robustness) as f:
        rows = list(csv.DictReader(f))
    result = table(rows, source)
    if source == "ablation":
        result += pooled(rows, source, lambda r: r["arm"] in ("guarantee", "both"), "all methods / guarantee or both")
        result += pooled(rows, source, lambda r: r["arm"] == "none", "all methods / none")
    else:
        result += pooled(rows, source, lambda r: r.get("controller") in ("learned:guarantee", "learned:both"),
                         "all scenarios / learned guarantee or both")
        result += pooled(rows, source, lambda r: r.get("controller") == "learned:none",
                         "all scenarios / learned none")
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    with open(os.path.join(a.out, "clopper_pearson.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "event", "k", "n", "rate", "cp_low", "cp_high",
                                          "one_sided_upper_if_zero"], extrasaction="ignore")
        w.writeheader()
        w.writerows(result)
    with open(os.path.join(a.out, "clopper_pearson.json"), "w") as f:
        json.dump({"source": source, "input": os.path.abspath(a.ablation or a.robustness), "confidence": 0.95,
                   "rows": result}, f, indent=1)
    for r in result:
        if r["k"] or r["group"].startswith("all"):
            print("{:45} {:13} {:>3}/{:<4} [{:.4f}, {:.4f}]".format(r["group"], r["event"], r["k"], r["n"],
                                                                   r["cp_low"], r["cp_high"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
