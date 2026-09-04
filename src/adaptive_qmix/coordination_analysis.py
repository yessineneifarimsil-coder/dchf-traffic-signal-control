"""Derive preregistered mechanism metrics, per travel direction, from raw logs.

Both corridor directions are treated as first-class: WE (J1 -> J2) and EW
(J2 -> J1) are derived separately and never collapsed into one scalar, because
the bidirectional trade-off is itself the scientific question.

Sign convention, identical in both directions:

    positive lag means the DOWNSTREAM signal follows the UPSTREAM signal

so the correlation is oriented J1 -> J2 for WE and J2 -> J1 for EW.
"""

from __future__ import absolute_import

import json
import os

import numpy as np

from .coordination import (
    DIRECTIONS,
    derive_central_directions,
    green_at_approach_detector,
    green_start_lag_distribution,
    phase_cross_correlation,
    projected_aog_percentage,
    projected_stop_line_arrival_events,
)
from .raw_logs import (
    available_episodes,
    derived_output_directory,
    read_raw_tables,
    select_episode,
    write_rows,
)


SIGN_CONVENTION = (
    "positive lag means the downstream signal follows the upstream signal"
)

REQUIRED_TABLES = ("signal_phases", "vehicle_crossings")


def _phase_series_and_intervals(rows, intersection):
    """Binary H series, H-green start times, and phase intervals.

    A row stamped time t describes the second [t-1, t), so an interval that
    begins with that row starts at t-1. Yellow is never counted as green.
    """
    selected = sorted(
        (row for row in rows if row["intersection"] == intersection),
        key=lambda row: float(row["time"]),
    )
    if not selected:
        return [], [], []
    series = [1 if row["actual_phase"] == "H" else 0 for row in selected]
    starts = [
        float(row["time"]) - 1.0
        for row in selected
        if row["actual_phase"] == "H"
        and str(row.get("green_start", "")).lower() in ("true", "1")
    ]
    intervals = []
    interval_start = float(selected[0]["time"]) - 1.0
    phase = selected[0]["actual_phase"]
    last_time = float(selected[0]["time"])
    for row in selected[1:]:
        time_value = float(row["time"])
        if row["actual_phase"] != phase:
            intervals.append(
                {"start": interval_start, "end": time_value - 1.0, "phase": phase}
            )
            interval_start = time_value - 1.0
            phase = row["actual_phase"]
        last_time = time_value
    intervals.append({"start": interval_start, "end": last_time, "phase": phase})
    return series, starts, intervals


def _vehicle_rows_for_direction(events, episode_index, direction):
    by_vehicle = {}
    for event in events:
        by_vehicle.setdefault(event["vehicle_id"], {})[event["event"]] = event
    rows = []
    for vehicle_id, vehicle_events in sorted(by_vehicle.items()):
        release = vehicle_events.get("UPSTREAM_RELEASE")
        detector = vehicle_events.get("GAD50")
        crossing = vehicle_events.get("STOP_LINE_EXIT")
        if detector is None:
            continue
        rows.append({
            "episode_index": episode_index,
            "direction": direction,
            "vehicle_id": vehicle_id,
            "release_to_detector_s": (
                float(detector["time"]) - float(release["time"])
                if release is not None else None
            ),
            "detector_to_stop_line_s": (
                float(crossing["time"]) - float(detector["time"])
                if crossing is not None else None
            ),
            "release_to_stop_line_s": (
                float(crossing["time"]) - float(release["time"])
                if release is not None and crossing is not None else None
            ),
            "GAD50_signal_state": detector["signal_state"],
            "actual_stop_line_signal_state": (
                crossing["signal_state"] if crossing is not None else None
            ),
            "stopped_after_GAD50": (
                str(crossing.get("stopped_after_GAD50", "")).lower()
                in ("true", "1") if crossing is not None else None
            ),
        })
    return rows


