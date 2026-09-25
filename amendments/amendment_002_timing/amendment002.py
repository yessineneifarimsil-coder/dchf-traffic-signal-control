"""Protocol Amendment 002 (revised): re-run the optimized-fixed-timing track.

Provenance strategy (a). Every stage runs from a clean checkout of
FROZEN_COMMIT. This driver is an external file. It never modifies the frozen
code or any original, boundary-audit or fixed-offset artefact. Its own SHA-256
is recorded in every new run's outcome marker, in both work orders, in every
artefact it derives and in the freeze. From the floor work order on, every
stage refuses to run under a different driver hash.

What is new relative to the frozen protocol is written in
PROTOCOL_AMENDMENT_002_ADDENDUM.md, which must be hashed into the floor work
order before any C < 20 run exists:

  R1  A candidate is a REALIZED plan (C, g_H, g_V, Delta mod C). Split labels
      that round to the same greens are one candidate. Every top 5 and top 10
      counts realized plans. Each realized plan is simulated once. Labels of
      one plan that already have runs must agree to 1e-12, or the stage stops.
  R2  Structural-floor audit: C in {16, 17, 18, 19}, the frozen coarse splits,
      Delta in {0, 5, 10, ...} with Delta < C, the frozen rounding and the
      frozen min-green rule, on design seeds only. It enters the combined
      coarse ranking before any top 5 is taken.
  R3  The fine rule is unchanged except the cycle clip, which becomes [16, 140].
  R4  A run that finishes with CLEARANCE_FAILURE gets a sealed terminal outcome
      marker and is never re-simulated. Its plan is INVALID (frozen rule).
  R5  The freeze goes in a new state directory, and there is only ever one
      freeze. Official training is launched only against it, and learner
      evidence is accepted only if the amended freeze authorised it.

Stages, in order:

    precheck              read-only; verifies all existing evidence
    prepare-floor         seal the floor work order (needs the addendum)
    run-floor             40 realized plans x design 2001-2005 (shardable)
    finalise-coarse       1980 + 208 + floor, top 5 realized plans, fine order
    run-fine              the new fine realized plans (shardable)
    finalise-fine         fine top 10 realized plans; global baseline_design
    run-validation        top 10 x benchmark_validation 2101-2105
    finalise-validation   frozen select_timing_plan
    freeze                amended freeze_baseline_plans, new state directory
    train-official        frozen train_adaptive.py against the amended freeze
    verify-learners       accept only runs the amended freeze authorised
    archive-withdrawn     copy the withdrawn Amendment-002 files, read-only
"""

from __future__ import print_function

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys


FROZEN_COMMIT = "8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d"
DEFAULT_REPOSITORY = r"C:\Users\LENOVO\QMIX_Traffic_Coordination"
DEFAULT_ORIGINAL_ROOT = r"D:\QMIX_Results\qualification_300m_medium_official"
DEFAULT_AUDIT_ROOT = (
    r"D:\QMIX_Results\qualification_300m_medium_boundary_audit_20260920"
)
# The withdrawn Amendment 002 lives here and is never written to or executed.
DEFAULT_WITHDRAWN_ROOT = (
    r"D:\QMIX_Results\qualification_300m_medium_timing_amendment_20260920"
)
DEFAULT_AMENDMENT_ROOT = (
    r"D:\QMIX_Results\qualification_300m_medium_timing_amendment002r"
)
DEFAULT_ARCHIVE_DIRECTORY = (
    r"D:\QMIX_Results\WITHDRAWN_timing_amendment_002_v1_20260920"
)
WITHDRAWN_FILES = ("amended_timing_campaign.py", "protocol_amendment_002.md")
AMENDMENT_001_SHA256 = (
    "edb9ec98281b6a9588fae96cfdf982eb90984b830b7fa815ad058160b3ba020a"
)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


DRIVER_PATH = os.path.abspath(__file__)
DRIVER_SHA256 = _sha256_file(DRIVER_PATH)


def _repository_from_argv(argv):
    for index, token in enumerate(argv):
        if token == "--repository-root" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--repository-root="):
            return token.split("=", 1)[1]
    return os.environ.get("AQ_FROZEN_REPOSITORY", DEFAULT_REPOSITORY)


