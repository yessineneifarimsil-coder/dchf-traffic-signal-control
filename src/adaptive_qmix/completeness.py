"""Whether an episode's logs support inference, or only diagnosis.

Sampling cadence and episode completeness are different facts, and conflating
them is how a truncated run quietly becomes a scientific result. A run stopped
by the interaction budget after 1235 s can still be logged at a full 1 s
cadence: every row it has is exact, there are simply not enough of them to
cover the preregistered demand-active window [0, generation_end_s]. Reporting
"full_1s" next to "primary_window = demand_active" would then read as a
complete demand-active result, which it is not.

So cadence keys here describe SAMPLING only, and completeness is established
separately from two independent pieces of evidence:

  1. the episode's recorded status in episode_summary.csv, which the
     environment writes and which it grants as CLEARED only after the vehicle
     ledger reconciles; and

  2. the observed coverage of the phase log itself -- every second of
     (0, generation_end_s] must actually be present, at every signal, before
     the demand-active window can be called complete. A status alone is not
     enough, because a status describes how a run ended and not which seconds
     survived into the file being analysed.

Derivation of an incomplete episode stays available, because a truncated smoke
episode is a useful engineering diagnostic. It is labelled as one:
scientific_analysis_permitted is false, analysis_class is diagnostic_partial,
and the note says so in words. Nothing here filters, reweights or alters a
single metric value; the numbers are exactly the numbers for the seconds that
exist, and this module only states what those seconds are and are not.

Absence of evidence is treated as absence of permission: a run directory with
no episode_summary.csv, or one whose summary does not mention the selected
episode, yields status UNKNOWN and is not permitted. Nothing is raised for
that case, so a synthetic or hand-built source can still be analysed as a
diagnostic without being able to claim scientific standing by omission.
"""

from __future__ import absolute_import

import csv
import math
import os


EPISODE_SUMMARY_FILE = "episode_summary.csv"
EPISODE_FIELD = "episode_index"
STATUS_FIELD = "status"

STATUS_CLEARED = "CLEARED"
STATUS_BUDGET_TRUNCATED = "BUDGET_TRUNCATED"
STATUS_CLEARANCE_FAILURE = "CLEARANCE_FAILURE"
STATUS_UNKNOWN = "UNKNOWN"

CLASS_SCIENTIFIC = "scientific"
CLASS_DIAGNOSTIC = "diagnostic_partial"

# Counts copied through from the episode summary as supporting evidence. They
# are reported, never recomputed and never used to override the status.
LEDGER_FIELDS = ("scheduled", "inserted", "completed", "exceptional_terminal",
                 "pending_due", "elapsed_s")


class CompletenessError(RuntimeError):
    pass


def read_episode_status(run_directory, episode_index):
    """The recorded status of one episode, or UNKNOWN when it cannot be read.

    Returns a dict with 'status', 'status_source' and 'status_reason', plus
    whatever ledger counts the summary row carries.
    """
    path = os.path.join(run_directory, EPISODE_SUMMARY_FILE)
    unknown = {
        "status": STATUS_UNKNOWN,
        "status_source": None,
        "ledger": {},
    }
    if not os.path.isfile(path):
        unknown["status_reason"] = (
            "no {} in the run directory, so the episode's outcome is unknown "
            "and cannot be assumed complete".format(EPISODE_SUMMARY_FILE)
        )
        return unknown

    with open(path, "r", newline="") as handle:
        rows = list(csv.DictReader(handle))
    matching = [
        row for row in rows
        if row.get(EPISODE_FIELD) not in (None, "")
        and int(row[EPISODE_FIELD]) == int(episode_index)
    ]
    if not matching:
        unknown["status_source"] = path
        unknown["status_reason"] = (
            "{} carries no row for episode {}".format(
                EPISODE_SUMMARY_FILE, int(episode_index)
            )
        )
        return unknown
    if len(matching) > 1:
        # Two summaries for one episode means the directory pools more than
        # one run; picking either would be a guess about which one produced
        # the rows being analysed.
        raise CompletenessError(
            "{} has {} rows for episode {}. A run directory must describe each "
            "episode once; this one appears to pool separate runs.".format(
                EPISODE_SUMMARY_FILE, len(matching), int(episode_index)
            )
        )

    row = matching[0]
    status = str(row.get(STATUS_FIELD, "") or "").strip()
    if not status:
        unknown["status_source"] = path
        unknown["status_reason"] = (
            "the summary row for episode {} has an empty '{}'".format(
                int(episode_index), STATUS_FIELD
            )
        )
        return unknown
    return {
        "status": status,
        "status_source": path,
        "status_reason": None,
        "ledger": dict(
            (field, row[field]) for field in LEDGER_FIELDS if field in row
        ),
    }


