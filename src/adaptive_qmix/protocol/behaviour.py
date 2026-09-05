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


def record_review(policy_identifier, report, reviewer, conclusion, notes=""):
    """A recorded human judgement against the preregistered review rule.

    The conclusion is a judgement, not a computation, which is exactly why it
    has to be written down with who made it and on what evidence.
    """
    assert_reports_complete(report)
    if conclusion not in ("no_pathology_observed", "pathology_observed"):
        raise BehaviourGateError(
            "Review conclusion must be 'no_pathology_observed' or "
            "'pathology_observed'; got {!r}.".format(conclusion)
        )
    if not str(reviewer).strip():
        raise BehaviourGateError("A review must name its reviewer.")
    return {
        "gate_version": GATE_VERSION,
        "policy": str(policy_identifier),
        "review_rule": REVIEW_RULE,
        "reviewer": str(reviewer),
        "conclusion": conclusion,
        "notes": str(notes),
        "reported": dict(report),
        "reviewed_before_performance": True,
    }
