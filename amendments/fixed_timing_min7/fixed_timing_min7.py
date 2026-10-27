"""Optimized fixed timing re-searched under a 7 s minimum green; development comparison.

An external driver, like Amendment 002. Every simulation runs from a clean
checkout of the frozen commit 8c14f32; this file and its byte-identical copy
of the executed Amendment-002 driver (amendment002.py, SHA-256 f624ec32...)
live outside it. Nothing is written outside the new root; the original
campaign, the boundary audit, the Amendment-002 root, the learners, the
selections and the pilots are read only.

WHAT IS REPRODUCED (the executed procedure, Amendment 002 revised)
  coarse   frozen grid C = 40..140 step 10, splits 0.30..0.75 step 0.05,
           offsets 0, 5, ..., C-5 (1980 labels), plus the boundary-audit grid
           C = 20, 25, 30, 35 with the same splits and offsets, plus the
           structural-floor audit (integer cycles from the structural
           minimum up to 19); frozen half-up rounding; one candidate per
           REALIZED plan (C, gH, gV, Delta); top 5 on benchmark_design
           2001-2005 by mean J_primary, ties on the realized key;
  fine     the frozen neighbourhood (C0 +/- 10 step 5, split +/- 0.050 step
           0.025 in [0.25, 0.80], Delta0 +/- 10 step 1 mod C) around EVERY
           coarse alias of each winning plan, union collapsed to realized
           plans, cycles clipped to [structural minimum, 140]; top 10 on
           design;
  select   the 10 on benchmark_validation 2101-2105, frozen
           select_timing_plan: mean J_primary, mean time loss, shorter
           cycle, realized key.
  A plan with any run that does not clear is invalid (frozen rule); a
  recorded clearance failure is terminal and never re-simulated.

WHAT CHANGES, AND NOTHING ELSE
  admissibility  every green >= MIN_GREEN_S = 7 s (study parameter fixed for
                 this experiment; no normative justification is claimed);
  structural minimum cycle 7 + 3 + 7 + 3 = 20 s, so the floor band
                 [20, 20) is empty and the fine clip is [20, 140].

EVIDENCE REUSE (as Amendment 002 did): a design run already made for the same
label in the original campaign, the boundary audit or Amendment 002 is reused
only after the frozen completion check (source commit, configuration,
network, manifests), the run manifest check (clean frozen tree, software
stack) and, for Amendment-002 runs, its sealed outcome marker. All runs of a
ranking must share one stack, the current one. The five coarse winners are
additionally re-simulated in the new root and must reproduce the reused
values to 1e-12 (determinism check) before the fine stage is ranked.

DEVELOPMENT COMPARISON (after the selection is sealed; traffic 9301-9305,
family development, never used for search or selection)
  A  the old optimized fixed timing (19, 577, 9) = C 19, gH 8, gV 5, Delta 9,
     read from the Amendment-002 freeze, unchanged;
  B  the new plan;
  C  the 10 historical QMIX policies of selection_records.json, hash-verified,
     frozen evaluator, no protection (50 evaluations);
  the three protected pilots (t250000, t360000) are READ, not re-evaluated.

Stages: plan | prepare | finalise-coarse | run-repro | run-fine | finalise-fine |
run-validation | finalise-validation | prepare-comparison | run-comparison |
progress | adopt-results | summarise. Local time and size per run are
measured beforehand by sumo_checks_min7.py, in <root>/checks, the only thing
allowed to exist in the root before prepare; prepare accepts the measurement
only with that script's complete, passing report for this code and stack.

An existing result is never re-simulated. A result written just before an
interruption, with no outcome marker yet, is refused by every stage until
adopt-results has verified its provenance and sealed it; files left by an
attempt interrupted before any result are set aside unchanged.
"""

from __future__ import print_function

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time

DRIVER_VERSION = "fixed-timing-min7-1.0"
FROZEN_COMMIT = "8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d"
A002_DRIVER_SHA256 = "f624ec322a3650cbdb9d047f840d099b03f8cce18e699ee26640559ccae3164f"
A002_ADDENDUM_SHA256 = "fcde9d2823556d26d771ff10debcbeb48a3b91c06d3d523a2410c6c071db22c4"
MIN_GREEN_S = 7
OLD_PLAN_KEY = (19, 577, 9)
OLD_PLAN_REALIZED = (19, 8, 5, 9)
ORIGINAL_SELECTED_KEY = (40, 650, 23)
OFFSET_PLAN_KEY = (90, 500, 41)
DEVELOPMENT_FAMILY = "development"
COMPARISON_SEEDS = (9301, 9302, 9303, 9304, 9305)
QMIX_SEEDS = tuple(range(101, 111))
PILOT_METHODS = ("qmix", "vdn", "idqn")
PILOT_SEED = 201
PILOT_CHECKPOINTS = (250000, 360000)
IDENTITY_TOLERANCE = 1e-12
J_RECOMPUTE_TOLERANCE = 1e-9
DEFAULT_RUN_BYTES = 16 * 1024 * 1024        # replaced by a local measurement
DEFAULT_RUN_SECONDS = 30.0                  # replaced by a local measurement
DISK_MARGIN = 1.5

DEFAULTS = {
    "repository_root": r"C:\Users\LENOVO\QMIX_Traffic_Coordination",
    "original_root": r"D:\QMIX_Results\qualification_300m_medium_official",
    "audit_root": r"D:\QMIX_Results\qualification_300m_medium_boundary_audit_20260920",
    "withdrawn_root": r"D:\QMIX_Results\qualification_300m_medium_timing_amendment_20260920",
    "a002_root": r"D:\QMIX_Results\qualification_300m_medium_timing_amendment002r",
    "a003_root": r"D:\QMIX_Results\qualification_300m_medium_amendment003",
    "learner_root": r"D:\QMIX_Results\qualification_300m_medium_timing_amendment002r\learners",
    "pilot_root": r"D:\QMIX_Results\protected_pilot_2026-10-24",
    "root": r"D:\QMIX_Results\fixed_timing_min7_2026-10-27",
}
PROTECTED_ROOTS = ("repository_root", "original_root", "audit_root", "withdrawn_root",
                   "a002_root", "a003_root", "learner_root", "pilot_root")
EXTRA_PROTECTED = (r"C:\Users\LENOVO\QMIX_PROTECTED",)

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_PATH = os.path.abspath(__file__)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


DRIVER_SHA256 = sha256_file(DRIVER_PATH)


class Min7Error(RuntimeError):
    pass


def _argv_value(argv, name, default):
    for index, token in enumerate(argv):
        if token == name and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith(name + "="):
            return token.split("=", 1)[1]
    return default


