"""Protocol Amendment 002: re-run the optimized-fixed-timing track, and only it.

This driver never modifies the frozen code. It imports the frozen package from
a checkout pinned at FROZEN_COMMIT and reuses its ranking, selection, marker
verification, artefact and freeze functions. Only three things are new here,
and each is documented in PROTOCOL_AMENDMENT_002_ADDENDUM.md before any run:

  1. The fine cycle clip is [20, 140] instead of [40, 140]. Nothing else in the
     fine geometry changes.

  2. Candidates are counted as EXECUTED PLANS. At C >= 40 every (C, split,
     Delta) key executes a different signal plan, so this is a no-op on the
     original campaign. At C <= 35 a 0.025 or 0.05 split step is smaller than
     one second of green, so several keys round half-up to the same greens and
     run the identical plan: two of the five audit "winners" are one plan, and
     the 834 amended fine keys are only 486 plans. Retention (coarse top 5,
     fine top 10) counts plans, and each plan is simulated once.

  3. A run that finishes but does not clear gets a hash-sealed failure marker.
     The frozen campaign writes no marker for it, so the frozen finaliser can
     only refuse the whole stage; here the candidate is simply INVALID, which
     is the frozen search rule.

Stages, in order. Nothing here can open final_test or learner_validation.

    precheck              read-only: verify evidence, print every count
    finalise-coarse       combined 1980 + 208 coarse artefact, work order
    run-fine              execute the new fine runs (shardable)
    finalise-fine         fine top 10, global baseline_design
    run-validation        top 10 x benchmark_validation 2101-2105 (shardable)
    finalise-validation   select with the frozen tie-break
    freeze                amended freeze_baseline_plans, in a NEW state dir
    verify-learners       which official learner runs the amended freeze
                          authorised; everything else is excluded
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys


FROZEN_COMMIT = "8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d"
DEFAULT_REPOSITORY = r"C:\Users\LENOVO\QMIX_Traffic_Coordination"
DEFAULT_ORIGINAL_ROOT = (
    r"D:\QMIX_Results\qualification_300m_medium_official"
)
DEFAULT_AUDIT_ROOT = (
    r"D:\QMIX_Results\qualification_300m_medium_boundary_audit_20260920"
)
DEFAULT_AMENDMENT_ROOT = (
    r"D:\QMIX_Results\qualification_300m_medium_timing_amendment_20260920"
)
AMENDMENT_001_SHA256 = (
    "edb9ec98281b6a9588fae96cfdf982eb90984b830b7fa815ad058160b3ba020a"
)


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
from adaptive_qmix.baselines.integrity import sha256_file  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.protocol import stages as protocol_stages  # noqa: E402


AMENDMENT_VERSION = "timing-amendment-002-1.0"

CONTROLLER = search.TIMING_CONTROLLER
DESIGN_FAMILY = search.DESIGN_FAMILY
VALIDATION_FAMILY = search.VALIDATION_FAMILY

AMENDED_CYCLE_BOUNDS_S = (20, 140)
AUDIT_CYCLES_S = (20, 25, 30, 35)

ORIGINAL_COARSE_COUNT = 1980
AUDIT_COARSE_ADMISSIBLE_COUNT = 208

# What the boundary audit reported under the frozen key-level rule. The
# combined evidence on disk must reproduce it, or it is not the evidence the
# reopen decision was taken on.
REPORTED_FROZEN_RULE_TOP_FIVE = [
    (20, 650, 10), (25, 650, 0), (25, 700, 0), (20, 550, 10), (20, 600, 10),
]

FAILURE_MARKER_FILENAME = "campaign_run.failed.json"
WORK_ORDER_FILENAME = "amendment002_work_order.json"
COPIED_ARTEFACTS = (
    campaign.shortlist_path("", campaign.OFFSET_DESIGN),
    campaign.selected_plan_path("", campaign.OFFSET_VALIDATION),
)

ROOT_ORIGINAL = "original"
ROOT_AUDIT = "audit"
ROOT_AMENDMENT = "amendment"


class AmendmentError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Grids. Pure functions of the frozen constants.
# ---------------------------------------------------------------------------

key_of = frozen_plans.candidate_key


def executed_identity(plan):
    """What SUMO is actually given. Split labels do not reach the executor."""
    return (
        int(plan["cycle_s"]), int(plan["green_H_s"]), int(plan["green_V_s"]),
        int(plan["yellow_s"]), int(plan["offset_s"]),
    )


def audit_coarse_candidates():
    """The Amendment-001 grid: C in 20..35, the frozen splits and offsets."""
    candidates = []
    for cycle_s in AUDIT_CYCLES_S:
        for split in frozen_plans.COARSE_SPLIT_THOUSANDTHS:
            for offset_s in range(0, cycle_s, frozen_plans.COARSE_OFFSET_STEP_S):
                plan = frozen_plans.make_plan(cycle_s, split, offset_s)
                if frozen_plans.candidate_is_valid(plan):
                    candidates.append(plan)
    return candidates


def fine_candidates(winners, cycle_bounds=AMENDED_CYCLE_BOUNDS_S,
                    include_invalid=False):
    """frozen plans.fine_timing_candidates with the cycle clip as a parameter.

    Line for line the frozen generator; with cycle_bounds=(40, 140) it returns
    exactly what the frozen function returns, in the same order (tested).
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


