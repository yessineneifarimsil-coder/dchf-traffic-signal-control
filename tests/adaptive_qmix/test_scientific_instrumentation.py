"""Batch S1: episode-safe logging, behaviour/starvation, bidirectional mechanism.

Everything here runs on synthetic logs, so each assertion is hand-computable
and no SUMO run is needed to prove the derivations correct.
"""

from __future__ import absolute_import

import csv
import math
import os
import shutil
import tempfile
import unittest

from .common import config_copy

from adaptive_qmix.behavior_analysis import (
    CADENCE_DECISION,
    CADENCE_FULL_1S,
    WINDOW_DEMAND_ACTIVE,
    WINDOW_FULL_EPISODE,
    contiguous_spells,
    derive_behavior_metrics,
    lane_state_cadence,
)
from adaptive_qmix.coordination import (
    DIRECTIONS,
    TopologyError,
    VirtualDetectorTracker,
    derive_central_directions,
)
from adaptive_qmix.coordination_analysis import derive_coordination_metrics
from adaptive_qmix.logging import SCHEMAS
from adaptive_qmix.raw_logs import EpisodeSelectionError, select_episode
from adaptive_qmix.traci_access import GetterDataSource, SubscriptionDataSource

from .test_traci_access import FakeTraci, FakeWorld


TIME_DEPENDENT_TABLES = (
    "signal_actions", "signal_phases", "lane_states",
    "vehicle_crossings", "reward_seconds", "learner_updates",
)


# A hand-computable single-intersection phase trace, one row per second.
#   t 1..10  H   ten seconds of H green, in progress from t = 0
#   t 11..13 Y   three seconds of yellow
#   t 14..20 V   seven seconds of V green
#   t 21..23 Y   three seconds of yellow
#   t 24..28 H   five seconds of H green
HAND_TRACE = (["H"] * 10) + (["Y"] * 3) + (["V"] * 7) + (["Y"] * 3) + (["H"] * 5)


def phase_rows(trace, intersection, episode_index=0):
    rows = []
    previous = None
    for index, phase in enumerate(trace):
        time_value = index + 1
        rows.append({
            "episode_index": episode_index,
            "time": float(time_value),
            "intersection": intersection,
            "actual_phase": phase,
            "logical_green_phase": phase if phase != "Y" else "H",
            "green_elapsed_s": 0,
            "yellow": phase == "Y",
            "green_start": phase in ("H", "V") and phase != previous,
            "green_end": previous in ("H", "V") and phase != previous,
            "H_red_elapsed_s": 0,
            "V_red_elapsed_s": 0,
        })
        previous = phase
    return rows


def write_table(directory, name, rows):
    path = os.path.join(directory, name + ".csv")
    fields = SCHEMAS[name]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


class EpisodeSafetyTests(unittest.TestCase):
    """M6: rows from different episodes must never be pooled."""

    def _two_episodes(self):
        tables = {"signal_phases": []}
        for episode in (0, 1):
            tables["signal_phases"].extend(
                phase_rows(HAND_TRACE, "J1", episode_index=episode)
            )
        return tables

    def test_two_episodes_with_identical_times_cannot_be_mixed(self):
        tables = self._two_episodes()
        times = [row["time"] for row in tables["signal_phases"]]
        self.assertEqual(times.count(1.0), 2, "both episodes contain t = 1")
        with self.assertRaises(EpisodeSelectionError) as caught:
            select_episode(tables)
        self.assertIn("2 episodes", str(caught.exception))

    def test_naming_an_episode_returns_only_that_episode(self):
        tables = self._two_episodes()
        chosen, filtered = select_episode(tables, episode_index=1)
        self.assertEqual(chosen, 1)
        self.assertEqual(len(filtered["signal_phases"]), len(HAND_TRACE))
        self.assertTrue(all(
            int(row["episode_index"]) == 1
            for row in filtered["signal_phases"]
        ))

    def test_a_single_episode_source_selects_automatically(self):
        tables = {"signal_phases": phase_rows(HAND_TRACE, "J1")}
        chosen, filtered = select_episode(tables)
        self.assertEqual(chosen, 0)
        self.assertEqual(len(filtered["signal_phases"]), len(HAND_TRACE))

    def test_an_absent_episode_is_rejected(self):
        tables = {"signal_phases": phase_rows(HAND_TRACE, "J1")}
        with self.assertRaises(EpisodeSelectionError):
            select_episode(tables, episode_index=7)

    def test_a_log_without_the_column_fails_closed(self):
        rows = phase_rows(HAND_TRACE, "J1")
        for row in rows:
            del row["episode_index"]
        with self.assertRaises(EpisodeSelectionError) as caught:
            select_episode({"signal_phases": rows})
        self.assertIn("schema 1.1", str(caught.exception))

    def test_every_time_dependent_table_persists_the_episode(self):
        for name in TIME_DEPENDENT_TABLES:
            self.assertEqual(
                SCHEMAS[name][0], "episode_index",
                "{} must carry episode_index".format(name),
            )