def derive_coordination_metrics(run_directory, config, episode_index=None,
                                output_directory=None):
    """Direction-resolved mechanism metrics for exactly one episode."""
    tables = read_raw_tables(run_directory, REQUIRED_TABLES)
    episodes = available_episodes(tables)
    chosen, filtered = select_episode(tables, episode_index)
    destination = derived_output_directory(
        run_directory, len(episodes), chosen, output_directory
    )
    phase_rows = filtered["signal_phases"]
    crossing_rows = []
    for row in filtered["vehicle_crossings"]:
        converted = dict(row)
        converted["time"] = float(row["time"])
        crossing_rows.append(converted)

    directions = derive_central_directions(config)
    per_intersection = dict(
        (name, _phase_series_and_intervals(phase_rows, name))
        for name in config["network"]["traffic_lights"]
    )
    lengths = set(len(value[0]) for value in per_intersection.values())
    if len(lengths) != 1:
        raise RuntimeError(
            "Phase logs have different lengths per intersection: {}".format(
                dict((k, len(v[0])) for k, v in per_intersection.items())
            )
        )

    max_lag = config["coordination"]["cross_correlation_max_lag_s"]
    summary_directions = {}
    lag_rows, correlation_rows, vehicle_rows = [], [], []

    for direction in DIRECTIONS:
        spec = directions[direction]
        upstream, downstream = spec["upstream"], spec["downstream"]
        upstream_series, upstream_starts, _ = per_intersection[upstream]
        downstream_series, downstream_starts, downstream_intervals = (
            per_intersection[downstream]
        )

        events = [
            row for row in crossing_rows if row.get("direction") == direction
        ]
        gad_events = [row for row in events if row["event"] == "GAD50"]
        projected = projected_stop_line_arrival_events(
            gad_events,
            downstream_intervals,
            config["coordination"]["detector_distance_to_stop_line_m"],
            config["coordination"]["free_flow_speed_m_s"],
        )
        direction_vehicle_rows = _vehicle_rows_for_direction(
            events, chosen, direction
        )
        completed = [
            row for row in direction_vehicle_rows
            if row["detector_to_stop_line_s"] is not None
        ]
        stopped = [row for row in completed if row["stopped_after_GAD50"]]
        on_green = [
            row for row in completed
            if row["actual_stop_line_signal_state"] == "H"
        ]
        travel_times = [row["detector_to_stop_line_s"] for row in completed]

        # Orientation is upstream first in both directions, so a positive lag
        # always means the downstream signal follows the upstream one.
        correlation = phase_cross_correlation(
            upstream_series, downstream_series, max_lag
        )
        lags = green_start_lag_distribution(
            upstream_starts, downstream_starts, max_lag
        )

        for row in lags:
            enriched = dict(row)
            enriched["episode_index"] = chosen
            enriched["direction"] = direction
            enriched["upstream_intersection"] = upstream
            enriched["downstream_intersection"] = downstream
            enriched["upstream_start"] = enriched.pop("J1_start", None)
            enriched["downstream_start"] = enriched.pop("J2_start", None)
            lag_rows.append(enriched)
        for row in correlation["distribution"]:
            enriched = dict(row)
            enriched["episode_index"] = chosen
            enriched["direction"] = direction
            correlation_rows.append(enriched)
        vehicle_rows.extend(direction_vehicle_rows)

        summary_directions[direction] = {
            "upstream_intersection": upstream,
            "downstream_intersection": downstream,
            "central_lanes": list(spec["lanes"]),
            "GAD50_percent": green_at_approach_detector(gad_events),
            "AOG_SL_projected_proxy_percent": projected_aog_percentage(projected),
            "AOG_SL_projected_is_proxy": True,
            "actual_stop_line_crossing_on_H_percent": (
                100.0 * len(on_green) / float(len(completed))
                if completed else float("nan")
            ),
            "downstream_stop_rate_percent": (
                100.0 * len(stopped) / float(len(completed))
                if completed else float("nan")
            ),
            "mean_detector_to_stop_line_s": (
                float(np.mean(travel_times)) if travel_times else float("nan")
            ),
            "median_detector_to_stop_line_s": (
                float(np.median(travel_times)) if travel_times else float("nan")
            ),
            "dominant_cross_correlation_lag_s": (
                None if correlation["dominant"] is None
                else correlation["dominant"]["lag_s"]
            ),
            "dominant_cross_correlation": (
                None if correlation["dominant"] is None
                else correlation["dominant"]["correlation"]
            ),
            "GAD50_count": len(gad_events),
            "actual_stop_line_crossing_count": len(completed),
            "green_start_lag_count": len(lags),
            "green_start_lag_censored_count": sum(
                1 for row in lags if row["censored"]
            ),
        }

    summary = {
        "episode_index": chosen,
        "episodes_in_source": episodes,
        "output_directory": destination,
        "sign_convention": SIGN_CONVENTION,
        "directions": summary_directions,
    }

    write_rows(
        os.path.join(destination, "phase_lag_green_start_distribution.csv"),
        lag_rows,
    )
    write_rows(
        os.path.join(destination, "phase_cross_correlation_distribution.csv"),
        correlation_rows,
    )
    write_rows(
        os.path.join(destination, "vehicle_coordination_metrics.csv"),
        vehicle_rows,
    )
    with open(
        os.path.join(destination, "coordination_summary.json"), "w"
    ) as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
    return summary
