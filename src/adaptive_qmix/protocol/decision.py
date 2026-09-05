"""The GO/NO-GO rule, written down before any result exists.

Everything a result could tempt someone to adjust is fixed here and hashed:
which comparisons decide, which direction counts as success, which are
reported but do not decide, and what is deliberately absent.

    PRIMARY      dJ_OFT  = J_QMIX - J_optimized_fixed_timing
                 GO requires the paired crossed 95% CI to lie entirely
                 below zero.

    COOPERATION  dJ_IDQN = J_QMIX - J_IDQN
                 GO also requires its 95% CI to lie entirely below zero. This
                 is what distinguishes cooperative value from "a learned
                 controller beats a fixed plan", which independent learners
                 could also achieve.

    MIXER        dJ_VDN  = J_QMIX - J_VDN
                 Reported with its CI whether or not it excludes zero. A null
                 result here is a finding about the mixer, not a failure, and
                 it does not gate GO.

    MAX PRESSURE mandatory to run and report. QMIX is NOT required to beat
                 canonical operational max pressure for GO: a strong
                 operational baseline may well win, and hiding that by making
                 it a gate would be choosing the conclusion.

    P-5          matched-authority diagnostic, never an eighth controller and
                 never a GO criterion.

There is deliberately NO percentage-improvement threshold. A minimum effect
size chosen without a preregistered justification is a threshold chosen to fit
whatever the data turn out to be; the CI excluding zero is the criterion, and
the effect size is reported so a reader can judge its practical relevance
themselves.
"""

from __future__ import absolute_import

import hashlib
import json

from . import behaviour, statistics


PROTOCOL_VERSION = "go-no-go-1.0"

PRIMARY_METRIC = "J_primary_mean_scheduled_waiting_burden_s"
SECONDARY_TIE_METRIC = "mean_completed_time_loss_s"

QMIX = "qmix"
VDN = "vdn"
IDQN = "idqn"
OPTIMIZED_FIXED_TIMING = "optimized_fixed_timing"
OPTIMIZED_FIXED_OFFSET = "optimized_fixed_offset"
SIMULTANEOUS_FIXED_TIME = "simultaneous_fixed_time"
CANONICAL_MAX_PRESSURE = "canonical_operational_max_pressure"
MATCHED_INTERVAL_PRESSURE_P5 = "matched_interval_pressure_P5"

LEARNED_METHODS = (IDQN, VDN, QMIX)

OFFICIAL_CONTROLLERS = (
    SIMULTANEOUS_FIXED_TIME,
    OPTIMIZED_FIXED_OFFSET,
    OPTIMIZED_FIXED_TIMING,
    IDQN,
    VDN,
    QMIX,
    CANONICAL_MAX_PRESSURE,
)

DIAGNOSTIC_CONTROLLERS = (MATCHED_INTERVAL_PRESSURE_P5,)

# Comparison roles.
ROLE_DECIDING = "deciding"
ROLE_REPORTED = "reported_not_deciding"

COMPARISONS = (
    {
        "name": "delta_J_OFT",
        "role": ROLE_DECIDING,
        "treatment": QMIX,
        "comparator": OPTIMIZED_FIXED_TIMING,
        "statistic": "J_QMIX - J_optimized_fixed_timing",
        "go_criterion": "paired crossed 95% CI entirely below zero",
        "rationale": (
            "the primary question: does the adaptive controller beat the best "
            "classical plan the same search budget can find"
        ),
    },
    {
        "name": "delta_J_IDQN",
        "role": ROLE_DECIDING,
        "treatment": QMIX,
        "comparator": IDQN,
        "statistic": "J_QMIX - J_IDQN",
        "go_criterion": "paired crossed 95% CI entirely below zero",
        "rationale": (
            "cooperation: without this, a win over a fixed plan would not "
            "show that joint learning contributed anything"
        ),
    },
    {
        "name": "delta_J_VDN",
        "role": ROLE_REPORTED,
        "treatment": QMIX,
        "comparator": VDN,
        "statistic": "J_QMIX - J_VDN",
        "go_criterion": None,
        "rationale": (
            "mixer value: reported with its CI whether or not it excludes "
            "zero, because a null mixer result is itself a finding"
        ),
    },
    {
        "name": "delta_J_MP",
        "role": ROLE_REPORTED,
        "treatment": QMIX,
        "comparator": CANONICAL_MAX_PRESSURE,
        "statistic": "J_QMIX - J_canonical_operational_max_pressure",
        "go_criterion": None,
        "rationale": (
            "mandatory to run and report; deliberately not a gate, so a strong "
            "operational baseline winning is a reportable result rather than a "
            "reason to redefine success"
        ),
    },
    {
        "name": "delta_J_P5",
        "role": ROLE_REPORTED,
        "treatment": QMIX,
        "comparator": MATCHED_INTERVAL_PRESSURE_P5,
        "statistic": "J_QMIX - J_matched_interval_pressure_P5",
        "go_criterion": None,
        "rationale": (
            "matched control-authority diagnostic, never a GO criterion and "
            "never an official controller"
        ),
    },
)

DECIDING_COMPARISONS = tuple(
    item["name"] for item in COMPARISONS if item["role"] == ROLE_DECIDING
)

NO_EFFECT_SIZE_THRESHOLD = (
    "No minimum percentage improvement is required, and none may be "
    "introduced after results are seen. A threshold chosen without "
    "preregistered justification is a threshold fitted to the data. The "
    "criterion is that the paired 95% CI excludes zero; the effect size is "
    "reported alongside so practical relevance can be judged openly."
)