def _load_a002(path):
    """The executed Amendment-002 driver, imported as a library after its hash
    is checked. It reads --repository-root from the command line."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise Min7Error("Amendment-002 driver not found at {}.".format(path))
    if sha256_file(path) != A002_DRIVER_SHA256:
        raise Min7Error("{} is not the executed Amendment-002 driver (SHA-256 {}).".format(
            path, A002_DRIVER_SHA256))
    spec = importlib.util.spec_from_file_location("amendment002", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPOSITORY_ROOT = os.path.abspath(_argv_value(
    sys.argv, "--repository-root",
    os.environ.get("AQ_FROZEN_REPOSITORY", DEFAULTS["repository_root"])))
if "--repository-root" not in sys.argv and not any(
        t.startswith("--repository-root=") for t in sys.argv):
    sys.argv += ["--repository-root", REPOSITORY_ROOT]
A = _load_a002(_argv_value(sys.argv, "--a002-driver", os.path.join(HERE, "amendment002.py")))

from adaptive_qmix.baselines import campaign  # noqa: E402
from adaptive_qmix.baselines import plans as P  # noqa: E402
from adaptive_qmix.baselines import search  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.protocol import stages as protocol_stages  # noqa: E402

CONTROLLER = search.TIMING_CONTROLLER
DESIGN_FAMILY, VALIDATION_FAMILY = search.DESIGN_FAMILY, search.VALIDATION_FAMILY
STRUCTURAL_MIN_CYCLE_S = 2 * MIN_GREEN_S + P.LOST_TIME_S
SHORT_CYCLES_S = tuple(A.AUDIT_CYCLES_S)
FLOOR_CYCLES_S = tuple(range(STRUCTURAL_MIN_CYCLE_S, min(SHORT_CYCLES_S)))
CYCLE_BOUNDS_S = (STRUCTURAL_MIN_CYCLE_S, P.CYCLE_BOUNDS_S[1])
ROOT_MIN7 = "min7"
STAGE_REPRO, STAGE_FINE, STAGE_VALIDATION = "repro", "fine", "validation"
STAGE_COMPARISON = "comparison"
OUTCOME_MARKER = "min7_outcome.json"


# ---------------------------------------------------------------------------
# Grids: the frozen generators, with the admissibility rule as the only change.
# ---------------------------------------------------------------------------

def admissible(plan, min_green=MIN_GREEN_S):
    return int(plan["green_H_s"]) >= min_green and int(plan["green_V_s"]) >= min_green


def short_cycle_labels(min_green=MIN_GREEN_S, include_invalid=False):
    """The boundary-audit grid (frozen splits and offsets) at C = 20..35."""
    return [p for p in A._grid(SHORT_CYCLES_S, include_invalid=True)
            if include_invalid or admissible(p, min_green)]


def floor_cycles(min_green=MIN_GREEN_S):
    return tuple(range(2 * min_green + P.LOST_TIME_S, min(SHORT_CYCLES_S)))


def floor_labels(min_green=MIN_GREEN_S, include_invalid=False):
    return [p for p in A._grid(floor_cycles(min_green), include_invalid=True)
            if include_invalid or admissible(p, min_green)]


def original_coarse_labels(min_green=MIN_GREEN_S, include_invalid=False):
    return [p for p in P.coarse_timing_candidates(include_invalid=True)
            if include_invalid or admissible(p, min_green)]


def coarse_labels(min_green=MIN_GREEN_S):
    """Every label of the combined coarse grid under this minimum green."""
    return (original_coarse_labels(min_green) + short_cycle_labels(min_green)
            + floor_labels(min_green))


def fine_candidates(winners, cycle_bounds=None, min_green=MIN_GREEN_S,
                    include_invalid=False):
    """A002 fine_candidates with the admissibility rule as a parameter.

    With min_green=5 and cycle_bounds=(16, 140) it is A002's generator; with
    (40, 140) it is the frozen plans.fine_timing_candidates (tested).
    """
    if cycle_bounds is None:
        cycle_bounds = (2 * min_green + P.LOST_TIME_S, P.CYCLE_BOUNDS_S[1])
    seen, candidates = set(), []
    for winner in winners:
        centre_offset = int(winner["offset_s"])
        cycles = P._clipped_range(int(winner["cycle_s"]), P.FINE_CYCLE_DELTA_S,
                                  P.FINE_CYCLE_STEP_S, tuple(cycle_bounds))
        splits = P._clipped_range(int(winner["split_thousandths"]),
                                  P.FINE_SPLIT_DELTA_THOUSANDTHS,
                                  P.FINE_SPLIT_STEP_THOUSANDTHS,
                                  P.SPLIT_BOUNDS_THOUSANDTHS)
        for cycle_s in cycles:
            for split in splits:
                for raw_offset in range(centre_offset - P.FINE_OFFSET_DELTA_S,
                                        centre_offset + P.FINE_OFFSET_DELTA_S + 1,
                                        P.FINE_OFFSET_STEP_S):
                    plan = P.make_plan(cycle_s, split, raw_offset % cycle_s)
                    if not include_invalid and not admissible(plan, min_green):
                        continue
                    key = P.candidate_key(plan)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(plan)
    return candidates


def fine_union(winner_plans, grid_labels, cycle_bounds=None, min_green=MIN_GREEN_S):
    """A002 R3: the neighbourhood of EVERY grid alias of every winning plan."""
    groups = A.label_groups(grid_labels)
    seeds, report = [], []
    for winner in winner_plans:
        realized = A.realized_key(winner)
        aliases = groups.get(realized)
        if not aliases:
            raise Min7Error("Winner {} has no label in the coarse grid.".format(realized))
        report.append({
            "realized_key": list(realized),
            "active_constraints": active_constraints(aliases[0]),
            "aliases": [list(A.key_of(a)) for a in aliases],
            "per_alias_realized_plans": [
                [list(A.key_of(a)), len(A.label_groups(
                    fine_candidates([a], cycle_bounds, min_green)))] for a in aliases],
            "union_realized": sorted(set(A.realized_key(p) for p in fine_candidates(
                aliases, cycle_bounds, min_green))),
        })
        seeds.extend(aliases)
    return fine_candidates(seeds, cycle_bounds, min_green), report


def active_constraints(plan, min_green=MIN_GREEN_S):
    active = []
    if int(plan["cycle_s"]) == 2 * min_green + P.LOST_TIME_S:
        active.append("cycle floor C={}".format(2 * min_green + P.LOST_TIME_S))
    if int(plan["green_V_s"]) == min_green:
        active.append("gV={}".format(min_green))
    if int(plan["green_H_s"]) == min_green:
        active.append("gH={}".format(min_green))
    return active


def describe(plan):
    cycle, g_h, g_v, offset = A.realized_key(plan)
    return "C={} gH={} gV={} D={} (label {}) active: {}".format(
        cycle, g_h, g_v, offset, tuple(A.key_of(plan)),
        ", ".join(active_constraints(plan)) or "none")


def grid_report(min_green=MIN_GREEN_S):
    original = original_coarse_labels(min_green)
    short = short_cycle_labels(min_green)
    floor = floor_labels(min_green)
    combined = original + short + floor
    per_cycle = []
    for cycle in sorted(set(p["cycle_s"] for p in combined)):
        labels = [p for p in combined if p["cycle_s"] == cycle]
        per_cycle.append({"cycle_s": cycle, "labels": len(labels),
                          "realized_plans": len(A.label_groups(labels)),
                          "offsets": sorted(set(p["offset_s"] for p in labels)),
                          "greens": sorted(set((p["green_H_s"], p["green_V_s"])
                                               for p in labels))})
    return {
        "min_green_s": min_green,
        "structural_min_cycle_s": 2 * min_green + P.LOST_TIME_S,
        "original_coarse": {"cycles": list(P.COARSE_CYCLES_S),
                            "labels_before_rule": len(original_coarse_labels(
                                min_green, include_invalid=True)),
                            "labels": len(original),
                            "realized_plans": len(A.label_groups(original))},
        "short_cycles": {"cycles": list(SHORT_CYCLES_S),
                         "labels_before_rule": len(short_cycle_labels(
                             min_green, include_invalid=True)),
                         "labels": len(short),
                         "realized_plans": len(A.label_groups(short))},
        "floor": {"cycles": list(floor_cycles(min_green)), "labels": len(floor),
                  "realized_plans": len(A.label_groups(floor))},
        "combined": {"labels": len(combined),
                     "realized_plans": len(A.label_groups(combined)),
                     "design_runs": len(A.label_groups(combined)) * len(search.DESIGN_SEEDS)},
        "per_cycle": per_cycle,
        "fine_rule": {"cycle_delta_s": P.FINE_CYCLE_DELTA_S,
                      "cycle_step_s": P.FINE_CYCLE_STEP_S,
                      "cycle_bounds_s": [2 * min_green + P.LOST_TIME_S, P.CYCLE_BOUNDS_S[1]],
                      "split_delta": P.FINE_SPLIT_DELTA_THOUSANDTHS,
                      "split_step": P.FINE_SPLIT_STEP_THOUSANDTHS,
                      "split_bounds": list(P.SPLIT_BOUNDS_THOUSANDTHS),
                      "offset_delta_s": P.FINE_OFFSET_DELTA_S,
                      "offset_step_s": P.FINE_OFFSET_STEP_S,
                      "seeds": "every coarse alias of each winning realized plan"},
        "retained": {"coarse": search.COARSE_RETAINED, "fine": search.FINE_RETAINED},
    }


def fine_upper_bound(min_green=MIN_GREEN_S):
    """Bound on NEW fine plans, before any score is read.

    For every possible winner, its fine union minus the plans the G5 coarse
    grids (1980 + 208 + 68) already evaluated; the bound is the sum of the
    five largest. Reuse of original and Amendment-002 fine runs, and overlap
    between winners, only lower the real count, which finalise-coarse states
    exactly. Also given per winning cycle, since winners cluster.
    """
    evaluated = set(A.label_groups(A.combined_coarse_labels()))
    retained = search.COARSE_RETAINED
    seeds = len(search.DESIGN_SEEDS)
    by_cycle = {}
    for realized, aliases in A.label_groups(coarse_labels(min_green)).items():
        union = set(A.realized_key(p) for p in fine_candidates(aliases, None, min_green))
        by_cycle.setdefault(realized[0], []).append(len(union - evaluated))
    every = sorted((n for sizes in by_cycle.values() for n in sizes), reverse=True)
    per_cycle = []
    for cycle in sorted(by_cycle):
        sizes = sorted(by_cycle[cycle], reverse=True)
        per_cycle.append({"cycle_s": cycle, "max_new_plans_one_winner": sizes[0],
                          "max_new_runs_five_winners": sum(sizes[:retained]) * seeds})
    return {"upper_bound_new_plans": sum(every[:retained]),
            "upper_bound_design_runs": sum(every[:retained]) * seeds,
            "per_winning_cycle": per_cycle}


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------

def read_json(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError):
        return None


def norm(path):
    return os.path.normcase(os.path.abspath(path))


def inside(child, parent):
    child, parent = norm(child), norm(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def payload_sha256(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def clean_number(value):
    return float(value) if finite(value) else None


# ---------------------------------------------------------------------------
# Layout.
# ---------------------------------------------------------------------------

class Layout(object):
    def __init__(self, args):
        self.paths = dict((name, os.path.abspath(getattr(args, name)))
                          for name in DEFAULTS)
        self.root = self.paths["root"]
        for name in PROTECTED_ROOTS:
            other = self.paths[name]
            if inside(self.root, other) or inside(other, self.root):
                raise Min7Error("The new root {} overlaps {} ({}).".format(
                    self.root, name, other))
        for other in EXTRA_PROTECTED:
            if inside(self.root, other):
                raise Min7Error("The new root is inside {}.".format(other))
        if inside(DRIVER_PATH, self.paths["repository_root"]):
            raise Min7Error("The driver must live outside the execution checkout.")
        self.a002 = A.Layout(self.paths["original_root"], self.paths["audit_root"],
                             self.paths["a002_root"],
                             withdrawn_root=self.paths["withdrawn_root"])
        self.plan_path = os.path.join(self.root, "plan.json")
        self.runs = os.path.join(self.root, "runs")
        self.repro_runs = os.path.join(self.root, "repro_runs")
        self.artefacts = os.path.join(self.root, "artefacts")
        self.coarse_order = os.path.join(self.artefacts, "min7_coarse_order.json")
        self.fine_result = os.path.join(self.artefacts, "min7_fine_result.json")
        self.selection = os.path.join(self.artefacts, "min7_selected_plan.json")
        self.comparison = os.path.join(self.root, "comparison")
        self.comparison_order = os.path.join(self.comparison, "comparison_order.json")
        self.comparison_manifests = os.path.join(self.comparison, "manifests")
        self.comparison_checkpoints = os.path.join(self.comparison, "checkpoints")
        self.comparison_runs = os.path.join(self.comparison, "runs")
        self.summary = os.path.join(self.root, "summary")

    def assert_writable(self, path):
        if not inside(path, self.root):
            raise Min7Error("Refusing to write {}: outside {}.".format(path, self.root))
        return True

    def runs_for(self, designation):
        if designation == ROOT_MIN7:
            return self.runs
        return self.a002.runs_for(designation)


def write_sealed(layout, path, payload, refuse_existing=True):
    layout.assert_writable(path)
    if refuse_existing and os.path.exists(path):
        raise Min7Error("{} already exists; it is written once.".format(path))
    sealed = dict(payload)
    sealed["payload_sha256"] = payload_sha256(payload)
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = path + ".partial"
    with open(temporary, "w") as handle:
        json.dump(sealed, handle, indent=2, sort_keys=True, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def read_sealed(path, what):
    data = read_json(path)
    if data is None:
        raise Min7Error("{} is missing: {}.".format(what, path))
    payload = dict((k, v) for k, v in data.items() if k != "payload_sha256")
    if data.get("payload_sha256") != payload_sha256(payload):
        raise Min7Error("{} has been modified since it was written.".format(path))
    return payload


def git(repository, *arguments):
    return subprocess.check_output(["git", "-C", repository] + list(arguments),
                                   stderr=subprocess.STDOUT).decode("utf-8").strip()


def verify_repository(layout, require_clean=True):
    head = git(layout.paths["repository_root"], "rev-parse", "HEAD")
    if head != FROZEN_COMMIT:
        raise Min7Error("Execution checkout is at {}, not {}.".format(head, FROZEN_COMMIT))
    if require_clean and git(layout.paths["repository_root"], "status", "--porcelain"):
        raise Min7Error("The execution checkout has uncommitted changes.")
    return head


# ---------------------------------------------------------------------------
# Reconstruction of the executed procedure, from its own artefacts.
# ---------------------------------------------------------------------------

def read_freeze(state_directory):
    artefact = protocol_stages.verify_stage_artefact(
        state_directory, protocol_stages.FREEZE_BASELINE_PLANS)
    path = protocol_stages.artefact_path(state_directory,
                                         protocol_stages.FREEZE_BASELINE_PLANS)
    return artefact, path


def reconstruction(layout):
    """The selected optimized_fixed_timing plan and its provenance, verified."""
    amended, amended_path = read_freeze(layout.a002.state)
    payload = amended["payload"]
    timing = payload["optimized_fixed_timing"]
    offset = payload["optimized_fixed_offset"]
    plan = dict(timing["plan"])
    realized = A.realized_key(plan)
    problems = []
    if tuple(timing["selected_key"]) != OLD_PLAN_KEY:
        problems.append("selected_key {} != {}".format(timing["selected_key"], OLD_PLAN_KEY))
    if realized != OLD_PLAN_REALIZED:
        problems.append("realized {} != {}".format(realized, OLD_PLAN_REALIZED))
    if tuple(offset["selected_key"]) != OFFSET_PLAN_KEY:
        problems.append("offset plan {} != {}".format(offset["selected_key"], OFFSET_PLAN_KEY))
    amendment = payload.get("protocol_amendment_002") or {}
    if amendment.get("driver_sha256") != A002_DRIVER_SHA256:
        problems.append("freeze driver_sha256 {}".format(amendment.get("driver_sha256")))
    if amendment.get("addendum_sha256") != A002_ADDENDUM_SHA256:
        problems.append("freeze addendum_sha256 {}".format(amendment.get("addendum_sha256")))
    if tuple((amendment.get("supersedes") or {}).get("optimized_fixed_timing_key")
             or ()) != ORIGINAL_SELECTED_KEY:
        problems.append("superseded timing key {}".format(
            (amendment.get("supersedes") or {}).get("optimized_fixed_timing_key")))
    floor_order = read_a002_order(layout.a002.floor_order, "Amendment-002 floor order")
    fine_order = A.read_fine_order(layout.a002)
    if floor_order.get("addendum_sha256") != A002_ADDENDUM_SHA256:
        problems.append("floor order addendum {}".format(floor_order.get("addendum_sha256")))
    if A._sha256_file(layout.a002.floor_order) != amendment.get("floor_order_sha256"):
        problems.append("floor order hash differs from the freeze")
    if A._sha256_file(layout.a002.fine_order) != amendment.get("fine_order_sha256"):
        problems.append("fine order hash differs from the freeze")
    validation = campaign.read_selected_plan_artefact(layout.a002.artefacts,
                                                      campaign.TIMING_VALIDATION)
    if problems:
        raise Min7Error("The executed procedure does not reconstruct: {}".format(problems))
    return {
        "old_plan": plan, "old_plan_realized": list(realized),
        "old_plan_key": list(timing["selected_key"]),
        "old_plan_provenance": timing.get("provenance"),
        "old_plan_validation_mean_J_primary_s": timing.get("validation_mean_J_primary_s"),
        "old_plan_validation_mean_time_loss_s": timing.get("validation_mean_time_loss_s"),
        "offset_plan_key": list(offset["selected_key"]),
        "amended_freeze_path": amended_path,
        "amended_freeze_sha256": sha256_file(amended_path),
        "superseded_original_timing_key": list(ORIGINAL_SELECTED_KEY),
        "a002_floor_order_sha256": A._sha256_file(layout.a002.floor_order),
        "a002_fine_order_sha256": A._sha256_file(layout.a002.fine_order),
        "a002_fine_new_plans": fine_order["new_plans"],
        "a002_fine_winners": fine_order["winners"],
        "a002_validation_selected_key": list(validation.get("selected_key") or []),
        "a002_software_stack": floor_order.get("software_stack"),
    }


def read_a002_order(path, what):
    """An Amendment-002 sealed order: seal and driver checked; the addendum is
    checked by hash, not by its recorded path, which may no longer exist."""
    order = A._read_sealed(path)
    if order is None:
        raise Min7Error("{} is missing: {}.".format(what, path))
    if order.get("driver_sha256") != A002_DRIVER_SHA256:
        raise Min7Error("{} was sealed by another driver.".format(what))
    return order


# ---------------------------------------------------------------------------
# Evidence: frozen and Amendment-002 checks for reused runs, ours for new ones.
# ---------------------------------------------------------------------------

def evidence_index(layout):
    """Every label an earlier stage evaluated on design seeds, and where.

    Original coarse (1980) and original fine labels -> original root; boundary
    audit (208, minimum green 5) -> audit root; Amendment-002 floor and new
    fine plans -> Amendment-002 root. Built from grids and sealed orders,
    never by scanning for runs.
    """
    index = A.evaluated_index(layout.a002, include_floor=True)
    fine_order = A.read_fine_order(layout.a002)
    index.add(fine_order["new_work"], A.ROOT_AMENDMENT)
    floor_keys = [A.key_of(p) for p in read_a002_order(
        layout.a002.floor_order, "Amendment-002 floor order")["floor_plans"]]
    return index, floor_keys


class Evidence(A.Evidence):
    """A002's Evidence for the three earlier roots; the new root for the rest."""

    def __init__(self, layout, config, index, floor_keys, stage, runtime,
                 allow_validation=False):
        A.Evidence.__init__(self, layout.a002, config, index,
                            order={"addendum_sha256": A002_ADDENDUM_SHA256, "stage": "fine"},
                            allow_validation=allow_validation, runtime=runtime,
                            floor_keys=floor_keys)
        self.min7 = layout
        self.stage = stage

    def designation(self, plan):
        return self.index.root_of.get(A.key_of(plan), ROOT_MIN7)

    def run(self, plan, family, seed):
        if self.designation(plan) != ROOT_MIN7:
            return A.Evidence.run(self, plan, family, seed)
        manifest = self.manifests(family)[int(seed)]
        directory = campaign.run_directory_for(self.min7.runs, CONTROLLER, plan, family, seed)
        problem = {"candidate_key": list(A.key_of(plan)), "traffic_seed": int(seed),
                   "run_directory": directory}
        marker_problems, marker = outcome_marker_problems(
            directory, plan, family, seed, manifest, self.environment, self.min7)
        if marker_problems:
            problem["problems"] = marker_problems
            return None, problem
        recorded = read_json(os.path.join(directory, campaign.METRICS_FILENAME)) or {}
        usable = (recorded.get("clearance_status") == "CLEARED"
                  and bool(recorded.get("J_primary_valid"))
                  and finite(recorded.get(search.PRIMARY_FIELD))
                  and finite(recorded.get(search.TIME_LOSS_FIELD)))
        if usable:
            # A usable run must also pass the frozen completion check; any other
            # recorded outcome enters as itself and makes its plan invalid.
            complete = campaign.completion_problems(
                directory, CONTROLLER, plan, family, seed, manifest["manifest_csv_sha256"],
                manifest["route_xml_sha256"], manifest["sumo_seed"], self.environment)
            if complete:
                problem["problems"] = complete
                return None, problem
        faults, stack = A._run_manifest_problems(directory)
        if faults:
            problem["problems"] = faults
            return None, problem
        self.stacks[stack] = self.stacks.get(stack, 0) + 1
        return campaign._load_metrics(directory), None


