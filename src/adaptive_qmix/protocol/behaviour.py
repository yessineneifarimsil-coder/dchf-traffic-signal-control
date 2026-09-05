"""The behavioural safety gate, opened before any performance number is read.

A network-average J_primary can be excellent while one movement is starved or
the signal flickers between phases every interval. Averages hide both. So the
behavioural distributions are required to be reported and reviewed FIRST, for
every adaptive policy, and the review is recorded before the comparison is
looked at.

What is deliberately NOT here is a numeric starvation threshold. Inventing one
in code after the fact -- "starvation means p95 above N seconds" -- would be
choosing N to match whatever the runs produced. If a threshold is ever wanted
it must be justified and preregistered before the campaign, and until then the
rule is a REVIEW rule, stated in words and applied by a human who has seen the
distributions:

    no qualitatively pathological starvation or flickering may be hidden by a
    good network-average J_primary

The quantitative distributions are always reported, whatever the review
concludes, so a reader can disagree with the reviewer.

Two facts, never one. "Reviewed" and "reviewed clean" are separate: a review
that FOUND pathology has been completed, and collapsing both into a single
recorded flag is precisely how such a policy could pass a gate. Every selected
policy of the gating method needs its own review, and any one of them
concluding pathology makes GO impossible however good the averages are.
Comparator reviews are mandatory to report, and comparator pathology is
surfaced rather than quietly becoming a point in the gating method's favour.
"""

from __future__ import absolute_import


GATE_VERSION = "behavioural-safety-1.0"

REVIEW_RULE = (
    "No qualitatively pathological starvation or flickering may be hidden by "
    "a good network-average J_primary."
)

THRESHOLD_POLICY = (
    "No numeric starvation or flickering threshold is defined in code. A "
    "threshold introduced after seeing results would be fitted to them. Any "
    "future threshold must be scientifically justified and preregistered "
    "before the campaign; until then this is a review rule applied to the "
    "reported distributions, which are published either way."
)

# Every quantity that must be reported, per adaptive policy, before the
# performance comparison is read. Each names where it comes from.
REQUIRED_REPORTS = (
    {
        "name": "max_service_deprivation_s",
        "movements": ("H", "V"),
        "source": "behavior_metrics_by_intersection_movement.csv",
        "field": "non_green_max_s",
        "why": "the worst single wait a movement endured",
    },
    {
        "name": "p95_service_deprivation_s",
        "movements": ("H", "V"),
        "source": "behavior_metrics_by_intersection_movement.csv",
        "field": "non_green_p95_s",
        "why": "the tail, which a mean would flatten",
    },
    {
        "name": "green_duration_distribution",
        "movements": ("H", "V"),
        "source": "green_spell_distribution.csv",
        "field": "duration_s",
        "why": "flickering shows up as a mass of very short greens",
    },
    {
        "name": "switch_rate",
        "movements": None,
        "source": "behavior_metrics_by_intersection_movement.csv",
        "field": "switches_per_hour",
        "why": "the direct flickering measure, where it is defined",
    },
    {
        "name": "yellow_fraction",
        "movements": None,
        "source": "behavior_summary.json",
        "field": "yellow_fraction_of_elapsed",
        "why": "time lost to transitions rather than service",
    },
    {
        "name": "service_frequency",
        "movements": ("H", "V"),
        "source": "behavior_metrics_by_intersection_movement.csv",
        "field": "services_per_hour",
        "why": "how often a movement is served at all",
    },
    {
        "name": "green_share",
        "movements": ("H", "V"),
        "source": "behavior_metrics_by_intersection_movement.csv",
        "field": "green_share_among_green_time",
        "why": "systematic bias towards one movement",
    },
    {
        "name": "queue_p95",
        "movements": ("H", "V"),
        "source": "behavior_metrics_by_intersection_movement.csv",
        "field": "queue_p95",
        "why": "standing demand the average conceals",
    },
    {
        "name": "queue_max",
        "movements": ("H", "V"),
        "source": "behavior_metrics_by_intersection_movement.csv",
        "field": "queue_max",
        "why": "the worst standing demand",
    },
    {
        "name": "emergent_cycle_distribution",
        "movements": None,
        "source": "emergent_cycle_distribution.csv",
        "field": "emergent_cycle_s",
        "why": "realised periodicity, which the controller never imposes",
    },
)

REQUIRED_REPORT_NAMES = tuple(item["name"] for item in REQUIRED_REPORTS)


class BehaviourGateError(RuntimeError):
    pass


def gate_definition():
    return {
        "gate_version": GATE_VERSION,
        "review_rule": REVIEW_RULE,
        "threshold_policy": THRESHOLD_POLICY,
        "required_reports": [dict(item) for item in REQUIRED_REPORTS],
        "required_report_names": list(REQUIRED_REPORT_NAMES),
        "ordering": (
            "This gate is completed and recorded before the performance "
            "comparison is read."
        ),
    }


