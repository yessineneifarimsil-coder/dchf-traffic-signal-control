"""Resolve the statistical reference of campaign B before its freeze (read-only on every protected folder).

    python -B tools/confirmation/stats_reference.py results  [--statistics <statistics.py>] --out <json>
    python -B tools/confirmation/stats_reference.py inspect-a003 --a003 <A003 folder> --out <json>
    python -B tools/confirmation/stats_reference.py extract-a003 --a003 <A003 folder> --inspection <json> --out <json>
    python -B tools/confirmation/stats_reference.py resolve --root <B root> --procedure b-crossed-bootstrap-1 --results <json>

The procedure retained for B is b-crossed-bootstrap-1: the paired crossed bootstrap of the frozen statistics module
(implementation statistics-1.1), with its synthetic reference results reproduced on the Windows stack. The label
statistics-1.2 is NOT claimed (no equivalence shown); the A003 inspection and extraction below are read-only
diagnostics of that historical reference and cannot change the procedure of B.

results       runs paired_crossed_bootstrap of the given statistics module (default: the frozen one B uses) on fixed
              synthetic panels (deterministic and learned comparators, 95 % and 1 - 0.05/12, 10,000 and 2,000
              replicates, square and rectangular panels) and compares every number with
              tools/confirmation/stats_reference_results.json (computed with the same file in the review copy).
              Module identity: byte-identical to the reference file, or identical after CRLF->LF normalisation (a
              Git checkout on Windows writes CRLF); any other difference fails. The module identity and the numbers
              are reported separately and every difference is printed in full.
              Also checks that a non-finite value is refused (missing data are never resampled). Exit 0 when every
              number is reproduced (tolerance 1e-12), 1 otherwise.
inspect-a003  NO IMPORT. Lists the folder (relative path, size, modification time, SHA-256), reports whether a
              __pycache__ folder exists and what it holds (as observed now: no claim about when or how it was
              created), parses amendment003.py with ast and lists its top-level statements that are not imports,
              definitions or literal assignments (they would run on import), and compares any SHA-256 manifest found
              in the folder with the files present. Never deletes or writes anything in the folder.
extract-a003  (diagnostic of the historical reference) imports amendment003 only after inspect-a003 found no top-level call (or with --accept-top-level-code
              after reading the inspection), in a child process `python -B` with PYTHONDONTWRITEBYTECODE=1, whose
              working folder is a scratch folder; snapshots the A003 folder before and after (a change is reported and
              makes the extraction invalid); records protocol_hashes()['statistics_1_2'] and the module-level objects
              whose canonical JSON (several canonicalisations tried) reproduces that hash.
resolve       writes <B root>\\stats_resolution.json, required by `b_runner.py freeze`, for the only accepted
              procedure b-crossed-bootstrap-1 (paired_crossed_bootstrap of the frozen module, implementation
              statistics-1.1), once its synthetic reference results are reproduced on this machine. Any other
              procedure, including "statistics-1.2", is refused.
"""
from __future__ import absolute_import, division, print_function

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")
REFERENCE_RESULTS = os.path.join(HERE, "stats_reference_results.json")
DECLARED_HASH = "8b6413a9ccffa2bbbcf0d3cfdde6c7460b4785193aa419f7d4725885dc38437a"
FAMILY_LEVEL = 1.0 - 0.05 / 12
PROCEDURES = ("b-crossed-bootstrap-1",)          # the only procedure retained for B
TOLERANCE = 1e-12


class StatsRefError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, payload):
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def default_statistics():
    return os.path.join(PROTECTED, "src", "adaptive_qmix", "protocol", "statistics.py")