def plan_fingerprint(layout):
    data = read_sealed(layout.plan_path, "plan.json")
    return data["fingerprint"]


def outcome_marker_problems(directory, plan, family, seed, manifest, environment, layout):
    path = os.path.join(directory, OUTCOME_MARKER)
    marker = read_json(path)
    if marker is None:
        return ["no min7 outcome marker"], None
    payload = dict((k, v) for k, v in marker.items() if k != "marker_sha256")
    problems = []
    if marker.get("marker_sha256") != payload_sha256(payload):
        problems.append("outcome marker modified")
    expected = {"controller": CONTROLLER, "candidate_key": list(A.key_of(plan)),
                "realized_key": list(A.realized_key(plan)), "traffic_family": family,
                "traffic_seed": int(seed),
                "manifest_csv_sha256": manifest["manifest_csv_sha256"],
                "route_xml_sha256": manifest["route_xml_sha256"],
                "sumo_seed": int(manifest["sumo_seed"]), "environment": dict(environment),
                "driver_sha256": DRIVER_SHA256, "frozen_commit": FROZEN_COMMIT,
                "plan_fingerprint": plan_fingerprint(layout)}
    for field, value in sorted(expected.items()):
        if marker.get(field) != value:
            problems.append("outcome marker {} is {!r}, needs {!r}".format(
                field, marker.get(field), value))
    metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
    if not os.path.isfile(metrics_path):
        return problems + ["evaluation_metrics.json is absent"], marker
    if marker.get("metrics_sha256") != sha256_file(metrics_path):
        problems.append("evaluation_metrics.json changed after the marker")
    if (read_json(metrics_path) or {}).get("clearance_status") != marker.get("outcome"):
        problems.append("outcome marker disagrees with the metrics")
    return problems, marker


RECORDED = "recorded"
INVALID_MARKER = "invalid_marker"
RESULT_WITHOUT_MARKER = "result_without_marker"
INTERRUPTED = "interrupted_before_any_result"
EMPTY = "empty"


def run_state(directory, marker_problems):
    """What a run or cell directory holds, for the never-rerun rule.

    RECORDED              a valid sealed outcome: final, whatever it is;
    INVALID_MARKER        a marker that does not verify: refused, never rerun;
    RESULT_WITHOUT_MARKER metrics written, interrupted before the marker:
                          never rerun; only `adopt-results` may seal it, after
                          its provenance is verified;
    INTERRUPTED           files but no metrics: no result exists; the files are
                          set aside, unchanged, and the run starts again;
    EMPTY                 nothing yet.
    """
    if not marker_problems:
        return RECORDED
    if os.path.isfile(os.path.join(directory, OUTCOME_MARKER)):
        return INVALID_MARKER
    if os.path.isfile(os.path.join(directory, campaign.METRICS_FILENAME)):
        return RESULT_WITHOUT_MARKER
    if os.path.isdir(directory) and os.listdir(directory):
        return INTERRUPTED
    return EMPTY


def set_aside(layout, directory):
    """Keep an interrupted attempt's files, unchanged, beside the run."""
    index = 1
    while os.path.exists("{}.interrupted-{}".format(directory, index)):
        index += 1
    target = "{}.interrupted-{}".format(directory, index)
    layout.assert_writable(target)
    os.rename(directory, target)
    os.makedirs(directory)
    return target


def refusal(state, directory, problems):
    if state == RESULT_WITHOUT_MARKER:
        return ("RESULT WITHOUT MARKER in {}: never re-simulated; verify and seal it with "
                "adopt-results, or inspect it by hand.".format(directory))
    return "INVALID MARKER in {} ({}): never re-simulated; inspect it by hand.".format(
        directory, "; ".join(problems))


def write_marker(directory, payload):
    marker = dict(payload)
    marker["marker_sha256"] = payload_sha256(payload)
    path = os.path.join(directory, OUTCOME_MARKER)
    with open(path + ".partial", "w") as handle:
        json.dump(marker, handle, indent=2, sort_keys=True, default=str)
    os.replace(path + ".partial", path)
    return path


def search_marker_payload(layout, plan, family, seed, manifest, environment, stage, directory,
                          adopted=None):
    metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
    payload = {"driver_version": DRIVER_VERSION, "controller": CONTROLLER,
               "candidate_key": list(A.key_of(plan)),
               "realized_key": list(A.realized_key(plan)), "plan": dict(plan),
               "traffic_family": family, "traffic_seed": int(seed),
               "sumo_seed": int(manifest["sumo_seed"]), "stage": stage,
               "metrics_sha256": sha256_file(metrics_path),
               "outcome": (read_json(metrics_path) or {}).get("clearance_status"),
               "environment": dict(environment), "driver_sha256": DRIVER_SHA256,
               "frozen_commit": FROZEN_COMMIT, "plan_fingerprint": plan_fingerprint(layout),
               "manifest_csv_sha256": manifest["manifest_csv_sha256"],
               "route_xml_sha256": manifest["route_xml_sha256"]}
    if adopted:
        payload["adopted"] = adopted
    return payload


def guarded_runner(runner, layout, config, stage):
    """Seal every new run's outcome; an existing result is never re-simulated."""
    environment = campaign.environment_identity(config, layout.paths["repository_root"])

    def run(traci_module, config_ref, repository_root, controller, manifest_csv_path,
            route_xml_path, family, seed, sumo_seed, output_directory, plan=None, **kwargs):
        search.assert_family_allowed(family, [seed])
        layout.assert_writable(output_directory)
        manifest = {"manifest_csv_sha256": sha256_file(manifest_csv_path),
                    "route_xml_sha256": sha256_file(route_xml_path),
                    "sumo_seed": int(sumo_seed)}
        problems, marker = outcome_marker_problems(output_directory, plan, family, seed,
                                                   manifest, environment, layout)
        state = run_state(output_directory, problems)
        if state == RECORDED:
            # A recorded outcome is final, whatever it is: a run is never
            # re-simulated to improve its result.
            return campaign._load_metrics(output_directory)
        if state in (INVALID_MARKER, RESULT_WITHOUT_MARKER):
            raise Min7Error(refusal(state, output_directory, problems))
        if state == INTERRUPTED:
            set_aside(layout, output_directory)
        metrics = runner(traci_module, config_ref, repository_root, controller,
                         manifest_csv_path, route_xml_path, family, seed, sumo_seed,
                         output_directory, plan=plan, **kwargs)
        if metrics and os.path.isfile(os.path.join(output_directory,
                                                   campaign.METRICS_FILENAME)):
            write_marker(output_directory, search_marker_payload(
                layout, plan, family, seed, manifest, environment, stage, output_directory))
        return metrics
    return run


# ---------------------------------------------------------------------------
# Plan.
# ---------------------------------------------------------------------------

def qmix_checkpoints(layout):
    """The 10 historical QMIX policies, from selection_records.json, by hash."""
    path = os.path.join(layout.paths["a003_root"], "selection", "selection_records.json")
    records = read_json(path)
    if records is None:
        raise Min7Error("selection_records.json is missing: {}".format(path))
    models, problems = [], []
    for seed in QMIX_SEEDS:
        chosen = None
        for record in (records.get("selection") or {}).get("qmix", []):
            if int(record.get("training_seed", -1)) == seed and record.get("selected"):
                chosen = record["selected"]
        if chosen is None:
            problems.append("qmix seed {} has no selected checkpoint".format(seed))
            continue
        name = "qmix_seed{}_t{:06d}.pth".format(seed, int(chosen["transition_index"]))
        found = [os.path.join(d, name) for d, _s, files in os.walk(layout.paths["learner_root"])
                 if name in files]
        if len(found) != 1:
            problems.append("{}: {} files found".format(name, len(found)))
            continue
        digest = sha256_file(found[0])
        if digest != chosen["checkpoint_sha256"]:
            problems.append("{}: hash differs from selection_records.json".format(name))
            continue
        models.append({"training_seed": seed, "transition_index": int(chosen["transition_index"]),
                       "source": found[0], "sha256": digest})
    return models, problems, sha256_file(path)


def build_plan(layout, config, runtime):
    head = verify_repository(layout)
    rebuilt = reconstruction(layout)
    grid = grid_report()
    models, problems, selection_sha = qmix_checkpoints(layout)
    if problems:
        raise Min7Error("QMIX checkpoints: {}".format(problems))
    payload = {
        "study": "fixed_timing_min7", "driver_version": DRIVER_VERSION,
        "driver_sha256": DRIVER_SHA256, "a002_driver_sha256": A002_DRIVER_SHA256,
        "frozen_commit": head, "baseline_config_sha256": config["_config_sha256"],
        "environment": campaign.environment_identity(config, layout.paths["repository_root"]),
        "min_green_s": MIN_GREEN_S,
        "min_green_status": ("study parameter fixed for this experiment; no normative or "
                             "pedestrian justification is claimed"),
        "grid": grid,
        "design": {"family": DESIGN_FAMILY, "seeds": list(search.DESIGN_SEEDS)},
        "validation": {"family": VALIDATION_FAMILY, "seeds": list(search.VALIDATION_SEEDS)},
        "data_reuse_note": ("benchmark_design 2001-2005 and benchmark_validation 2101-2105 "
                            "are the groups of the original search, reused so that the "
                            "demand stays constant when only the constraint changes. They "
                            "are known development data: the selection is not an "
                            "independent validation."),
        "reconstruction": rebuilt,
        "comparison": {"family": DEVELOPMENT_FAMILY, "seeds": list(COMPARISON_SEEDS),
                       "A": rebuilt["old_plan"], "B": "the selected min7 plan",
                       "C_qmix": [dict((k, m[k]) for k in ("training_seed",
                                                          "transition_index", "sha256"))
                                  for m in models],
                       "selection_records_sha256": selection_sha,
                       "pilots_read_only": {"root": layout.paths["pilot_root"],
                                            "methods": list(PILOT_METHODS),
                                            "seed": PILOT_SEED,
                                            "checkpoints": list(PILOT_CHECKPOINTS)},
                       "expected_evaluations": {"A": 5, "B": 5, "C": 50, "total": 60},
                       "metric": search.PRIMARY_FIELD},
        "roots": layout.paths,
        "software_stack": dict(runtime),
        "reused_evidence_stack": rebuilt["a002_software_stack"],
    }
    payload["fingerprint"] = payload_sha256(payload)
    return payload, models


