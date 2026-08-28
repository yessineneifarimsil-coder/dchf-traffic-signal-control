"""Derive preregistered mechanism metrics from raw CSV logs."""

from __future__ import absolute_import

import csv
import json
import math
import os

import numpy as np

from .coordination import (
    green_at_approach_detector,
    green_start_lag_distribution,
    phase_cross_correlation,
    projected_aog_percentage,
    projected_stop_line_arrival_events,
)


def _read_csv(path):
    with open(path, "r", newline="") as handle:
        return list(csv.DictReader(handle))


def _phase_series_and_intervals(rows, intersection):
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


def derive_coordination_metrics(run_directory, config):
    phase_rows = _read_csv(os.path.join(run_directory, "signal_phases.csv"))
    crossing_rows = _read_csv(os.path.join(run_directory, "vehicle_crossings.csv"))
    j1_series, j1_starts, _j1_intervals = _phase_series_and_intervals(
        phase_rows, "J1"
    )
    j2_series, j2_starts, j2_intervals = _phase_series_and_intervals(
        phase_rows, "J2"
    )
    if len(j1_series) != len(j2_series):
        raise RuntimeError("J1/J2 phase logs have different lengths.")

    events = []
    for row in crossing_rows:
        converted = dict(row)
        converted["time"] = float(row["time"])
        converted["vehicle_id"] = row["vehicle_id"]
        events.append(converted)
    gad_events = [row for row in events if row["event"] == "GAD50"]
    projected = projected_stop_line_arrival_events(
        gad_events,
        j2_intervals,
        config["coordination"]["detector_distance_to_stop_line_m"],
        config["coordination"]["free_flow_speed_m_s"],
    )

    by_vehicle = {}
    for event in events:
        by_vehicle.setdefault(event["vehicle_id"], {})[event["event"]] = event
    downstream_rows = []
    for vehicle_id, vehicle_events in sorted(by_vehicle.items()):
        release = vehicle_events.get("UPSTREAM_RELEASE")
        detector = vehicle_events.get("GAD50")
        crossing = vehicle_events.get("STOP_LINE_EXIT")
        if detector is None:
            continue
        downstream_rows.append(
            {
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
            }
        )

    completed_downstream = [
        row for row in downstream_rows
        if row["detector_to_stop_line_s"] is not None
    ]
    stopped = [
        row for row in completed_downstream if row["stopped_after_GAD50"]
    ]
    actual_green = [
        row for row in completed_downstream
        if row["actual_stop_line_signal_state"] == "H"
    ]
    travel_times = [row["detector_to_stop_line_s"] for row in completed_downstream]

    cross_correlation = phase_cross_correlation(
        j1_series,
        j2_series,
        config["coordination"]["cross_correlation_max_lag_s"],
    )
    event_lags = green_start_lag_distribution(
        j1_starts,
        j2_starts,
        config["coordination"]["cross_correlation_max_lag_s"],
    )
    summary = {
        "GAD50_percent": green_at_approach_detector(gad_events),
        "AOG_SL_projected_proxy_percent": projected_aog_percentage(projected),
        "AOG_SL_projected_is_proxy": True,
        "actual_stop_line_crossing_on_H_percent": (
            100.0 * len(actual_green) / float(len(completed_downstream))
            if completed_downstream else float("nan")
        ),
        "downstream_stop_rate_percent": (
            100.0 * len(stopped) / float(len(completed_downstream))
            if completed_downstream else float("nan")
        ),
        "mean_detector_to_stop_line_s": (
            float(np.mean(travel_times)) if travel_times else float("nan")
        ),
        "median_detector_to_stop_line_s": (
            float(np.median(travel_times)) if travel_times else float("nan")
        ),
        "dominant_cross_correlation_lag_s": (
            None if cross_correlation["dominant"] is None
            else cross_correlation["dominant"]["lag_s"]
        ),
        "GAD50_count": len(gad_events),
        "actual_stop_line_crossing_count": len(completed_downstream),
    }

    _write_csv(
        os.path.join(run_directory, "phase_lag_green_start_distribution.csv"),
        event_lags,
    )
    _write_csv(
        os.path.join(run_directory, "phase_cross_correlation_distribution.csv"),
        cross_correlation["distribution"],
    )
    _write_csv(
        os.path.join(run_directory, "vehicle_coordination_metrics.csv"),
        downstream_rows,
    )
    with open(os.path.join(run_directory, "coordination_summary.json"), "w") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
    return summary


def _write_csv(path, rows):
    if not rows:
        with open(path, "w") as handle:
            handle.write("")
        return
    fields = list(rows[0])
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