GATE_ORDER_NOTE = (
    "Validity and behavioural-safety reporting precede the performance "
    "comparison. A network-average J_primary is not permitted to be the first "
    "thing anyone looks at."
)

GO_NO_GO = {
    "protocol_version": PROTOCOL_VERSION,
    "primary_metric": PRIMARY_METRIC,
    "secondary_tie_metric": SECONDARY_TIE_METRIC,
    "official_controllers": list(OFFICIAL_CONTROLLERS),
    "diagnostic_controllers": list(DIAGNOSTIC_CONTROLLERS),
    "comparisons": [dict(item) for item in COMPARISONS],
    "deciding_comparisons": list(DECIDING_COMPARISONS),
    "go_rule": (
        "GO if and only if EVERY deciding comparison's paired crossed "
        "two-factor 95% CI lies entirely below zero, AND every hard validity "
        "gate passes, AND every selected QMIX policy has a completed "
        "behavioural review, AND none of those reviews concluded pathology."
    ),
    "no_effect_size_threshold": NO_EFFECT_SIZE_THRESHOLD,
    "gate_order": GATE_ORDER_NOTE,
    "behaviour_gate": (
        "Every selected QMIX training-seed policy must carry its own "
        "behavioural review. Any one concluding pathology makes GO "
        "impossible, whatever the intervals show. Comparator reviews are "
        "mandatory to report; comparator pathology never becomes a QMIX "
        "success criterion."
    ),
    "max_pressure_is_not_a_gate": True,
    "p5_is_not_an_official_controller": True,
}


class DecisionProtocolError(RuntimeError):
    pass


def canonical_bytes(payload):
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def protocol_sha256():
    """Hash of the frozen GO/NO-GO definition, recorded in freeze artefacts."""
    return hashlib.sha256(canonical_bytes(GO_NO_GO)).hexdigest()


def serialize():
    """The definition as a JSON string, byte-stable across processes."""
    return canonical_bytes(GO_NO_GO).decode("ascii")


def comparison(name):
    for item in COMPARISONS:
        if item["name"] == name:
            return dict(item)
    raise DecisionProtocolError("Unknown comparison {!r}.".format(name))


def evaluate_go_no_go(interval_by_comparison, validity_passed,
                      behaviour_reviews):
    """Apply the frozen rule to already-computed CIs and behavioural reviews.

    'interval_by_comparison' maps a comparison name to (low, high). Only the
    deciding comparisons are consulted for the verdict; the rest are carried
    through so the record shows what was reported alongside.

    'behaviour_reviews' maps each method to its per-training-seed review
    records, and is summarised rather than reduced to a flag. Every selected
    QMIX policy must be reviewed, and ANY of them concluding pathology makes
    GO impossible however far below zero the intervals sit -- an average that
    good while a movement starves is a reason to look harder, not to ship.
    Comparator reviews are required to be reported; comparator pathology is
    recorded and never becomes a point in QMIX's favour.
    """
    missing = [
        name for name in DECIDING_COMPARISONS
        if name not in interval_by_comparison
    ]
    if missing:
        raise DecisionProtocolError(
            "Cannot decide without the deciding comparisons {}.".format(missing)
        )
    findings = {}
    for name in DECIDING_COMPARISONS:
        low, high = interval_by_comparison[name]
        findings[name] = {
            "ci_low": float(low),
            "ci_high": float(high),
            "entirely_below_zero": bool(float(high) < 0.0),
        }
    criteria_met = all(
        item["entirely_below_zero"] for item in findings.values()
    )

    review_summary = behaviour.summarise_reviews(
        behaviour_reviews or {}, statistics.TRAINING_SEEDS, QMIX
    )
    review_complete = review_summary["gating_review_complete"]
    pathology = review_summary["gating_pathology_observed"]

    verdict = (
        "GO" if (
            criteria_met and validity_passed and review_complete
            and not pathology
        ) else "NO-GO"
    )
    reasons = []
    if not validity_passed:
        reasons.append("hard validity gates did not pass")
    if not review_complete:
        gating = review_summary["methods"].get(QMIX, {})
        reasons.append(
            "the behavioural safety review of {} is incomplete (missing "
            "training seeds {}, invalid conclusions {})".format(
                QMIX, gating.get("missing_training_seeds", "all"),
                gating.get("invalid_conclusions", []),
            )
        )
    if pathology:
        reasons.append(
            "behavioural pathology was observed for {} training seeds {}; a "
            "good network-average J_primary does not override it".format(
                QMIX,
                review_summary["methods"][QMIX]["pathology_training_seeds"],
            )
        )
    for name, item in sorted(findings.items()):
        if not item["entirely_below_zero"]:
            reasons.append(
                "{} CI [{:.6g}, {:.6g}] does not lie entirely below "
                "zero".format(name, item["ci_low"], item["ci_high"])
            )
    return {
        "verdict": verdict,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256(),
        "deciding": findings,
        "reported_only": sorted(
            name for name in interval_by_comparison
            if name not in DECIDING_COMPARISONS
        ),
        "validity_passed": bool(validity_passed),
        "behaviour_review": review_summary,
        "behaviour_review_complete": review_complete,
        "behaviour_pathology_observed": pathology,
        "comparator_pathology": review_summary["comparator_pathology"],
        "comparator_review_incomplete": (
            review_summary["comparator_review_incomplete"]
        ),
        "reasons": reasons,
    }