def disk_free(path):
    probe = path
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return shutil.disk_usage(probe).free


def estimates(plan, bound, measurement):
    seconds = (measurement or {}).get("seconds_per_run", DEFAULT_RUN_SECONDS)
    size = (measurement or {}).get("bytes_per_run", DEFAULT_RUN_BYTES)
    qmix_seconds = (measurement or {}).get("seconds_per_qmix_evaluation", seconds * 1.3)
    stages = [
        ("coarse (reuse, verification only)", 0, 0),
        ("determinism re-simulation, 5 winners x 5 design seeds", 25, 25),
        ("fine (upper bound; exact after finalise-coarse)", bound["upper_bound_design_runs"],
         bound["upper_bound_design_runs"]),
        ("validation, 10 x 5", 50, 50),
        ("comparison A + B (fixed plans), 2 x 5", 10, 10),
        ("comparison C (QMIX), 10 x 5", 50, 50),
    ]
    rows = []
    for name, runs, stored in stages:
        per = qmix_seconds if "QMIX" in name else seconds
        rows.append({"stage": name, "simulations": runs, "hours_one_process": runs * per / 3600.0,
                     "gigabytes": stored * size / 1e9, "bounded_only": "upper bound" in name})
    return {"measured": bool(measurement), "seconds_per_run": seconds, "bytes_per_run": size,
            "seconds_per_qmix_evaluation": qmix_seconds, "rows": rows,
            "fixed_gigabytes": sum(r["gigabytes"] for r in rows if not r["bounded_only"]),
            "total_simulations_upper_bound": sum(r["simulations"] for r in rows),
            "total_hours_one_process_upper_bound": sum(r["hours_one_process"] for r in rows),
            "total_gigabytes_upper_bound": sum(r["gigabytes"] for r in rows)}


# ---------------------------------------------------------------------------
# Search stages.
# ---------------------------------------------------------------------------

def stack_problem(plan):
    """Reuse is valid only under the stack the reused runs were made with."""
    if plan["software_stack"] != plan["reused_evidence_stack"]:
        return ("this process runs {} but the reused design runs were made under {}; "
                "they cannot be pooled. Use that stack, or decide explicitly on a full "
                "re-simulation (not part of this plan).".format(
                    plan["software_stack"], plan["reused_evidence_stack"]))
    return None


def load_plan(layout, config, runtime=None):
    stored = read_sealed(layout.plan_path, "plan.json")
    current, models = build_plan(layout, config, runtime or A.current_runtime())
    if stored["fingerprint"] != current["fingerprint"]:
        raise Min7Error("The plan rebuilt now differs from plan.json (code, inputs or "
                        "parameters changed).")
    return stored, models


def coarse_scores(layout, config, runtime, index, floor_keys):
    labels = coarse_labels()
    classes = A.plan_classes(labels, index)
    new = [c for c in classes if c["evidence"] == "new"]
    if new:
        raise Min7Error("{} coarse plans have no earlier design run: {}".format(
            len(new), [c["identity"] for c in new[:5]]))
    evidence = Evidence(layout, config, index, floor_keys, "coarse", runtime)
    records, problems, aliases = A.score_classes(evidence, classes, DESIGN_FAMILY)
    A._fail_on(problems, "Coarse min7 evidence")
    stack = evidence.assert_one_stack()
    return records, aliases, stack, evidence


def finalise_coarse(layout, config, runtime):
    verify_repository(layout)
    plan, _models = load_plan(layout, config, runtime)
    if os.path.exists(layout.coarse_order):
        raise Min7Error("The coarse stage is already finalised.")
    index, floor_keys = evidence_index(layout)
    records, aliases, stack, evidence = coarse_scores(layout, config, runtime, index,
                                                      floor_keys)
    winners = A.rank_realized(records, search.COARSE_RETAINED)
    winner_plans = [r["plan"] for r in winners]
    fine, report = fine_union(winner_plans, coarse_labels())
    classes = A.plan_classes(fine, index)
    new = [c for c in classes if c["evidence"] == "new"]
    # The determinism check re-simulates, for each winner, the very label whose
    # runs were reused.
    repro = [P.make_plan(*r["evidence_key"]) for r in winners]
    payload = {
        "plan_fingerprint": plan["fingerprint"], "driver_sha256": DRIVER_SHA256,
        "software_stack": dict(stack), "labels": len(coarse_labels()),
        "realized_plans": len(records),
        "invalid_plans": sum(1 for r in records if not r["valid"]),
        "alias_groups": aliases["groups"], "alias_checks": aliases["checks"],
        "scores": A._scores(records),
        "winners": [{"realized_key": r["identity"], "name": r["plan"],
                     "evidence_label": list(r["evidence_key"]),
                     "mean_J_primary_s": r["mean_J_primary_s"],
                     "mean_time_loss_s": r["mean_time_loss_s"]} for r in winners],
        "fine_per_winner": [dict(item, union_realized=[list(k) for k in item["union_realized"]])
                            for item in report],
        "fine_labels": len(fine), "fine_realized_plans": len(classes),
        "fine_reused_plans": len(classes) - len(new), "fine_new_plans": len(new),
        "fine_new_runs": len(new) * len(search.DESIGN_SEEDS),
        "fine_classes": [{"identity": list(c["identity"]), "name": c["name"],
                          "evidence_label": c["evidence_label"],
                          "labels": [list(A.key_of(m)) for m in c["members"]],
                          "evidence": c["evidence"]} for c in classes],
        "new_work": [c["evidence_label"] for c in new],
        "repro_work": repro,
    }
    write_sealed(layout, layout.coarse_order, payload)
    return payload, records


def read_coarse_order(layout, plan):
    order = read_sealed(layout.coarse_order, "coarse order")
    if order["plan_fingerprint"] != plan["fingerprint"] or order["driver_sha256"] != DRIVER_SHA256:
        raise Min7Error("The coarse order belongs to another plan or driver.")
    return order


def coarse_order_seal(layout):
    return (read_json(layout.coarse_order) or {}).get("payload_sha256")


def check_fine_ready(layout, config, runtime, plan, order, approved_coarse):
    """Everything the fine stage needs, checked before its first simulation:
    the approved coarse count, the complete and identical reproduction of the
    five winners (25 runs), and the disk space for the exact count."""
    if approved_coarse != coarse_order_seal(layout):
        raise Min7Error("The fine stage ({} new runs) starts only with --approved-coarse "
                        "{}, after its count has been read.".format(
                            order["fine_new_runs"], coarse_order_seal(layout)))
    index, floor_keys = evidence_index(layout)
    repro = assert_reproduced(layout, config, runtime, order, index, floor_keys)
    per_run = plan["preparation"]["estimate"]["bytes_per_run"]
    needed = order["fine_new_runs"] * per_run * DISK_MARGIN
    if disk_free(layout.root) < needed:
        raise Min7Error("Not enough free space for the fine stage: {:.1f} GB free, "
                        "{:.1f} GB needed ({} runs, margin {}).".format(
                            disk_free(layout.root) / 1e9, needed / 1e9,
                            order["fine_new_runs"], DISK_MARGIN))
    return repro


def run_stage(layout, config, stage, runner, traci_module=None, shard_index=0, shard_count=1,
              approved_coarse=None, runtime=None):
    verify_repository(layout)
    plan, _models = load_plan(layout, config, runtime)
    order = read_coarse_order(layout, plan)
    if stage == STAGE_FINE:
        check_fine_ready(layout, config, runtime or A.current_runtime(), plan, order,
                         approved_coarse)
    if stage == STAGE_REPRO:
        family, plans, output = DESIGN_FAMILY, order["repro_work"], layout.repro_runs
    elif stage == STAGE_FINE:
        family, plans, output = DESIGN_FAMILY, order["new_work"], layout.runs
    elif stage == STAGE_VALIDATION:
        fine = read_sealed(layout.fine_result, "fine result")
        family = VALIDATION_FAMILY
        plans, output = [w["name"] for w in fine["retained"]], layout.runs
    else:
        raise Min7Error("Unknown stage {}.".format(stage))
    ledger_directory = os.path.join(layout.root, "ledgers_" + stage)
    for path in (output, ledger_directory):
        layout.assert_writable(path)
        if not os.path.isdir(path):
            os.makedirs(path)
    return campaign.execute_campaign(
        guarded_runner(runner, layout, config, stage), CONTROLLER, plans, family, config,
        output, layout.a002.original_manifests, layout.paths["repository_root"],
        shard_index=shard_index, shard_count=shard_count, traci_module=traci_module,
        ledger_directory=ledger_directory, allow_manifest_generation=False)


REPRO_FIELDS = ("clearance_status", "J_primary_valid", search.PRIMARY_FIELD,
                "J_primary_total_scheduled_waiting_burden_vehicle_s",
                "mean_completed_waiting_time_s", "mean_completed_depart_delay_s",
                search.TIME_LOSS_FIELD, "mean_completed_travel_time_s",
                "mean_completed_stops", "scheduled_count", "inserted_count",
                "completed_count", "exceptional_count", "tripinfo_count",
                "J_legacy_time_averaged_aggregate_waiting_state",
                "controller_decision_count")


def scalar_metrics(metrics):
    """Every simulated outcome; wall time and paths are not outcomes."""
    return dict((field, metrics.get(field)) for field in REPRO_FIELDS)


def repro_check(layout, config, runtime, order, index, floor_keys):
    """Each coarse winner, re-simulated now, must reproduce the reused runs."""
    evidence = Evidence(layout, config, index, floor_keys, "coarse", runtime)
    manifests = evidence.manifests(DESIGN_FAMILY)
    environment = campaign.environment_identity(config, layout.paths["repository_root"])
    rows, problems = [], []
    for label in order["repro_work"]:
        plan = P.make_plan(*A.key_of(label))
        reused, missing = evidence.runs(plan, DESIGN_FAMILY)
        if missing:
            problems.extend(missing)
            continue
        for seed, old in zip(search.DESIGN_SEEDS, reused):
            directory = campaign.run_directory_for(layout.repro_runs, CONTROLLER, plan,
                                                   DESIGN_FAMILY, seed)
            marker_problems, marker = outcome_marker_problems(
                directory, plan, DESIGN_FAMILY, seed, manifests[seed], environment, layout)
            new = read_json(os.path.join(directory, campaign.METRICS_FILENAME))
            if marker_problems or new is None:
                problems.append({"key": A.key_of(plan), "seed": seed,
                                 "problems": marker_problems or ["no metrics"]})
                continue
            a, b = scalar_metrics(old), scalar_metrics(new)
            differing = []
            for field in sorted(set(a) | set(b)):
                x, y = a.get(field), b.get(field)
                if isinstance(x, float) or isinstance(y, float):
                    if not A._same(x, y):
                        differing.append(field)
                elif x != y:
                    differing.append(field)
            rows.append({"key": list(A.key_of(plan)), "seed": seed, "differing": differing,
                         "J_reused": old.get(search.PRIMARY_FIELD),
                         "J_now": new.get(search.PRIMARY_FIELD)})
    return rows, problems


def assert_reproduced(layout, config, runtime, order, index, floor_keys):
    """All 25 re-simulations recorded, and identical to the reused runs."""
    repro, problems = repro_check(layout, config, runtime, order, index, floor_keys)
    expected = len(order["repro_work"]) * len(search.DESIGN_SEEDS)
    if problems:
        raise Min7Error("Determinism re-simulation absent or incomplete ({} of {} recorded; "
                        "run run-repro first): {}".format(len(repro), expected, problems[:3]))
    differing = [r for r in repro if r["differing"]]
    if differing or len(repro) != expected:
        raise Min7Error("Re-simulated winners do not reproduce the reused runs: {}".format(
            differing[:3]))
    return repro