def load_module(path):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("b_reference_statistics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Synthetic reference results.
# ---------------------------------------------------------------------------

def panels():
    """Fixed synthetic panels (pure arithmetic, no random generator)."""
    def learned(rows, cols, a, b, c):
        return dict((101 + i, dict((8051 + k, 3.0 + a * ((i * 7 + k * 3) % 11) / 10.0 + b * i / 10.0 + c * k / 10.0)
                                   for k in range(cols))) for i in range(rows))
    t = learned(10, 10, 0.31, -0.05, 0.02)
    r = learned(10, 10, 0.27, 0.03, -0.01)
    det = dict((8051 + k, 3.1 + ((k * 5) % 7) / 20.0) for k in range(10))
    t_rect = learned(10, 6, 0.5, 0.1, -0.2)
    det_rect = dict((8051 + k, 2.9 + k / 25.0) for k in range(6))
    return [("learned_10x10", t, r, "learned"), ("deterministic_10x10", t, det, "deterministic"),
            ("deterministic_10x6", t_rect, det_rect, "deterministic")]


def compute(ST):
    out = {}
    for name, treatment, comparator, kind in panels():
        k = ST.COMPARATOR_LEARNED if kind == "learned" else ST.COMPARATOR_DETERMINISTIC
        for conf in (0.95, FAMILY_LEVEL):
            for reps in (10000, 2000):
                b = ST.paired_crossed_bootstrap(treatment, comparator, replicates=reps, confidence=conf, comparator_kind=k)
                out["{}|{:.12f}|{}".format(name, conf, reps)] = {
                    "observed": b["observed_mean_difference"], "ci_low": b["ci_low"], "ci_high": b["ci_high"],
                    "replicates": b["replicates"], "rows": b["training_seed_count"], "columns": b["evaluation_seed_count"]}
    draws = []
    ST.paired_crossed_bootstrap(panels()[0][1], panels()[0][2], replicates=3, comparator_kind=ST.COMPARATOR_LEARNED,
                                draw_log=draws)
    out["first_draws_learned_10x10"] = draws
    bad = dict((s, dict(v)) for s, v in panels()[0][1].items())
    bad[101][8051] = float("nan")
    try:
        ST.paired_crossed_bootstrap(bad, panels()[0][2], replicates=10, comparator_kind=ST.COMPARATOR_LEARNED)
        out["non_finite_refused"] = False
    except Exception as error:  # noqa: BLE001 - the expected StatisticsError
        out["non_finite_refused"] = type(error).__name__
    return out


def compare(got, ref):
    diffs = []
    for key in sorted(set(got) | set(ref)):
        a, b = got.get(key), ref.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            for f in sorted(set(a) | set(b)):
                x, y = a.get(f), b.get(f)
                if isinstance(x, float) or isinstance(y, float):
                    if x is None or y is None or abs(float(x) - float(y)) > TOLERANCE:
                        diffs.append("{} {}: {!r} vs reference {!r}".format(key, f, x, y))
                elif x != y:
                    diffs.append("{} {}: {!r} vs reference {!r}".format(key, f, x, y))
        elif a != b:
            diffs.append("{}: {!r} vs reference {!r}".format(key, a, b))
    return diffs


def results(statistics, out, write_reference=False):
    path = os.path.abspath(statistics or default_statistics())
    ST = load_module(path)
    got = compute(ST)
    import numpy
    with open(path, "rb") as handle:
        raw = handle.read()
    payload = {"statistics_module": path, "statistics_module_sha256": sha256_file(path),
               "statistics_module_sha256_lf": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
               "statistics_module_crlf_count": raw.count(b"\r\n"),
               "protocol_version": getattr(ST, "PROTOCOL_VERSION", None), "numpy": numpy.__version__,
               "python": platform.python_version(), "platform": platform.platform(), "results": got,
               "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if write_reference:
        write_json(REFERENCE_RESULTS, payload)
        return payload, []
    ref = read_json(REFERENCE_RESULTS)
    # Module identity: the reference is the LF file ed133bb2...; a Git checkout on Windows writes it with CRLF line
    # endings (other bytes, same source). Accepted: byte-identical, or identical once CRLF is turned into LF. Any
    # other content difference is a module difference.
    if payload["statistics_module_sha256"] == ref["statistics_module_sha256"]:
        identity, module_diffs = "byte-identical to the reference file", []
    elif payload["statistics_module_sha256_lf"] == ref["statistics_module_sha256"]:
        identity, module_diffs = ("identical to the reference file after CRLF->LF normalisation ({} CRLF line endings; "
                                  "raw SHA-256 {})".format(payload["statistics_module_crlf_count"],
                                                           payload["statistics_module_sha256"])), []
    else:
        identity = "DIFFERENT from the reference file"
        module_diffs = ["module identity: statistics module {} (after CRLF->LF {}) is not the reference file {}".format(
            payload["statistics_module_sha256"], payload["statistics_module_sha256_lf"], ref["statistics_module_sha256"])]
    number_diffs = ["number: " + d for d in compare(got, ref["results"])]
    diffs = module_diffs + number_diffs
    payload.update({"reference_file": REFERENCE_RESULTS, "reference_sha256": sha256_file(REFERENCE_RESULTS),
                    "reference_environment": {"python": ref["python"], "numpy": ref["numpy"]},
                    "module_identity": identity, "module_differences": module_diffs,
                    "numbers_checked": sum(len(v) if isinstance(v, dict) else 1 for v in got.values()),
                    "number_differences": number_diffs,
                    "differences": diffs, "status": "REPRODUCED" if not diffs else "DIFFERENT"})
    write_json(out, payload)
    return payload, diffs


# ---------------------------------------------------------------------------
# A003, read only.
# ---------------------------------------------------------------------------

def snapshot(folder):
    out = {}
    for a, dirs, files in os.walk(folder):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(a, f)
            st = os.stat(p)
            out[os.path.relpath(p, folder).replace(os.sep, "/")] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                                                                    "sha256": sha256_file(p)}
    return out


SAFE_NODES = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)


