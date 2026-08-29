"""Incremental network stopped-delay plus due insertion delay."""

from __future__ import absolute_import


STOPPED_SPEED_THRESHOLD_M_S = 0.1


def is_stopped(speed_m_s):
    return float(speed_m_s) <= STOPPED_SPEED_THRESHOLD_M_S


class NetworkDelayReward(object):
    def __init__(self, data_source, ledger):
        self.source = data_source
        self.ledger = ledger
        self.reset_block()

    def reset_block(self):
        self.active_stopped_vehicle_seconds = 0
        self.pending_due_vehicle_seconds = 0
        self.second_rows = []

    def sample_second(self, simulation_time):
        vehicle_ids = list(self.source.vehicle_ids())
        stopped = sum(
            1 for vehicle_id in vehicle_ids
            if is_stopped(self.source.vehicle_speed(vehicle_id))
        )
        pending = len(self.ledger.pending_due_ids(simulation_time))
        self.active_stopped_vehicle_seconds += stopped
        self.pending_due_vehicle_seconds += pending
        row = {
            "time": float(simulation_time),
            "active_vehicle_count": len(vehicle_ids),
            "stopped_active_count": int(stopped),
            "pending_due_count": int(pending),
            "incremental_delay_vehicle_seconds": int(stopped + pending),
        }
        self.second_rows.append(row)
        return row

    def finish_block(self):
        delay = self.active_stopped_vehicle_seconds + self.pending_due_vehicle_seconds
        return {
            "reward": -float(delay),
            "active_stopped_vehicle_seconds": int(self.active_stopped_vehicle_seconds),
            "pending_due_vehicle_seconds": int(self.pending_due_vehicle_seconds),
            "total_delay_vehicle_seconds": int(delay),
            "seconds": list(self.second_rows),
        }


def legacy_waiting_state(data_source):
    return sum(
        data_source.vehicle_waiting_time(vehicle_id)
        for vehicle_id in data_source.vehicle_ids()
    )

