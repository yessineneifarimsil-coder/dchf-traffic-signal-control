"""Preregistered coordination metrics and virtual-detector event tracking."""

from __future__ import absolute_import

import bisect

import numpy as np

from .reward import is_stopped


WE = "WE"
EW = "EW"
DIRECTIONS = (WE, EW)


class TopologyError(RuntimeError):
    pass


def derive_central_directions(config):
    """Derive both central travel directions from the observation topology.

    The corridor link between two adjacent signals is exactly the set of lanes
    that leave the upstream junction on H and enter the downstream junction on
    H. Reading it from the frozen observation lane sets avoids introducing a
    second, independent network definition that could silently drift from the
    one the controller actually uses.

    For the N=2 qualification corridor this resolves to E1_* westbound-origin
    (J1 -> J2) and -E1_* eastbound-origin (J2 -> J1).
    """
    lanes = config["observation"]["lanes"]
    traffic_lights = list(config["network"]["traffic_lights"])
    if len(traffic_lights) != 2:
        raise TopologyError(
            "Bidirectional central-link derivation currently supports exactly "
            "two traffic lights; got {}.".format(traffic_lights)
        )
    upstream_first, downstream_first = traffic_lights

    def central(upstream, downstream):
        shared = set(lanes[upstream]["H_out"]) & set(lanes[downstream]["H_in"])
        return sorted(shared)

    directions = {
        WE: {
            "direction": WE,
            "upstream": upstream_first,
            "downstream": downstream_first,
            "lanes": central(upstream_first, downstream_first),
        },
        EW: {
            "direction": EW,
            "upstream": downstream_first,
            "downstream": upstream_first,
            "lanes": central(downstream_first, upstream_first),
        },
    }
    validate_central_directions(directions, config)
    return directions


def validate_central_directions(directions, config):
    """Fail loudly on any topology that does not yield two disjoint links."""
    expected_lengths = config["observation"]["expected_lane_lengths_m"]
    central_length = float(config["coordination"]["central_lane_length_m"])
    seen = {}
    for name in DIRECTIONS:
        spec = directions[name]
        lane_ids = spec["lanes"]
        if not lane_ids:
            raise TopologyError(
                "No central lanes resolved for direction {} ({} -> {}); the "
                "observation topology does not describe a shared corridor "
                "link.".format(name, spec["upstream"], spec["downstream"])
            )
        if spec["upstream"] == spec["downstream"]:
            raise TopologyError(
                "Direction {} has the same upstream and downstream "
                "intersection.".format(name)
            )
        for lane_id in lane_ids:
            if lane_id in seen:
                raise TopologyError(
                    "Lane {} is claimed by both direction {} and direction "
                    "{}; the two travel directions must be disjoint.".format(
                        lane_id, seen[lane_id], name
                    )
                )
            seen[lane_id] = name
            if lane_id not in expected_lengths:
                raise TopologyError(
                    "Central lane {} for direction {} is absent from the "
                    "frozen expected lane lengths.".format(lane_id, name)
                )
            if abs(float(expected_lengths[lane_id]) - central_length) > 1e-6:
                raise TopologyError(
                    "Central lane {} is {} m but the coordination block "
                    "declares a {} m central link; the detector offset would "
                    "not be 50 m upstream of the stop line.".format(
                        lane_id, expected_lengths[lane_id], central_length
                    )
                )
    return directions


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

    def __init__(self, data_source, lane_ids, detector_position_m,
                 direction=None, upstream=None, downstream=None):
        self.source = data_source
        self.lane_ids = set(lane_ids)
        self.detector_position_m = float(detector_position_m)
        # SUMO lane coordinates increase along the travel direction, so the
        # same offset is 50 m upstream of the stop line in either direction.
        self.direction = direction
        self.upstream = upstream
        self.downstream = downstream
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
                        "direction": self.direction,
                        "upstream_intersection": self.upstream,
                        "downstream_intersection": self.downstream,
                        "intersection": self.upstream,
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
                        "direction": self.direction,
                        "upstream_intersection": self.upstream,
                        "downstream_intersection": self.downstream,
                        "intersection": self.downstream,
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
                    "direction": self.direction,
                    "upstream_intersection": self.upstream,
                    "downstream_intersection": self.downstream,
                    "intersection": self.downstream,
                }
            )
        self.previous = current
        return events
