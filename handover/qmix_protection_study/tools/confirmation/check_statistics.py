"""Check the A004 statistics module (statistics-1.2) and compare its crossed bootstrap with the frozen one.

    python tools/confirmation/check_statistics.py --a004 <path to the statistics.py of A004> --out logs\\check_statistics.json

1. The file must have SHA-256 8b6413a9ccffa2bbbcf0d3cfdde6c7460b4785193aa419f7d4725885dc38437a (statistics-1.2,
   the reference named by the decision of 2026-11-07); otherwise exit 2 and nothing else is trusted.
2. It is loaded from its path and compared with the frozen module of commit 8c14f32 (statistics-1.1, the version
   cited by the comparison summaries): protocol version, design constants, the source of
   paired_crossed_bootstrap and of every function it calls, its signature.
3. Numerical check: both modules run on the same synthetic crossed panels (10 x 10; deterministic and learned
   comparators; 95 % and 99.5 %; 10,000 replicates) and the outputs are compared exactly.
Verdict: IDENTICAL_BOOTSTRAP (same numbers to the last bit) or DIFFERENT_BOOTSTRAP (listed). In both cases the
confirmation analysis uses the A004 module itself (confirmation_analysis.py --statistics, hash-checked).
"""
from __future__ import absolute_import, print_function

import argparse
import difflib
import hashlib
import importlib.util
import inspect
import json
import os
import sys

REFERENCE_SHA256 = "8b6413a9ccffa2bbbcf0d3cfdde6c7460b4785193aa419f7d4725885dc38437a"
PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")
FUNCTIONS = ("paired_crossed_bootstrap", "difference_matrix", "replicate_indices", "crossed_replicate_mean",
             "_check_panel", "_as_matrix", "_looks_deterministic", "_finite", "assert_official_panel")
CONSTANTS = ("PROTOCOL_VERSION", "RESAMPLING_DESIGN", "BOOTSTRAP_REPLICATES", "BOOTSTRAP_RNG_NAMESPACE",
             "CONFIDENCE_LEVEL", "COMPARATOR_LEARNED", "COMPARATOR_DETERMINISTIC")


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def panels():
    import numpy as np
    rng = np.random.Generator(np.random.PCG64(20261107))
    models, traffics = list(range(101, 111)), [8051 + k for k in range(10)]
    treat = dict((m, dict((t, float(3 + rng.normal(0, 0.4))) for t in traffics)) for m in models)
    learned = dict((m, dict((t, float(3.1 + rng.normal(0, 0.4))) for t in traffics)) for m in models)
    determ = dict((t, float(3.05 + rng.normal(0, 0.3))) for t in traffics)
    return treat, learned, determ


def run(module, confidence, kind):
    treat, learned, determ = panels()
    comparator = determ if kind == "deterministic" else learned
    ckind = module.COMPARATOR_DETERMINISTIC if kind == "deterministic" else module.COMPARATOR_LEARNED
    return module.paired_crossed_bootstrap(treat, comparator, replicates=10000, confidence=confidence,
                                           comparator_kind=ckind)


def compare(a004, frozen):
    out = {"constants": {}, "functions": {}, "numerical": {}}
    for c in CONSTANTS:
        va, vf = getattr(a004, c, "<absent>"), getattr(frozen, c, "<absent>")
        out["constants"][c] = {"a004": va, "frozen_8c14f32": vf, "identical": va == vf}
    for f in FUNCTIONS:
        fa, ff = getattr(a004, f, None), getattr(frozen, f, None)
        if fa is None or ff is None:
            out["functions"][f] = {"identical": False, "note": "absent in {}".format("A004" if fa is None else "frozen")}
            continue
        sa, sf = inspect.getsource(fa), inspect.getsource(ff)
        diff = list(difflib.unified_diff(sf.splitlines(), sa.splitlines(), "frozen", "a004", lineterm="", n=0))
        out["functions"][f] = {"identical": sa == sf, "diff": diff[:60]}
    out["signature"] = {"a004": str(inspect.signature(a004.paired_crossed_bootstrap)),
                        "frozen_8c14f32": str(inspect.signature(frozen.paired_crossed_bootstrap))}
    for confidence in (0.95, 0.995):
        for kind in ("deterministic", "learned"):
            key = "{} {}".format(kind, confidence)
            try:
                ra, rf = run(a004, confidence, kind), run(frozen, confidence, kind)
            except Exception as error:  # noqa: BLE001 - reported, not hidden
                out["numerical"][key] = {"identical": False, "error": repr(error)}
                continue
            fields = ("observed_mean_difference", "ci_low", "ci_high", "per_training_seed_difference",
                      "per_traffic_seed_difference")
            same = all(ra.get(k) == rf.get(k) for k in fields)
            out["numerical"][key] = {"identical": same, "a004": dict((k, ra.get(k)) for k in fields[:3]),
                                     "frozen_8c14f32": dict((k, rf.get(k)) for k in fields[:3])}
    bootstrap_same = (all(v["identical"] for v in out["functions"].values())
                      and all(v["identical"] for v in out["numerical"].values())
                      and all(out["constants"][c]["identical"] for c in CONSTANTS if c != "PROTOCOL_VERSION"))
    out["verdict"] = "IDENTICAL_BOOTSTRAP" if bootstrap_same else "DIFFERENT_BOOTSTRAP"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a004", required=True)
    ap.add_argument("--frozen", default=os.path.join(PROTECTED, "src", "adaptive_qmix", "protocol", "statistics.py"))
    ap.add_argument("--reference-sha256", default=REFERENCE_SHA256)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    digest = sha256(a.a004)
    result = {"a004_path": os.path.abspath(a.a004), "a004_sha256": digest, "reference_sha256": a.reference_sha256,
              "a004_hash_ok": digest == a.reference_sha256, "frozen_path": os.path.abspath(a.frozen),
              "frozen_sha256": sha256(a.frozen)}
    if result["a004_hash_ok"]:
        result.update(compare(load(a.a004, "a004_statistics"), load(a.frozen, "frozen_statistics")))
    else:
        result["verdict"] = "A004_FILE_NOT_VERIFIED"
    text = json.dumps(result, indent=1, default=str)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
    print(json.dumps({k: result.get(k) for k in ("a004_sha256", "a004_hash_ok", "verdict", "signature")}, indent=1))
    return 0 if result["a004_hash_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