def top_level_code(source):
    """Top-level statements that would execute something beyond imports, definitions and literal assignments."""
    risky = []
    for node in ast.parse(source).body:
        if isinstance(node, SAFE_NODES) or (hasattr(ast, "AsyncFunctionDef") and isinstance(node, ast.AsyncFunctionDef)):
            continue
        literal = tuple(getattr(ast, n) for n in ("Str", "Constant") if hasattr(ast, n))
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), literal):
            continue                                    # docstring
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            try:
                ast.literal_eval(node.value)
                continue
            except (ValueError, SyntaxError, TypeError):
                pass
        risky.append({"line": node.lineno, "kind": type(node).__name__})
    return risky


def manifests_in(folder, snap):
    """Text files listing '<sha256> ... <path>' lines; compared with the files present."""
    found = []
    for rel in snap:
        if rel.startswith("__pycache__") or "/__pycache__/" in rel or snap[rel]["size"] > 5 * 1024 * 1024:
            continue
        try:
            with open(os.path.join(folder, rel), encoding="utf-8") as handle:
                text = handle.read()
        except (UnicodeDecodeError, OSError):
            continue
        listed = {}
        for line in text.splitlines():
            m = re.match(r"^\s*([0-9a-f]{64})\s+(?:\d+\s+)?\*?(\S.*?)\s*$", line)
            if m:
                listed[m.group(2).replace("\\", "/")] = m.group(1)
        if len(listed) >= 2:
            present = set(snap)
            found.append({"file": rel, "listed": len(listed),
                          "listed_missing": sorted(p for p in listed if p not in present),
                          "listed_different": sorted(p for p in listed if p in present and snap[p]["sha256"] != listed[p]),
                          "present_not_listed": sorted(p for p in present if p not in listed and p != rel)})
    return found


def inspect_a003(folder, out):
    if not os.path.isdir(folder):
        raise StatsRefError("A003 folder not found: {}".format(folder))
    snap = snapshot(folder)
    pyc = sorted(p for p in snap if p.startswith("__pycache__/") or "/__pycache__/" in p)
    module = os.path.join(folder, "amendment003.py")
    report = {"folder": os.path.abspath(folder), "files": snap, "observed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "pycache": {"exists": bool(pyc) or os.path.isdir(os.path.join(folder, "__pycache__")), "files": pyc,
                          "note": "observed now; this does not establish when or by which command it was created"},
              "amendment003_py": None, "manifests": manifests_in(folder, snap)}
    if os.path.isfile(module):
        with open(module, encoding="utf-8") as handle:
            source = handle.read()
        report["amendment003_py"] = {"sha256": sha256_file(module), "top_level_code": top_level_code(source),
                                     "defines_protocol_hashes": bool(re.search(r"^def protocol_hashes\b", source, re.M))}
    report["effect_on_integrity"] = (
        "a __pycache__ folder changes a directory listing and any integrity check that hashes every file of the folder; "
        "see manifests[].present_not_listed for the manifests found here" if report["pycache"]["exists"]
        else "no __pycache__ folder observed")
    write_json(out, report)
    return report


CHILD = r'''
import hashlib, json, sys
sys.dont_write_bytecode = True
folder, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, folder)
import amendment003 as A
value = A.protocol_hashes()["statistics_1_2"]
def canon(obj):
    forms = {}
    for name, kw in (("sort_keys", dict(sort_keys=True)), ("sort_keys_compact", dict(sort_keys=True, separators=(",", ":"))),
                     ("sort_keys_compact_ascii_off", dict(sort_keys=True, separators=(",", ":"), ensure_ascii=False))):
        try:
            forms[name] = hashlib.sha256(json.dumps(obj, **kw).encode("utf-8")).hexdigest()
        except (TypeError, ValueError):
            pass
    return forms
matches = []
for name in sorted(vars(A)):
    obj = getattr(A, name)
    if isinstance(obj, dict):
        for form, h in canon(obj).items():
            if h == value:
                matches.append({"name": name, "canonical_form": form, "object": obj})
        for key, sub in sorted(obj.items(), key=lambda kv: str(kv[0])):
            if isinstance(sub, dict):
                for form, h in canon(sub).items():
                    if h == value:
                        matches.append({"name": "{}[{!r}]".format(name, key), "canonical_form": form, "object": sub})
json.dump({"statistics_1_2": value, "module_file": A.__file__, "matches": matches}, open(out, "w"), indent=1, default=str)
'''