def plan_classes(plans, prior_keys=frozenset()):
    """Group keys that execute the same plan.

    The representative is chosen structurally, never by score: the lowest key
    among members that an earlier preregistered grid already evaluated, else
    the lowest key. Aliases score identically, so the choice changes which
    runs are needed, not what is ranked.
    """
    groups = {}
    for plan in plans:
        groups.setdefault(executed_identity(plan), []).append(dict(plan))
    classes = []
    for identity, members in groups.items():
        members.sort(key=key_of)
        representative = min(
            members, key=lambda p: (key_of(p) not in prior_keys, key_of(p))
        )
        classes.append({
            "identity": identity,
            "representative": representative,
            "members": members,
        })
    classes.sort(key=lambda item: key_of(item["representative"]))
    return classes


# ---------------------------------------------------------------------------
# Hash-sealed files.
# ---------------------------------------------------------------------------

def _sha256_payload(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _write_sealed(path, payload, seal_field="payload_sha256"):
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


# ---------------------------------------------------------------------------
# Layout and evidence.
# ---------------------------------------------------------------------------

class Layout(object):
    def __init__(self, original_root, audit_root, amendment_root,
                 audit_runs=None, config_path=None, adaptive_config_path=None,
                 repository_root=REPOSITORY_ROOT):
        self.repository_root = os.path.abspath(repository_root)
        self.original_root = os.path.abspath(original_root)
        self.audit_root = os.path.abspath(audit_root)
        self.amendment_root = os.path.abspath(amendment_root)
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
        self.work_order = os.path.join(self.artefacts, WORK_ORDER_FILENAME)
        self.config_path = config_path or os.path.join(
            self.repository_root, "config", "adaptive_qmix",
            "baselines_300m_medium.json",
        )
        self.adaptive_config_path = adaptive_config_path or os.path.join(
            self.repository_root, "config", "adaptive_qmix",
            "qualification_300m_medium.json",
        )
        if len(set([self.original_root, self.audit_root,
                    self.amendment_root])) != 3:
            raise AmendmentError(
                "The original, audit and amendment roots must be three "
                "different directories."
            )

    def runs_for(self, designation):
        return {
            ROOT_ORIGINAL: self.original_runs,
            ROOT_AUDIT: self.audit_runs,
            ROOT_AMENDMENT: self.runs,
        }[designation]


def verify_repository(layout, require_clean=True):
    """The frozen code, and nothing else, must be what is imported."""
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
    return head


def failure_marker_problems(run_directory, plan, family, seed, manifest,
                            environment):
    """Like campaign.completion_problems, for a verified clearance failure."""
    path = os.path.join(run_directory, FAILURE_MARKER_FILENAME)
    marker = _read_sealed(path, seal_field="marker_sha256") if (
        os.path.isfile(path)
    ) else None
    if marker is None:
        return ["no failure marker"]
    problems = []
    expected = {
        "controller": CONTROLLER,
        "candidate_key": list(key_of(plan)),
        "traffic_family": family,
        "traffic_seed": int(seed),
        "manifest_csv_sha256": manifest["manifest_csv_sha256"],
        "route_xml_sha256": manifest["route_xml_sha256"],
        "sumo_seed": int(manifest["sumo_seed"]),
        "environment": dict(environment),
        "clearance_status": "CLEARANCE_FAILURE",
    }
    for field, value in sorted(expected.items()):
        found = marker.get(field)
        if field == "candidate_key" and found is not None:
            found = list(found)
        if found != value:
            problems.append("failure marker {} is {!r}, needs {!r}".format(
                field, found, value))
    metrics_path = os.path.join(run_directory, campaign.METRICS_FILENAME)
    if not os.path.isfile(metrics_path):
        return problems + ["evaluation_metrics.json is absent"]
    if marker.get("metrics_sha256") != sha256_file(metrics_path):
        problems.append("evaluation_metrics.json changed after the marker")
    return problems


def write_failure_marker(run_directory, plan, family, seed, manifest,
                         environment, metrics):
    metrics_path = os.path.join(run_directory, campaign.METRICS_FILENAME)
    return _write_sealed(
        os.path.join(run_directory, FAILURE_MARKER_FILENAME),
        {
            "amendment_version": AMENDMENT_VERSION,
            "controller": CONTROLLER,
            "candidate_key": list(key_of(plan)),
            "plan": dict(plan),
            "traffic_family": family,
            "traffic_seed": int(seed),
            "manifest_csv_sha256": manifest["manifest_csv_sha256"],
            "route_xml_sha256": manifest["route_xml_sha256"],
            "sumo_seed": int(manifest["sumo_seed"]),
            "metrics_sha256": sha256_file(metrics_path),
            "clearance_status": metrics.get("clearance_status"),
            "environment": dict(environment),
        },
        seal_field="marker_sha256",
    )


class Evidence(object):
    """Verified runs, each read from the one root designated for its key."""

    def __init__(self, layout, config, designations):
        self.layout = layout
        self.config = config
        self.designations = dict(designations)
        self.environment = campaign.environment_identity(
            config, layout.repository_root
        )
        self._manifests = {}

    def manifests(self, family):
        if family not in self._manifests:
            self._manifests[family] = campaign.load_seed_manifests(
                self.layout.original_manifests, self.config, family
            )
        return self._manifests[family]

    def designation(self, plan):
        return self.designations.get(key_of(plan), ROOT_AMENDMENT)

    def run(self, plan, family, seed):
        """(metrics, None) for a verified run, or (None, problems)."""
        manifest = self.manifests(family)[int(seed)]
        directory = campaign.run_directory_for(
            self.layout.runs_for(self.designation(plan)), CONTROLLER, plan,
            family, seed,
        )
        problems = campaign.completion_problems(
            directory, CONTROLLER, plan, family, seed,
            manifest["manifest_csv_sha256"], manifest["route_xml_sha256"],
            manifest["sumo_seed"], self.environment,
        )
        if not problems:
            return campaign._load_metrics(directory), None
        failure = failure_marker_problems(
            directory, plan, family, seed, manifest, self.environment
        )
        if not failure:
            return campaign._load_metrics(directory), None
        return None, {
            "candidate_key": list(key_of(plan)), "traffic_seed": int(seed),
            "run_directory": directory, "problems": problems,
        }

    def runs(self, plan, family):
        runs, problems = [], []
        for seed in search.required_seeds(family):
            metrics, problem = self.run(plan, family, seed)
            if problem is not None:
                problems.append(problem)
            else:
                runs.append(metrics)
        return runs, problems


def _outcome(run):
    return (
        run.get("clearance_status"),
        run.get(search.PRIMARY_FIELD),
        run.get(search.TIME_LOSS_FIELD),
    )


def score_classes(evidence, classes, family, check_aliases=True):
    """One frozen search record per executed plan, aliases cross-checked.

    Every member that has a designated earlier root is read, and its per-seed
    outcome must equal the representative's exactly. That is the empirical
    check that a split label cannot change a run; if it ever fails, the
    collapse is wrong and the stage stops.
    """
    records, problems, alias_checks = [], [], 0
    pairing = []
    for item in classes:
        representative = item["representative"]
        runs, missing = evidence.runs(representative, family)
        problems.extend(missing)
        if missing:
            continue
        for member in item["members"]:
            if key_of(member) == key_of(representative) or not check_aliases:
                continue
            if evidence.designation(member) == ROOT_AMENDMENT:
                continue
            member_runs, member_missing = evidence.runs(member, family)
            if member_missing:
                problems.extend(member_missing)
                continue
            for mine, theirs in zip(runs, member_runs):
                alias_checks += 1
                if _outcome(mine) != _outcome(theirs):
                    raise AmendmentError(
                        "Keys {} and {} execute the same plan {} but "
                        "recorded different outcomes on seed {}: {} versus "
                        "{}. A split label must not change a run; the "
                        "executed-plan collapse is invalid.".format(
                            key_of(representative), key_of(member),
                            item["identity"], mine.get("traffic_seed"),
                            _outcome(mine), _outcome(theirs),
                        )
                    )
        record = search.summarise_candidate(
            representative, runs, family, CONTROLLER
        )
        record["members"] = [list(key_of(m)) for m in item["members"]]
        record["identity"] = list(item["identity"])
        records.append(record)
        pairing.append((key_of(representative), runs))
    if not problems:
        search.assert_stage_traffic_pairing(pairing, family)
    return records, problems, alias_checks


def _scores(records):
    return [
        {
            "key": list(record["key"]),
            "valid": record["valid"],
            "mean_J_primary_s": record["mean_J_primary_s"],
            "mean_time_loss_s": record["mean_time_loss_s"],
            "failed_seeds": record["failed_seeds"],
            "alias_keys": [k for k in record["members"]
                           if k != list(record["key"])],
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
# Coarse: 1980 original + 208 audit, scored as executed plans.
# ---------------------------------------------------------------------------

def coarse_sets():
    original = frozen_plans.coarse_timing_candidates()
    audit = audit_coarse_candidates()
    if len(original) != ORIGINAL_COARSE_COUNT:
        raise AmendmentError("Original coarse grid is not 1980 plans.")
    if len(audit) != AUDIT_COARSE_ADMISSIBLE_COUNT:
        raise AmendmentError("Audit coarse grid is not 208 admissible plans.")
    if set(map(key_of, original)) & set(map(key_of, audit)):
        raise AmendmentError("The original and audit grids overlap.")
    return original, audit


def original_fine_keys(layout):
    """The original fine grid, regenerated from its own sealed artefact."""
    artefact = campaign.read_shortlist_artefact(
        layout.original_artefacts, campaign.TIMING_COARSE_DESIGN
    )
    return set(map(key_of, frozen_plans.fine_timing_candidates(
        artefact["plans"]
    )))


def designations(layout):
    """Which root holds each earlier key's evidence. Structural, not scanned."""
    original, audit = coarse_sets()
    mapping = {}
    for key in original_fine_keys(layout):
        mapping[key] = ROOT_ORIGINAL
    for plan in original:
        mapping[key_of(plan)] = ROOT_ORIGINAL
    for plan in audit:
        mapping[key_of(plan)] = ROOT_AUDIT
    return mapping


def evaluate_coarse(layout, config):
    original, audit = coarse_sets()
    evidence = Evidence(layout, config, designations(layout))
    every_key = original + audit
    classes = plan_classes(every_key, prior_keys=set(map(key_of, every_key)))
    records, problems, alias_checks = score_classes(
        evidence, classes, DESIGN_FAMILY
    )
    _fail_on(problems, "Combined coarse evidence")
    # The key-level ranking the audit reported, reconstructed from the same
    # verified runs: aliases carry their representative's record.
    by_identity = dict((tuple(r["identity"]), r) for r in records)
    key_records = []
    for plan in every_key:
        record = dict(by_identity[executed_identity(plan)])
        record["key"] = key_of(plan)
        key_records.append(record)
    frozen_rule_top_five = [
        tuple(r["key"]) for r in search.rank_by_design(
            key_records, search.COARSE_RETAINED
        )
    ]
    if frozen_rule_top_five != REPORTED_FROZEN_RULE_TOP_FIVE:
        raise AmendmentError(
            "The verified evidence ranks {} under the frozen key rule, but "
            "the boundary audit reported {}. These are not the runs the "
            "reopen decision rested on.".format(
                frozen_rule_top_five, REPORTED_FROZEN_RULE_TOP_FIVE
            )
        )
    winners = search.rank_by_design(records, search.COARSE_RETAINED)
    return {
        "records": records,
        "classes": classes,
        "winners": winners,
        "frozen_rule_top_five": frozen_rule_top_five,
        "key_count": len(every_key),
        "run_count": len(every_key) * len(search.DESIGN_SEEDS),
        "alias_checks": alias_checks,
        "environment": evidence.environment,
    }


def fine_plan(layout, winner_plans):
    """The amended fine grid, its executed plans, and the runs still needed."""
    fine = fine_candidates(winner_plans)
    fine_all = fine_candidates(winner_plans, include_invalid=True)
    mapping = designations(layout)
    classes = plan_classes(fine, prior_keys=set(mapping))
    reuse = [c for c in classes
             if mapping.get(key_of(c["representative"])) is not None]
    new = [c for c in classes
           if mapping.get(key_of(c["representative"])) is None]
    seeds = len(search.DESIGN_SEEDS)
    return {
        "winners": [dict(p) for p in winner_plans],
        "cycle_bounds_s": list(AMENDED_CYCLE_BOUNDS_S),
        "fine_key_count": len(fine),
        "rejected_by_min_green": len(fine_all) - len(fine),
        "executed_plan_count": len(classes),
        "alias_key_count": len(fine) - len(classes),
        "keys_with_earlier_evidence": sum(
            1 for p in fine if key_of(p) in mapping
        ),
        "reused_plan_count": len(reuse),
        "reused_run_count": len(reuse) * seeds,
        "new_plan_count": len(new),
        "new_run_count": len(new) * seeds,
        "validation_run_count": search.FINE_RETAINED * len(
            search.VALIDATION_SEEDS
        ),
        "classes": [
            {
                "representative": c["representative"],
                "members": [list(key_of(m)) for m in c["members"]],
                "identity": list(c["identity"]),
                "evidence_root": mapping.get(
                    key_of(c["representative"]), ROOT_AMENDMENT
                ),
            }
            for c in classes
        ],
        "new_work": [c["representative"] for c in new],
    }


def _classes_from_work_order(order):
    return [
        {
            "identity": tuple(item["identity"]),
            "representative": item["representative"],
            "members": [
                frozen_plans.make_plan(*member) for member in item["members"]
            ],
        }
        for item in order["fine"]["classes"]
    ]


# ---------------------------------------------------------------------------
# Guards.
# ---------------------------------------------------------------------------

def scan_for_leakage(layout):
    """No held-out traffic anywhere; no validation traffic in the audit.

    The reopen decision must have rested on design seeds alone, so the audit
    root may not hold a single benchmark_validation run.
    """
    problems = []
    forbidden = ("final_test", "learner_validation")
    for root in (layout.original_root, layout.audit_root,
                 layout.amendment_root):
        for sub in ("manifests", "runs"):
            directory = os.path.join(root, sub)
            if sub == "runs" and root == layout.audit_root:
                directory = layout.audit_runs
            if not os.path.isdir(directory):
                continue
            names = list(os.listdir(directory))
            if sub == "runs":
                for candidate in list(names):
                    path = os.path.join(directory, candidate)
                    if os.path.isdir(path):
                        names.extend(os.listdir(path))
            for name in names:
                if any(token in name for token in forbidden):
                    problems.append(os.path.join(directory, name))
                if root == layout.audit_root and (
                    VALIDATION_FAMILY in name
                ):
                    problems.append(os.path.join(directory, name))
    if problems:
        raise AmendmentError(
            "Held-out or validation traffic where none may exist: {}".format(
                problems[:5]
            )
        )
    return True


def refuse_original_state(layout):
    if os.path.abspath(layout.state) == os.path.abspath(layout.original_state):
        raise AmendmentError("The amended state directory is the original.")
    return True


# ---------------------------------------------------------------------------
# Stages.
# ---------------------------------------------------------------------------

def precheck(layout, config, require_clean=True):
    verify_repository(layout, require_clean)
    scan_for_leakage(layout)
    refuse_original_state(layout)
    coarse = evaluate_coarse(layout, config)
    fine = fine_plan(layout, [r["plan"] for r in coarse["winners"]])
    return {"coarse": coarse, "fine": fine}


def finalise_coarse(layout, config, require_clean=True):
    """Seal the combined coarse shortlist and the fine work order, once."""
    if os.path.exists(layout.work_order):
        read_work_order(layout)
        raise AmendmentError(
            "The coarse stage is already finalised and its work order "
            "verifies; it is never re-derived. Use precheck to re-inspect."
        )
    result = precheck(layout, config, require_clean)
    coarse, fine = result["coarse"], result["fine"]
    records = coarse["records"]
    derivation = {
        "expected_candidate_count": len(records),
        "expected_run_count": len(records) * len(search.DESIGN_SEEDS),
        "verified_run_count": len(records) * len(search.DESIGN_SEEDS),
        "seeds": list(search.DESIGN_SEEDS),
        "family": DESIGN_FAMILY,
        "controller": CONTROLLER,
        "environment": coarse["environment"],
        "ranking": (
            "search.rank_by_design on mean design J_primary, one record per "
            "executed plan (Amendment 002)"
        ),
        "scores": _scores(records),
        "derived_from_stage": None,
        "amendment_002": {
            "version": AMENDMENT_VERSION,
            "key_count": coarse["key_count"],
            "verified_key_run_count": coarse["run_count"],
            "sources": {
                "original": {"runs": layout.original_runs,
                             "keys": ORIGINAL_COARSE_COUNT},
                "audit": {"runs": layout.audit_runs,
                          "keys": AUDIT_COARSE_ADMISSIBLE_COUNT},
            },
            "frozen_rule_top_five": [
                list(k) for k in coarse["frozen_rule_top_five"]
            ],
            "alias_outcome_checks": coarse["alias_checks"],
        },
    }
    _copy_offset_artefacts(layout)
    campaign._write_shortlist_artefact(
        layout.artefacts, campaign.TIMING_COARSE_DESIGN,
        [r["plan"] for r in coarse["winners"]],
        {"ranked_on": DESIGN_FAMILY, "seeds": list(search.DESIGN_SEEDS),
         "protocol": "design ranks; validation selects"},
        derivation,
    )
    order = {
        "amendment_version": AMENDMENT_VERSION,
        "frozen_commit": FROZEN_COMMIT,
        "coarse_artefact_sha256": sha256_file(campaign.shortlist_path(
            layout.artefacts, campaign.TIMING_COARSE_DESIGN
        )),
        "fine": dict((k, v) for k, v in fine.items()),
    }
    _write_sealed(layout.work_order, order)
    return result


def _copy_offset_artefacts(layout):
    """The offset track is reused byte for byte, not re-derived."""
    for name in COPIED_ARTEFACTS:
        source = os.path.join(layout.original_artefacts, name)
        target = os.path.join(layout.artefacts, name)
        if not os.path.isfile(source):
            raise AmendmentError("Missing original artefact {}.".format(source))
        if os.path.isfile(target):
            if sha256_file(target) != sha256_file(source):
                raise AmendmentError(
                    "{} differs from the original offset artefact.".format(
                        target
                    )
                )
            continue
        if not os.path.isdir(layout.artefacts):
            os.makedirs(layout.artefacts)
        shutil.copyfile(source, target)
    campaign.read_shortlist_artefact(layout.artefacts, campaign.OFFSET_DESIGN)
    campaign.read_selected_plan_artefact(
        layout.artefacts, campaign.OFFSET_VALIDATION
    )


def verify_offset_copies(layout):
    for name in COPIED_ARTEFACTS:
        if sha256_file(os.path.join(layout.artefacts, name)) != sha256_file(
            os.path.join(layout.original_artefacts, name)
        ):
            raise AmendmentError(
                "{} is no longer the original offset artefact.".format(name)
            )
    return True


def read_work_order(layout):
    order = _read_sealed(layout.work_order)
    if order is None:
        raise AmendmentError("No work order; run finalise-coarse first.")
    artefact = campaign.read_shortlist_artefact(
        layout.artefacts, campaign.TIMING_COARSE_DESIGN
    )
    if sha256_file(campaign.shortlist_path(
        layout.artefacts, campaign.TIMING_COARSE_DESIGN
    )) != order["coarse_artefact_sha256"]:
        raise AmendmentError("The coarse artefact changed after the order.")
    regenerated = fine_plan(layout, artefact["plans"])
    if regenerated != order["fine"]:
        raise AmendmentError(
            "The work order does not regenerate from the sealed coarse "
            "winners; it has been edited or the code changed."
        )
    return order


def guarded_runner(runner, layout, config):
    """Record a completed-but-uncleared run as a verified failure, once."""
    environment = campaign.environment_identity(config, layout.repository_root)

    def run(traci_module, config_ref, repository_root, controller,
            manifest_csv_path, route_xml_path, family, seed, sumo_seed,
            output_directory, plan=None, **kwargs):
        search.assert_family_allowed(family, [seed])
        manifest = {
            "manifest_csv_sha256": sha256_file(manifest_csv_path),
            "route_xml_sha256": sha256_file(route_xml_path),
            "sumo_seed": int(sumo_seed),
        }
        if not failure_marker_problems(
            output_directory, plan, family, seed, manifest, environment
        ):
            return campaign._load_metrics(output_directory)
        metrics = runner(
            traci_module, config_ref, repository_root, controller,
            manifest_csv_path, route_xml_path, family, seed, sumo_seed,
            output_directory, plan=plan, **kwargs
        )
        if metrics and metrics.get("clearance_status") == "CLEARANCE_FAILURE":
            write_failure_marker(
                output_directory, plan, family, seed, manifest, environment,
                metrics,
            )
        return metrics
    return run


def run_stage(layout, config, stage, runner, traci_module=None,
              shard_index=0, shard_count=1):
    if stage == "fine":
        family = DESIGN_FAMILY
        plans = read_work_order(layout)["fine"]["new_work"]
    elif stage == "validation":
        family = VALIDATION_FAMILY
        plans = campaign.read_shortlist_artefact(
            layout.artefacts, campaign.TIMING_FINE_DESIGN
        )["plans"]
    else:
        raise AmendmentError("Unknown stage {!r}.".format(stage))
    ledger_directory = os.path.join(layout.runs, "ledgers_" + stage)
    return campaign.execute_campaign(
        guarded_runner(runner, layout, config), CONTROLLER, plans, family,
        config, layout.runs, layout.original_manifests,
        layout.repository_root, shard_index=shard_index,
        shard_count=shard_count, traci_module=traci_module,
        ledger_directory=ledger_directory, allow_manifest_generation=False,
    )


def finalise_fine(layout, config, require_clean=True):
    verify_repository(layout, require_clean)
    order = read_work_order(layout)
    coarse_artefact = campaign.read_shortlist_artefact(
        layout.artefacts, campaign.TIMING_COARSE_DESIGN
    )
    classes = _classes_from_work_order(order)
    evidence = Evidence(layout, config, designations(layout))
    records, problems, alias_checks = score_classes(
        evidence, classes, DESIGN_FAMILY
    )
    _fail_on(problems, "Amended fine stage")
    retained = search.rank_by_design(records, search.FINE_RETAINED)
    derivation = {
        "expected_candidate_count": len(records),
        "expected_run_count": len(records) * len(search.DESIGN_SEEDS),
        "verified_run_count": len(records) * len(search.DESIGN_SEEDS),
        "seeds": list(search.DESIGN_SEEDS),
        "family": DESIGN_FAMILY,
        "controller": CONTROLLER,
        "environment": evidence.environment,
        "ranking": (
            "search.rank_by_design on mean design J_primary, one record per "
            "executed plan (Amendment 002)"
        ),
        "scores": _scores(records),
        "derived_from_stage": coarse_artefact["stage"],
        "amendment_002": {
            "version": AMENDMENT_VERSION,
            "work_order_sha256": sha256_file(layout.work_order),
            "fine_key_count": order["fine"]["fine_key_count"],
            "reused_plan_count": order["fine"]["reused_plan_count"],
            "new_plan_count": order["fine"]["new_plan_count"],
            "alias_outcome_checks": alias_checks,
        },
    }
    campaign._write_shortlist_artefact(
        layout.artefacts, campaign.TIMING_FINE_DESIGN,
        [r["plan"] for r in retained],
        {"ranked_on": DESIGN_FAMILY, "seeds": list(search.DESIGN_SEEDS),
         "protocol": "design ranks; validation selects"},
        derivation,
    )
    refuse_original_state(layout)
    completion = campaign.complete_global_stage(
        protocol_stages.BASELINE_DESIGN, layout.artefacts, layout.state
    )
    return {"retained": retained, "records": records,
            "global_stage": completion}


def finalise_validation(layout, config, require_clean=True):
    verify_repository(layout, require_clean)
    fine_artefact = campaign.read_shortlist_artefact(
        layout.artefacts, campaign.TIMING_FINE_DESIGN
    )
    protocol_stages.assert_stage_allowed(
        layout.state, protocol_stages.BASELINE_VALIDATION
    )
    finalists = [dict(p) for p in fine_artefact["plans"]]
    evidence = Evidence(layout, config, {})
    classes = [{"identity": executed_identity(p), "representative": p,
                "members": [p]} for p in finalists]
    records, problems, _ = score_classes(
        evidence, classes, VALIDATION_FAMILY, check_aliases=False
    )
    _fail_on(problems, "Amended timing validation")
    if len(records) != search.FINE_RETAINED:
        raise AmendmentError("Validation must score exactly 10 finalists.")
    selected = search.select_timing_plan(records)
    derivation = {
        "expected_candidate_count": len(records),
        "expected_run_count": len(records) * len(search.VALIDATION_SEEDS),
        "verified_run_count": len(records) * len(search.VALIDATION_SEEDS),
        "seeds": list(search.VALIDATION_SEEDS),
        "family": VALIDATION_FAMILY,
        "controller": CONTROLLER,
        "environment": evidence.environment,
        "ranking": "search.select_timing_plan (frozen tie-break)",
        "scores": _scores(records),
        "derived_from_stage": fine_artefact["stage"],
    }
    campaign._write_selected_plan_artefact(
        layout.artefacts, campaign.TIMING_VALIDATION, CONTROLLER, selected,
        derivation, config, layout.repository_root, fine_artefact,
    )
    completion = campaign.complete_global_stage(
        protocol_stages.BASELINE_VALIDATION, layout.artefacts, layout.state
    )
    return {"selected": selected, "records": records,
            "global_stage": completion}


def freeze(layout, config, adaptive_config, amendment_document=None,
           require_clean=True):
    verify_repository(layout, require_clean)
    refuse_original_state(layout)
    verify_offset_copies(layout)
    target = protocol_stages.artefact_path(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS
    )
    if os.path.exists(target):
        raise AmendmentError(
            "{} already exists. write_stage_artefact overwrites silently, so "
            "a second freeze is refused here.".format(target)
        )
    payload = campaign.build_baseline_freeze_payload(
        layout.artefacts, config, layout.repository_root, adaptive_config
    )
    original_freeze = protocol_stages.artefact_path(
        layout.original_state, protocol_stages.FREEZE_BASELINE_PLANS
    )
    superseded = None
    if os.path.isfile(original_freeze):
        with open(original_freeze, "r") as handle:
            old = json.load(handle).get("payload", {})
        superseded = {
            "artefact_path": original_freeze,
            "artefact_sha256": sha256_file(original_freeze),
            "optimized_fixed_timing_key": (
                old.get("optimized_fixed_timing", {}).get("selected_key")
            ),
            "optimized_fixed_offset_key": (
                old.get("optimized_fixed_offset", {}).get("selected_key")
            ),
        }
        if superseded["optimized_fixed_offset_key"] != (
            payload["optimized_fixed_offset"]["selected_key"]
        ):
            raise AmendmentError(
                "The offset plan differs from the original freeze; Amendment "
                "002 reopens the timing track only."
            )
    payload["protocol_amendment_002"] = {
        "version": AMENDMENT_VERSION,
        "reopened_track": "optimized_fixed_timing",
        "offset_track": "reused byte-identical from the original campaign",
        "amendment_001_sha256": AMENDMENT_001_SHA256,
        "amendment_002_document_sha256": (
            sha256_file(amendment_document) if amendment_document else None
        ),
        "work_order_sha256": sha256_file(layout.work_order),
        "supersedes": superseded,
        "learner_rule": (
            "Only official learner runs whose run_manifest records "
            "authorising_artefact_sha256 equal to this file's SHA-256 enter "
            "learner validation; every other run is excluded."
        ),
    }
    protocol_stages.assert_stage_allowed(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS
    )
    path = protocol_stages.write_stage_artefact(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS, payload
    )
    return {"artefact": path, "payload": payload,
            "artefact_sha256": sha256_file(path)}


def verify_learners(layout, learner_root):
    """Split official learner runs into authorised-by-amendment and excluded."""
    freeze_path = protocol_stages.artefact_path(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS
    )
    protocol_stages.verify_stage_artefact(
        layout.state, protocol_stages.FREEZE_BASELINE_PLANS
    )
    required = sha256_file(freeze_path)
    accepted, excluded = [], []
    for directory, _dirs, files in os.walk(learner_root):
        if "run_manifest.json" not in files:
            continue
        with open(os.path.join(directory, "run_manifest.json"), "r") as h:
            manifest = json.load(h)
        if not manifest.get("official_scientific_result"):
            continue
        entry = {
            "directory": directory,
            "method": manifest.get("method"),
            "training_seed": manifest.get("training_seed"),
            "authorising_artefact_sha256": manifest.get(
                "authorising_artefact_sha256"
            ),
        }
        (accepted if entry["authorising_artefact_sha256"] == required
         else excluded).append(entry)
    return {"required_sha256": required, "accepted": accepted,
            "excluded": excluded}


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

ACTIONS = (
    "precheck", "finalise-coarse", "run-fine", "finalise-fine",
    "run-validation", "finalise-validation", "freeze", "verify-learners",
)


def _print_counts(result):
    coarse, fine = result["coarse"], result["fine"]
    print("combined coarse: {} keys, {} runs verified, {} executed plans, "
          "{} alias outcome checks passed".format(
              coarse["key_count"], coarse["run_count"],
              len(coarse["records"]), coarse["alias_checks"]))
    print("frozen key-rule top five (as the audit reported): {}".format(
        coarse["frozen_rule_top_five"]))
    print("executed-plan top five (seeds the fine grid):")
    for record in coarse["winners"]:
        print("  {}  J={:.6f}  aliases={}".format(
            tuple(record["key"]), record["mean_J_primary_s"],
            [tuple(k) for k in record["members"]
             if tuple(k) != tuple(record["key"])]))
    print("amended fine keys        : {} ({} rejected by the 5 s min "
          "green)".format(fine["fine_key_count"],
                          fine["rejected_by_min_green"]))
    print("keys with earlier runs   : {}".format(
        fine["keys_with_earlier_evidence"]))
    print("executed plans           : {} ({} alias keys)".format(
        fine["executed_plan_count"], fine["alias_key_count"]))
    print("reused plans             : {} => {} runs".format(
        fine["reused_plan_count"], fine["reused_run_count"]))
    print("new plans                : {} => {} runs".format(
        fine["new_plan_count"], fine["new_run_count"]))
    print("later validation         : 10 x 5 = {} runs".format(
        fine["validation_run_count"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--action", required=True, choices=ACTIONS)
    parser.add_argument("--repository-root", default=REPOSITORY_ROOT)
    parser.add_argument("--original-root", default=DEFAULT_ORIGINAL_ROOT)
    parser.add_argument("--audit-root", default=DEFAULT_AUDIT_ROOT)
    parser.add_argument("--audit-runs", default=None)
    parser.add_argument("--amendment-root", default=DEFAULT_AMENDMENT_ROOT)
    parser.add_argument("--amendment-document", default=None)
    parser.add_argument("--learner-root", default=None)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args(argv)
    if os.path.abspath(args.repository_root) != REPOSITORY_ROOT:
        raise AmendmentError("--repository-root must be given once.")

    layout = Layout(args.original_root, args.audit_root, args.amendment_root,
                    audit_runs=args.audit_runs)
    config = load_config(layout.config_path)

    if args.action == "precheck":
        _print_counts(precheck(layout, config))
        print("AMENDMENT 002 PRECHECK PASS (nothing was written)")
    elif args.action == "finalise-coarse":
        _print_counts(finalise_coarse(layout, config))
        print("coarse artefact and work order sealed in {}".format(
            layout.artefacts))
    elif args.action in ("run-fine", "run-validation"):
        verify_repository(layout)
        from adaptive_qmix.baselines.runner import run_baseline
        import traci
        ledger = run_stage(
            layout, config, args.action.split("-", 1)[1], run_baseline,
            traci, args.shard_index, args.shard_count,
        )
        counts = {}
        for entry in ledger:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        print("shard {} of {}: {}".format(
            args.shard_index, args.shard_count, counts))
    elif args.action == "finalise-fine":
        result = finalise_fine(layout, config)
        print("fine top 10 (executed plans):")
        for record in result["retained"]:
            print("  {}  J={:.6f}".format(
                tuple(record["key"]), record["mean_J_primary_s"]))
        print("global baseline_design: {}".format(result["global_stage"]))
    elif args.action == "finalise-validation":
        result = finalise_validation(layout, config)
        print("selected: {}  validation J={:.6f}".format(
            tuple(result["selected"]["key"]),
            result["selected"]["mean_J_primary_s"]))
    elif args.action == "freeze":
        adaptive = load_config(layout.adaptive_config_path)
        result = freeze(layout, config, adaptive, args.amendment_document)
        print("amended freeze: {}".format(result["artefact"]))
        print("  sha256: {}".format(result["artefact_sha256"]))
        for track in ("optimized_fixed_offset", "optimized_fixed_timing"):
            print("  {:22s}: {}".format(
                track, result["payload"][track]["selected_key"]))
        print("official training must pass --campaign-state {}".format(
            layout.state))
    elif args.action == "verify-learners":
        if not args.learner_root:
            raise AmendmentError("--learner-root is required.")
        result = verify_learners(layout, args.learner_root)
        print("accepted: {}".format(len(result["accepted"])))
        for entry in result["excluded"]:
            print("EXCLUDED {} seed {}: {}".format(
                entry["method"], entry["training_seed"], entry["directory"]))
        return 1 if result["excluded"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
