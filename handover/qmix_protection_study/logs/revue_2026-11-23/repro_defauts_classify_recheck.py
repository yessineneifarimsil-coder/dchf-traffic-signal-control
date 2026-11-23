"""Reproduction of the two technical-lock defects of b_runner (review of a9640b1), run against a given copy.

    python -B logs/revue_2026-11-23/repro_defauts_classify_recheck.py <study copy root>

(a) classify: a CLEARED guarantee cell whose summary says max_counter_s = 200 (> 127) and sumo_mismatch_s = 3.
(b) recheck: after a real cell is finalised (gzip) and re-read, max_counter_s and sumo_mismatch_s are changed in
    cell_summary.json; does the re-read notice?
Prints one line per case: the state / the re-read differences. Uses the real reader on a complete synthetic cell
(tests/test_robustness_analysis.World) and stand-in roots; nothing outside a temporary folder is written.
"""
import json, os, shutil, sys, tempfile
copy = os.path.abspath(sys.argv[1])
sys.path.insert(0, os.path.join(copy, "tests"))
sys.path.insert(0, os.path.join(copy, "tools", "confirmation"))
import b_runner as BR
import test_robustness_analysis as TRA
base = tempfile.mkdtemp()
try:
    world = TRA.World(os.path.join(base, "world"))
    root = os.path.join(base, "b")
    os.makedirs(os.path.join(root, "manifests"))
    n = world.n["R0_reference"]
    with open(os.path.join(root, "manifests", "R0_reference_8051.metadata.json"), "w") as f:
        json.dump({"scenario": "R0_reference", "seed_value": 8051, "scheduled_total": n}, f)
    j = {"kind": "learned", "profile": "R0_reference", "seed": 8051, "model": "qmix_seed101_t350000", "method": "qmix",
         "arm": "guarantee", "controller": "learned:guarantee", "checkpoint_sha256": "c" * 64,
         "directory": os.path.join("cells", "R0_reference", "8051", "qmix_seed101_t350000", "guarantee")}
    world.model_sha[j["model"]] = j["checkpoint_sha256"]
    work = os.path.join(root, j["directory"]) + ".tmp"
    os.makedirs(os.path.dirname(work))
    world.cell({"scenario": "R0_reference", "seed": 8051, "controller": "learned:guarantee", "model": j["model"],
                "directory": work}, j_wait=3.0)
    BR.finalize_cell(root, j, work, os.path.join(root, j["directory"]), n)
    print("baseline real cell:", BR.classify(root, j)[0])
    path = os.path.join(root, j["directory"], "cell_summary.json")
    s = json.load(open(path))
    s["max_counter_s"], s["sumo_mismatch_s"] = 200, 3
    json.dump(s, open(path, "w"))
    print("(a) classify with max_counter_s=200, sumo_mismatch_s=3 in a guarantee cell:", BR.classify(root, j))
    print("(b) re-read differences after changing these two fields:", BR.recheck_cell(root, j, os.path.join(root, "manifests")))
finally:
    shutil.rmtree(base)