def extract_a003(folder, inspection, out, accept_top_level=False):
    rep = read_json(inspection)
    if os.path.abspath(rep["folder"]) != os.path.abspath(folder):
        raise StatsRefError("the inspection is of another folder")
    if not rep.get("amendment003_py"):
        raise StatsRefError("amendment003.py not found by the inspection")
    if rep["amendment003_py"]["top_level_code"] and not accept_top_level:
        raise StatsRefError("amendment003.py has top-level code {} that would run on import; read it, then pass "
                            "--accept-top-level-code".format(rep["amendment003_py"]["top_level_code"]))
    before = snapshot(folder)
    if before != rep["files"]:
        raise StatsRefError("the A003 folder changed since the inspection: inspect it again")
    scratch = tempfile.mkdtemp(prefix="a003_extract_")
    try:
        child_out = os.path.join(scratch, "child.json")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, "-B", "-c", CHILD, os.path.abspath(folder), child_out], cwd=scratch,
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        after = snapshot(folder)
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        payload = {"folder": os.path.abspath(folder), "returncode": proc.returncode,
                   "output": proc.stdout.decode("utf-8", "replace")[-4000:], "folder_changed": changed,
                   "declared_hash": DECLARED_HASH}
        if proc.returncode == 0 and os.path.isfile(child_out):
            payload.update(read_json(child_out))
            payload["equal_to_declared"] = payload["statistics_1_2"] == DECLARED_HASH
        payload["valid"] = (proc.returncode == 0 and not changed and payload.get("equal_to_declared") is True)
        write_json(out, payload)
        return payload
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# Resolution (read by b_runner.freeze).
# ---------------------------------------------------------------------------

def resolve(root, procedure, results_path):
    if procedure not in PROCEDURES:
        raise StatsRefError("procedure {!r} refused: the procedure retained for B is b-crossed-bootstrap-1 "
                            "(statistics-1.2 is not claimed)".format(procedure))
    res = read_json(results_path)
    if res.get("status") != "REPRODUCED":
        raise StatsRefError("the synthetic reference results are not reproduced ({}): no resolution".format(res.get("status")))
    payload = {"procedure": procedure, "results": {"path": os.path.abspath(results_path), "sha256": sha256_file(results_path),
                                                   "statistics_module_sha256": res["statistics_module_sha256"],
                                                   "python": res["python"], "numpy": res["numpy"]},
               "resolved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    payload["label"] = ("b-crossed-bootstrap-1: paired_crossed_bootstrap of the frozen statistics module "
                        "(implementation {}), not labelled statistics-1.2".format(res.get("protocol_version")))
    write_json(os.path.join(root, "stats_resolution.json"), payload)
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("results", "inspect-a003", "extract-a003", "resolve", "write-reference"))
    ap.add_argument("--statistics")
    ap.add_argument("--a003")
    ap.add_argument("--inspection")
    ap.add_argument("--accept-top-level-code", action="store_true")
    ap.add_argument("--root")
    ap.add_argument("--procedure")
    ap.add_argument("--results")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if a.action == "write-reference":
            results(a.statistics, None, write_reference=True)
            print("reference written:", REFERENCE_RESULTS)
            return 0
        if a.action == "results":
            payload, diffs = results(a.statistics, a.out or os.path.join("logs", "stats_reference_check.json"))
            print("module identity: {}".format(payload["module_identity"]))
            for d in diffs:                                             # every difference, in full
                print("DIFFERENT:", d)
            print("{}: module identity {} | numbers: {} checked, {} differing (numpy {}, python {})".format(
                payload["status"], "OK" if not payload["module_differences"] else "DIFFERENT",
                payload["numbers_checked"], len(payload["number_differences"]), payload["numpy"], payload["python"]))
            return 0 if not diffs else 1
        if a.action == "inspect-a003":
            rep = inspect_a003(a.a003, a.out or os.path.join("logs", "a003_inspection.json"))
            print("files: {} | __pycache__: {} {} | top-level code in amendment003.py: {} | manifests: {}".format(
                len(rep["files"]), "PRESENT" if rep["pycache"]["exists"] else "absent", rep["pycache"]["files"],
                (rep["amendment003_py"] or {}).get("top_level_code"), [(m["file"], len(m["present_not_listed"]))
                                                                       for m in rep["manifests"]]))
            return 0
        if a.action == "extract-a003":
            ex = extract_a003(a.a003, a.inspection, a.out or os.path.join("logs", "a003_extract.json"),
                              a.accept_top_level_code)
            print("statistics_1_2 = {} | equal to declared: {} | specification objects matching: {} | folder changed: {}"
                  .format(ex.get("statistics_1_2"), ex.get("equal_to_declared"), len(ex.get("matches", [])),
                          ex["folder_changed"]))
            return 0 if ex["valid"] else 1
        r = resolve(a.root, a.procedure, a.results)
        print("RESOLVED:", r["label"])
        return 0
    except (StatsRefError, OSError, ValueError, KeyError) as error:
        print("STOP:", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
