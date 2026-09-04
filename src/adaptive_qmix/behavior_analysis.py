"""Preregistered behaviour, starvation and service metrics from raw logs.

The adaptive controller imposes no minimum or maximum green, so how long a
movement waits is an outcome to be measured rather than a rule to be trusted.
These derivations are transparent physical quantities only: no fairness index,
no weighting, no penalty, no reward shaping.

Definitions used throughout.

  A row stamped time t describes the second [t-1, t), so a run of k consecutive
  rows is exactly k seconds of that state.

  GREEN SPELL for movement m at intersection i is a maximal run of consecutive
  seconds with actual_phase == m. The spell in progress at t = 0 counts as a
  genuine service spell even though no SWITCH produced it.

  NON-GREEN SPELL (service deprivation) for movement m is a maximal run of
  consecutive seconds with actual_phase != m. It therefore includes the
  opposing green AND the yellow transition, because a movement receives no
  green service during either. It is deliberately not called "red", and it is
  computed from the phase trace rather than from the existing
  H_red_elapsed_s / V_red_elapsed_s counters, whose meaning is left untouched.

  EMERGENT CYCLE is the interval between consecutive H-green starts at the same
  intersection. It is a descriptive measure of realised behaviour and is never
  a controller-imposed cycle: no cycle exists in this controller.

Two analysis windows are reported. The demand-active window
[0, generation_end_s] is the primary starvation and service window; the full
episode [0, clearance] is secondary information.

Naming a window is not the same as filling it. Every summary therefore carries
the completeness verdict from adaptive_qmix.completeness, and the two ideas are
kept apart in the keys: '..._sampling_is_full_1s' describes the sampling
cadence and gates the utilisation computation, while '..._are_official'
additionally requires that the episode is a complete preregistered
observation. A truncated episode still reports correct values for the seconds
it has, labelled diagnostic rather than scientific.
"""

from __future__ import absolute_import

import json
import os

import numpy as np

from .completeness import assess_episode
from .raw_logs import (
    available_episodes,
    derived_output_directory,
    read_raw_tables,
    select_episode,
    write_rows,
)


WINDOW_DEMAND_ACTIVE = "demand_active"
WINDOW_FULL_EPISODE = "full_episode"
WINDOWS = (WINDOW_DEMAND_ACTIVE, WINDOW_FULL_EPISODE)

MOVEMENTS = ("H", "V")
YELLOW = "Y"

# Reported in place of an action-based number when the controller takes no
# online decisions at all. A pretimed plan does not make zero switches per
# hour; the quantity simply does not exist for it, and reporting 0.0 would
# invite a comparison across controller families that have different decision
# semantics.
NOT_APPLICABLE = "not_applicable"

CADENCE_FULL_1S = "full_1s"
CADENCE_DECISION = "decision"
CADENCE_IRREGULAR = "irregular"

REQUIRED_TABLES = ("signal_phases", "signal_actions", "lane_states")


class BehaviorAnalysisError(RuntimeError):
    pass


def _stats(values):
    """Scalar summary of a duration distribution.

    p95 uses numpy's default linear interpolation, which is stable across the
    numpy versions in use and is what the regression tests assert against.
    """
    if not values:
        return {
            "count": 0, "mean_s": float("nan"), "median_s": float("nan"),
            "p95_s": float("nan"), "max_s": float("nan"), "sd_s": float("nan"),
            "total_s": 0.0,
        }
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "mean_s": float(np.mean(array)),
        "median_s": float(np.median(array)),
        "p95_s": float(np.percentile(array, 95)),
        "max_s": float(np.max(array)),
        "sd_s": float(np.std(array, ddof=1)) if array.size > 1 else 0.0,
        "total_s": float(np.sum(array)),
    }


def contiguous_spells(second_rows, matches, window_start, window_end):
    """Maximal runs of consecutive seconds whose phase satisfies `matches`.

    second_rows is [(time, phase), ...] sorted ascending. A gap in the log
    breaks a spell rather than bridging it, so a truncated log can never
    fabricate a longer spell than was observed.
    """
    spells = []
    current = None
    previous_time = None
    for time_value, phase in second_rows:
        contiguous = (
            previous_time is not None
            and abs(time_value - previous_time - 1.0) < 1e-9
        )
        if matches(phase):
            if current is None or not contiguous:
                if current is not None:
                    spells.append(current)
                current = {"start_s": time_value - 1.0, "end_s": time_value}
            else:
                current["end_s"] = time_value
        elif current is not None:
            spells.append(current)
            current = None
        previous_time = time_value
    if current is not None:
        spells.append(current)

    for index, spell in enumerate(spells):
        spell["spell_index"] = index
        spell["duration_s"] = spell["end_s"] - spell["start_s"]
        # A spell touching a window edge is truncated by the window, not by the
        # controller, so max and p95 understate it. Flagged, never dropped.
        spell["right_censored"] = abs(spell["end_s"] - window_end) < 1e-9
        spell["at_window_start"] = abs(spell["start_s"] - window_start) < 1e-9
    return spells