def finalise_fine(layout, config, runtime):
    verify_repository(layout)
    plan, _models = load_plan(layout, config, runtime)
    order = read_coarse_order(layout, plan)
    if os.path.exists(layout.fine_result):
        raise Min7Error("The fine stage is already finalised.")
    index, floor_keys = evidence_index(layout)
    repro = assert_reproduced(layout, config, runtime, order, index, floor_keys)
    classes = [{"identity": tuple(c["identity"]), "name": c["name"],
                "evidence_label": c["evidence_label"],
                "members": [P.make_plan(*label) for label in c["labels"]]}
               for c in order["fine_classes"]]
    evidence = Evidence(layout, config, index, floor_keys, STAGE_FINE, runtime)
    records, run_problems, aliases = A.score_classes(evidence, classes, DESIGN_FAMILY)
    A._fail_on(run_problems, "Fine min7 stage")
    stack = evidence.assert_one_stack()
    retained = A.rank_realized(records, search.FINE_RETAINED)
    payload = {"plan_fingerprint": plan["fingerprint"], "driver_sha256": DRIVER_SHA256,
               "coarse_order_sha256": sha256_file(layout.coarse_order),
               "software_stack": dict(stack), "repro": repro,
               "alias_checks": aliases["checks"], "scores": A._scores(records),
               "invalid_plans": sum(1 for r in records if not r["valid"]),
               "retained": [{"realized_key": r["identity"], "name": r["plan"],
                             "mean_J_primary_s": r["mean_J_primary_s"],
                             "mean_time_loss_s": r["mean_time_loss_s"]} for r in retained]}
    write_sealed(layout, layout.fine_result, payload)
    return payload


def finalise_validation(layout, config, runtime):
    verify_repository(layout)
    plan, _models = load_plan(layout, config, runtime)
    read_coarse_order(layout, plan)
    fine = read_sealed(layout.fine_result, "fine result")
    if fine["coarse_order_sha256"] != sha256_file(layout.coarse_order):
        raise Min7Error("The coarse order changed after the fine stage.")
    if os.path.exists(layout.selection):
        raise Min7Error("The selection is already sealed.")
    finalists = [dict(w["name"]) for w in fine["retained"]]
    evidence = Evidence(layout, config, A.EvaluatedIndex(), [], STAGE_VALIDATION, runtime,
                        allow_validation=True)
    classes = [{"identity": A.realized_key(p), "name": p, "evidence_label": p,
                "members": [p]} for p in finalists]
    records, problems, _aliases = A.score_classes(evidence, classes, VALIDATION_FAMILY)
    A._fail_on(problems, "Validation min7 stage")
    evidence.assert_one_stack()
    if len(records) != search.FINE_RETAINED:
        raise Min7Error("Validation must score exactly 10 finalists.")
    selected = A.select_realized(records)
    payload = {"plan_fingerprint": plan["fingerprint"], "driver_sha256": DRIVER_SHA256,
               "fine_result_sha256": sha256_file(layout.fine_result),
               "selected_plan": selected["plan"],
               "selected_key": list(selected["key"]),
               "selected_realized_key": list(selected["identity"]),
               "active_constraints": active_constraints(selected["plan"]),
               "validation_mean_J_primary_s": selected["mean_J_primary_s"],
               "validation_mean_time_loss_s": selected["mean_time_loss_s"],
               "validation_scores": A._scores(records),
               "rule": "frozen select_timing_plan: J_primary, time loss, cycle, realized key",
               "min_green_s": MIN_GREEN_S}
    write_sealed(layout, layout.selection, payload)
    return payload


# ---------------------------------------------------------------------------
# Development comparison.
# ---------------------------------------------------------------------------

def comparison_cells(old_plan, new_plan, models):
    cells = []
    for seed in COMPARISON_SEEDS:
        cells.append({"id": "A_old_fixed__traffic{}".format(seed), "kind": "fixed",
                      "arm": "A_old_fixed", "plan": dict(old_plan), "traffic_seed": seed})
        cells.append({"id": "B_min7_fixed__traffic{}".format(seed), "kind": "fixed",
                      "arm": "B_min7_fixed", "plan": dict(new_plan), "traffic_seed": seed})
        for model in models:
            name = "qmix_seed{}_t{:06d}".format(model["training_seed"], model["transition_index"])
            cells.append({"id": "C_{}__traffic{}".format(name, seed), "kind": "qmix",
                          "arm": "C_qmix_historical", "model": name,
                          "checkpoint_sha256": model["sha256"], "traffic_seed": seed})
    return cells


def prepare_comparison(layout, config, runtime=None):
    verify_repository(layout)
    plan, models = load_plan(layout, config, runtime)
    selection = read_sealed(layout.selection, "selected min7 plan")
    if selection["plan_fingerprint"] != plan["fingerprint"]:
        raise Min7Error("The selection belongs to another plan.")
    if os.path.exists(layout.comparison_order):
        raise Min7Error("The comparison is already prepared.")
    old_plan = plan["reconstruction"]["old_plan"]
    if not admissible(selection["selected_plan"]):
        raise Min7Error("The selected plan violates the minimum green.")
    for path in (layout.comparison_manifests, layout.comparison_checkpoints):
        layout.assert_writable(path)
        if not os.path.isdir(path):
            os.makedirs(path)
    manifests = campaign.prepare_seed_manifests(layout.comparison_manifests, config,
                                                DEVELOPMENT_FAMILY, seeds=COMPARISON_SEEDS)
    differing = pilot_manifest_problems(layout, dict(
        (str(s), m) for s, m in manifests.items()))
    if differing:
        raise Min7Error("The pilots were not evaluated on these traffics: {}. Nothing "
                        "is compared on different demands.".format(differing))
    for model in models:
        target = os.path.join(layout.comparison_checkpoints, os.path.basename(model["source"]))
        shutil.copyfile(model["source"], target)
        if sha256_file(target) != model["sha256"]:
            raise Min7Error("Checkpoint copy differs: {}".format(target))
    cells = comparison_cells(old_plan, selection["selected_plan"], models)
    payload = {"plan_fingerprint": plan["fingerprint"], "driver_sha256": DRIVER_SHA256,
               "selection_sha256": sha256_file(layout.selection),
               "family": DEVELOPMENT_FAMILY, "seeds": list(COMPARISON_SEEDS),
               "manifests": dict((str(s), {k: m[k] for k in ("manifest_csv_sha256",
                                                             "route_xml_sha256", "sumo_seed")})
                                 for s, m in manifests.items()),
               "cells": cells}
    write_sealed(layout, layout.comparison_order, payload)
    return payload


def read_comparison_order(layout, plan):
    order = read_sealed(layout.comparison_order, "comparison order")
    if order["plan_fingerprint"] != plan["fingerprint"] or (
            order["selection_sha256"] != sha256_file(layout.selection)):
        raise Min7Error("The comparison order belongs to another plan or selection.")
    return order


def cell_directory(layout, cell):
    return os.path.join(layout.comparison_runs, cell["id"])


def comparison_marker_problems(layout, cell, order, environment):
    directory = cell_directory(layout, cell)
    marker = read_json(os.path.join(directory, OUTCOME_MARKER))
    if marker is None:
        return ["no outcome marker"], None
    payload = dict((k, v) for k, v in marker.items() if k != "marker_sha256")
    problems = []
    if marker.get("marker_sha256") != payload_sha256(payload):
        problems.append("outcome marker modified")
    manifest = order["manifests"][str(cell["traffic_seed"])]
    expected = {"cell": cell, "stage": STAGE_COMPARISON, "driver_sha256": DRIVER_SHA256,
                "plan_fingerprint": order["plan_fingerprint"],
                "environment": dict(environment), "frozen_commit": FROZEN_COMMIT}
    expected.update(manifest)
    for field, value in sorted(expected.items()):
        if marker.get(field) != value:
            problems.append("outcome marker {} differs".format(field))
    metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
    if not os.path.isfile(metrics_path) or marker.get("metrics_sha256") != sha256_file(
            metrics_path):
        problems.append("evaluation_metrics.json absent or changed")
    return problems, marker


def frozen_qmix_evaluator(layout, cell, manifest_prefix, sumo_seed, directory):
    """The frozen evaluator script, run as is (development evaluation)."""
    checkpoint = os.path.join(layout.comparison_checkpoints, cell["model"] + ".pth")
    if sha256_file(checkpoint) != cell["checkpoint_sha256"]:
        raise Min7Error("Checkpoint {} changed.".format(checkpoint))
    log = os.path.join(directory + ".log")
    with open(log, "w") as handle:
        code = subprocess.call(
            [sys.executable, "-B", os.path.join(layout.paths["repository_root"], "scripts",
                                                "adaptive_qmix", "evaluate_checkpoint.py"),
             "--checkpoint", checkpoint, "--manifest-csv", manifest_prefix + ".csv",
             "--route-xml", manifest_prefix + ".rou.xml",
             "--traffic-seed", str(cell["traffic_seed"]), "--sumo-seed", str(sumo_seed),
             "--output-directory", directory, "--run-kind", "development_evaluation",
             "--lane-state-logging", "full", "--traci-access-mode", "subscription"],
            stdout=handle, stderr=subprocess.STDOUT, cwd=layout.paths["repository_root"])
    if code != 0:
        raise Min7Error("frozen evaluator exited with {} (see {})".format(code, log))
    return read_json(os.path.join(directory, campaign.METRICS_FILENAME))


def run_comparison(layout, config, baseline_runner, qmix_evaluator=None, traci_module=None,
                   shard_index=0, shard_count=1, out=print, runtime=None):
    verify_repository(layout)
    plan, _models = load_plan(layout, config, runtime)
    order = read_comparison_order(layout, plan)
    environment = campaign.environment_identity(config, layout.paths["repository_root"])
    qmix_evaluator = qmix_evaluator or frozen_qmix_evaluator
    refused = 0
    for position, cell in enumerate(order["cells"]):
        if position % shard_count != shard_index:
            continue
        problems, marker = comparison_marker_problems(layout, cell, order, environment)
        directory = cell_directory(layout, cell)
        state = run_state(directory, problems)
        if state == RECORDED:
            continue            # recorded once, CLEARED or CLEARANCE_FAILURE: never rerun
        if state in (INVALID_MARKER, RESULT_WITHOUT_MARKER):
            out("REFUS {} : {}".format(cell["id"], refusal(state, directory, problems)))
            refused += 1
            continue
        layout.assert_writable(directory)
        if state == INTERRUPTED:
            out("{} : tentative interrompue sans resultat conservee dans {}".format(
                cell["id"], set_aside(layout, directory)))
        prefix = campaign.manifest_prefix_for(layout.comparison_manifests, DEVELOPMENT_FAMILY,
                                              cell["traffic_seed"])
        manifest = order["manifests"][str(cell["traffic_seed"])]
        if sha256_file(prefix + ".csv") != manifest["manifest_csv_sha256"] or sha256_file(
                prefix + ".rou.xml") != manifest["route_xml_sha256"]:
            raise Min7Error("Comparison manifest for {} changed.".format(cell["traffic_seed"]))
        if not os.path.isdir(directory):
            os.makedirs(directory)
        start = time.time()
        try:
            if cell["kind"] == "fixed":
                metrics = baseline_runner(
                    traci_module, config, layout.paths["repository_root"], CONTROLLER,
                    prefix + ".csv", prefix + ".rou.xml", DEVELOPMENT_FAMILY,
                    cell["traffic_seed"], manifest["sumo_seed"], directory,
                    plan=cell["plan"], manifest_index=0, manifest_prefix=prefix)
            else:
                metrics = qmix_evaluator(layout, cell, prefix, manifest["sumo_seed"], directory)
        except Exception as error:  # noqa: BLE001 - reported; crashes may be re-run
            out("ECHEC TECHNIQUE {} : {!r} (cellule relancable)".format(cell["id"], error))
            continue
        metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
        if metrics is None or not os.path.isfile(metrics_path):
            out("ECHEC TECHNIQUE {} : pas de metriques".format(cell["id"]))
            continue
        payload = cell_marker_payload(cell, order, environment, directory)
        payload["elapsed_wall_s"] = time.time() - start
        write_marker(directory, payload)
        out("{} : {} J={} ({:.0f} s)".format(cell["id"], metrics.get("clearance_status"),
                                             metrics.get(search.PRIMARY_FIELD),
                                             time.time() - start))
    return 4 if refused else 0


