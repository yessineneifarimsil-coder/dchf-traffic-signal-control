"""Preregistered coordination metrics and virtual-detector event tracking."""

from __future__ import absolute_import

import bisect

import numpy as np

from .reward import is_stopped


def green_at_approach_detector(events):
    """GAD50: fraction of 50-m detector crossings observed during H green."""
    eligible = [event for event in events if event.get("event") == "GAD50"]
    if not eligible:
        return float("nan")
    green = sum(1 for event in eligible if event.get("signal_state") == "H")
    return 100.0 * float(green) / float(len(eligible))


def projected_stop_line_arrival_events(events, phase_intervals, distance_m=50.0,
                                       free_flow_speed_m_s=13.89):
    """Free-flow projection proxy; never an observed stop-line AOG measure."""
    projected = []
    travel = float(distance_m) / float(free_flow_speed_m_s)
    for event in events:
        if event.get("event") != "GAD50":
            continue
        projected_time = float(event["time"]) + travel
        projected.append(
            {
                "vehicle_id": event["vehicle_id"],
                "detector_time": float(event["time"]),
                "projected_stop_line_time": projected_time,
                "projected_signal_state": phase_at_time(
                    phase_intervals, projected_time
                ),
                "is_proxy": True,
            }
        )
    return projected


def projected_aog_percentage(projected_events):
    if not projected_events:
        return float("nan")
    green = sum(
        1 for event in projected_events
        if event["projected_signal_state"] == "H"
    )
    return 100.0 * float(green) / float(len(projected_events))


def phase_at_time(intervals, time_value):
    """Return the phase for half-open intervals [start, end)."""
    for interval in intervals:
        if float(interval["start"]) <= time_value < float(interval["end"]):
            return interval["phase"]
    return None


def green_start_lag_distribution(j1_green_starts, j2_green_starts, max_lag_s=120):
    """Directional event lag: first J2 H start at/after each J1 H start."""
    downstream = sorted(float(value) for value in j2_green_starts)
    rows = []
    for upstream_time in sorted(float(value) for value in j1_green_starts):
        position = bisect.bisect_left(downstream, upstream_time)
        if position >= len(downstream):
            rows.append({"J1_start": upstream_time, "J2_start": None,
                         "lag_s": None, "censored": True})
            continue
        downstream_time = downstream[position]
        lag = downstream_time - upstream_time
        censored = lag > float(max_lag_s)
        rows.append(
            {
                "J1_start": upstream_time,
                "J2_start": downstream_time,
                "lag_s": None if censored else lag,
                "censored": censored,
            }
        )
    return rows


def phase_cross_correlation(j1_phase_h, j2_phase_h, max_lag_s=120):
    """corr(g1(t), g2(t+lag)); a positive lag means J2 follows J1."""
    first = np.asarray(j1_phase_h, dtype=np.float64)
    second = np.asarray(j2_phase_h, dtype=np.float64)
    if first.shape != second.shape or first.ndim != 1:
        raise ValueError("Phase series must be equal-length one-dimensional arrays.")
    rows = []
    max_lag = min(int(max_lag_s), max(0, len(first) - 2))
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x_values = first[:len(first) - lag] if lag else first
            y_values = second[lag:]
        else:
            x_values = first[-lag:]
            y_values = second[:len(second) + lag]
        if len(x_values) < 2 or np.std(x_values) == 0 or np.std(y_values) == 0:
            correlation = float("nan")
        else:
            correlation = float(np.corrcoef(x_values, y_values)[0, 1])
        rows.append({"lag_s": lag, "correlation": correlation})
    finite = [row for row in rows if np.isfinite(row["correlation"])]
    if not finite:
        dominant = None
    else:
        dominant = sorted(
            finite,
            key=lambda row: (-row["correlation"], abs(row["lag_s"]), row["lag_s"]),
        )[0]
    return {"distribution": rows, "dominant": dominant}


class VirtualDetectorTracker(object):
    """Track physical 50-m crossings, downstream stops and stop-line exits."""

    def __init__(self, data_source, lane_ids, detector_position_m):
        self.source = data_source
        self.lane_ids = set(lane_ids)
        self.detector_position_m = float(detector_position_m)
        self.previous = {}
        self.detector_crossed = set()
        self.stopped_after_detector = set()
        self.release_seen = set()

    def sample(self, simulation_time, signal_state, release_signal_state=None):
        current = {}
        events = []
        for vehicle_id in self.source.vehicle_ids():
            lane_id = self.source.vehicle_lane_id(vehicle_id)
            if lane_id not in self.lane_ids:
                continue
            position = float(self.source.vehicle_lane_position(vehicle_id))
            speed = float(self.source.vehicle_speed(vehicle_id))
            current[vehicle_id] = (lane_id, position, speed)
            prior = self.previous.get(vehicle_id)
            if prior is None and vehicle_id not in self.release_seen:
                self.release_seen.add(vehicle_id)
                events.append(
                    {
                        "vehicle_id": vehicle_id,
                        "event": "UPSTREAM_RELEASE",
                        "time": float(simulation_time),
                        "lane": lane_id,
                        "position_m": position,
                        "speed_m_s": speed,
                        "signal_state": release_signal_state,
                    }
                )
            if (
                vehicle_id not in self.detector_crossed
                and position >= self.detector_position_m
                and (prior is None or prior[1] < self.detector_position_m)
            ):
                self.detector_crossed.add(vehicle_id)
                events.append(
                    {
                        "vehicle_id": vehicle_id,
                        "event": "GAD50",
                        "time": float(simulation_time),
                        "lane": lane_id,
                        "position_m": position,
                        "speed_m_s": speed,
                        "signal_state": signal_state,
                    }
                )
            if vehicle_id in self.detector_crossed and is_stopped(speed):
                self.stopped_after_detector.add(vehicle_id)
        for vehicle_id, prior in self.previous.items():
            if vehicle_id in current or vehicle_id not in self.detector_crossed:
                continue
            events.append(
                {
                    "vehicle_id": vehicle_id,
                    "event": "STOP_LINE_EXIT",
                    "time": float(simulation_time),
                    "lane": prior[0],
                    "position_m": prior[1],
                    "speed_m_s": prior[2],
                    "signal_state": signal_state,
                    "stopped_after_GAD50": vehicle_id in self.stopped_after_detector,
                }
            )
        self.previous = current
        return events
