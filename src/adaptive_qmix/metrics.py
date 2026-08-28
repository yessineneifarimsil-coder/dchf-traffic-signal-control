"""Primary scheduled-demand and secondary legacy evaluation metrics."""

from __future__ import absolute_import

import math
import xml.etree.ElementTree as ET


class MetricReconciliationError(RuntimeError):
    pass


def parse_tripinfo(path):
    rows = {}
    root = ET.parse(path).getroot()
    for element in root.findall("tripinfo"):
        vehicle_id = element.attrib["id"]
        if vehicle_id in rows:
            raise MetricReconciliationError(
                "Duplicate tripinfo ID: {}".format(vehicle_id)
            )
        row = dict(element.attrib)
        for field in (
            "depart", "departDelay", "arrival", "duration", "routeLength",
            "waitingTime", "waitingCount", "timeLoss",
        ):
            if field in row:
                row[field] = float(row[field])
        rows[vehicle_id] = row
    return rows


def scheduled_demand_metrics(ledger, tripinfo_rows, clearance_status):
    """Compute J_primary only when all 2800 scheduled outcomes are valid trips."""
    scheduled_ids = set(ledger.scheduled)
    trip_ids = set(tripinfo_rows)
    unknown = sorted(trip_ids - scheduled_ids)
    if unknown:
        raise MetricReconciliationError(
            "Tripinfo contains unscheduled IDs: {}".format(unknown[:10])
        )
    missing = sorted(scheduled_ids - trip_ids)
    completed = sorted(set(ledger.completed_at))
    if clearance_status == "CLEARED" and missing:
        raise MetricReconciliationError(
            "Cleared run is missing tripinfo for {} scheduled vehicles.".format(
                len(missing)
            )
        )

    primary_valid = (
        clearance_status == "CLEARED"
        and not missing
        and not ledger.exceptional
        and len(completed) == len(scheduled_ids)
    )
    burdens = []
    waiting_times = []
    depart_delays = []
    time_losses = []
    travel_times = []
    stop_counts = []
    for vehicle_id in completed:
        if vehicle_id not in tripinfo_rows:
            continue
        trip = tripinfo_rows[vehicle_id]
        waiting = float(trip["waitingTime"])
        depart_delay = float(trip["departDelay"])
        burdens.append(waiting + depart_delay)
        waiting_times.append(waiting)
        depart_delays.append(depart_delay)
        time_losses.append(float(trip.get("timeLoss", float("nan"))))
        travel_times.append(float(trip.get("duration", float("nan"))))
        stop_counts.append(float(trip.get("waitingCount", float("nan"))))

    def mean(values):
        finite = [value for value in values if math.isfinite(value)]
        return float("nan") if not finite else sum(finite) / float(len(finite))

    return {
        "J_primary_mean_scheduled_waiting_burden_s": (
            sum(burdens) / 2800.0 if primary_valid else float("nan")
        ),
        "J_primary_total_scheduled_waiting_burden_vehicle_s": (
            sum(burdens) if primary_valid else float("nan")
        ),
        "J_primary_valid": primary_valid,
        "mean_completed_waiting_time_s": mean(waiting_times),
        "mean_completed_depart_delay_s": mean(depart_delays),
        "mean_completed_time_loss_s": mean(time_losses),
        "mean_completed_travel_time_s": mean(travel_times),
        "mean_completed_stops": mean(stop_counts),
        "scheduled_count": len(scheduled_ids),
        "inserted_count": len(ledger.inserted_at),
        "completed_count": len(ledger.completed_at),
        "exceptional_count": len(ledger.exceptional),
        "tripinfo_count": len(tripinfo_rows),
        "missing_tripinfo_ids": missing,
        "exceptional_outcomes": dict(ledger.exceptional),
        "definition_note": (
            "J_primary is mean(waitingTime + departDelay) over all 2800 "
            "scheduled vehicles; it is not J_legacy."
        ),
    }


def legacy_metric(legacy_waiting_state_integral, sample_count):
    """Time-averaged aggregate active-vehicle getWaitingTime state."""
    if int(sample_count) <= 0:
        return float("nan")
    return float(legacy_waiting_state_integral) / float(sample_count)