def missing_reports(report):
    """Which required quantities a submitted behavioural report lacks."""
    return sorted(
        name for name in REQUIRED_REPORT_NAMES
        if name not in report or report[name] is None
    )


def assert_reports_complete(report):
    absent = missing_reports(report)
    if absent:
        raise BehaviourGateError(
            "The behavioural safety gate requires every distribution to be "
            "reported before performance is read. Missing: {}.".format(absent)
        )
    return True


CONCLUSION_CLEAN = "no_pathology_observed"
CONCLUSION_PATHOLOGY = "pathology_observed"
CONCLUSIONS = (CONCLUSION_CLEAN, CONCLUSION_PATHOLOGY)


def summarise_reviews(reviews_by_method, required_training_seeds,
                      gating_method):
    """Completeness and conclusions, kept as two separate facts.

    "Reviewed" and "reviewed clean" are different things, and collapsing them
    into one boolean is exactly how a policy with observed pathology could be
    waved through: a review that found a problem would have set the same flag
    as one that did not. So this reports, per method, which policies were
    reviewed and which concluded pathology, and it names the gating method
    separately from the comparators.

    Comparator pathology is surfaced, never silently converted into a success
    criterion for the gating method: a comparator behaving badly does not make
    QMIX good, and a comparator behaving badly is itself worth reporting.
    """
    required = sorted(int(seed) for seed in required_training_seeds)
    summary = {"gating_method": gating_method, "methods": {}}
    for method in sorted(reviews_by_method):
        reviews = _normalise_reviews(reviews_by_method[method])
        reviewed = sorted(reviews)
        missing = sorted(set(required) - set(reviewed))
        foreign = sorted(set(reviewed) - set(required))
        invalid = sorted(
            seed for seed, review in reviews.items()
            if review.get("conclusion") not in CONCLUSIONS
        )
        pathology = sorted(
            seed for seed, review in reviews.items()
            if review.get("conclusion") == CONCLUSION_PATHOLOGY
        )
        summary["methods"][method] = {
            "reviewed_training_seeds": reviewed,
            "missing_training_seeds": missing,
            "foreign_training_seeds": foreign,
            "invalid_conclusions": invalid,
            "pathology_training_seeds": pathology,
            "review_complete": not missing and not foreign and not invalid,
            "any_pathology_observed": bool(pathology),
        }
    for method in sorted(reviews_by_method):
        summary["methods"][method].setdefault("review_complete", False)

    gating = summary["methods"].get(gating_method)
    summary["gating_review_complete"] = bool(
        gating and gating["review_complete"]
    )
    summary["gating_pathology_observed"] = bool(
        gating and gating["any_pathology_observed"]
    )
    summary["comparator_pathology"] = dict(
        (method, item["pathology_training_seeds"])
        for method, item in summary["methods"].items()
        if method != gating_method and item["any_pathology_observed"]
    )
    summary["comparator_review_incomplete"] = sorted(
        method for method, item in summary["methods"].items()
        if method != gating_method and not item["review_complete"]
    )
    summary["comparator_note"] = (
        "Comparator behavioural findings are reported, never treated as a "
        "success criterion for {}.".format(gating_method)
    )
    return summary


def _normalise_reviews(reviews):
    """Accept a list of records or a {training seed: record} mapping."""
    if isinstance(reviews, dict):
        return dict(
            (int(seed), review) for seed, review in reviews.items()
        )
    normalised = {}
    for review in reviews or []:
        seed = review.get("training_seed")
        if seed is None:
            raise BehaviourGateError(
                "A behavioural review must name its training seed."
            )
        normalised[int(seed)] = review
    return normalised


def record_review(policy_identifier, report, reviewer, conclusion, notes="",
                  training_seed=None, method=None):
    """A recorded human judgement against the preregistered review rule.

    The conclusion is a judgement, not a computation, which is exactly why it
    has to be written down with who made it and on what evidence.
    """
    assert_reports_complete(report)
    if conclusion not in CONCLUSIONS:
        raise BehaviourGateError(
            "Review conclusion must be one of {}; got {!r}.".format(
                list(CONCLUSIONS), conclusion
            )
        )
    if not str(reviewer).strip():
        raise BehaviourGateError("A review must name its reviewer.")
    return {
        "gate_version": GATE_VERSION,
        "policy": str(policy_identifier),
        "method": None if method is None else str(method),
        "training_seed": None if training_seed is None else int(training_seed),
        "review_rule": REVIEW_RULE,
        "reviewer": str(reviewer),
        "conclusion": conclusion,
        "review_complete": True,
        "notes": str(notes),
        "reported": dict(report),
        "reviewed_before_performance": True,
    }