def _phase_seconds(phase_rows, intersection):
    selected = [
        (float(row["time"]), row["actual_phase"])
        for row in phase_rows if row["intersection"] == intersection
    ]
    selected.sort(key=lambda item: item[0])
    return selected


def lane_state_cadence(lane_rows, control_interval_s):
    """Classify the lane-state sampling cadence actually present in the log."""
    times = sorted(set(float(row["time"]) for row in lane_rows))
    if len(times) < 2:
        return CADENCE_IRREGULAR
    diffs = set(round(times[i + 1] - times[i], 6) for i in range(len(times) - 1))
    if diffs == {1.0}:
        return CADENCE_FULL_1S
    if diffs == {float(control_interval_s)}:
        return CADENCE_DECISION
    return CADENCE_IRREGULAR


def _summed_lane_series(lane_rows, lane_ids, field):
    """time -> summed field over the given lanes."""
    wanted = set(lane_ids)
    totals = {}
    for row in lane_rows:
        if row["lane"] not in wanted:
            continue
        time_value = float(row["time"])
        totals[time_value] = totals.get(time_value, 0.0) + float(row[field])
    return totals


def derive_behavior_metrics(run_directory, config, episode_index=None,
                            output_directory=None):
    tables = read_raw_tables(run_directory, REQUIRED_TABLES)
    episodes = available_episodes(tables)
    chosen, filtered = select_episode(tables, episode_index)
    destination = derived_output_directory(
        run_directory, len(episodes), chosen, output_directory
    )
    phase_rows = filtered["signal_phases"]
    action_rows = filtered["signal_actions"]
    lane_rows = filtered["lane_states"]

    traffic_lights = list(config["network"]["traffic_lights"])
    control_interval = int(config["executor"]["control_interval_s"])
    generation_end = float(config["demand"]["generation_end_s"])
    lanes = config["observation"]["lanes"]

    all_times = [float(row["time"]) for row in phase_rows]
    if not all_times:
        raise BehaviorAnalysisError("signal_phases contains no rows.")
    clearance_time = max(all_times)

    cadence = lane_state_cadence(lane_rows, control_interval)
    completeness = assess_episode(
        run_directory, config, chosen, phase_rows, traffic_lights
    )
    # A SAMPLING descriptor: the logged seconds are at 1 s resolution. It is
    # what green-demand utilisation needs, and it is deliberately the only
    # thing gating that computation, so a truncated episode still reports the
    # correct utilisation for the seconds it has.
    sampling_is_full_1s = cadence == CADENCE_FULL_1S
    # The OFFICIALNESS claim, which additionally requires that the episode is
    # a complete preregistered observation. It labels, and gates nothing.
    queue_metrics_are_official = bool(
        sampling_is_full_1s and completeness["scientific_analysis_permitted"]
    )

    window_bounds = {
        WINDOW_DEMAND_ACTIVE: (0.0, min(generation_end, clearance_time)),
        WINDOW_FULL_EPISODE: (0.0, clearance_time),
    }

    # An online decision log is what makes switch counts meaningful. A
    # pretimed controller writes none, so those quantities are labelled
    # inapplicable rather than fabricated as zero. Phase-derived quantities --
    # green spells, service deprivation, yellow fraction, emergent cycle --
    # are unaffected and stay comparable across every controller family.
    action_metrics_applicable = bool(action_rows)

    green_spell_rows, non_green_spell_rows, cycle_rows = [], [], []
    movement_rows = []
    by_intersection = {}

    for window in WINDOWS:
        window_start, window_end = window_bounds[window]
        window_seconds = window_end - window_start
        by_intersection.setdefault(window, {})

        for intersection in traffic_lights:
            seconds = [
                item for item in _phase_seconds(phase_rows, intersection)
                if item[0] <= window_end + 1e-9
            ]
            phases = [phase for _time, phase in seconds]
            yellow_seconds = sum(1 for phase in phases if phase == YELLOW)
            green_seconds = dict(
                (movement, sum(1 for phase in phases if phase == movement))
                for movement in MOVEMENTS
            )
            total_green = sum(green_seconds.values())

            actions_in_window = [
                row for row in action_rows
                if row["intersection"] == intersection
                and float(row["decision_time"]) < window_end - 1e-9
            ]
            switch_count = sum(
                1 for row in actions_in_window if row["action"] == "SWITCH"
            )
            decision_count = len(actions_in_window)

            h_starts = []
            for movement in MOVEMENTS:
                green = contiguous_spells(
                    seconds, lambda phase, m=movement: phase == m,
                    window_start, window_end,
                )
                non_green = contiguous_spells(
                    seconds, lambda phase, m=movement: phase != m,
                    window_start, window_end,
                )
                if movement == "H":
                    h_starts = [spell["start_s"] for spell in green]

                for spell in green:
                    green_spell_rows.append(dict(
                        spell, episode_index=chosen, window=window,
                        intersection=intersection, movement=movement,
                    ))
                for spell in non_green:
                    non_green_spell_rows.append(dict(
                        spell, episode_index=chosen, window=window,
                        intersection=intersection, movement=movement,
                    ))

                green_stats = _stats([s["duration_s"] for s in green])
                non_green_stats = _stats([s["duration_s"] for s in non_green])

                incoming = lanes[intersection]["{}_in".format(movement)]
                queue_series = _summed_lane_series(lane_rows, incoming, "queue")
                queue_values = [
                    value for time_value, value in sorted(queue_series.items())
                    if window_start < time_value <= window_end + 1e-9
                ]
                queue_stats = _stats(queue_values)

                utilisation = float("nan")
                utilisation_green_seconds = 0
                if sampling_is_full_1s:
                    counts = _summed_lane_series(
                        lane_rows, incoming, "vehicle_count"
                    )
                    green_second_times = [
                        time_value for time_value, phase in seconds
                        if phase == movement
                    ]
                    utilisation_green_seconds = len(green_second_times)
                    if utilisation_green_seconds:
                        used = sum(
                            1 for time_value in green_second_times
                            if counts.get(time_value, 0.0) > 0.0
                        )
                        utilisation = float(used) / float(
                            utilisation_green_seconds
                        )

                movement_rows.append({
                    "episode_index": chosen,
                    "window": window,
                    "window_start_s": window_start,
                    "window_end_s": window_end,
                    "intersection": intersection,
                    "movement": movement,
                    "green_spell_count": green_stats["count"],
                    "green_mean_s": green_stats["mean_s"],
                    "green_median_s": green_stats["median_s"],
                    "green_p95_s": green_stats["p95_s"],
                    "green_max_s": green_stats["max_s"],
                    "green_total_s": green_stats["total_s"],
                    "green_right_censored_count": sum(
                        1 for s in green if s["right_censored"]
                    ),
                    "non_green_spell_count": non_green_stats["count"],
                    "non_green_mean_s": non_green_stats["mean_s"],
                    "non_green_median_s": non_green_stats["median_s"],
                    "non_green_p95_s": non_green_stats["p95_s"],
                    "non_green_max_s": non_green_stats["max_s"],
                    "non_green_right_censored_count": sum(
                        1 for s in non_green if s["right_censored"]
                    ),
                    "green_service_count": green_stats["count"],
                    "services_per_hour": (
                        3600.0 * green_stats["count"] / window_seconds
                        if window_seconds > 0 else float("nan")
                    ),
                    "green_share_among_green_time": (
                        float(green_seconds[movement]) / total_green
                        if total_green else float("nan")
                    ),
                    "queue_mean": queue_stats["mean_s"],
                    "queue_median": queue_stats["median_s"],
                    "queue_p95": queue_stats["p95_s"],
                    "queue_max": queue_stats["max_s"],
                    "queue_sample_count": queue_stats["count"],
                    "queue_sampling_cadence": cadence,
                    "queue_metrics_sampling_is_full_1s": sampling_is_full_1s,
                    "queue_metrics_are_official": queue_metrics_are_official,
                    "green_demand_utilisation": utilisation,
                    "green_demand_utilisation_green_seconds": (
                        utilisation_green_seconds
                    ),
                    "green_demand_utilisation_sampling_is_full_1s": (
                        sampling_is_full_1s
                    ),
                    "green_demand_utilisation_is_official": (
                        queue_metrics_are_official
                    ),
                })

            ordered_starts = sorted(h_starts)
            cycles = [
                ordered_starts[index + 1] - ordered_starts[index]
                for index in range(len(ordered_starts) - 1)
            ]
            for index, value in enumerate(cycles):
                cycle_rows.append({
                    "episode_index": chosen,
                    "window": window,
                    "intersection": intersection,
                    "cycle_index": index,
                    "h_start_s": ordered_starts[index],
                    "next_h_start_s": ordered_starts[index + 1],
                    "emergent_cycle_s": value,
                })
            cycle_stats = _stats(cycles)

            by_intersection[window][intersection] = {
                "window_start_s": window_start,
                "window_end_s": window_end,
                "H_green_seconds": green_seconds["H"],
                "V_green_seconds": green_seconds["V"],
                "yellow_seconds": yellow_seconds,
                "H_green_share_among_green_time": (
                    float(green_seconds["H"]) / total_green
                    if total_green else float("nan")
                ),
                "V_green_share_among_green_time": (
                    float(green_seconds["V"]) / total_green
                    if total_green else float("nan")
                ),
                "yellow_fraction_of_elapsed": (
                    float(yellow_seconds) / window_seconds
                    if window_seconds > 0 else float("nan")
                ),
                "action_metrics_applicable": action_metrics_applicable,
                "switch_count": (
                    switch_count if action_metrics_applicable else NOT_APPLICABLE
                ),
                "decision_count": (
                    decision_count if action_metrics_applicable
                    else NOT_APPLICABLE
                ),
                "switches_per_hour": (
                    NOT_APPLICABLE if not action_metrics_applicable
                    else 3600.0 * switch_count / window_seconds
                    if window_seconds > 0 else float("nan")
                ),
                "switch_fraction_of_decisions": (
                    NOT_APPLICABLE if not action_metrics_applicable
                    else float(switch_count) / decision_count
                    if decision_count else float("nan")
                ),
                "emergent_cycle_mean_s": cycle_stats["mean_s"],
                "emergent_cycle_median_s": cycle_stats["median_s"],
                "emergent_cycle_p95_s": cycle_stats["p95_s"],
                "emergent_cycle_sd_s": cycle_stats["sd_s"],
                "emergent_cycle_count": cycle_stats["count"],
            }

    summary = {
        "episode_index": chosen,
        "episodes_in_source": episodes,
        "output_directory": destination,
        "clearance_time_s": clearance_time,
        "demand_generation_end_s": generation_end,
        "action_metrics_applicable": action_metrics_applicable,
        "action_metrics_note": (
            "Switch counts, decision counts and switch rates exist only for a "
            "controller that takes online decisions. This source logged {} "
            "decisions, so they are reported as '{}' rather than as zero, and "
            "must not be compared across controller families with different "
            "decision semantics. Phase-derived quantities stay comparable."
            .format(len(action_rows), NOT_APPLICABLE)
            if not action_metrics_applicable else
            "This source logged {} online decisions, so action-based "
            "quantities are defined. They remain comparable only within a "
            "controller family that shares the same decision semantics."
            .format(len(action_rows))
        ),
        "primary_window": WINDOW_DEMAND_ACTIVE,
        "primary_window_complete": completeness["demand_active_window_complete"],
        # The demand-active window is clipped to the observed trace, so a
        # truncated episode reports [0, 1235] under the name "demand_active".
        # The bounds are stated rather than left implicit in the label.
        "window_bounds_s": dict(
            (window, list(window_bounds[window])) for window in WINDOWS
        ),
        "lane_state_sampling_cadence": cadence,
        "queue_metrics_sampling_is_full_1s": sampling_is_full_1s,
        "queue_metrics_are_official": queue_metrics_are_official,
        "queue_metrics_note": (
            "Queue and green-demand-utilisation metrics are official only when "
            "the lane-state log is a full 1 s log AND the episode is a "
            "complete preregistered observation. This source is sampled at "
            "'{}' and its demand-active window is {}."
            .format(
                cadence,
                "complete" if completeness["demand_active_window_complete"]
                else "INCOMPLETE",
            )
        ),
        "non_green_definition": (
            "service deprivation: contiguous seconds with actual_phase != "
            "movement, including the opposing green and the yellow transition"
        ),
        "emergent_cycle_definition": (
            "interval between consecutive H-green starts at one intersection; "
            "descriptive only, the controller imposes no cycle"
        ),
        "by_intersection": by_intersection,
    }
    summary.update(completeness)

    write_rows(
        os.path.join(destination, "green_spell_distribution.csv"),
        green_spell_rows,
        ["episode_index", "window", "intersection", "movement", "spell_index",
         "start_s", "end_s", "duration_s", "right_censored", "at_window_start"],
    )
    write_rows(
        os.path.join(destination, "non_green_spell_distribution.csv"),
        non_green_spell_rows,
        ["episode_index", "window", "intersection", "movement", "spell_index",
         "start_s", "end_s", "duration_s", "right_censored", "at_window_start"],
    )
    write_rows(
        os.path.join(destination, "emergent_cycle_distribution.csv"),
        cycle_rows,
    )
    write_rows(
        os.path.join(
            destination, "behavior_metrics_by_intersection_movement.csv"
        ),
        movement_rows,
    )
    with open(
        os.path.join(destination, "behavior_summary.json"), "w"
    ) as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
    return summary