def cell_marker_payload(cell, order, environment, directory, adopted=None):
    metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
    payload = {"cell": cell, "stage": STAGE_COMPARISON, "driver_sha256": DRIVER_SHA256,
               "plan_fingerprint": order["plan_fingerprint"],
               "environment": dict(environment), "frozen_commit": FROZEN_COMMIT,
               "metrics_sha256": sha256_file(metrics_path),
               "outcome": (read_json(metrics_path) or {}).get("clearance_status")}
    payload.update(order["manifests"][str(cell["traffic_seed"])])
    if adopted:
        payload["adopted"] = adopted
    return payload


# ---------------------------------------------------------------------------
# Adoption of results written before an interruption, after provenance checks.
# ---------------------------------------------------------------------------

def provenance_problems(directory, runtime, expected_metrics, expected_manifest, config):
    """Does this directory hold the result of exactly this run, made by the
    frozen code on this software stack? Nothing is modified."""
    problems = []
    metrics = read_json(os.path.join(directory, campaign.METRICS_FILENAME))
    if metrics is None:
        return ["evaluation_metrics.json unreadable"]
    for field, value in sorted(expected_metrics.items()):
        if metrics.get(field) != value:
            problems.append("metrics {} is {!r}, needs {!r}".format(field, metrics.get(field),
                                                                    value))
    faults, stack = A._run_manifest_problems(directory)
    problems.extend(faults)
    if stack is not None and dict(stack) != dict(runtime):
        problems.append("made under {} but this process runs {}".format(dict(stack), runtime))
    manifest = read_json(os.path.join(directory, A.RUN_MANIFEST_FILENAME)) or {}
    for field, value in sorted(expected_manifest.items()):
        if manifest.get(field) != value:
            problems.append("run_manifest {} is {!r}, needs {!r}".format(
                field, manifest.get(field), value))
    if manifest.get("network_sha256") != config["network"]["sha256"]:
        problems.append("run_manifest network_sha256 differs from the frozen network")
    problems.extend(j_problems(metrics, recompute_j(directory)))
    return problems


def baseline_expectations(plan, family, seed, manifest, config):
    metrics = {"phase_parameters": dict(plan), "traffic_family": family,
               "traffic_seed": int(seed), "sumo_seed": int(manifest["sumo_seed"]),
               "manifest_csv_sha256": manifest["manifest_csv_sha256"],
               "route_xml_sha256": manifest["route_xml_sha256"], "controller": CONTROLLER,
               "baseline_config_sha256": config["_config_sha256"]}
    run_manifest = {"phase_parameters": dict(plan), "traffic_family": family,
                    "traffic_seed": int(seed), "sumo_seed": int(manifest["sumo_seed"]),
                    "route_xml_sha256": manifest["route_xml_sha256"],
                    "controller": CONTROLLER}
    return metrics, run_manifest


def adoption_note():
    return {"by": "adopt-results", "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": "metrics written before an interruption, provenance verified; "
                      "no file was modified"}


def search_directories(layout, plan):
    """Every directory a search stage of this plan may have written."""
    items = []
    if not os.path.isfile(layout.coarse_order):
        return items
    order = read_coarse_order(layout, plan)
    for stage, root, plans, family in (
            (STAGE_REPRO, layout.repro_runs, order["repro_work"], DESIGN_FAMILY),
            (STAGE_FINE, layout.runs, order["new_work"], DESIGN_FAMILY)):
        for label in plans:
            for seed in search.DESIGN_SEEDS:
                items.append((stage, root, P.make_plan(*A.key_of(label)), family, seed))
    if os.path.isfile(layout.fine_result):
        for item in read_sealed(layout.fine_result, "fine result")["retained"]:
            for seed in search.VALIDATION_SEEDS:
                items.append((STAGE_VALIDATION, layout.runs, dict(item["name"]),
                              VALIDATION_FAMILY, seed))
    return items


def adopt_results(layout, config, runtime=None, out=print):
    """Seal results that exist without a marker, if and only if their
    provenance verifies. Refuses invalid markers and anything that does not
    verify. Writes nothing but the marker; never simulates."""
    verify_repository(layout)
    runtime = runtime or A.current_runtime()
    plan, _models = load_plan(layout, config, runtime)
    environment = campaign.environment_identity(config, layout.paths["repository_root"])
    adopted, refused = [], []
    manifests = {}
    for stage, root, run_plan, family, seed in search_directories(layout, plan):
        if family not in manifests:
            manifests[family] = campaign.load_seed_manifests(
                layout.a002.original_manifests, config, family)
        manifest = manifests[family][seed]
        directory = campaign.run_directory_for(root, CONTROLLER, run_plan, family, seed)
        problems, _marker = outcome_marker_problems(directory, run_plan, family, seed,
                                                    manifest, environment, layout)
        state = run_state(directory, problems)
        if state == INVALID_MARKER:
            refused.append((directory, problems))
        elif state == RESULT_WITHOUT_MARKER:
            expected_metrics, expected_manifest = baseline_expectations(
                run_plan, family, seed, manifest, config)
            faults = provenance_problems(directory, runtime, expected_metrics,
                                         expected_manifest, config)
            if faults:
                refused.append((directory, faults))
            else:
                write_marker(directory, search_marker_payload(
                    layout, run_plan, family, seed, manifest, environment, stage, directory,
                    adopted=adoption_note()))
                adopted.append(directory)
    if os.path.isfile(layout.comparison_order):
        order = read_comparison_order(layout, plan)
        for cell in order["cells"]:
            directory = cell_directory(layout, cell)
            problems, _marker = comparison_marker_problems(layout, cell, order, environment)
            state = run_state(directory, problems)
            if state == INVALID_MARKER:
                refused.append((directory, problems))
                continue
            if state != RESULT_WITHOUT_MARKER:
                continue
            manifest = order["manifests"][str(cell["traffic_seed"])]
            if cell["kind"] == "fixed":
                expected_metrics, expected_manifest = baseline_expectations(
                    cell["plan"], DEVELOPMENT_FAMILY, cell["traffic_seed"], manifest, config)
            else:
                seed = int(cell["model"].split("_")[1][len("seed"):])
                expected_metrics = {"traffic_seed": cell["traffic_seed"], "method": "qmix",
                                    "training_seed": seed}
                expected_manifest = {"checkpoint_sha256": cell["checkpoint_sha256"],
                                     "traffic_seed": cell["traffic_seed"],
                                     "sumo_seed": int(manifest["sumo_seed"]),
                                     "route_manifest_sha256": manifest["manifest_csv_sha256"],
                                     "run_kind": "development_evaluation", "method": "qmix",
                                     "training_seed": seed}
            faults = provenance_problems(directory, runtime, expected_metrics,
                                         expected_manifest, config)
            if faults:
                refused.append((directory, faults))
            else:
                write_marker(directory, cell_marker_payload(cell, order, environment, directory,
                                                            adopted=adoption_note()))
                adopted.append(directory)
    for directory in adopted:
        out("ADOPTE (provenance verifiee, aucun fichier modifie) : {}".format(directory))
    for directory, problems in refused:
        out("REFUSE : {} : {}".format(directory, "; ".join(str(p) for p in problems[:4])))
    out("Adoption : {} adoptes, {} refuses.".format(len(adopted), len(refused)))
    return 1 if refused else 0


SCHEDULED_VEHICLES = 2800


def recompute_j(directory):
    """J_primary from tripinfo.xml, independently of evaluation_metrics.json:
    mean(waitingTime + departDelay) over the 2800 scheduled vehicles, None
    unless all 2800 arrived. The frozen runs write unfinished trips too
    (--tripinfo-output.write-unfinished), with arrival -1. SUMO's printed
    mean waiting is never used."""
    path = os.path.join(directory, "tripinfo.xml")
    if not os.path.isfile(path):
        return None
    from adaptive_qmix.metrics import parse_tripinfo
    rows = parse_tripinfo(path)
    if len(rows) != SCHEDULED_VEHICLES or any(
            float(row.get("arrival", -1.0)) < 0 for row in rows.values()):
        return None
    total = sum(float(row["waitingTime"]) + float(row["departDelay"])
                for row in rows.values())
    return total / float(SCHEDULED_VEHICLES)


def j_problems(metrics, recomputed):
    """A J declared valid must be a CLEARED run's finite J, equal to the value
    recomputed from tripinfo.xml. An invalid J is never imputed or checked
    further: it enters as invalid."""
    if not metrics.get("J_primary_valid"):
        return []
    problems = []
    if metrics.get("clearance_status") != "CLEARED":
        problems.append("J declared valid for a {} run".format(metrics.get("clearance_status")))
    j = metrics.get(search.PRIMARY_FIELD)
    if not finite(j):
        problems.append("J declared valid but absent or not finite ({!r})".format(j))
    elif recomputed is None:
        problems.append("J declared valid but tripinfo.xml is absent or not all 2800 "
                        "vehicles arrived")
    elif abs(float(j) - recomputed) > J_RECOMPUTE_TOLERANCE:
        problems.append("J {!r} differs from tripinfo ({!r})".format(j, recomputed))
    return problems


def pilot_manifest_prefixes(layout, seed):
    """Where the pilot tool wrote its development manifests (either naming)."""
    directory = os.path.join(layout.paths["pilot_root"], "manifests")
    return [os.path.join(directory, "development_{}".format(seed)),
            campaign.manifest_prefix_for(directory, DEVELOPMENT_FAMILY, seed)]


def pilot_manifest_problems(layout, manifests):
    """The pilots' development manifests must be byte-identical to ours."""
    problems = []
    for seed in COMPARISON_SEEDS:
        found = [prefix for prefix in pilot_manifest_prefixes(layout, seed)
                 if os.path.isfile(prefix + ".csv") and os.path.isfile(prefix + ".rou.xml")]
        if len(found) != 1:
            problems.append("pilot manifest for {}: {} candidates found among {}".format(
                seed, len(found), pilot_manifest_prefixes(layout, seed)))
            continue
        prefix = found[0]
        if sha256_file(prefix + ".csv") != manifests[str(seed)]["manifest_csv_sha256"] or (
                sha256_file(prefix + ".rou.xml") != manifests[str(seed)]["route_xml_sha256"]):
            problems.append("pilot traffic {} differs from the comparison traffic".format(seed))
    return problems


def pilot_results(layout, manifests):
    """Read the protected pilots' evaluations; never re-evaluate them."""
    root = layout.paths["pilot_root"]
    rows, problems = [], pilot_manifest_problems(layout, manifests)
    for method in PILOT_METHODS:
        base = os.path.join(root, "{}_seed{}".format(method, PILOT_SEED))
        check = read_json(os.path.join(base, "pilot_check.json")) or {}
        for transition in PILOT_CHECKPOINTS:
            for seed in COMPARISON_SEEDS:
                directory = os.path.join(base, "evaluations", "t{:06d}".format(transition),
                                         "traffic{}".format(seed))
                metrics = read_json(os.path.join(directory, "evaluation_metrics.json"))
                record = read_json(os.path.join(directory, "protection_record.json")) or {}
                if metrics is None:
                    problems.append("pilot {} t{} traffic {} absent".format(method, transition,
                                                                            seed))
                    continue
                recomputed = recompute_j(directory)
                for problem in j_problems(metrics, recomputed):
                    problems.append("pilot {} t{} traffic {} : {}".format(
                        method, transition, seed, problem))
                rows.append(result_row("pilot_{}_seed{}".format(method, PILOT_SEED),
                                       "t{:06d}".format(transition), seed, metrics,
                                       recomputed, check.get("verdict"), record))
    return rows, problems


