"""Independent accounting ledger for all scheduled vehicle IDs."""

from __future__ import absolute_import


class LedgerError(RuntimeError):
    pass


class VehicleLedger(object):
    """Track scheduled, inserted, active, completed and exceptional vehicles."""

    def __init__(self, records):
        scheduled = {}
        for record in records:
            vehicle_id = str(record["vehicle_id"])
            if vehicle_id in scheduled:
                raise LedgerError("Duplicate scheduled vehicle ID: {}".format(vehicle_id))
            scheduled[vehicle_id] = int(record["depart"])
        if len(scheduled) != 2800:
            raise LedgerError("Qualification ledger requires exactly 2800 IDs.")

        self.scheduled = scheduled
        self.inserted_at = {}
        self.completed_at = {}
        self.exceptional = {}
        self.teleport_started = set()
        self.teleport_ended = set()

    def mark_departed(self, vehicle_ids, simulation_time):
        time_value = float(simulation_time)
        for vehicle_id in vehicle_ids:
            if vehicle_id not in self.scheduled:
                raise LedgerError("SUMO inserted unscheduled ID: {}".format(vehicle_id))
            if vehicle_id in self.inserted_at:
                raise LedgerError("Vehicle departed more than once: {}".format(vehicle_id))
            self.inserted_at[vehicle_id] = time_value

    def mark_arrived(self, vehicle_ids, simulation_time):
        time_value = float(simulation_time)
        for vehicle_id in vehicle_ids:
            if vehicle_id not in self.scheduled:
                raise LedgerError("SUMO completed unscheduled ID: {}".format(vehicle_id))
            if vehicle_id not in self.inserted_at:
                raise LedgerError("Vehicle arrived without a recorded insertion: {}".format(vehicle_id))
            if vehicle_id in self.completed_at:
                raise LedgerError("Vehicle arrived more than once: {}".format(vehicle_id))
            self.completed_at[vehicle_id] = time_value

    def mark_exceptional(self, vehicle_id, category, simulation_time, detail=""):
        if vehicle_id not in self.scheduled:
            raise LedgerError("Exceptional outcome for unscheduled ID: {}".format(vehicle_id))
        if vehicle_id in self.completed_at:
            raise LedgerError("Completed vehicle cannot also be exceptional: {}".format(vehicle_id))
        self.exceptional[vehicle_id] = {
            "category": str(category),
            "time": float(simulation_time),
            "detail": str(detail),
        }

    def mark_teleport_start(self, vehicle_ids):
        self.teleport_started.update(vehicle_ids)

    def mark_teleport_end(self, vehicle_ids):
        self.teleport_ended.update(vehicle_ids)

    def pending_due_ids(self, simulation_time):
        time_value = float(simulation_time)
        return {
            vehicle_id
            for vehicle_id, depart in self.scheduled.items()
            if depart <= time_value
            and vehicle_id not in self.inserted_at
            and vehicle_id not in self.exceptional
        }

    def scheduled_future_ids(self, simulation_time):
        time_value = float(simulation_time)
        return {
            vehicle_id
            for vehicle_id, depart in self.scheduled.items()
            if depart > time_value
            and vehicle_id not in self.inserted_at
            and vehicle_id not in self.exceptional
        }

    def active_ids_from_ledger(self):
        terminal = set(self.completed_at) | set(self.exceptional)
        return set(self.inserted_at) - terminal

    def assert_active_consistency(self, sumo_active_ids):
        ledger_active = self.active_ids_from_ledger()
        sumo_active = set(sumo_active_ids)
        silently_missing = ledger_active - sumo_active
        unknown_active = sumo_active - set(self.scheduled)
        if silently_missing:
            raise LedgerError(
                "UNACCOUNTED_VEHICLE: inserted IDs disappeared without terminal event: {}".format(
                    sorted(silently_missing)[:10]
                )
            )
        if unknown_active:
            raise LedgerError("SUMO contains unknown active IDs: {}".format(sorted(unknown_active)[:10]))

    def is_reconciled_clear(self, simulation_time, sumo_active_ids, min_expected_number):
        if float(simulation_time) < 3600.0:
            return False
        if set(sumo_active_ids):
            return False
        if self.pending_due_ids(simulation_time):
            return False
        if self.scheduled_future_ids(simulation_time):
            return False
        if int(min_expected_number) != 0:
            return False
        accounted = len(self.completed_at) + len(self.exceptional)
        return accounted == len(self.scheduled)

    def snapshot(self, simulation_time, sumo_active_ids=None, min_expected_number=None):
        active = set(sumo_active_ids or [])
        return {
            "simulation_time": float(simulation_time),
            "scheduled": len(self.scheduled),
            "inserted": len(self.inserted_at),
            "completed": len(self.completed_at),
            "exceptional_terminal": len(self.exceptional),
            "pending_due": len(self.pending_due_ids(simulation_time)),
            "scheduled_future": len(self.scheduled_future_ids(simulation_time)),
            "active_sumo": len(active),
            "active_ledger": len(self.active_ids_from_ledger()),
            "min_expected_number": (
                None if min_expected_number is None else int(min_expected_number)
            ),
            "teleport_started": len(self.teleport_started),
            "teleport_ended": len(self.teleport_ended),
        }

    def total_depart_delay(self):
        return sum(
            max(0.0, inserted - self.scheduled[vehicle_id])
            for vehicle_id, inserted in self.inserted_at.items()
        )


def reconcile_scheduled_outcomes(ledger):
    accounted = set(ledger.completed_at) | set(ledger.exceptional)
    missing = set(ledger.scheduled) - accounted
    overlap = set(ledger.completed_at) & set(ledger.exceptional)
    return {
        "valid": not missing and not overlap,
        "missing_ids": sorted(missing),
        "overlap_ids": sorted(overlap),
    }