class SpellReconstructionTests(unittest.TestCase):
    """M7: green and service-deprivation spells on the hand-computable trace."""

    def setUp(self):
        self.seconds = [
            (float(index + 1), phase) for index, phase in enumerate(HAND_TRACE)
        ]
        self.end = float(len(HAND_TRACE))

    def _spells(self, movement, negate=False):
        if negate:
            return contiguous_spells(
                self.seconds, lambda phase: phase != movement, 0.0, self.end
            )
        return contiguous_spells(
            self.seconds, lambda phase: phase == movement, 0.0, self.end
        )

    def test_green_spells_are_exact(self):
        spells = self._spells("H")
        self.assertEqual(
            [(s["start_s"], s["end_s"], s["duration_s"]) for s in spells],
            [(0.0, 10.0, 10.0), (23.0, 28.0, 5.0)],
        )
        self.assertEqual(
            [(s["start_s"], s["end_s"], s["duration_s"])
             for s in self._spells("V")],
            [(13.0, 20.0, 7.0)],
        )

    def test_initial_green_at_time_zero_counts_as_a_service(self):
        spells = self._spells("H")
        self.assertEqual(len(spells), 2)
        self.assertEqual(spells[0]["start_s"], 0.0)
        self.assertTrue(spells[0]["at_window_start"])

    def test_yellow_counts_as_service_deprivation(self):
        """V is deprived through the H green AND both yellows."""
        spells = self._spells("V", negate=True)
        self.assertEqual(
            [(s["start_s"], s["end_s"], s["duration_s"]) for s in spells],
            [(0.0, 13.0, 13.0), (20.0, 28.0, 8.0)],
        )
        # 13 = 10 s of H green + 3 s of yellow. Excluding yellow would give 10.
        self.assertEqual(spells[0]["duration_s"], 13.0)

    def test_non_green_for_h_spans_yellow_and_the_opposing_green(self):
        spells = self._spells("H", negate=True)
        self.assertEqual(
            [(s["start_s"], s["end_s"], s["duration_s"]) for s in spells],
            [(10.0, 23.0, 13.0)],
        )

    def test_p95_and_max_deprivation_are_correct(self):
        """V deprivation durations are [13, 8]; p95 is linear-interpolated."""
        spells = self._spells("V", negate=True)
        durations = sorted(s["duration_s"] for s in spells)
        self.assertEqual(durations, [8.0, 13.0])
        expected_p95 = 8.0 + 0.95 * (13.0 - 8.0)
        self.assertAlmostEqual(expected_p95, 12.75)

    def test_a_gap_in_the_log_breaks_a_spell(self):
        seconds = [(1.0, "H"), (2.0, "H"), (9.0, "H")]
        spells = contiguous_spells(
            seconds, lambda phase: phase == "H", 0.0, 9.0
        )
        self.assertEqual([s["duration_s"] for s in spells], [2.0, 1.0])