def result_row(arm, model, seed, metrics, recomputed, verdict=None, record=None):
    j = metrics.get(search.PRIMARY_FIELD) if metrics.get("J_primary_valid") else None
    consistent = None
    if j is not None and recomputed is not None:
        consistent = abs(float(j) - recomputed) <= J_RECOMPUTE_TOLERANCE
    return {"arm": arm, "model": model, "traffic_seed": seed,
            "status": metrics.get("clearance_status"), "J_primary_s": clean_number(j),
            "J_recomputed_s": clean_number(recomputed), "J_consistent": consistent,
            "mean_time_loss_s": clean_number(metrics.get(search.TIME_LOSS_FIELD)),
            "completed": metrics.get("completed_count"),
            "pilot_verdict": verdict,
            "interventions_guarantee": (record or {}).get("interventions_guarantee"),
            "interventions_min_green": (record or {}).get("interventions_min_green")}


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def summarise(layout, config, out=print, runtime=None):
    verify_repository(layout, require_clean=False)
    plan, _models = load_plan(layout, config, runtime)
    order = read_comparison_order(layout, plan)
    environment = campaign.environment_identity(config, layout.paths["repository_root"])
    rows, problems = [], []
    for cell in order["cells"]:
        marker_problems, marker = comparison_marker_problems(layout, cell, order, environment)
        directory = cell_directory(layout, cell)
        if marker_problems:
            problems.append("{} : {}".format(cell["id"], "; ".join(marker_problems)))
            continue
        metrics = read_json(os.path.join(directory, campaign.METRICS_FILENAME))
        recomputed = recompute_j(directory)
        model = cell.get("model") or "C{}_gH{}_gV{}_D{}".format(*A.realized_key(cell["plan"]))
        row = result_row(cell["arm"], model, cell["traffic_seed"], metrics, recomputed)
        for problem in j_problems(metrics, recomputed):
            problems.append("{} : J incoherent : {}".format(cell["id"], problem))
        rows.append(row)
    pilots, pilot_problems = pilot_results(layout, order["manifests"])
    counts = {"expected": len(order["cells"]), "complete": len(rows),
              "pilot_expected": len(PILOT_METHODS) * len(PILOT_CHECKPOINTS)
              * len(COMPARISON_SEEDS), "pilot_found": len(pilots)}
    out("Evaluations de comparaison : attendues {expected} | terminees {complete} | "
        "pilotes lus {pilot_found}/{pilot_expected}".format(**counts))
    for problem in problems + pilot_problems:
        out("  PROBLEME : {}".format(problem))
    if problems or pilot_problems:
        out("Synthese NON ECRITE : ensemble incomplet ou incoherent.")
        return 1
    every = rows + pilots
    layout.assert_writable(layout.summary)
    if not os.path.isdir(layout.summary):
        os.makedirs(layout.summary)
    fields = ["arm", "model", "traffic_seed", "status", "J_primary_s", "J_recomputed_s",
              "J_consistent", "mean_time_loss_s", "completed", "pilot_verdict",
              "interventions_guarantee", "interventions_min_green"]
    with open(os.path.join(layout.summary, "comparison_runs.csv"), "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(every)
    groups = {}
    for row in every:
        groups.setdefault((row["arm"], row["model"]), []).append(row)
    by_group = []
    for (arm, model), members in sorted(groups.items()):
        by_group.append({"arm": arm, "model": model, "evaluations": len(members),
                         "cleared": sum(r["status"] == "CLEARED" for r in members),
                         "clearance_failures": sum(r["status"] == "CLEARANCE_FAILURE"
                                                   for r in members),
                         "J_valid": sum(r["J_primary_s"] is not None for r in members),
                         "mean_J_primary_s_over_valid": mean([r["J_primary_s"] for r in members]),
                         "mean_time_loss_s_over_cleared": mean([r["mean_time_loss_s"]
                                                                for r in members
                                                                if r["status"] == "CLEARED"])})
    index = dict(((r["arm"], r["traffic_seed"]), r) for r in rows if r["arm"] != "C_qmix_historical")
    paired = []
    for seed in COMPARISON_SEEDS:
        a, b = index[("A_old_fixed", seed)], index[("B_min7_fixed", seed)]
        delta = (b["J_primary_s"] - a["J_primary_s"]
                 if a["J_primary_s"] is not None and b["J_primary_s"] is not None else None)
        paired.append({"traffic_seed": seed, "J_A": a["J_primary_s"], "J_B": b["J_primary_s"],
                       "delta_B_minus_A_s": delta, "status_A": a["status"],
                       "status_B": b["status"]})
    qmix_pooled = [r for r in rows if r["arm"] == "C_qmix_historical"]
    summary = {
        "label": "DEVELOPPEMENT - descriptif ; aucune inference ; ni test final ni selection",
        "plan_fingerprint": plan["fingerprint"],
        "metric": search.PRIMARY_FIELD + " (mean waitingTime + departDelay over 2800 "
                  "scheduled vehicles; invalid if not cleared; never imputed)",
        "traffic": {"family": DEVELOPMENT_FAMILY, "seeds": list(COMPARISON_SEEDS)},
        "old_plan": plan["reconstruction"]["old_plan"],
        "new_plan": read_sealed(layout.selection, "selection")["selected_plan"],
        "by_group": by_group,
        "paired_B_minus_A": paired,
        "paired_mean_delta_s": mean([p["delta_B_minus_A_s"] for p in paired]),
        "paired_comparable": sum(p["delta_B_minus_A_s"] is not None for p in paired),
        "qmix_historical_pooled": {
            "evaluations": len(qmix_pooled),
            "clearance_failures": sum(r["status"] != "CLEARED" for r in qmix_pooled),
            "mean_J_over_valid": mean([r["J_primary_s"] for r in qmix_pooled]),
            "note": "50 evaluations = 10 modeles x 5 trafics, pas 50 modeles independants"},
        "limits": ["Les 10 politiques QMIX historiques et le pilote QMIX protege unique ne "
                   "sont pas apparies par graine d'entrainement : un ecart ne peut etre "
                   "attribue ni au seul reentrainement, ni au seul vert minimal.",
                   "Les checkpoints t250000 et t360000 des pilotes sont tous deux montres ; "
                   "aucun n'est choisi apres coup.",
                   "Les 50 evaluations historiques sont 10 modeles x 5 trafics, pas 50 "
                   "modeles independants.",
                   "Le vert minimal de 7 s est un parametre d'etude, sans justification "
                   "normative ou pietonne.",
                   "Trafics de developpement : comparaison descriptive, aucune inference."],
    }
    with open(os.path.join(layout.summary, "comparison_summary.json"), "w") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, default=str)
    report(summary, every, out)
    return 0


def fmt(value, digits=2):
    if value is None:
        return "-"
    if isinstance(value, float):
        return "{:.{}f}".format(value, digits)
    return str(value)


def report(summary, rows, out):
    out("")
    out(summary["label"])
    out("Ancien plan : {} | nouveau plan : {}".format(describe(summary["old_plan"]),
                                                      describe(summary["new_plan"])))
    columns = []
    for row in rows:
        key = (row["arm"], row["model"])
        if key not in columns:
            columns.append(key)
    out("== J_primary par trafic (s ; ECHEC = echec d'evacuation, J non impute) ==")
    out("  {:<20} {:<24}".format("bras", "modele / point") + "".join(
        "{:>10}".format(seed) for seed in COMPARISON_SEEDS))
    for arm, model in columns:
        cells = []
        for seed in COMPARISON_SEEDS:
            match = [r for r in rows if r["arm"] == arm and r["model"] == model
                     and r["traffic_seed"] == seed]
            if not match:
                cells.append("absent")
            elif match[0]["J_primary_s"] is not None:
                cells.append(fmt(match[0]["J_primary_s"], 3))
            else:
                cells.append("ECHEC" if match[0]["status"] == "CLEARANCE_FAILURE"
                             else str(match[0]["status"]))
        out("  {:<20} {:<24}".format(arm, model) + "".join("{:>10}".format(c) for c in cells))
    out("== Par groupe (moyennes sur les evaluations valides) ==")
    for g in summary["by_group"]:
        out("  {:<20} {:<26} evaluations {} | evacuees {} | echecs {} | J valides {} | "
            "J moyen {} | perte de temps moyenne {}".format(
                g["arm"], g["model"], g["evaluations"], g["cleared"], g["clearance_failures"],
                g["J_valid"], fmt(g["mean_J_primary_s_over_valid"], 3),
                fmt(g["mean_time_loss_s_over_cleared"], 3)))
    out("== Ecarts apparies B (min 7 s) - A (ancien plan), par trafic ==")
    for p in summary["paired_B_minus_A"]:
        out("  trafic {traffic_seed} : A {J_A} | B {J_B} | B - A {delta_B_minus_A_s}".format(
            **dict((k, fmt(v, 3) if isinstance(v, float) else v) for k, v in p.items())))
    out("  moyenne des ecarts sur {} paires comparables : {}".format(
        summary["paired_comparable"], fmt(summary["paired_mean_delta_s"], 3)))
    q = summary["qmix_historical_pooled"]
    out("QMIX historiques regroupes : {} evaluations (10 modeles x 5 trafics, pas 50 modeles "
        "independants) | echecs {} | J moyen sur valides {}".format(
            q["evaluations"], q["clearance_failures"], fmt(q["mean_J_over_valid"], 3)))
    for limit in summary["limits"]:
        out("LIMITE : {}".format(limit))


def progress(layout, config, out=print, runtime=None):
    plan, _models = load_plan(layout, config, runtime)
    order = read_comparison_order(layout, plan)
    environment = campaign.environment_identity(config, layout.paths["repository_root"])
    states = {}
    for cell in order["cells"]:
        problems, _marker = comparison_marker_problems(layout, cell, order, environment)
        state = run_state(cell_directory(layout, cell), problems)
        states.setdefault(state, []).append(cell["id"])
    done = len(states.get(RECORDED, []))
    out("Comparaison : {}/{} evaluations enregistrees".format(done, len(order["cells"])))
    for state in (RESULT_WITHOUT_MARKER, INVALID_MARKER, INTERRUPTED):
        if states.get(state):
            out("  {} : {}".format(state, ", ".join(states[state])))
    return 0 if done == len(order["cells"]) else 3


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def print_plan(plan, bound, estimate, free, out=print):
    rebuilt, grid = plan["reconstruction"], plan["grid"]
    out("[OK] depot gele {} propre ; pilote A002 {} ; pilote min7 {}".format(
        plan["frozen_commit"][:7], A002_DRIVER_SHA256[:12], DRIVER_SHA256[:12]))
    out("[OK] plan fixe optimise actuel (optimized_fixed_timing, gel amende) : label {} = "
        "C={} gH={} gV={} D={} ; validation J={} perte de temps={}".format(
            tuple(rebuilt["old_plan_key"]), *(rebuilt["old_plan_realized"] + [
                rebuilt["old_plan_validation_mean_J_primary_s"],
                rebuilt["old_plan_validation_mean_time_loss_s"]])))
    out("     provenance : {}".format(json.dumps(rebuilt["old_plan_provenance"],
                                                 sort_keys=True)))
    out("     remplace le plan d'origine {} ; distinct du plan a decalage optimise "
        "(optimized_fixed_offset) {}".format(tuple(rebuilt["superseded_original_timing_key"]),
                                            tuple(rebuilt["offset_plan_key"])))
    out("     ordres A002 : plancher {} ; fine {} ({} nouveaux plans) ; gel {}".format(
        rebuilt["a002_floor_order_sha256"][:12], rebuilt["a002_fine_order_sha256"][:12],
        rebuilt["a002_fine_new_plans"], rebuilt["amended_freeze_sha256"][:12]))
    out("Contrainte : verts >= {} s ; cycle minimal {} s ; bande plancher {} (vide si "
        "[])".format(grid["min_green_s"], grid["structural_min_cycle_s"], grid["floor"]["cycles"]))
    out("Grossier : C 40-140 {} etiquettes ({} plans) ; C 20-35 {} etiquettes ({} plans, {} "
        "avant la regle) ; total {} plans x 5 graines de conception = {} executions "
        "(reutilisees apres verification)".format(
            grid["original_coarse"]["labels"], grid["original_coarse"]["realized_plans"],
            grid["short_cycles"]["labels"], grid["short_cycles"]["realized_plans"],
            grid["short_cycles"]["labels_before_rule"], grid["combined"]["realized_plans"],
            grid["combined"]["design_runs"]))
    for item in grid["per_cycle"]:
        if item["cycle_s"] < 40:
            out("  C={cycle_s}: {labels} etiquettes, {realized_plans} plans, verts "
                "{greens}".format(**item))
    out("Fin : voisinage gele autour de chaque alias des 5 gagnants, cycles {}-{} ; borne "
        "superieure {} nouveaux plans ({} executions) ; nombre exact apres "
        "finalise-coarse".format(
            grid["fine_rule"]["cycle_bounds_s"][0], grid["fine_rule"]["cycle_bounds_s"][1],
            bound["upper_bound_new_plans"], bound["upper_bound_design_runs"]))
    out("  borne si les 5 gagnants sont au cycle C : " + " ; ".join(
        "C={cycle_s} {max_new_runs_five_winners}".format(**item)
        for item in bound["per_winning_cycle"]))
    out("Validation : 10 x 5 = 50 executions neuves (2101-2105) ; selection gelee "
        "(J, perte de temps, cycle, cle realisee)")
    out("Comparaison (developpement 9301-9305, apres selection) : A 5 + B 5 + QMIX 10 x 5 = "
        "60 evaluations ; pilotes 3 x 2 x 5 = 30 resultats lus")
    for model in plan["comparison"]["C_qmix"]:
        out("  [OK] qmix seed {training_seed} t{transition_index} {sha256}".format(**model))
    out("Estimations ({}) : {:.1f} s/execution, {:.1f} Mo/execution".format(
        "mesure locale" if estimate["measured"] else "valeurs par defaut, NON mesurees",
        estimate["seconds_per_run"], estimate["bytes_per_run"] / 1e6))
    for row in estimate["rows"]:
        out("  {:<60} {:>6} executions {:>7.1f} h {:>7.2f} Go".format(
            row["stage"], row["simulations"], row["hours_one_process"], row["gigabytes"]))
    out("  borne totale : {} executions, {:.1f} h sur un processus, {:.1f} Go ; espace libre "
        "{:.1f} Go".format(estimate["total_simulations_upper_bound"],
                           estimate["total_hours_one_process_upper_bound"],
                           estimate["total_gigabytes_upper_bound"], free / 1e9))
    out("  etapes de taille connue : {:.1f} Go (verifie a la preparation, marge {}) ; etape "
        "fine : verifiee sur son nombre exact avant run-fine".format(
            estimate["fixed_gigabytes"], DISK_MARGIN))
    out("Empreinte du plan : {}".format(plan["fingerprint"]))


