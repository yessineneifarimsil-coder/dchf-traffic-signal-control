"""Hard validity gates: what makes a single run admissible evidence at all.

A run either satisfies every one of these or it is not evidence. There is no
partial credit and no repair path, because every repair path is a way of
turning a run that went wrong into a number that looks fine:

  * all 2800 scheduled vehicles accounted for;
  * status CLEARED;
  * no unexpected disappearance;
  * no unresolved teleport or accounting error;
  * complete 1 s evaluation logging;
  * scientific_analysis_permitted true;
  * finite primary and required secondary metrics.

Never converted to a favourable value. The temptation with a failed run is to
average over the vehicles that did finish, which rewards a controller exactly
in proportion to how many vehicles it failed to serve. invalid_primary_value()
exists so that the only value a failed run can contribute is NaN, and
assert_no_favourable_imputation() is there to catch a future caller trying to
substitute something else.
"""

from __future__ import absolute_import

import math


SCHEDULED_TOTAL = 2800
STATUS_CLEARED = "CLEARED"

PRIMARY_FIELD = "J_primary_mean_scheduled_waiting_burden_s"
REQUIRED_SECONDARY_FIELDS = (
    "mean_completed_time_loss_s",
    "mean_completed_travel_time_s",
    "mean_completed_waiting_time_s",
    "mean_completed_depart_delay_s",
    "mean_completed_stops",
)

GATE_NAMES = (
    "all_scheduled_accounted_for",
    "cleared",
    "no_unexpected_disappearance",
    "no_unresolved_teleport_or_accounting_error",
    "complete_one_second_logging",
    "scientific_analysis_permitted",
    "finite_primary_and_secondary_metrics",
)


class ValidityError(RuntimeError):
    pass


def invalid_primary_value():
    """The only value a failed run may contribute."""
    return float("nan")


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def assert_no_favourable_imputation(value, clearance_status):
    """A non-cleared run may not carry a finite primary value.

    Called wherever a primary value is about to be used, so that an imputed
    or completed-only mean cannot enter the analysis by a route nobody
    reviewed.
    """
    if clearance_status != STATUS_CLEARED and _finite(value):
        raise ValidityError(
            "A run with status {!r} carries the finite primary value {!r}. A "
            "failed run must contribute NaN: averaging only the vehicles that "
            "finished rewards a controller for the ones it never "
            "served.".format(clearance_status, value)
        )
    return True


def evaluate_run_validity(metrics, behaviour_summary=None,
                          expected_seconds=None):
    """Every hard gate for one run, as a dict of pass/fail plus the reasons.

    'metrics' is a run's evaluation_metrics.json; 'behaviour_summary' is its
    behavior_summary.json, which carries the completeness verdict and the
    logging cadence.
    """
    behaviour_summary = behaviour_summary or {}
    reasons = []
    gates = {}

    scheduled = int(metrics.get("scheduled_count", -1))
    completed = int(metrics.get("completed_count", -1))
    exceptional = int(metrics.get("exceptional_count", 0))
    missing = list(metrics.get("missing_tripinfo_ids", []) or [])
    tripinfo_count = int(metrics.get("tripinfo_count", -1))

    gates["all_scheduled_accounted_for"] = (
        scheduled == SCHEDULED_TOTAL
        and completed == SCHEDULED_TOTAL
        and tripinfo_count == SCHEDULED_TOTAL
    )
    if not gates["all_scheduled_accounted_for"]:
        reasons.append(
            "scheduled={} completed={} tripinfo={} (each must be {})".format(
                scheduled, completed, tripinfo_count, SCHEDULED_TOTAL
            )
        )

    status = metrics.get("clearance_status")
    gates["cleared"] = status == STATUS_CLEARED
    if not gates["cleared"]:
        reasons.append("clearance status is {!r}".format(status))

    gates["no_unexpected_disappearance"] = not missing
    if missing:
        reasons.append(
            "{} scheduled vehicles have no tripinfo record".format(len(missing))
        )

    outcomes = metrics.get("exceptional_outcomes", {}) or {}
    gates["no_unresolved_teleport_or_accounting_error"] = (
        exceptional == 0 and not outcomes
    )
    if not gates["no_unresolved_teleport_or_accounting_error"]:
        reasons.append(
            "{} exceptional terminal outcomes: {}".format(
                exceptional, sorted(outcomes)[:5]
            )
        )

    cadence = behaviour_summary.get("lane_state_sampling_cadence")
    logged = behaviour_summary.get("demand_active_seconds_logged")
    required = behaviour_summary.get("demand_active_seconds_required")
    complete_logging = cadence == "full_1s"
    if expected_seconds is not None:
        complete_logging = complete_logging and logged == expected_seconds
    elif logged is not None and required is not None:
        complete_logging = complete_logging and logged == required
    gates["complete_one_second_logging"] = bool(complete_logging)
    if not gates["complete_one_second_logging"]:
        reasons.append(
            "evaluation logging is not complete at 1 s (cadence={!r}, "
            "logged={}, required={})".format(cadence, logged, required)
        )

    permitted = bool(
        behaviour_summary.get("scientific_analysis_permitted", False)
    )
    gates["scientific_analysis_permitted"] = permitted
    if not permitted:
        reasons.append(
            "scientific_analysis_permitted is false ({})".format(
                behaviour_summary.get("episode_status", "no completeness "
                                      "record")
            )
        )

    primary = metrics.get(PRIMARY_FIELD)
    finite_fields = _finite(primary) and bool(
        metrics.get("J_primary_valid", False)
    )
    non_finite = [] if _finite(primary) else [PRIMARY_FIELD]
    for field in REQUIRED_SECONDARY_FIELDS:
        if not _finite(metrics.get(field)):
            non_finite.append(field)
            finite_fields = False
    gates["finite_primary_and_secondary_metrics"] = bool(finite_fields)
    if not finite_fields:
        reasons.append(
            "non-finite or invalid metrics: {}".format(sorted(set(non_finite)))
        )

    valid = all(gates[name] for name in GATE_NAMES)
    return {
        "valid": valid,
        "gates": dict((name, bool(gates[name])) for name in GATE_NAMES),
        "failed_gates": sorted(
            name for name in GATE_NAMES if not gates[name]
        ),
        "reasons": reasons,
        "primary_value": float(primary) if _finite(primary) else invalid_primary_value(),
        "clearance_status": status,
        "controller": metrics.get("controller") or metrics.get("method"),
        "traffic_family": metrics.get("traffic_family"),
        "traffic_seed": metrics.get("traffic_seed"),
    }


def assert_run_valid(metrics, behaviour_summary=None, expected_seconds=None):
    verdict = evaluate_run_validity(
        metrics, behaviour_summary, expected_seconds
    )
    if not verdict["valid"]:
        raise ValidityError(
            "Run is not admissible evidence. Failed gates {}: {}".format(
                verdict["failed_gates"], "; ".join(verdict["reasons"])
            )
        )
    return verdict
