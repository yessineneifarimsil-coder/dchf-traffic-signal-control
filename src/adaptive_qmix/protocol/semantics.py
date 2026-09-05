"""The frozen primary adaptive-control specification.

The point of writing this down as code, and hashing it, is that the control
authority QMIX is being judged on cannot be adjusted after the numbers arrive.
Every value here is the qualification specification itself:

    decision interval   5 s, globally synchronised
    EXTEND              5 s more of the current green
    SWITCH              3 s yellow + 2 s new green
    fixed cycle         none
    minimum green       none imposed
    maximum green       none imposed

The absent constraints matter as much as the present ones. QMIX has no
imposed minimum or maximum green: how long a movement is served, and how long
it waits, are outcomes to be measured rather than rules the controller is
given. Any minimum-green wrapper is a POST-GO practical-realism sensitivity,
a different specification reported separately, and it is deliberately not
implemented here -- so it cannot be reached for if the primary result
disappoints.

The classical benchmark's 5 s plan-admissibility rule and canonical max
pressure's 10 s operational minimum green belong to those controllers. Neither
is a QMIX constraint, and assert_no_imposed_green_bounds exists to keep that
distinction enforceable rather than merely stated.
"""

from __future__ import absolute_import

import hashlib
import json


SPECIFICATION_VERSION = "primary-adaptive-semantics-1.0"

CONTROL_INTERVAL_S = 5
EXTEND_GREEN_S = 5
YELLOW_S = 3
SWITCH_NEW_GREEN_S = 2
SWITCH_DURATION_S = YELLOW_S + SWITCH_NEW_GREEN_S

DECISION_CLOCK = "globally_synchronized"

# The declaration that replaces the provisional-yellow blocker. A run may be
# official only when the configuration names exactly this, and the numbers
# behind it verify.
FROZEN_YELLOW_SEMANTICS = "frozen_primary_synchronous_3plus2"
PROVISIONAL_PREFIX = "provisional_"

# Constraints the primary specification deliberately does NOT impose.
FORBIDDEN_PRIMARY_KEYS = (
    "minimum_green_s", "min_green_s", "maximum_green_s", "max_green_s",
    "cycle_s", "fixed_cycle_s", "offset_s",
)

PRIMARY_SPECIFICATION = {
    "specification_version": SPECIFICATION_VERSION,
    "decision_clock": DECISION_CLOCK,
    "control_interval_s": CONTROL_INTERVAL_S,
    "extend_duration_s": EXTEND_GREEN_S,
    "extend_semantics": "5 s more of the current green",
    "switch_duration_s": SWITCH_DURATION_S,
    "switch_semantics": "3 s yellow then 2 s of the new green",
    "yellow_duration_s": YELLOW_S,
    "switch_new_green_s": SWITCH_NEW_GREEN_S,
    "yellow_semantics": FROZEN_YELLOW_SEMANTICS,
    "fixed_cycle": None,
    "imposed_minimum_green_s": None,
    "imposed_maximum_green_s": None,
    "minimum_green_wrapper": (
        "Not part of the primary specification. A practical-realism minimum "
        "green is a POST-GO sensitivity analysis on a separate specification "
        "and is not implemented in the primary controller."
    ),
    "green_bound_note": (
        "The classical benchmark's 5 s plan admissibility and canonical max "
        "pressure's 10 s operational minimum green are properties of those "
        "controllers, never of QMIX."
    ),
}


class SemanticsError(RuntimeError):
    """Raised when a configuration is not the frozen primary specification."""


def specification_sha256():
    """A stable hash of the frozen specification, for freeze artefacts."""
    payload = json.dumps(
        PRIMARY_SPECIFICATION, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_frozen_timing(executor_config):
    """The four durations must be exactly 5 / 5 / 3 / 2."""
    actual = {
        "control_interval_s": int(executor_config["control_interval_s"]),
        "extend_duration_s": int(executor_config["extend_duration_s"]),
        "yellow_duration_s": int(executor_config["yellow_duration_s"]),
        "switch_new_green_s": int(executor_config["switch_new_green_s"]),
    }
    expected = {
        "control_interval_s": CONTROL_INTERVAL_S,
        "extend_duration_s": EXTEND_GREEN_S,
        "yellow_duration_s": YELLOW_S,
        "switch_new_green_s": SWITCH_NEW_GREEN_S,
    }
    differences = [
        (key, actual[key], expected[key])
        for key in sorted(expected) if actual[key] != expected[key]
    ]
    if differences:
        raise SemanticsError(
            "The primary control semantics is frozen at 5 s decisions, "
            "EXTEND = 5 s, SWITCH = 3 s yellow + 2 s new green. Differences "
            "(field, configured, frozen): {}.".format(differences)
        )
    if int(executor_config["switch_duration_s"]) != SWITCH_DURATION_S:
        raise SemanticsError(
            "SWITCH must last {} s (3 + 2); configured {}.".format(
                SWITCH_DURATION_S, executor_config["switch_duration_s"]
            )
        )
    if str(executor_config.get("decision_clock")) != DECISION_CLOCK:
        raise SemanticsError(
            "The primary decision clock is {!r}.".format(DECISION_CLOCK)
        )
    return True


def assert_no_imposed_green_bounds(executor_config):
    """QMIX is given no minimum green, maximum green or cycle."""
    present = [
        key for key in FORBIDDEN_PRIMARY_KEYS if key in executor_config
    ]
    if present:
        raise SemanticsError(
            "The primary specification imposes no {}. Their presence in the "
            "executor configuration would make QMIX a different controller "
            "from the one preregistered; a minimum-green wrapper is a post-GO "
            "sensitivity on its own specification.".format(present)
        )
    for key in ("imposed_minimum_green_s", "imposed_maximum_green_s"):
        if PRIMARY_SPECIFICATION[key] is not None:
            raise SemanticsError(
                "{} must remain unset in the primary specification.".format(key)
            )
    return True


def assert_primary_semantics_frozen(config):
    """Everything A requires, checked together."""
    executor = config["executor"]
    assert_frozen_timing(executor)
    assert_no_imposed_green_bounds(executor)
    semantics = str(executor.get("yellow_semantics", ""))
    if semantics.startswith(PROVISIONAL_PREFIX):
        raise SemanticsError(
            "Yellow semantics is still declared provisional ({!r}). The "
            "primary specification must be frozen as {!r} before any official "
            "run.".format(semantics, FROZEN_YELLOW_SEMANTICS)
        )
    if semantics != FROZEN_YELLOW_SEMANTICS:
        raise SemanticsError(
            "Yellow semantics must be declared {!r}; got {!r}.".format(
                FROZEN_YELLOW_SEMANTICS, semantics
            )
        )
    return True