ACTIONS = ("plan", "prepare", "finalise-coarse", "run-repro", "run-fine", "finalise-fine",
           "run-validation", "finalise-validation", "prepare-comparison", "run-comparison",
           "progress", "adopt-results", "summarise")
RUN_ACTIONS = ("run-repro", "run-fine", "run-validation", "run-comparison")
CHECKS_DIRECTORY = "checks"


def without_options(argv, names):
    """argv minus the given options, in either --name value or --name=value form."""
    kept, skip = [], False
    for token in argv:
        if skip:
            skip = False
            continue
        if token in names:
            skip = True
            continue
        if any(token.startswith(name + "=") for name in names):
            continue
        kept.append(token)
    return kept


def run_workers(layout, action, argv, workers, out=print):
    """The same action in N processes, one shard each; waits for all of them."""
    logs = os.path.join(layout.root, "logs")
    layout.assert_writable(logs)
    if not os.path.isdir(logs):
        os.makedirs(logs)
    base = without_options(argv, ("--workers", "--shard"))
    processes = []
    for index in range(workers):
        log = os.path.join(logs, "{}_shard{}of{}_{}.log".format(
            action, index, workers, time.strftime("%Y%m%d_%H%M%S")))
        handle = open(log, "w")
        command = [sys.executable, "-B", DRIVER_PATH] + base + [
            "--shard", "{}/{}".format(index, workers)]
        processes.append((subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT),
                          handle, log))
    out("{} processus lances ; journaux dans {}".format(workers, logs))
    codes = []
    for process, handle, log in processes:
        codes.append(process.wait())
        handle.close()
        with open(log) as text:
            tail = text.read().strip().splitlines()[-3:]
        out("  {} -> code {} : {}".format(os.path.basename(log), codes[-1], " | ".join(tail)))
    return max(codes) if codes else 0


SUMO_CHECKS_PATH = os.path.join(HERE, "sumo_checks_min7.py")
LOCAL_CHECK_REPORT = "sumo_checks.json"
LOCAL_CHECK_RUNS = ("old_optimized_fixed_timing", "min7_cycle_bound", "min7_short_cycle",
                    "synthetic_qmix")


def local_checks_problems(measure_file, runtime, config):
    """The measurement counts only with a complete, passing report of the local
    SUMO checks, made by this code, on this stack, with this measurement."""
    measurement = read_json(measure_file)
    report_path = os.path.join(os.path.dirname(os.path.abspath(measure_file)),
                               LOCAL_CHECK_REPORT)
    report = read_json(report_path)
    if measurement is None:
        return ["no local measurement at {}".format(measure_file)], None
    if report is None:
        return ["no local SUMO check report at {}".format(report_path)], None
    problems = []
    if report.get("verdict") != "OK":
        problems.append("the local SUMO checks failed (verdict {!r})".format(report.get("verdict")))
    if report.get("complete") is not True:
        problems.append("the local SUMO checks were partial (--quick or --skip-qmix)")
    runs = report.get("runs") or {}
    missing = [name for name in LOCAL_CHECK_RUNS if name not in runs]
    if missing:
        problems.append("checks missing from the report: {}".format(missing))
    for name, run in sorted(runs.items()):
        if run.get("problems") or run.get("problems") is None:
            problems.append("check {} failed: {}".format(name, run.get("problems")))
    if report.get("measurement") != measurement:
        problems.append("measure.json differs from the measurement in the report")
    expected = {"driver_sha256": DRIVER_SHA256, "a002_driver_sha256": A002_DRIVER_SHA256,
                "sumo_checks_sha256": sha256_file(SUMO_CHECKS_PATH),
                "frozen_commit": FROZEN_COMMIT, "runtime": dict(runtime),
                "network_sha256": config["network"]["sha256"]}
    for field, value in sorted(expected.items()):
        if report.get(field) != value:
            problems.append("report {} is {!r}, this process has {!r}".format(
                field, report.get(field), value))
    return problems, {"report_sha256": sha256_file(report_path),
                      "measure_sha256": sha256_file(measure_file)}


def root_is_fresh(layout):
    """Before prepare, the root may hold only the local SUMO checks."""
    if not os.path.exists(layout.root):
        return True
    return set(os.listdir(layout.root)) <= {CHECKS_DIRECTORY}


def main(argv=None, out=print):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=ACTIONS)
    for name, value in sorted(DEFAULTS.items()):
        parser.add_argument("--" + name.replace("_", "-"), dest=name, default=value)
    parser.add_argument("--a002-driver", default=os.path.join(HERE, "amendment002.py"))
    parser.add_argument("--approved-plan")
    parser.add_argument("--approved-coarse")
    parser.add_argument("--measure-file")
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    args.repository_root = REPOSITORY_ROOT
    layout = Layout(args)
    config = load_config(layout.a002.config_path)
    shard_index, shard_count = (int(x) for x in args.shard.split("/"))
    measure_file = args.measure_file or os.path.join(layout.root, CHECKS_DIRECTORY,
                                                     "measure.json")
    try:
        if args.workers > 1:
            if args.action not in RUN_ACTIONS:
                raise Min7Error("--workers applies to {} only.".format(", ".join(RUN_ACTIONS)))
            verify_repository(layout)
            plan, _models = load_plan(layout, config)
            if args.action == "run-fine":
                check_fine_ready(layout, config, A.current_runtime(), plan,
                                 read_coarse_order(layout, plan), args.approved_coarse)
            return run_workers(layout, args.action, argv, args.workers, out)
        if args.action in ("plan", "prepare"):
            plan, _models = build_plan(layout, config, A.current_runtime())
            bound = fine_upper_bound()
            runtime = A.current_runtime()
            check_problems, check_hashes = local_checks_problems(measure_file, runtime, config)
            measurement = None if check_problems else read_json(measure_file)
            estimate = estimates(plan, bound, measurement)
            free = disk_free(layout.root)
            print_plan(plan, bound, estimate, free, out)
            problem = stack_problem(plan)
            if problem:
                out("PROBLEME DE PILE LOGICIELLE : " + problem)
            for item in check_problems:
                out("CONTROLES LOCAUX NON VALIDES : " + item)
            if args.action == "plan":
                out("Rien n'a ete ecrit.")
                return 0
            if args.approved_plan != plan["fingerprint"]:
                out("REFUS : --approved-plan doit etre {}".format(plan["fingerprint"]))
                return 2
            if problem:
                out("REFUS : pile logicielle differente de celle des executions reutilisees.")
                return 2
            if check_problems:
                out("REFUS : controles SUMO locaux absents, partiels ou en echec ; relancez "
                    "sumo_checks_min7.py sur cette machine apres correction.")
                return 2
            # The fixed stages must fit now; the fine stage is checked again
            # against its exact size before it starts (run-fine).
            needed = estimate["fixed_gigabytes"] * 1e9 * DISK_MARGIN
            if free < needed:
                out("REFUS : espace libre {:.1f} Go < {:.1f} Go necessaires aux etapes de "
                    "taille connue (marge {}).".format(free / 1e9, needed / 1e9, DISK_MARGIN))
                return 2
            if not root_is_fresh(layout):
                out("REFUS : {} contient deja autre chose que {}.".format(
                    layout.root, CHECKS_DIRECTORY))
                return 2
            plan_out = dict(plan)
            plan_out["preparation"] = {"estimate": estimate, "fine_bound": bound,
                                       "disk_free_bytes": free,
                                       "measure_file": measure_file,
                                       "measure_sha256": check_hashes["measure_sha256"],
                                       "local_checks_sha256": check_hashes["report_sha256"]}
            if not os.path.isdir(layout.root):
                os.makedirs(layout.root)
            write_sealed(layout, layout.plan_path, dict(plan_out, fingerprint=plan["fingerprint"]))
            out("Pret : {}".format(layout.plan_path))
            return 0
        import traci
        from adaptive_qmix.baselines.runner import run_baseline
        runtime = A.current_runtime()
        if args.action == "finalise-coarse":
            payload, _records = finalise_coarse(layout, config, runtime)
            print_coarse(payload, out)
            out("Empreinte de l'ordre grossier (a fournir a run-fine --approved-coarse) : "
                "{}".format(coarse_order_seal(layout)))
        elif args.action in ("run-repro", "run-fine", "run-validation"):
            stage = args.action.split("-", 1)[1]
            ledger = run_stage(layout, config, stage, run_baseline, traci, shard_index,
                               shard_count, args.approved_coarse)
            counts, refused = {}, []
            for entry in ledger:
                counts[entry["status"]] = counts.get(entry["status"], 0) + 1
                if entry.get("failure"):
                    refused.append(entry["failure"])
            out("{} shard {}/{} : {}".format(stage, shard_index, shard_count, counts))
            for failure in refused:
                out("  NON EXECUTE OU INTERROMPU : {}".format(failure))
            return 4 if refused else 0
        elif args.action == "finalise-fine":
            payload = finalise_fine(layout, config, runtime)
            out("Reproduction des 5 gagnants : {} executions identiques".format(
                len(payload["repro"])))
            for item in payload["retained"]:
                out("  {}  J={:.6f}".format(describe(item["name"]), item["mean_J_primary_s"]))
        elif args.action == "finalise-validation":
            payload = finalise_validation(layout, config, runtime)
            out("Plan selectionne : {}  validation J={:.6f} perte de temps={:.6f}".format(
                describe(payload["selected_plan"]), payload["validation_mean_J_primary_s"],
                payload["validation_mean_time_loss_s"]))
            out("Empreinte de la selection : {}".format(sha256_file(layout.selection)))
        elif args.action == "prepare-comparison":
            payload = prepare_comparison(layout, config)
            out("Comparaison preparee : {} evaluations".format(len(payload["cells"])))
        elif args.action == "run-comparison":
            return run_comparison(layout, config, run_baseline, None, traci, shard_index,
                                  shard_count, out)
        elif args.action == "progress":
            return progress(layout, config, out)
        elif args.action == "adopt-results":
            return adopt_results(layout, config, runtime, out)
        elif args.action == "summarise":
            return summarise(layout, config, out)
    except (Min7Error, A.AmendmentError, search.SelectionError,
            protocol_stages.ArtefactError, campaign.CampaignError,
            campaign.StageSequenceError) as error:
        out("ARRET : {}".format(error))
        return 1
    return 0


def print_coarse(payload, out=print):
    out("Grossier : {} etiquettes, {} plans, {} invalides ; {} controles d'alias".format(
        payload["labels"], payload["realized_plans"], payload["invalid_plans"],
        payload["alias_checks"]))
    for rank, winner in enumerate(payload["winners"], 1):
        out("{}. {} J={:.6f}".format(rank, describe(winner["name"]), winner["mean_J_primary_s"]))
    for item in payload["fine_per_winner"]:
        out("   alias {} -> union {} plans".format(item["aliases"], len(item["union_realized"])))
    out("Fin : {} etiquettes -> {} plans ; reutilises {} ; nouveaux {} -> {} executions ; "
        "reproduction 25 executions".format(payload["fine_labels"],
                                            payload["fine_realized_plans"],
                                            payload["fine_reused_plans"],
                                            payload["fine_new_plans"], payload["fine_new_runs"]))


if __name__ == "__main__":
    sys.exit(main())
