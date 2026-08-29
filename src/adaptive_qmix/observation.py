"""Symmetric eight-dimensional local observations."""

from __future__ import absolute_import

from collections import deque

import numpy as np


class NetworkSchemaError(RuntimeError):
    pass


class SymmetricObservationBuilder(object):
    def __init__(self, traci_module, config, data_source=None):
        self.traci = traci_module
        self.source = data_source
        self.config = config
        self.spec = config["observation"]
        self.tl_ids = list(config["network"]["traffic_lights"])
        self.arrival_window_s = int(self.spec["arrival_window_s"])
        self.previous_members = {}
        self.arrival_counts = {}
        for tl_id in self.tl_ids:
            for movement in ("H", "V"):
                key = (tl_id, movement)
                self.previous_members[key] = set()
                self.arrival_counts[key] = deque(maxlen=self.arrival_window_s)

    def validate_runtime_schema(self):
        available = set(self.traci.lane.getIDList())
        all_expected = set()
        for tl_lanes in self.spec["lanes"].values():
            for lane_group in tl_lanes.values():
                all_expected.update(lane_group)
        missing = sorted(all_expected - available)
        if missing:
            raise NetworkSchemaError("Missing configured lanes: {}".format(missing))

        tolerance = float(self.spec["lane_length_tolerance_m"])
        for lane_id, expected_length in self.spec["expected_lane_lengths_m"].items():
            actual = float(self.traci.lane.getLength(lane_id))
            if abs(actual - float(expected_length)) > tolerance:
                raise NetworkSchemaError(
                    "Lane length mismatch for {}: expected {}, got {}".format(
                        lane_id, expected_length, actual
                    )
                )

        vehicle_type = self.config["demand"]["vehicle_type"]["id"]
        actual_length = float(self.traci.vehicletype.getLength(vehicle_type))
        actual_gap = float(self.traci.vehicletype.getMinGap(vehicle_type))
        if abs(actual_length - float(self.spec["vehicle_length_m"])) > 1e-9:
            raise NetworkSchemaError("Vehicle length differs from the frozen value.")
        if abs(actual_gap - float(self.spec["min_gap_m"])) > 1e-9:
            raise NetworkSchemaError("Vehicle minGap differs from the frozen value.")

    def reset_history(self):
        for key in self.previous_members:
            self.previous_members[key] = set()
            self.arrival_counts[key].clear()

    def _vehicle_members(self, lane_ids):
        members = set()
        for lane_id in lane_ids:
            members.update(self.source.lane_vehicle_ids(lane_id))
        return members

    def update_arrivals_one_second(self):
        result = {}
        for tl_id in self.tl_ids:
            lane_spec = self.spec["lanes"][tl_id]
            for movement in ("H", "V"):
                key = (tl_id, movement)
                current = self._vehicle_members(lane_spec["{}_in".format(movement)])
                arrivals = current - self.previous_members[key]
                self.arrival_counts[key].append(len(arrivals))
                self.previous_members[key] = current
                result[key] = sorted(arrivals)
        return result

    def _queue(self, lane_ids):
        return sum(
            int(self.source.lane_halting_number(lane_id))
            for lane_id in lane_ids
        )

    def _max_occupancy(self, lane_ids):
        if not lane_ids:
            return 0.0
        return min(
            1.0,
            max(
                0.0,
                max(
                    float(self.source.lane_occupancy(lane_id)) / 100.0
                    for lane_id in lane_ids
                ),
            ),
        )

    def build(self, current_phase, green_elapsed):
        normalized = []
        raw_rows = []
        for tl_id in self.tl_ids:
            lanes = self.spec["lanes"][tl_id]
            q_h = self._queue(lanes["H_in"])
            q_v = self._queue(lanes["V_in"])
            lambda_h = sum(self.arrival_counts[(tl_id, "H")]) / float(
                self.arrival_window_s
            )
            lambda_v = sum(self.arrival_counts[(tl_id, "V")]) / float(
                self.arrival_window_s
            )
            occ_h = self._max_occupancy(lanes["H_out"])
            occ_v = self._max_occupancy(lanes["V_out"])
            phase_h = 1.0 if current_phase[tl_id] == "H" else 0.0
            elapsed = float(green_elapsed[tl_id])
            elapsed_scale = float(self.spec["green_elapsed_scale_s"])

            vector = np.asarray(
                [
                    min(1.0, max(0.0, q_h / float(self.spec["queue_normalizer_H"]))),
                    min(1.0, max(0.0, q_v / float(self.spec["queue_normalizer_V"]))),
                    phase_h,
                    elapsed / (elapsed + elapsed_scale),
                    lambda_h / (lambda_h + float(self.spec["arrival_rate_scale_veh_s"])),
                    lambda_v / (lambda_v + float(self.spec["arrival_rate_scale_veh_s"])),
                    occ_h,
                    occ_v,
                ],
                dtype=np.float32,
            )
            if vector.shape != (8,) or not np.all(np.isfinite(vector)):
                raise RuntimeError("Invalid normalized observation for {}".format(tl_id))
            normalized.append(vector)
            raw_rows.append(
                {
                    "intersection": tl_id,
                    "q_H": q_h,
                    "q_V": q_v,
                    "phase": current_phase[tl_id],
                    "green_elapsed_s": elapsed,
                    "lambda_H_veh_s": lambda_h,
                    "lambda_V_veh_s": lambda_v,
                    "occ_H_out": occ_h,
                    "occ_V_out": occ_v,
                }
            )
        observations = np.stack(normalized, axis=0)
        return observations, observations.reshape(-1).copy(), raw_rows