class BehaviorDerivationTests(unittest.TestCase):
    """M7 end to end, over written synthetic logs."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = config_copy()
        self.lanes = self.config["observation"]["lanes"]

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write(self, cadence_seconds=1, trace=HAND_TRACE):
        rows = []
        for intersection in ("J1", "J2"):
            rows.extend(phase_rows(trace, intersection))
        write_table(self.directory, "signal_phases", rows)

        actions = []
        for index in range(len(trace) // 5):
            for intersection in ("J1", "J2"):
                actions.append({
                    "episode_index": 0,
                    "decision_time": float(index * 5),
                    "decision_index": index,
                    "intersection": intersection,
                    "action": "SWITCH" if index % 3 == 2 else "EXTEND",
                })
        write_table(self.directory, "signal_actions", actions)

        lane_rows = []
        for time_value in range(cadence_seconds, len(trace) + 1, cadence_seconds):
            for intersection in ("J1", "J2"):
                for movement, queue, count in (("H", 1, 2), ("V", 10, 0)):
                    for lane in self.lanes[intersection][
                        "{}_in".format(movement)
                    ]:
                        lane_rows.append({
                            "episode_index": 0,
                            "time": float(time_value),
                            "lane": lane,
                            "queue": queue,
                            "vehicle_count": count,
                            "occupancy": 0.0,
                            "mean_speed": 0.0,
                        })
        write_table(self.directory, "lane_states", lane_rows)

    def _movement_row(self, intersection, movement, window=WINDOW_FULL_EPISODE):
        path = os.path.join(
            self.directory, "behavior_metrics_by_intersection_movement.csv"
        )
        with open(path, "r") as handle:
            for row in csv.DictReader(handle):
                if (row["intersection"] == intersection
                        and row["movement"] == movement
                        and row["window"] == window):
                    return row
        raise AssertionError("no row for {} {}".format(intersection, movement))

    def test_emergent_cycle_is_the_h_to_h_start_interval(self):
        self._write()
        summary = derive_behavior_metrics(self.directory, self.config)
        # H green starts at 0 and 23, so exactly one emergent cycle of 23 s.
        stats = summary["by_intersection"][WINDOW_FULL_EPISODE]["J1"]
        self.assertEqual(stats["emergent_cycle_count"], 1)
        self.assertAlmostEqual(stats["emergent_cycle_mean_s"], 23.0)
        with open(os.path.join(
            self.directory, "emergent_cycle_distribution.csv"
        )) as handle:
            cycles = [
                row for row in csv.DictReader(handle)
                if row["window"] == WINDOW_FULL_EPISODE
                and row["intersection"] == "J1"
            ]
        self.assertEqual(len(cycles), 1)
        self.assertAlmostEqual(float(cycles[0]["emergent_cycle_s"]), 23.0)
        self.assertAlmostEqual(float(cycles[0]["h_start_s"]), 0.0)
        self.assertAlmostEqual(float(cycles[0]["next_h_start_s"]), 23.0)

    def test_queue_aggregation_uses_the_configured_movement_lanes(self):
        self._write()
        derive_behavior_metrics(self.directory, self.config)
        # Four H_in lanes at queue 1 sum to 4; four V_in lanes at 10 sum to 40.
        self.assertAlmostEqual(
            float(self._movement_row("J1", "H")["queue_mean"]), 4.0
        )
        self.assertAlmostEqual(
            float(self._movement_row("J1", "V")["queue_mean"]), 40.0
        )

    def test_full_one_second_logs_yield_official_queue_metrics(self):
        self._write(cadence_seconds=1)
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertEqual(
            summary["lane_state_sampling_cadence"], CADENCE_FULL_1S
        )
        self.assertTrue(summary["queue_metrics_are_official_1s"])
        row = self._movement_row("J1", "H")
        self.assertEqual(row["queue_metrics_are_official_1s"], "True")
        # H_in carries two vehicles per lane on every green second.
        self.assertAlmostEqual(float(row["green_demand_utilisation"]), 1.0)
        # V_in is empty, so its green seconds are unused demand.
        self.assertAlmostEqual(
            float(self._movement_row("J1", "V")["green_demand_utilisation"]), 0.0
        )

    def test_five_second_logs_cannot_masquerade_as_official_one_second(self):
        self._write(cadence_seconds=5)
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertEqual(
            summary["lane_state_sampling_cadence"], CADENCE_DECISION
        )
        self.assertFalse(summary["queue_metrics_are_official_1s"])
        row = self._movement_row("J1", "H")
        self.assertEqual(row["queue_sampling_cadence"], CADENCE_DECISION)
        self.assertEqual(row["queue_metrics_are_official_1s"], "False")
        self.assertTrue(
            math.isnan(float(row["green_demand_utilisation"])),
            "utilisation must be NaN when the source is not 1 s sampled",
        )
        self.assertEqual(
            row["green_demand_utilisation_is_official_1s"], "False"
        )

    def test_cadence_classifier(self):
        self.assertEqual(lane_state_cadence(
            [{"time": t} for t in (1, 2, 3, 4)], 5), CADENCE_FULL_1S)
        self.assertEqual(lane_state_cadence(
            [{"time": t} for t in (5, 10, 15)], 5), CADENCE_DECISION)

    def test_both_windows_are_reported(self):
        self._write()
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertEqual(summary["primary_window"], WINDOW_DEMAND_ACTIVE)
        for window in (WINDOW_DEMAND_ACTIVE, WINDOW_FULL_EPISODE):
            self.assertIn(window, summary["by_intersection"])

    def test_service_and_share_metrics(self):
        self._write()
        summary = derive_behavior_metrics(self.directory, self.config)
        stats = summary["by_intersection"][WINDOW_FULL_EPISODE]["J1"]
        self.assertEqual(stats["H_green_seconds"], 15)
        self.assertEqual(stats["V_green_seconds"], 7)
        self.assertEqual(stats["yellow_seconds"], 6)
        self.assertAlmostEqual(
            stats["H_green_share_among_green_time"], 15.0 / 22.0
        )
        self.assertAlmostEqual(stats["yellow_fraction_of_elapsed"], 6.0 / 28.0)
        self.assertEqual(
            int(self._movement_row("J1", "H")["green_service_count"]), 2
        )

    def test_multiple_episodes_require_an_explicit_index(self):
        self._write()
        path = os.path.join(self.directory, "signal_phases.csv")
        with open(path, "r") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["episode_index"] = 1
        with open(path, "a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SCHEMAS["signal_phases"])
            writer.writerows(rows)
        with self.assertRaises(EpisodeSelectionError):
            derive_behavior_metrics(self.directory, self.config)
        summary = derive_behavior_metrics(self.directory, self.config, 1)
        self.assertEqual(summary["episode_index"], 1)


class TopologyTests(unittest.TestCase):
    """M8: both central directions come from the observation topology."""

    def setUp(self):
        self.config = config_copy()

    def test_we_resolves_to_the_eastbound_central_lanes(self):
        spec = derive_central_directions(self.config)["WE"]
        self.assertEqual(spec["lanes"], ["E1_0", "E1_1"])
        self.assertEqual((spec["upstream"], spec["downstream"]), ("J1", "J2"))

    def test_ew_resolves_to_the_westbound_central_lanes(self):
        spec = derive_central_directions(self.config)["EW"]
        self.assertEqual(spec["lanes"], ["-E1_0", "-E1_1"])
        self.assertEqual((spec["upstream"], spec["downstream"]), ("J2", "J1"))

    def test_the_two_directions_are_disjoint(self):
        directions = derive_central_directions(self.config)
        self.assertFalse(
            set(directions["WE"]["lanes"]) & set(directions["EW"]["lanes"])
        )

    def test_an_inconsistent_topology_fails(self):
        config = config_copy()
        config["observation"]["lanes"]["J1"]["H_out"] = ["E9_0"]
        with self.assertRaises(TopologyError):
            derive_central_directions(config)

    def test_a_central_lane_of_the_wrong_length_fails(self):
        config = config_copy()
        config["coordination"]["central_lane_length_m"] = 111.0
        with self.assertRaises(TopologyError):
            derive_central_directions(config)


class BidirectionalDetectorTests(unittest.TestCase):
    """M8: the two directions observe disjoint traffic and stay labelled."""

    def _world(self):
        config = config_copy()
        lane_ids = sorted(config["observation"]["expected_lane_lengths_m"])
        world = FakeWorld(lane_ids)
        # One vehicle past the detector in each direction.
        world.add_vehicle("we_vehicle", 9.0, 0.0, "E1_0", 240.0)
        world.add_vehicle("ew_vehicle", 8.0, 0.0, "-E1_1", 235.0)
        return config, world

    def _trackers(self, source, config):
        directions = derive_central_directions(config)
        return dict(
            (name, VirtualDetectorTracker(
                source, directions[name]["lanes"], 229.2,
                direction=name,
                upstream=directions[name]["upstream"],
                downstream=directions[name]["downstream"],
            ))
            for name in DIRECTIONS
        )

    def test_we_and_ew_events_are_separated_and_labelled(self):
        config, world = self._world()
        traci_module = FakeTraci(world)
        source = GetterDataSource(traci_module)
        source.begin_episode([])
        source.refresh()
        trackers = self._trackers(source, config)
        we_events = trackers["WE"].sample(1.0, "H", "H")
        ew_events = trackers["EW"].sample(1.0, "V", "V")

        self.assertTrue(we_events and ew_events)
        self.assertTrue(all(e["direction"] == "WE" for e in we_events))
        self.assertTrue(all(e["direction"] == "EW" for e in ew_events))
        self.assertEqual(
            set(e["vehicle_id"] for e in we_events), {"we_vehicle"}
        )
        self.assertEqual(
            set(e["vehicle_id"] for e in ew_events), {"ew_vehicle"}
        )

    def test_upstream_and_downstream_are_direction_specific(self):
        config, world = self._world()
        source = GetterDataSource(FakeTraci(world))
        source.begin_episode([])
        source.refresh()
        trackers = self._trackers(source, config)
        we = [e for e in trackers["WE"].sample(1.0, "H", "H")
              if e["event"] == "GAD50"][0]
        ew = [e for e in trackers["EW"].sample(1.0, "H", "H")
              if e["event"] == "GAD50"][0]
        self.assertEqual((we["upstream_intersection"], we["downstream_intersection"]),
                         ("J1", "J2"))
        self.assertEqual((ew["upstream_intersection"], ew["downstream_intersection"]),
                         ("J2", "J1"))
        # GAD50 is a downstream event in both directions.
        self.assertEqual(we["intersection"], "J2")
        self.assertEqual(ew["intersection"], "J1")

    def test_both_transports_still_agree_on_bidirectional_events(self):
        """No new subscription-versus-getter discrepancy is introduced."""
        config, world = self._world()
        traci_module = FakeTraci(world)
        results = []
        for factory in (GetterDataSource, SubscriptionDataSource):
            source = factory(traci_module)
            source.begin_episode([])
            source.note_departures(traci_module.vehicle.getIDList())
            source.refresh()
            trackers = self._trackers(source, config)
            results.append([
                trackers[name].sample(1.0, "H", "V") for name in DIRECTIONS
            ])
        self.assertEqual(results[0], results[1])


class BidirectionalLagTests(unittest.TestCase):
    """M8: positive lag means downstream follows upstream, in both directions."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = config_copy()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_sign_convention_holds_for_both_directions(self):
        # J2 repeats J1's pattern three seconds later, so J1 leads.
        period, shift, cycles = 20, 3, 12
        base = ([1] * 10 + [0] * 10) * cycles
        j1 = base[:period * cycles]
        j2 = ([0] * shift + base)[:period * cycles]

        rows = []
        for series, intersection in ((j1, "J1"), (j2, "J2")):
            trace = ["H" if value else "V" for value in series]
            rows.extend(phase_rows(trace, intersection))
        write_table(self.directory, "signal_phases", rows)
        write_table(self.directory, "vehicle_crossings", [])

        summary = derive_coordination_metrics(self.directory, self.config)
        self.assertIn("downstream signal follows the upstream signal",
                      summary["sign_convention"])
        # WE is oriented J1 -> J2: the downstream signal follows, so +3.
        self.assertEqual(
            summary["directions"]["WE"]["dominant_cross_correlation_lag_s"],
            shift,
        )
        # EW is oriented J2 -> J1: its downstream signal J1 leads, so -3.
        self.assertEqual(
            summary["directions"]["EW"]["dominant_cross_correlation_lag_s"],
            -shift,
        )

    def test_direction_is_stamped_on_every_derived_row(self):
        rows = []
        for intersection in ("J1", "J2"):
            rows.extend(phase_rows(HAND_TRACE, intersection))
        write_table(self.directory, "signal_phases", rows)
        write_table(self.directory, "vehicle_crossings", [])
        derive_coordination_metrics(self.directory, self.config)
        for name in ("phase_lag_green_start_distribution",
                     "phase_cross_correlation_distribution"):
            path = os.path.join(self.directory, name + ".csv")
            with open(path, "r") as handle:
                found = set(
                    row["direction"] for row in csv.DictReader(handle)
                )
            self.assertEqual(found, {"WE", "EW"}, name)

    def test_multiple_episodes_require_an_explicit_index(self):
        rows = []
        for episode in (0, 1):
            for intersection in ("J1", "J2"):
                rows.extend(phase_rows(HAND_TRACE, intersection, episode))
        write_table(self.directory, "signal_phases", rows)
        write_table(self.directory, "vehicle_crossings", [])
        with self.assertRaises(EpisodeSelectionError):
            derive_coordination_metrics(self.directory, self.config)
        summary = derive_coordination_metrics(self.directory, self.config, 1)
        self.assertEqual(summary["episode_index"], 1)

    def test_projected_aog_remains_labelled_a_proxy(self):
        rows = []
        for intersection in ("J1", "J2"):
            rows.extend(phase_rows(HAND_TRACE, intersection))
        write_table(self.directory, "signal_phases", rows)
        write_table(self.directory, "vehicle_crossings", [])
        summary = derive_coordination_metrics(self.directory, self.config)
        for name in DIRECTIONS:
            self.assertTrue(
                summary["directions"][name]["AOG_SL_projected_is_proxy"]
            )


if __name__ == "__main__":
    unittest.main()