REPOSITORY_ROOT = os.path.abspath(_repository_from_argv(sys.argv))
if os.path.join(REPOSITORY_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.baselines import campaign  # noqa: E402
from adaptive_qmix.baselines import plans as frozen_plans  # noqa: E402
from adaptive_qmix.baselines import search  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.protocol import stages as protocol_stages  # noqa: E402


AMENDMENT_VERSION = "timing-amendment-002r-1.0"

CONTROLLER = search.TIMING_CONTROLLER
DESIGN_FAMILY = search.DESIGN_FAMILY
VALIDATION_FAMILY = search.VALIDATION_FAMILY

AUDIT_CYCLES_S = (20, 25, 30, 35)
FLOOR_CYCLES_S = (16, 17, 18, 19)
AMENDED_CYCLE_BOUNDS_S = (16, 140)
STRUCTURAL_MIN_CYCLE_S = 2 * frozen_plans.MIN_GREEN_S + frozen_plans.LOST_TIME_S

ORIGINAL_COARSE_COUNT = 1980
AUDIT_COARSE_ADMISSIBLE_COUNT = 208
OFFSET_CANDIDATE_COUNT = 90

IDENTITY_TOLERANCE = 1e-12

# What the boundary audit reported. The verified evidence must reproduce both,
# or it is not the evidence the reopen decision was taken on.
REPORTED_FROZEN_RULE_TOP_FIVE = [
    (20, 650, 10), (25, 650, 0), (25, 700, 0), (20, 550, 10), (20, 600, 10),
]
REPORTED_BEST_BELOW_40 = ((20, 650, 10), 3.0422142857142855)

# Recorded by the frozen runner in each run's run_manifest.json.
RUNTIME_FIELDS = ("python", "numpy", "pytorch", "sumo")

OUTCOME_MARKER_FILENAME = "amendment002_outcome.json"
RUN_MANIFEST_FILENAME = "run_manifest.json"
FLOOR_ORDER_FILENAME = "amendment002_floor_order.json"
FINE_ORDER_FILENAME = "amendment002_fine_order.json"
COPIED_ARTEFACTS = (
    campaign.shortlist_path("", campaign.OFFSET_DESIGN),
    campaign.selected_plan_path("", campaign.OFFSET_VALIDATION),
)

ROOT_ORIGINAL = "original"
ROOT_AUDIT = "audit"
ROOT_AMENDMENT = "amendment"

STAGE_FLOOR = "floor"
STAGE_FINE = "fine"
STAGE_VALIDATION = "validation"


class AmendmentError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Realized plans and grids. Pure functions of the frozen constants.
# ---------------------------------------------------------------------------

key_of = frozen_plans.candidate_key


def realized_key(plan):
    """What the executor is given. Split labels never reach it."""
    if int(plan["yellow_s"]) != frozen_plans.YELLOW_S:
        raise AmendmentError("Plan {} has a non-frozen yellow.".format(plan))
    cycle = int(plan["cycle_s"])
    return (cycle, int(plan["green_H_s"]), int(plan["green_V_s"]),
            int(plan["offset_s"]) % cycle)


def _grid(cycles, include_invalid=False):
    candidates = []
    for cycle_s in cycles:
        for split in frozen_plans.COARSE_SPLIT_THOUSANDTHS:
            for offset_s in floor_offsets(cycle_s):
                plan = frozen_plans.make_plan(cycle_s, split, offset_s)
                if include_invalid or frozen_plans.candidate_is_valid(plan):
                    candidates.append(plan)
    return candidates


def floor_offsets(cycle_s):
    """Delta in {0, 5, 10, ...} with Delta < C: the frozen coarse generator."""
    return list(range(0, int(cycle_s), frozen_plans.COARSE_OFFSET_STEP_S))


def audit_coarse_candidates():
    return _grid(AUDIT_CYCLES_S)


def floor_candidates(include_invalid=False):
    return _grid(FLOOR_CYCLES_S, include_invalid)


def fine_candidates(winners, cycle_bounds=AMENDED_CYCLE_BOUNDS_S,
                    include_invalid=False):
    """frozen plans.fine_timing_candidates with the cycle clip as a parameter.

    With cycle_bounds=(40, 140) this returns exactly what the frozen function
    returns, in the same order (tested).
    """
    seen = set()
    candidates = []
    for winner in winners:
        centre_offset = int(winner["offset_s"])
        cycles = frozen_plans._clipped_range(
            int(winner["cycle_s"]), frozen_plans.FINE_CYCLE_DELTA_S,
            frozen_plans.FINE_CYCLE_STEP_S, tuple(cycle_bounds),
        )
        splits = frozen_plans._clipped_range(
            int(winner["split_thousandths"]),
            frozen_plans.FINE_SPLIT_DELTA_THOUSANDTHS,
            frozen_plans.FINE_SPLIT_STEP_THOUSANDTHS,
            frozen_plans.SPLIT_BOUNDS_THOUSANDTHS,
        )
        for cycle_s in cycles:
            for split in splits:
                for raw_offset in range(
                    centre_offset - frozen_plans.FINE_OFFSET_DELTA_S,
                    centre_offset + frozen_plans.FINE_OFFSET_DELTA_S + 1,
                    frozen_plans.FINE_OFFSET_STEP_S,
                ):
                    plan = frozen_plans.make_plan(
                        cycle_s, split, raw_offset % cycle_s
                    )
                    if not include_invalid and not (
                        frozen_plans.candidate_is_valid(plan)
                    ):
                        continue
                    key = key_of(plan)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(plan)
    return candidates


def label_groups(plans):
    """Realized key -> its labels, lowest first."""
    groups = {}
    for plan in plans:
        groups.setdefault(realized_key(plan), []).append(dict(plan))
    for members in groups.values():
        members.sort(key=key_of)
    return groups


def active_constraints(plan):
    """Which structural limits a realized plan sits on."""
    active = []
    if int(plan["cycle_s"]) == STRUCTURAL_MIN_CYCLE_S:
        active.append("cycle floor C=16")
    if int(plan["green_V_s"]) == frozen_plans.MIN_GREEN_S:
        active.append("gV=5")
    if int(plan["green_H_s"]) == frozen_plans.MIN_GREEN_S:
        active.append("gH=5")
    return active


def describe(plan):
    cycle, g_h, g_v, offset = realized_key(plan)
    return "C={} gH={} gV={} D={} (label {}) active: {}".format(
        cycle, g_h, g_v, offset, key_of(plan),
        ", ".join(active_constraints(plan)) or "none",
    )


class EvaluatedIndex(object):
    """Every label an earlier preregistered stage evaluated, and where.

    Built from the grids and sealed artefacts, never by scanning for runs, so
    which runs are reused is fixed before any score is read.
    """

    def __init__(self):
        self.root_of = {}
        self.by_realized = {}

    def add(self, plans, root):
        for plan in plans:
            key = key_of(plan)
            if key in self.root_of and self.root_of[key] != root:
                raise AmendmentError(
                    "Label {} is claimed by both {} and {}.".format(
                        key, self.root_of[key], root
                    )
                )
            self.root_of[key] = root
            members = self.by_realized.setdefault(realized_key(plan), [])
            if key not in [key_of(m) for m in members]:
                members.append(dict(plan))
                members.sort(key=key_of)
        return self

    def representative(self, realized):
        members = self.by_realized.get(realized)
        return None if not members else members[0]


def plan_classes(plans, index):
    """Collapse labels to realized plans; reuse any earlier evaluation of one.

    The representative is the lowest label an earlier stage already evaluated
    for that realized plan -- even if that label is not in this stage's grid --
    or, if none exists, the lowest label in the grid. Chosen structurally,
    never by score.
    """
    classes = []
    for realized, members in label_groups(plans).items():
        earlier = index.representative(realized)
        classes.append({
            "identity": realized,
            "representative": dict(earlier or members[0]),
            "members": members,
            "evidence": "earlier" if earlier is not None else "new",
        })
    classes.sort(key=lambda item: key_of(item["representative"]))
    return classes


# ---------------------------------------------------------------------------
# Sealed files and path guards.
# ---------------------------------------------------------------------------

def _sha256_payload(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _inside(child, parent):
    child, parent = _norm(child), _norm(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def _write_sealed(layout, path, payload, seal_field="payload_sha256",
                  refuse_existing=False):
    layout.assert_writable(path)
    if refuse_existing and os.path.exists(path):
        raise AmendmentError("{} already exists; it is written once.".format(
            path))
    sealed = dict(payload)
    sealed[seal_field] = _sha256_payload(payload)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = path + ".partial"
    with open(temporary, "w") as handle:
        json.dump(sealed, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def _read_sealed(path, seal_field="payload_sha256"):
    if not os.path.isfile(path):
        return None
    with open(path, "r") as handle:
        sealed = json.load(handle)
    payload = dict((k, v) for k, v in sealed.items() if k != seal_field)
    if sealed.get(seal_field) != _sha256_payload(payload):
        raise AmendmentError(
            "{} has been modified since it was written.".format(path)
        )
    return payload


def _read_json(path):
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Layout.
# ---------------------------------------------------------------------------

class Layout(object):
    def __init__(self, original_root, audit_root, amendment_root,
                 withdrawn_root=DEFAULT_WITHDRAWN_ROOT, audit_runs=None,
                 repository_root=REPOSITORY_ROOT):
        self.repository_root = os.path.abspath(repository_root)
        self.original_root = os.path.abspath(original_root)
        self.audit_root = os.path.abspath(audit_root)
        self.amendment_root = os.path.abspath(amendment_root)
        self.withdrawn_root = os.path.abspath(withdrawn_root)
        self.original_runs = os.path.join(self.original_root, "runs")
        self.original_manifests = os.path.join(self.original_root, "manifests")
        self.original_artefacts = os.path.join(self.original_root, "artefacts")
        self.original_state = os.path.join(
            self.original_root, "campaign_state"
        )
        self.audit_runs = os.path.abspath(
            audit_runs or os.path.join(self.audit_root, "runs")
        )
        self.runs = os.path.join(self.amendment_root, "runs")
        self.artefacts = os.path.join(self.amendment_root, "artefacts")
        self.state = os.path.join(self.amendment_root, "campaign_state")
        self.learners = os.path.join(self.amendment_root, "learners")
        self.floor_order = os.path.join(self.artefacts, FLOOR_ORDER_FILENAME)
        self.fine_order = os.path.join(self.artefacts, FINE_ORDER_FILENAME)
        self.config_path = os.path.join(
            self.repository_root, "config", "adaptive_qmix",
            "baselines_300m_medium.json",
        )
        self.adaptive_config_path = os.path.join(
            self.repository_root, "config", "adaptive_qmix",
            "qualification_300m_medium.json",
        )
        protected = [self.original_root, self.audit_root, self.withdrawn_root,
                     self.repository_root]
        for other in protected:
            if _inside(self.amendment_root, other) or _inside(
                    other, self.amendment_root):
                raise AmendmentError(
                    "The amendment root {} overlaps protected root {}.".format(
                        self.amendment_root, other
                    )
                )
        if os.path.isdir(self.amendment_root):
            present = [name for name in WITHDRAWN_FILES if os.path.exists(
                os.path.join(self.amendment_root, name))]
            if present:
                raise AmendmentError(
                    "{} holds the withdrawn Amendment 002 ({}); it may not be "
                    "used as the execution root.".format(
                        self.amendment_root, present
                    )
                )

    def assert_writable(self, path):
        """Nothing is ever written outside the amendment root."""
        if not _inside(path, self.amendment_root):
            raise AmendmentError(
                "Refusing to write {}: outside the amendment root {}.".format(
                    path, self.amendment_root
                )
            )
        return True

    def runs_for(self, designation):
        return {
            ROOT_ORIGINAL: self.original_runs,
            ROOT_AUDIT: self.audit_runs,
            ROOT_AMENDMENT: self.runs,
        }[designation]


def verify_repository(layout, require_clean=True):
    def git(*args):
        return subprocess.check_output(
            ["git"] + list(args), cwd=layout.repository_root
        ).decode("utf-8").strip()
    head = git("rev-parse", "HEAD")
    if head != FROZEN_COMMIT:
        raise AmendmentError(
            "Repository HEAD is {}, not the frozen {}.".format(
                head, FROZEN_COMMIT
            )
        )
    if require_clean:
        dirty = git("status", "--porcelain")
        if dirty:
            raise AmendmentError(
                "The frozen repository has uncommitted changes:\n{}".format(
                    dirty
                )
            )
    if _inside(DRIVER_PATH, layout.repository_root):
        raise AmendmentError(
            "The driver must be an external file, not inside the execution "
            "checkout."
        )
    return head


def current_runtime():
    """The software stack this process would simulate with."""
    from adaptive_qmix.provenance import runtime_versions
    runtime = runtime_versions("cpu")
    return dict((field, runtime.get(field)) for field in RUNTIME_FIELDS)


# ---------------------------------------------------------------------------
# Evidence.
# ---------------------------------------------------------------------------

def _outcome_marker_problems(directory, plan, family, seed, manifest,
                             environment, expected_order):
    marker = _read_sealed(
        os.path.join(directory, OUTCOME_MARKER_FILENAME),
        seal_field="marker_sha256",
    )
    if marker is None:
        return ["no amendment outcome marker"], None
    problems = []
    expected = {
        "controller": CONTROLLER,
        "candidate_key": list(key_of(plan)),
        "realized_key": list(realized_key(plan)),
        "traffic_family": family,
        "traffic_seed": int(seed),
        "manifest_csv_sha256": manifest["manifest_csv_sha256"],
        "route_xml_sha256": manifest["route_xml_sha256"],
        "sumo_seed": int(manifest["sumo_seed"]),
        "environment": dict(environment),
        "driver_sha256": DRIVER_SHA256,
        "frozen_commit": FROZEN_COMMIT,
    }
    expected.update(expected_order)
    for field, value in sorted(expected.items()):
        found = marker.get(field)
        if found != value:
            problems.append("outcome marker {} is {!r}, needs {!r}".format(
                field, found, value))
    metrics_path = os.path.join(directory, campaign.METRICS_FILENAME)
    if not os.path.isfile(metrics_path):
        return problems + ["evaluation_metrics.json is absent"], marker
    if marker.get("metrics_sha256") != _sha256_file(metrics_path):
        problems.append("evaluation_metrics.json changed after the marker")
    metrics = _read_json(metrics_path) or {}
    if metrics.get("clearance_status") != marker.get("outcome"):
        problems.append("outcome marker disagrees with the metrics")
    return problems, marker


def _run_manifest_problems(directory):
    manifest = _read_json(os.path.join(directory, RUN_MANIFEST_FILENAME))
    if manifest is None:
        return ["run_manifest.json is absent or unreadable"], None
    problems = []
    if manifest.get("git_commit") != FROZEN_COMMIT:
        problems.append("run_manifest git_commit is {!r}".format(
            manifest.get("git_commit")))
    if manifest.get("git_status_porcelain") != "":
        problems.append("the tree was not clean when this run was made "
                        "(git_status_porcelain {!r})".format(
                            manifest.get("git_status_porcelain")))
    if str(manifest.get("git_describe") or "").endswith("-dirty"):
        problems.append("git_describe marks the tree dirty")
    runtime = manifest.get("runtime") or {}
    stack = tuple((field, runtime.get(field)) for field in RUNTIME_FIELDS)
    if any(value is None for _field, value in stack):
        problems.append("run_manifest does not record {}".format(
            [field for field, value in stack if value is None]))
    return problems, stack


class Evidence(object):
    """Verified runs, each read from the one root designated for its label.

    Old runs must pass the frozen completion_problems with the full
    environment identity, source_commit included. New runs must also carry
    this driver's outcome marker. Every run must record the frozen commit, a
    clean tree and the software stack; all runs entering one ranking must share
    one stack, and it must be the current one.
    """

    def __init__(self, layout, config, index, order=None,
                 allow_validation=False, runtime=None, floor_keys=()):
        self.layout = layout
        self.config = config
        self.index = index
        self.order = dict(order or {})
        # Floor runs reused by a later stage carry the stage they were made in.
        self.floor_keys = set(tuple(k) for k in floor_keys)
        self.allow_validation = allow_validation
        self.environment = campaign.environment_identity(
            config, layout.repository_root
        )
        self.runtime = runtime
        self.stacks = {}
        self._manifests = {}

    def manifests(self, family):
        if family == VALIDATION_FAMILY and not self.allow_validation:
            raise AmendmentError(
                "benchmark_validation is closed until the fine stage is "
                "finalised."
            )
        search.assert_family_allowed(family)
        if family not in self._manifests:
            self._manifests[family] = campaign.load_seed_manifests(
                self.layout.original_manifests, self.config, family
            )
        return self._manifests[family]

    def designation(self, plan):
        return self.index.root_of.get(key_of(plan), ROOT_AMENDMENT)

    def run(self, plan, family, seed):
        manifest = self.manifests(family)[int(seed)]
        root = self.designation(plan)
        directory = campaign.run_directory_for(
            self.layout.runs_for(root), CONTROLLER, plan, family, seed,
        )
        problem = {"candidate_key": list(key_of(plan)),
                   "traffic_seed": int(seed), "run_directory": directory}
        complete = campaign.completion_problems(
            directory, CONTROLLER, plan, family, seed,
            manifest["manifest_csv_sha256"], manifest["route_xml_sha256"],
            manifest["sumo_seed"], self.environment,
        )
        if root == ROOT_AMENDMENT:
            expected = dict(self.order)
            if key_of(plan) in self.floor_keys:
                expected["stage"] = STAGE_FLOOR
            outcome, marker = _outcome_marker_problems(
                directory, plan, family, seed, manifest, self.environment,
                expected,
            )
            if outcome:
                problem["problems"] = outcome
                return None, problem
            if marker["outcome"] == "CLEARED" and complete:
                problem["problems"] = complete
                return None, problem
        elif complete:
            problem["problems"] = complete
            return None, problem
        faults, stack = _run_manifest_problems(directory)
        if faults:
            problem["problems"] = faults
            return None, problem
        self.stacks.setdefault(stack, 0)
        self.stacks[stack] += 1
        return campaign._load_metrics(directory), None

    def runs(self, plan, family):
        runs, problems = [], []
        for seed in search.required_seeds(family):
            metrics, problem = self.run(plan, family, seed)
            if problem is not None:
                problems.append(problem)
            else:
                runs.append(metrics)
        return runs, problems

    def assert_one_stack(self):
        if len(self.stacks) != 1:
            raise AmendmentError(
                "Runs entering one ranking were made under {} different "
                "software stacks: {}".format(len(self.stacks), self.stacks))
        stack = dict(list(self.stacks)[0])
        if self.runtime is not None and stack != self.runtime:
            raise AmendmentError(
                "The evidence was made under {} but this process runs {}."
                .format(stack, self.runtime))
        return stack


def _same(a, b):
    if a is None or b is None:
        return a is b
    a, b = float(a), float(b)
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return abs(a - b) <= IDENTITY_TOLERANCE


def score_classes(evidence, classes, family):
    """One frozen search record per realized plan, labels cross-checked.

    Every other label of the same realized plan that an earlier stage
    evaluated is read, and its per-seed outcome must match the
    representative's to 1e-12. If any does not, the collapse is wrong and the
    stage stops.
    """
    records, problems, pairing = [], [], []
    alias_report = {"groups": [], "checks": 0, "max_abs_difference": 0.0,
                    "label_records": {}}
    for item in classes:
        representative = item["representative"]
        runs, missing = evidence.runs(representative, family)
        problems.extend(missing)
        if missing:
            continue
        others = [plan for plan in evidence.index.by_realized.get(
            item["identity"], []) if key_of(plan) != key_of(representative)]
        for other in others:
            other_runs, other_missing = evidence.runs(other, family)
            if other_missing:
                problems.extend(other_missing)
                continue
            alias_report["label_records"][key_of(other)] = (
                search.summarise_candidate(other, other_runs, family,
                                           CONTROLLER))
            for mine, theirs in zip(runs, other_runs):
                alias_report["checks"] += 1
                for field in (search.PRIMARY_FIELD, search.TIME_LOSS_FIELD):
                    a, b = mine.get(field), theirs.get(field)
                    if a is not None and b is not None and not (
                        math.isnan(float(a)) or math.isnan(float(b))
                    ):
                        alias_report["max_abs_difference"] = max(
                            alias_report["max_abs_difference"],
                            abs(float(a) - float(b)),
                        )
                identical = (
                    mine.get("clearance_status") == theirs.get(
                        "clearance_status")
                    and bool(mine.get("J_primary_valid")) == bool(
                        theirs.get("J_primary_valid"))
                    and _same(mine.get(search.PRIMARY_FIELD),
                              theirs.get(search.PRIMARY_FIELD))
                    and _same(mine.get(search.TIME_LOSS_FIELD),
                              theirs.get(search.TIME_LOSS_FIELD))
                )
                if not identical:
                    raise AmendmentError(
                        "Labels {} and {} realize the same plan {} but "
                        "differ on seed {} beyond {}: {} versus {}. The "
                        "realized-plan collapse is invalid; stage "
                        "stopped.".format(
                            key_of(representative), key_of(other),
                            item["identity"], mine.get("traffic_seed"),
                            IDENTITY_TOLERANCE,
                            [mine.get(f) for f in (search.PRIMARY_FIELD,
                                                   search.TIME_LOSS_FIELD)],
                            [theirs.get(f) for f in (search.PRIMARY_FIELD,
                                                     search.TIME_LOSS_FIELD)],
                        )
                    )
        if others:
            alias_report["groups"].append(
                [list(key_of(representative))]
                + [list(key_of(o)) for o in others]
            )
        record = search.summarise_candidate(
            representative, runs, family, CONTROLLER
        )
        alias_report["label_records"][key_of(representative)] = record
        record["identity"] = list(item["identity"])
        record["labels"] = [list(key_of(m)) for m in item["members"]]
        records.append(record)
        pairing.append((key_of(representative), runs))
    if not problems:
        search.assert_stage_traffic_pairing(pairing, family)
    return records, problems, alias_report


def _scores(records):
    return [
        {
            "key": list(record["key"]),
            "realized_key": record["identity"],
            "labels": record["labels"],
            "valid": record["valid"],
            "mean_J_primary_s": record["mean_J_primary_s"],
            "mean_time_loss_s": record["mean_time_loss_s"],
            "failed_seeds": record["failed_seeds"],
        }
        for record in records
    ]


def _fail_on(problems, what):
    if problems:
        raise AmendmentError(
            "{}: {} runs do not verify. First problems: {}".format(
                what, len(problems), json.dumps(problems[:3], indent=1)
            )
        )


# ---------------------------------------------------------------------------
# Structural sets.
# ---------------------------------------------------------------------------

def coarse_sets():
    original = frozen_plans.coarse_timing_candidates()
    audit = audit_coarse_candidates()
    if len(original) != ORIGINAL_COARSE_COUNT:
        raise AmendmentError("Original coarse grid is not 1980 labels.")
    if len(audit) != AUDIT_COARSE_ADMISSIBLE_COUNT:
        raise AmendmentError("Audit coarse grid is not 208 labels.")
    return original, audit


def original_fine_labels(layout):
    """The original fine grid, regenerated from its own sealed artefact."""
    artefact = campaign.read_shortlist_artefact(
        layout.original_artefacts, campaign.TIMING_COARSE_DESIGN
    )
    return frozen_plans.fine_timing_candidates(artefact["plans"])


def floor_representatives():
    return [members[0] for _realized, members in sorted(
        label_groups(floor_candidates()).items())]


def evaluated_index(layout, include_floor):
    original, audit = coarse_sets()
    index = EvaluatedIndex()
    index.add(original + original_fine_labels(layout), ROOT_ORIGINAL)
    index.add(audit, ROOT_AUDIT)
    if include_floor:
        index.add(floor_representatives(), ROOT_AMENDMENT)
    return index


def no_op_report(layout):
    """R1 changes nothing where the original campaign ran (C >= 40)."""
    original, _audit = coarse_sets()
    fine = original_fine_labels(layout)
    offsets = frozen_plans.fixed_offset_candidates()
    report = {
        "original_coarse": (len(original), len(label_groups(original))),
        "original_fine": (len(fine), len(label_groups(fine))),
        "fixed_offset": (len(offsets), len(label_groups(offsets))),
    }
    for name, (labels, plans) in report.items():
        if labels != plans:
            raise AmendmentError(
                "{}: {} labels are only {} realized plans; R1 would change "
                "the original campaign.".format(name, labels, plans))
    if len(offsets) != OFFSET_CANDIDATE_COUNT:
        raise AmendmentError("The fixed-offset grid is not 90 plans.")
    return report


def floor_report():
    labels = floor_candidates()
    rejected = len(floor_candidates(include_invalid=True)) - len(labels)
    groups = label_groups(labels)
    per_cycle = {}
    for cycle in FLOOR_CYCLES_S:
        cycle_labels = [p for p in labels if p["cycle_s"] == cycle]
        per_cycle[cycle] = {
            "offsets": floor_offsets(cycle),
            "labels": len(cycle_labels),
            "realized_plans": len(label_groups(cycle_labels)),
            "greens": sorted({(p["green_H_s"], p["green_V_s"])
                              for p in cycle_labels}),
        }
    return {
        "labels": len(labels),
        "rejected_by_min_green": rejected,
        "realized_plans": len(groups),
        "runs": len(groups) * len(search.DESIGN_SEEDS),
        "per_cycle": per_cycle,
        "groups": [[list(key_of(m)) for m in members]
                   for _r, members in sorted(groups.items())],
    }


# ---------------------------------------------------------------------------
# Guards.
# ---------------------------------------------------------------------------

def _candidate_cycle(name):
    prefix = CONTROLLER + "__C"
    if not name.startswith(prefix):
        return None
    try:
        return int(name[len(prefix):len(prefix) + 3])
    except ValueError:
        return None


def scan_for_leakage(layout):
    """No held-out traffic anywhere; no validation traffic in the audit.

    Only directory NAMES are listed. No manifest or run under a validation
    or held-out family is opened.
    """
    problems = []
    forbidden = ("final_test", "learner_validation")
    for root, runs in ((layout.original_root, layout.original_runs),
                       (layout.audit_root, layout.audit_runs),
                       (layout.amendment_root, layout.runs)):
        for directory in (os.path.join(root, "manifests"), runs):
            if not os.path.isdir(directory):
                continue
            names = list(os.listdir(directory))
            if directory == runs:
                for candidate in list(names):
                    path = os.path.join(directory, candidate)
                    if os.path.isdir(path):
                        names.extend(os.listdir(path))
            for name in names:
                if any(token in name for token in forbidden):
                    problems.append(os.path.join(directory, name))
                if root == layout.audit_root and VALIDATION_FAMILY in name:
                    problems.append(os.path.join(directory, name))
    if problems:
        raise AmendmentError(
            "Held-out or validation traffic where none may exist: {}".format(
                problems[:5]))
    return True


def assert_floor_not_yet_run(layout):
    """Proof that no C < 20 simulation predates the sealed floor order."""
    allowed = set()
    order = _read_sealed(layout.floor_order)
    if order is not None:
        allowed = set(campaign.candidate_directory_name(CONTROLLER, plan)
                      for plan in order["floor_plans"])
    found = []
    for runs, may in ((layout.original_runs, False), (layout.audit_runs, False),
                      (layout.runs, True)):
        if not os.path.isdir(runs):
            continue
        for name in os.listdir(runs):
            cycle = _candidate_cycle(name)
            if cycle is not None and cycle < 20 and not (may and name in allowed):
                found.append(os.path.join(runs, name))
    if found:
        raise AmendmentError(
            "C < 20 runs exist outside the sealed floor order: {}".format(
                found[:5]))
    return True


def refuse_original_state(layout):
    if _norm(layout.state) == _norm(layout.original_state):
        raise AmendmentError("The amended state directory is the original.")
    return True


def _check_order_identity(layout, order):
    if order.get("driver_sha256") != DRIVER_SHA256:
        raise AmendmentError(
            "This driver ({}) is not the one the work order was sealed with "
            "({}). The driver is frozen from prepare-floor on.".format(
                DRIVER_SHA256, order.get("driver_sha256")))
    document = order.get("addendum_path")
    if not document or not os.path.isfile(document) or (
            _sha256_file(document) != order.get("addendum_sha256")):
        raise AmendmentError(
            "The addendum {} is missing or no longer hashes to {}.".format(
                document, order.get("addendum_sha256")))
    return True


def read_floor_order(layout):
    order = _read_sealed(layout.floor_order)
    if order is None:
        raise AmendmentError("No floor work order; run prepare-floor first.")
    _check_order_identity(layout, order)
    if order["floor_plans"] != floor_representatives():
        raise AmendmentError("The floor order does not regenerate.")
    return order


def _order_fields(order, stage):
    return {"addendum_sha256": order["addendum_sha256"], "stage": stage}


# ---------------------------------------------------------------------------
# Stages.
# ---------------------------------------------------------------------------

def evaluate_existing_coarse(layout, config, runtime):
    """Rebuild the 1980 + 208 ranking on realized plans. No top 5 is taken."""
    original, audit = coarse_sets()
    index = evaluated_index(layout, include_floor=False)
    labels = original + audit
    classes = plan_classes(labels, index)
    evidence = Evidence(layout, config, index, runtime=runtime)
    records, problems, aliases = score_classes(evidence, classes, DESIGN_FAMILY)
    _fail_on(problems, "Existing coarse evidence")
    stack = evidence.assert_one_stack()
    by_identity = dict((tuple(r["identity"]), r) for r in records)
    # The withdrawn label rule, rebuilt from each label's OWN verified runs.
    key_records = [aliases["label_records"][key_of(plan)] for plan in labels]
    reproduced = [tuple(r["key"]) for r in search.rank_by_design(
        key_records, search.COARSE_RETAINED)]
    if reproduced != REPORTED_FROZEN_RULE_TOP_FIVE:
        raise AmendmentError(
            "Verified evidence ranks {} under the withdrawn label rule, but "
            "the audit reported {}.".format(
                reproduced, REPORTED_FROZEN_RULE_TOP_FIVE))
    best_label, best_j = REPORTED_BEST_BELOW_40
    best = by_identity[realized_key(frozen_plans.make_plan(*best_label))]
    if abs(best["mean_J_primary_s"] - best_j) > IDENTITY_TOLERANCE:
        raise AmendmentError(
            "The audit reported J={!r} for {} but the verified runs give "
            "{!r}.".format(best_j, best_label, best["mean_J_primary_s"]))
    valid = [r for r in records if r["valid"]]
    leader = min(valid, key=lambda r: (r["mean_J_primary_s"], r["key"]))
    return {
        "labels": len(labels),
        "runs": len(labels) * len(search.DESIGN_SEEDS),
        "records": records,
        "realized_plans": len(records),
        "invalid_plans": len(records) - len(valid),
        "aliases": aliases,
        "stack": stack,
        "leader": leader,
        "environment": evidence.environment,
    }


def precheck(layout, config, runtime=None, require_clean=True):
    """Read-only. Writes nothing, anywhere."""
    verify_repository(layout, require_clean)
    refuse_original_state(layout)
    scan_for_leakage(layout)
    assert_floor_not_yet_run(layout)
    no_op = no_op_report(layout)
    existing = evaluate_existing_coarse(layout, config, runtime)
    return {"no_op": no_op, "existing": existing, "floor": floor_report(),
            "driver_sha256": DRIVER_SHA256}


def prepare_floor(layout, config, amendment_document, runtime=None,
                  require_clean=True):
    if not amendment_document or not os.path.isfile(amendment_document):
        raise AmendmentError(
            "The addendum must exist and be hashed before any C < 20 run.")
    if _read_sealed(layout.floor_order) is not None:
        raise AmendmentError("The floor order is already sealed.")
    result = precheck(layout, config, runtime, require_clean)
    floor = result["floor"]
    _write_sealed(layout, layout.floor_order, {
        "amendment_version": AMENDMENT_VERSION,
        "frozen_commit": FROZEN_COMMIT,
        "driver_sha256": DRIVER_SHA256,
        "addendum_path": os.path.abspath(amendment_document),
        "addendum_sha256": _sha256_file(amendment_document),
        "amendment_001_sha256": AMENDMENT_001_SHA256,
        "offset_rule": "Delta in {0,5,10,...} with Delta < C",
        "offsets_by_cycle": dict(
            (str(c), floor_offsets(c)) for c in FLOOR_CYCLES_S),
        "floor_plans": floor_representatives(),
        "floor_label_groups": floor["groups"],
        "floor_runs": floor["runs"],
        "existing_coarse_realized_plans": result["existing"]["realized_plans"],
        "software_stack": dict(result["existing"]["stack"]),
    }, refuse_existing=True)
    return result


def guarded_runner(runner, layout, config, order, stage):
    """Seal every new run's outcome; never re-simulate a recorded failure."""
    environment = campaign.environment_identity(config, layout.repository_root)
    fields = _order_fields(order, stage)

    def run(traci_module, config_ref, repository_root, controller,
            manifest_csv_path, route_xml_path, family, seed, sumo_seed,
            output_directory, plan=None, **kwargs):
        search.assert_family_allowed(family, [seed])
        layout.assert_writable(output_directory)
        manifest = {
            "manifest_csv_sha256": _sha256_file(manifest_csv_path),
            "route_xml_sha256": _sha256_file(route_xml_path),
            "sumo_seed": int(sumo_seed),
        }
        problems, marker = _outcome_marker_problems(
            output_directory, plan, family, seed, manifest, environment,
            fields,
        )
        if not problems and marker["outcome"] == "CLEARANCE_FAILURE":
            return campaign._load_metrics(output_directory)
        metrics = runner(
            traci_module, config_ref, repository_root, controller,
            manifest_csv_path, route_xml_path, family, seed, sumo_seed,
            output_directory, plan=plan, **kwargs
        )
        metrics_path = os.path.join(output_directory, campaign.METRICS_FILENAME)
        if metrics and os.path.isfile(metrics_path):
            payload = {
                "amendment_version": AMENDMENT_VERSION,
                "controller": CONTROLLER,
                "candidate_key": list(key_of(plan)),
                "realized_key": list(realized_key(plan)),
                "plan": dict(plan),
                "traffic_family": family,
                "traffic_seed": int(seed),
                "sumo_seed": int(sumo_seed),
                "metrics_sha256": _sha256_file(metrics_path),
                "outcome": metrics.get("clearance_status"),
                "environment": dict(environment),
                "driver_sha256": DRIVER_SHA256,
                "frozen_commit": FROZEN_COMMIT,
            }
            payload.update(manifest)
            payload.update(fields)
            _write_sealed(
                layout, os.path.join(output_directory, OUTCOME_MARKER_FILENAME),
                payload, seal_field="marker_sha256",
            )
        return metrics
    return run


def run_stage(layout, config, stage, runner, traci_module=None,
              shard_index=0, shard_count=1, require_clean=True):
    verify_repository(layout, require_clean)
    order = read_floor_order(layout)
    if stage == STAGE_FLOOR:
        family, plans = DESIGN_FAMILY, order["floor_plans"]
    elif stage == STAGE_FINE:
        family = DESIGN_FAMILY
        plans = read_fine_order(layout)["new_work"]
    elif stage == STAGE_VALIDATION:
        protocol_stages.verify_stage_artefact(
            layout.state, protocol_stages.BASELINE_DESIGN)
        family = VALIDATION_FAMILY
        plans = campaign.read_shortlist_artefact(
            layout.artefacts, campaign.TIMING_FINE_DESIGN)["plans"]
    else:
        raise AmendmentError("Unknown stage {!r}.".format(stage))
    ledger_directory = os.path.join(layout.runs, "ledgers_" + stage)
    for path in (layout.runs, ledger_directory):
        layout.assert_writable(path)
    return campaign.execute_campaign(
        guarded_runner(runner, layout, config, order, stage), CONTROLLER,
        plans, family, config, layout.runs, layout.original_manifests,
        layout.repository_root, shard_index=shard_index,
        shard_count=shard_count, traci_module=traci_module,
        ledger_directory=ledger_directory, allow_manifest_generation=False,
    )


def _derivation(records, family, seeds, evidence, source_stage, extra):
    return {
        "expected_candidate_count": len(records),
        "expected_run_count": len(records) * len(seeds),
        "verified_run_count": len(records) * len(seeds),
        "seeds": list(seeds),
        "family": family,
        "controller": CONTROLLER,
        "environment": evidence.environment,
        "ranking": (
            "search.rank_by_design / select_timing_plan, one record per "
            "realized plan (Amendment 002 R1)"
        ),
        "scores": _scores(records),
        "derived_from_stage": source_stage,
        "amendment_002": dict(extra, driver_sha256=DRIVER_SHA256,
                              version=AMENDMENT_VERSION),
    }


def finalise_coarse(layout, config, runtime=None, require_clean=True):
    """Floor in first; then the top 5 realized plans and the fine order."""
    verify_repository(layout, require_clean)
    if _read_sealed(layout.fine_order) is not None:
        raise AmendmentError("The coarse stage is already finalised.")
    order = read_floor_order(layout)
    scan_for_leakage(layout)
    assert_floor_not_yet_run(layout)
    original, audit = coarse_sets()
    index = evaluated_index(layout, include_floor=True)
    labels = original + audit + floor_candidates()
    classes = plan_classes(labels, index)
    evidence = Evidence(layout, config, index,
                        order=_order_fields(order, STAGE_FLOOR),
                        runtime=runtime,
                        floor_keys=map(key_of, order["floor_plans"]))
    records, problems, aliases = score_classes(evidence, classes, DESIGN_FAMILY)
    _fail_on(problems, "Combined coarse evidence (original, audit, floor)")
    stack = evidence.assert_one_stack()
    winners = search.rank_by_design(records, search.COARSE_RETAINED)
    layout.assert_writable(layout.artefacts)
    _copy_offset_artefacts(layout)
    campaign._write_shortlist_artefact(
        layout.artefacts, campaign.TIMING_COARSE_DESIGN,
        [r["plan"] for r in winners],
        {"ranked_on": DESIGN_FAMILY, "seeds": list(search.DESIGN_SEEDS),
         "protocol": "design ranks; validation selects"},
        _derivation(records, DESIGN_FAMILY, search.DESIGN_SEEDS, evidence,
                    None, {
                        "labels": len(labels),
                        "floor_order_sha256": _sha256_file(layout.floor_order),
                        "alias_groups": aliases["groups"],
                        "alias_checks": aliases["checks"],
                        "software_stack": dict(stack),
                    }),
    )
    fine = fine_plan(layout, [r["plan"] for r in winners])
    _write_sealed(layout, layout.fine_order, dict(fine, **{
        "amendment_version": AMENDMENT_VERSION,
        "driver_sha256": DRIVER_SHA256,
        "floor_order_sha256": _sha256_file(layout.floor_order),
        "coarse_artefact_sha256": _sha256_file(campaign.shortlist_path(
            layout.artefacts, campaign.TIMING_COARSE_DESIGN)),
    }), refuse_existing=True)
    return {"records": records, "winners": winners, "fine": fine,
            "aliases": aliases}


def fine_plan(layout, winner_plans):
    fine = fine_candidates(winner_plans)
    every = fine_candidates(winner_plans, include_invalid=True)
    classes = plan_classes(fine, evaluated_index(layout, include_floor=True))
    new = [c for c in classes if c["evidence"] == "new"]
    seeds = len(search.DESIGN_SEEDS)
    return {
        "winners": [dict(p) for p in winner_plans],
        "cycle_bounds_s": list(AMENDED_CYCLE_BOUNDS_S),
        "fine_labels": len(fine),
        "rejected_by_min_green": len(every) - len(fine),
        "realized_plans": len(classes),
        "reused_plans": len(classes) - len(new),
        "new_plans": len(new),
        "new_runs": len(new) * seeds,
        "validation_runs": search.FINE_RETAINED * len(search.VALIDATION_SEEDS),
        "classes": [
            {"identity": list(c["identity"]),
             "representative": c["representative"],
             "labels": [list(key_of(m)) for m in c["members"]],
             "evidence": c["evidence"]}
            for c in classes
        ],
        "new_work": [c["representative"] for c in new],
    }


def read_fine_order(layout):
    order = _read_sealed(layout.fine_order)
    if order is None:
        raise AmendmentError("No fine order; run finalise-coarse first.")
    if order.get("driver_sha256") != DRIVER_SHA256:
        raise AmendmentError("The fine order was sealed by another driver.")
    artefact = campaign.read_shortlist_artefact(
        layout.artefacts, campaign.TIMING_COARSE_DESIGN)
    if _sha256_file(campaign.shortlist_path(
            layout.artefacts, campaign.TIMING_COARSE_DESIGN)) != (
            order["coarse_artefact_sha256"]):
        raise AmendmentError("The coarse artefact changed after the order.")
    regenerated = fine_plan(layout, artefact["plans"])
    if any(order[k] != v for k, v in regenerated.items()):
        raise AmendmentError(
            "The fine order does not regenerate from the sealed coarse "
            "winners; it has been edited or the code changed.")
    return order


def _copy_offset_artefacts(layout):
    """The offset track is reused byte for byte, never re-derived."""
    for name in COPIED_ARTEFACTS:
        source = os.path.join(layout.original_artefacts, name)
        target = os.path.join(layout.artefacts, name)
        layout.assert_writable(target)
        if not os.path.isfile(source):
            raise AmendmentError("Missing original artefact {}.".format(source))
        if os.path.isfile(target):
            if _sha256_file(target) != _sha256_file(source):
                raise AmendmentError("{} differs from the original.".format(
                    target))
            continue
        if not os.path.isdir(layout.artefacts):
            os.makedirs(layout.artefacts)
        shutil.copyfile(source, target)
    campaign.read_shortlist_artefact(layout.artefacts, campaign.OFFSET_DESIGN)
    campaign.read_selected_plan_artefact(
        layout.artefacts, campaign.OFFSET_VALIDATION)


def verify_offset_copies(layout):
    for name in COPIED_ARTEFACTS:
        if _sha256_file(os.path.join(layout.artefacts, name)) != _sha256_file(
                os.path.join(layout.original_artefacts, name)):
            raise AmendmentError(
                "{} is no longer the original offset artefact.".format(name))
    return True


def _classes_from_order(order):
    return [
        {"identity": tuple(item["identity"]),
         "representative": item["representative"],
         "members": [frozen_plans.make_plan(*label)
                     for label in item["labels"]]}
        for item in order["classes"]
    ]


def finalise_fine(layout, config, runtime=None, require_clean=True):
    verify_repository(layout, require_clean)
    floor = read_floor_order(layout)
    order = read_fine_order(layout)
    # New fine runs carry stage "fine"; reused floor runs carry "floor"; reused
    # original and audit runs are checked by their frozen markers alone.
    evidence = Evidence(layout, config, evaluated_index(layout, True),
                        order=_order_fields(floor, STAGE_FINE),
                        runtime=runtime,
                        floor_keys=map(key_of, floor["floor_plans"]))
    records, problems, aliases = score_classes(
        evidence, _classes_from_order(order), DESIGN_FAMILY)
    _fail_on(problems, "Amended fine stage")
    evidence.assert_one_stack()
    retained = search.rank_by_design(records, search.FINE_RETAINED)
    layout.assert_writable(layout.artefacts)
    coarse = campaign.read_shortlist_artefact(
        layout.artefacts, campaign.TIMING_COARSE_DESIGN)
    campaign._write_shortlist_artefact(
        layout.artefacts, campaign.TIMING_FINE_DESIGN,
        [r["plan"] for r in retained],
        {"ranked_on": DESIGN_FAMILY, "seeds": list(search.DESIGN_SEEDS),
         "protocol": "design ranks; validation selects"},
        _derivation(records, DESIGN_FAMILY, search.DESIGN_SEEDS, evidence,
                    coarse["stage"], {
                        "fine_order_sha256": _sha256_file(layout.fine_order),
                        "alias_groups": aliases["groups"],
                        "alias_checks": aliases["checks"],
                    }),
    )
    refuse_original_state(layout)
    layout.assert_writable(layout.state)
    completion = campaign.complete_global_stage(
        protocol_stages.BASELINE_DESIGN, layout.artefacts, layout.state)
    return {"retained": retained, "records": records,
            "global_stage": completion}


def finalise_validation(layout, config, runtime=None, require_clean=True):
    verify_repository(layout, require_clean)
    floor = read_floor_order(layout)
    protocol_stages.assert_stage_allowed(
        layout.state, protocol_stages.BASELINE_VALIDATION)
    fine_artefact = campaign.read_shortlist_artefact(
        layout.artefacts, campaign.TIMING_FINE_DESIGN)
    finalists = [dict(p) for p in fine_artefact["plans"]]
    # An empty index: validation evidence comes only from this amendment's
    # own runs, so no C = 40 validation result can enter.
    evidence = Evidence(layout, config, EvaluatedIndex(),
                        order=_order_fields(floor, STAGE_VALIDATION),
                        allow_validation=True, runtime=runtime)
    classes = [{"identity": realized_key(p), "representative": p,
                "members": [p]} for p in finalists]
    records, problems, _ = score_classes(evidence, classes, VALIDATION_FAMILY)
    _fail_on(problems, "Amended timing validation")
    evidence.assert_one_stack()
    if len(records) != search.FINE_RETAINED:
        raise AmendmentError("Validation must score exactly 10 finalists.")
    selected = search.select_timing_plan(records)
    layout.assert_writable(layout.artefacts)
    layout.assert_writable(layout.state)
    campaign._write_selected_plan_artefact(
        layout.artefacts, campaign.TIMING_VALIDATION, CONTROLLER, selected,
        _derivation(records, VALIDATION_FAMILY, search.VALIDATION_SEEDS,
                    evidence, fine_artefact["stage"], {}),
        config, layout.repository_root, fine_artefact,
    )
    completion = campaign.complete_global_stage(
        protocol_stages.BASELINE_VALIDATION, layout.artefacts, layout.state)
    return {"selected": selected, "records": records,
            "global_stage": completion}


def freeze(layout, config, adaptive_config, require_clean=True):
    verify_repository(layout, require_clean)
    refuse_original_state(layout)
    floor = read_floor_order(layout)
    read_fine_order(layout)
    verify_offset_copies(layout)
    target = protocol_stages.artefact_path(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS)
    layout.assert_writable(target)
    if os.path.exists(target):
        raise AmendmentError(
            "{} already exists. There is only one amended freeze.".format(
                target))
    payload = campaign.build_baseline_freeze_payload(
        layout.artefacts, config, layout.repository_root, adaptive_config)
    original_freeze = protocol_stages.artefact_path(
        layout.original_state, protocol_stages.FREEZE_BASELINE_PLANS)
    if not os.path.isfile(original_freeze):
        raise AmendmentError(
            "The superseded freeze {} is missing.".format(original_freeze))
    old = (_read_json(original_freeze) or {}).get("payload", {})
    superseded = {
        "artefact_path": original_freeze,
        "artefact_sha256": _sha256_file(original_freeze),
        "optimized_fixed_timing_key": (
            old.get("optimized_fixed_timing", {}).get("selected_key")),
        "optimized_fixed_offset_key": (
            old.get("optimized_fixed_offset", {}).get("selected_key")),
    }
    if superseded["optimized_fixed_offset_key"] != (
            payload["optimized_fixed_offset"]["selected_key"]):
        raise AmendmentError(
            "The offset plan differs from the original freeze; Amendment 002 "
            "reopens the timing track only.")
    payload["protocol_amendment_002"] = {
        "version": AMENDMENT_VERSION,
        "reopened_track": "optimized_fixed_timing",
        "offset_track": "byte-identical copies of the original artefacts",
        "frozen_commit": FROZEN_COMMIT,
        "driver_sha256": DRIVER_SHA256,
        "addendum_sha256": floor["addendum_sha256"],
        "amendment_001_sha256": AMENDMENT_001_SHA256,
        "floor_order_sha256": _sha256_file(layout.floor_order),
        "fine_order_sha256": _sha256_file(layout.fine_order),
        "supersedes": superseded,
        "withdrawn": (
            "The first Amendment-002 script and document are withdrawn: "
            "they deduplicated candidate_key labels, not realized plans."),
        "learner_rule": (
            "Only official learner runs whose run_manifest records "
            "authorising_artefact_sha256 equal to this file's SHA-256 enter "
            "learner validation."),
    }
    protocol_stages.assert_stage_allowed(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS)
    path = protocol_stages.write_stage_artefact(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS, payload)
    return {"artefact": path, "payload": payload,
            "artefact_sha256": _sha256_file(path)}


def amended_freeze_sha256(layout):
    artefact = protocol_stages.verify_stage_artefact(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS)
    if (artefact["payload"].get("protocol_amendment_002") or {}).get(
            "driver_sha256") != DRIVER_SHA256:
        raise AmendmentError("The freeze at {} is not this amendment's.".format(
            layout.state))
    return _sha256_file(protocol_stages.artefact_path(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS))


def training_command(layout, method, training_seed, output_directory=None,
                     require_clean=True):
    """The frozen trainer, authorised by the amended freeze and nothing else."""
    from adaptive_qmix.protocol import authorization
    verify_repository(layout, require_clean)
    if method not in ("qmix", "vdn", "idqn"):
        raise AmendmentError("Unknown method {!r}.".format(method))
    required = amended_freeze_sha256(layout)
    evidence = authorization.authorization_evidence(layout.state)
    if evidence["authorising_artefact_sha256"] != required:
        raise AmendmentError("Authorisation does not come from the amended "
                             "freeze.")
    output_directory = os.path.abspath(output_directory or os.path.join(
        layout.learners, method, "seed{}".format(int(training_seed))))
    for root in (layout.original_root, layout.audit_root,
                 layout.withdrawn_root):
        if _inside(output_directory, root):
            raise AmendmentError(
                "Learner output {} is inside protected root {}.".format(
                    output_directory, root))
    if os.path.exists(output_directory):
        raise AmendmentError(
            "{} already exists; an official run never reuses a directory."
            .format(output_directory))
    return [
        sys.executable, "-B",
        os.path.join(layout.repository_root, "scripts", "adaptive_qmix",
                     "train_adaptive.py"),
        "--method", method, "--training-seed", str(int(training_seed)),
        "--run-kind", "official_training",
        "--campaign-state", layout.state,
        "--output-directory", output_directory,
    ]


def verify_learners(layout, learner_root):
    required = amended_freeze_sha256(layout)
    accepted, excluded = [], []
    for directory, _dirs, files in os.walk(learner_root):
        if RUN_MANIFEST_FILENAME not in files:
            continue
        manifest = _read_json(os.path.join(directory, RUN_MANIFEST_FILENAME))
        if not manifest or not manifest.get("official_scientific_result"):
            continue
        entry = {
            "directory": directory,
            "method": manifest.get("method"),
            "training_seed": manifest.get("training_seed"),
            "authorising_artefact_sha256": manifest.get(
                "authorising_artefact_sha256"),
        }
        (accepted if entry["authorising_artefact_sha256"] == required
         else excluded).append(entry)
    return {"required_sha256": required, "accepted": accepted,
            "excluded": excluded}


def archive_withdrawn(withdrawn_root, archive_directory, extra_files=()):
    """Copy the withdrawn Amendment 002 read-only; never touch the source."""
    withdrawn_root = os.path.abspath(withdrawn_root)
    archive_directory = os.path.abspath(archive_directory)
    if _inside(archive_directory, withdrawn_root):
        raise AmendmentError("The archive may not be inside the withdrawn "
                             "root; nothing is written there.")
    if os.path.exists(archive_directory):
        raise AmendmentError("{} already exists.".format(archive_directory))
    sources = [os.path.join(withdrawn_root, name) for name in WITHDRAWN_FILES]
    sources += [os.path.abspath(path) for path in extra_files]
    missing = [path for path in sources if not os.path.isfile(path)]
    if missing:
        raise AmendmentError("Missing withdrawn files: {}".format(missing))
    before = dict((path, _sha256_file(path)) for path in sources)
    os.makedirs(archive_directory)
    lines = []
    for path in sources:
        target = os.path.join(archive_directory, os.path.basename(path))
        shutil.copy2(path, target)
        if _sha256_file(target) != before[path]:
            raise AmendmentError("Copy of {} does not verify.".format(path))
        lines.append("{}  {}".format(before[path], os.path.basename(path)))
    after = dict((path, _sha256_file(path)) for path in sources)
    if after != before:
        raise AmendmentError("A withdrawn source changed during archiving.")
    with open(os.path.join(archive_directory, "SHA256SUMS"), "w") as handle:
        handle.write("\n".join(lines) + "\n")
    with open(os.path.join(archive_directory, "README_WITHDRAWN.md"),
              "w") as handle:
        handle.write(WITHDRAWN_README.format(
            root=withdrawn_root, files="\n".join(
                "- `{}`".format(line) for line in lines)))
    return {"archive": archive_directory, "files": lines}


WITHDRAWN_README = """# WITHDRAWN: first Amendment 002 (timing track)

Status: WITHDRAWN. Never executed. Not evidence. Not an execution commit.

These files were copied byte for byte from `{root}`, which was not modified.

Reason: the fine search deduplicated candidates by `candidate_key` =
(C, split_thousandths, Delta), which is a label. It did not deduplicate by the
realized plan (C, g_H, g_V, Delta mod C). At C <= 35, half-up rounding maps
several split labels onto one plan. The 834 fine labels are 486 plans, the
208 boundary labels are 195 plans, and two of the five coarse "winners",
(20,550,10) and (20,600,10), are the same plan. Its counts (834 / 99 / 735 /
3675) are therefore withdrawn.

Superseded by: `amendment002.py` and `PROTOCOL_AMENDMENT_002_ADDENDUM.md`
(revised). Their hashes are recorded in the floor work order and the freeze.

SHA-256 at archive time:

{files}
"""


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

ACTIONS = (
    "precheck", "prepare-floor", "run-floor", "finalise-coarse", "run-fine",
    "finalise-fine", "run-validation", "finalise-validation", "freeze",
    "train-official", "verify-learners", "archive-withdrawn",
)


def print_precheck(result):
    existing, floor, no_op = (result["existing"], result["floor"],
                              result["no_op"])
    print("driver sha256            : {}".format(result["driver_sha256"]))
    print("frozen commit            : {} (clean)".format(FROZEN_COMMIT))
    print("R1 no-op on C >= 40      : coarse {} -> {}, fine {} -> {}, "
          "offset {} -> {} (labels -> realized plans)".format(
              *(no_op["original_coarse"] + no_op["original_fine"]
                + no_op["fixed_offset"])))
    print("existing coarse evidence : {} labels, {} runs verified (markers, "
          "environment incl. source_commit, clean-tree run manifests)".format(
              existing["labels"], existing["runs"]))
    print("software stack           : {}".format(dict(existing["stack"])))
    print("DISTINCT REALIZED PLANS  : {} ({} invalid) in the rebuilt coarse "
          "ranking".format(existing["realized_plans"],
                           existing["invalid_plans"]))
    aliases = existing["aliases"]
    print("equivalent-label groups  : {} groups, {} per-seed comparisons, "
          "max |diff| {:.3g} (tolerance {:g})".format(
              len(aliases["groups"]), aliases["checks"],
              aliases["max_abs_difference"], IDENTITY_TOLERANCE))
    scores = dict((tuple(r["key"]), r["mean_J_primary_s"])
                  for r in existing["records"])
    for group in aliases["groups"]:
        print("  {}  J={:.12f}".format(
            " == ".join(str(tuple(k)) for k in group),
            scores[tuple(group[0])]))
    print("audit report reproduced  : withdrawn label-rule ranking and "
          "best C<40 J={!r}".format(REPORTED_BEST_BELOW_40[1]))
    print("current best plan        : {}  J={:.12f}".format(
        describe(existing["leader"]["plan"]),
        existing["leader"]["mean_J_primary_s"]))
    print("(no top 5 is taken until the floor audit is in the ranking)")
    print("structural-floor audit   : C in {}, design seeds {} only".format(
        list(FLOOR_CYCLES_S), list(search.DESIGN_SEEDS)))
    for cycle, item in sorted(floor["per_cycle"].items()):
        print("  C={}: offsets {}  labels {}  realized plans {}  (gH,gV) {}"
              .format(cycle, item["offsets"], item["labels"],
                      item["realized_plans"], item["greens"]))
    print("  floor labels {} (+{} rejected by min green) -> UNIQUE PLANS {} "
          "-> REQUIRED RUNS {}".format(
              floor["labels"], floor["rejected_by_min_green"],
              floor["realized_plans"], floor["runs"]))
    for group in floor["groups"]:
        if len(group) > 1:
            print("  floor group: {}".format(
                " == ".join(str(tuple(k)) for k in group)))
    print("no C<20 run exists yet   : verified")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--action", required=True, choices=ACTIONS)
    parser.add_argument("--repository-root", default=REPOSITORY_ROOT)
    parser.add_argument("--original-root", default=DEFAULT_ORIGINAL_ROOT)
    parser.add_argument("--audit-root", default=DEFAULT_AUDIT_ROOT)
    parser.add_argument("--audit-runs", default=None)
    parser.add_argument("--withdrawn-root", default=DEFAULT_WITHDRAWN_ROOT)
    parser.add_argument("--amendment-root", default=DEFAULT_AMENDMENT_ROOT)
    parser.add_argument("--amendment-document", default=None)
    parser.add_argument("--archive-directory",
                        default=DEFAULT_ARCHIVE_DIRECTORY)
    parser.add_argument("--extra-withdrawn-file", action="append", default=[])
    parser.add_argument("--learner-root", default=None)
    parser.add_argument("--method", default=None)
    parser.add_argument("--training-seed", type=int, default=None)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args(argv)
    if _norm(args.repository_root) != _norm(REPOSITORY_ROOT):
        raise AmendmentError("--repository-root must be given once.")

    if args.action == "archive-withdrawn":
        result = archive_withdrawn(args.withdrawn_root, args.archive_directory,
                                   args.extra_withdrawn_file)
        print("archived to {}".format(result["archive"]))
        for line in result["files"]:
            print("  " + line)
        return 0

    layout = Layout(args.original_root, args.audit_root, args.amendment_root,
                    withdrawn_root=args.withdrawn_root,
                    audit_runs=args.audit_runs)
    config = load_config(layout.config_path)
    runtime = current_runtime()

    if args.action == "precheck":
        try:
            print_precheck(precheck(layout, config, runtime))
        except AmendmentError as error:
            print("PRECHECK FAIL: {}".format(error))
            return 1
        print("PRECHECK PASS (read-only: nothing was written)")
    elif args.action == "prepare-floor":
        prepare_floor(layout, config, args.amendment_document, runtime)
        print("floor order sealed: {}".format(layout.floor_order))
    elif args.action in ("run-floor", "run-fine", "run-validation"):
        from adaptive_qmix.baselines.runner import run_baseline
        import traci
        ledger = run_stage(
            layout, config, args.action.split("-", 1)[1], run_baseline, traci,
            args.shard_index, args.shard_count)
        counts = {}
        for entry in ledger:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        print("shard {} of {}: {}".format(
            args.shard_index, args.shard_count, counts))
    elif args.action == "finalise-coarse":
        result = finalise_coarse(layout, config, runtime)
        print("top 5 distinct realized plans:")
        for record in result["winners"]:
            print("  {}  J={:.12f}".format(describe(record["plan"]),
                                           record["mean_J_primary_s"]))
        fine = result["fine"]
        print("fine: {} labels -> {} realized plans; {} reused, {} new -> "
              "{} runs".format(fine["fine_labels"], fine["realized_plans"],
                               fine["reused_plans"], fine["new_plans"],
                               fine["new_runs"]))
    elif args.action == "finalise-fine":
        result = finalise_fine(layout, config, runtime)
        for record in result["retained"]:
            print("  {}  J={:.12f}".format(describe(record["plan"]),
                                           record["mean_J_primary_s"]))
    elif args.action == "finalise-validation":
        result = finalise_validation(layout, config, runtime)
        print("selected: {}  validation J={:.12f}".format(
            describe(result["selected"]["plan"]),
            result["selected"]["mean_J_primary_s"]))
    elif args.action == "freeze":
        result = freeze(layout, config, load_config(
            layout.adaptive_config_path))
        print("amended freeze: {}  sha256 {}".format(
            result["artefact"], result["artefact_sha256"]))
    elif args.action == "train-official":
        command = training_command(layout, args.method, args.training_seed)
        print(" ".join(command))
        return subprocess.call(command)
    elif args.action == "verify-learners":
        result = verify_learners(layout, args.learner_root or layout.learners)
        print("accepted: {}".format(len(result["accepted"])))
        for entry in result["excluded"]:
            print("EXCLUDED {} seed {}: {}".format(
                entry["method"], entry["training_seed"], entry["directory"]))
        return 1 if result["excluded"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