def logged_second_coverage(phase_rows, intersections, window_end):
    """How much of (0, window_end] every signal actually logged.

    A row stamped t describes the second [t-1, t), so covering (0, window_end]
    needs a row at every integer second 1 .. ceil(window_end), at each signal.
    The minimum across signals is reported, because a window is only as
    complete as its least-covered intersection.
    """
    required = set(range(1, int(math.ceil(window_end - 1e-9)) + 1))
    present_by_intersection = {}
    for row in phase_rows:
        name = row["intersection"]
        present_by_intersection.setdefault(name, set()).add(
            int(round(float(row["time"])))
        )
    covered = []
    for name in intersections:
        present = present_by_intersection.get(name, set())
        covered.append(len(required & present))
    least = min(covered) if covered else 0
    return {
        "required_seconds": len(required),
        "logged_seconds": least,
        "complete": bool(required) and least == len(required),
    }


def assess_episode(run_directory, config, episode_index, phase_rows,
                   intersections):
    """Completeness metadata for one episode's derived products."""
    generation_end = float(config["demand"]["generation_end_s"])
    recorded = read_episode_status(run_directory, episode_index)
    status = recorded["status"]
    is_cleared = status == STATUS_CLEARED

    coverage = logged_second_coverage(phase_rows, intersections, generation_end)
    demand_active_complete = coverage["complete"]
    # The environment refuses to write CLEARED unless the vehicle ledger
    # reconciles, so the status is itself the clearance evidence.
    full_clearance_complete = is_cleared
    permitted = bool(
        is_cleared and demand_active_complete and full_clearance_complete
    )

    observed_times = [float(row["time"]) for row in phase_rows]
    observed_end = max(observed_times) if observed_times else 0.0

    if permitted:
        note = (
            "Episode {} is {} and its phase log covers the whole demand-active "
            "window [0, {:g}] s, so the preregistered metrics are complete and "
            "may be interpreted scientifically.".format(
                int(episode_index), status, generation_end
            )
        )
    else:
        reasons = []
        if not is_cleared:
            reasons.append(
                "its recorded status is {}{}".format(
                    status,
                    "" if recorded.get("status_reason") is None
                    else " ({})".format(recorded["status_reason"]),
                )
            )
        if not demand_active_complete:
            reasons.append(
                "only {} of the {} seconds of the demand-active window "
                "[0, {:g}] s are logged".format(
                    coverage["logged_seconds"], coverage["required_seconds"],
                    generation_end,
                )
            )
        note = (
            "DIAGNOSTIC ONLY, NOT A SCIENTIFIC RESULT. Every value below is "
            "correctly computed for the seconds that exist, but this episode "
            "is not a complete preregistered observation: {}. Do not report "
            "these numbers as a demand-active or full-episode result, and do "
            "not compare them with complete episodes.".format(
                "; ".join(reasons)
            )
        )

    metadata = {
        "episode_status": status,
        "episode_is_cleared": is_cleared,
        "demand_active_window_complete": demand_active_complete,
        "full_clearance_complete": full_clearance_complete,
        "scientific_analysis_permitted": permitted,
        "analysis_class": CLASS_SCIENTIFIC if permitted else CLASS_DIAGNOSTIC,
        "completeness_note": note,
        "episode_status_source": recorded["status_source"],
        "episode_status_reason": recorded.get("status_reason"),
        "demand_active_window_required_end_s": generation_end,
        "demand_active_seconds_required": coverage["required_seconds"],
        "demand_active_seconds_logged": coverage["logged_seconds"],
        "observed_log_end_s": observed_end,
        "episode_summary_ledger": recorded["ledger"],
        "cadence_versus_completeness_note": (
            "Sampling cadence and window completeness are independent. A "
            "cadence of full_1s says every logged second is present at 1 s "
            "resolution; it says nothing about how many seconds the episode "
            "produced, and never implies that the demand-active window is "
            "complete."
        ),
    }
    return metadata
