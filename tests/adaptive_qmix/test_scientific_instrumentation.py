"""Batch S1: episode-safe logging, behaviour/starvation, bidirectional mechanism.

Everything here runs on synthetic logs, so each assertion is hand-computable
and no SUMO run is needed to prove the derivations correct.
"""

from __future__ import absolute_import

import csv
import json
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
from adaptive_qmix.completeness import CompletenessError
from adaptive_qmix.coordination_analysis import derive_coordination_metrics
from adaptive_qmix.logging import SCHEMAS
from adaptive_qmix.raw_logs import (
    EpisodeSelectionError,
    available_episodes,
    derived_output_directory,
    read_raw_tables,
    select_episode,
)
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
        self.assertTrue(summary["queue_metrics_sampling_is_full_1s"])
        row = self._movement_row("J1", "H")
        self.assertEqual(row["queue_metrics_sampling_is_full_1s"], "True")
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
        self.assertFalse(summary["queue_metrics_sampling_is_full_1s"])
        row = self._movement_row("J1", "H")
        self.assertEqual(row["queue_sampling_cadence"], CADENCE_DECISION)
        self.assertEqual(row["queue_metrics_sampling_is_full_1s"], "False")
        self.assertTrue(
            math.isnan(float(row["green_demand_utilisation"])),
            "utilisation must be NaN when the source is not 1 s sampled",
        )
        self.assertEqual(
            row["green_demand_utilisation_sampling_is_full_1s"], "False"
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


# A second hand-computable trace, deliberately unlike HAND_TRACE, so an
# episode's derived numbers identify which episode produced them.
#   t 1..5   H   five seconds of H green, in progress from t = 0
#   t 6..8   Y
#   t 9..12  V
#   t 13..15 Y
#   t 16..20 H   H green starts again at 15, so the emergent cycle is 15 s
SECOND_TRACE = (["H"] * 5) + (["Y"] * 3) + (["V"] * 4) + (["Y"] * 3) + (["H"] * 5)

BEHAVIOR_PRODUCTS = (
    "behavior_summary.json",
    "behavior_metrics_by_intersection_movement.csv",
    "green_spell_distribution.csv",
    "non_green_spell_distribution.csv",
    "emergent_cycle_distribution.csv",
)

COORDINATION_PRODUCTS = (
    "coordination_summary.json",
    "phase_lag_green_start_distribution.csv",
    "phase_cross_correlation_distribution.csv",
    "vehicle_coordination_metrics.csv",
)


class DerivedOutputIsolationTests(unittest.TestCase):
    """Deriving one episode must never overwrite another episode's products.

    A training run appends every episode to the same raw CSVs, so deriving
    episode 0 and then episode 1 in that run directory used to write both
    results to the same filenames: the second derivation silently replaced the
    first, and the surviving files carried no evidence of which episode they
    described. Products are therefore separated per episode whenever the
    source is ambiguous, while a genuinely single-episode frozen-policy
    evaluation keeps writing beside its raw logs.
    """

    EPISODE_TRACES = {0: HAND_TRACE, 1: SECOND_TRACE}

    # H green starts at 0 and 23 in HAND_TRACE, at 0 and 15 in SECOND_TRACE.
    EXPECTED_CYCLE = {0: 23.0, 1: 15.0}

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = config_copy()
        self.lanes = self.config["observation"]["lanes"]

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write_source(self, episodes):
        """Write one raw source holding the given episodes, appended together."""
        phases, actions, lane_rows = [], [], []
        for episode in episodes:
            trace = self.EPISODE_TRACES[episode]
            for intersection in ("J1", "J2"):
                phases.extend(phase_rows(trace, intersection, episode))
            for index in range(len(trace) // 5):
                for intersection in ("J1", "J2"):
                    actions.append({
                        "episode_index": episode,
                        "decision_time": float(index * 5),
                        "decision_index": index,
                        "intersection": intersection,
                        "action": "EXTEND",
                    })
            for time_value in range(1, len(trace) + 1):
                for intersection in ("J1", "J2"):
                    for movement, queue in (("H", 1), ("V", 10)):
                        for lane in self.lanes[intersection][
                            "{}_in".format(movement)
                        ]:
                            lane_rows.append({
                                "episode_index": episode,
                                "time": float(time_value),
                                "lane": lane,
                                "queue": queue,
                                "vehicle_count": 0,
                                "occupancy": 0.0,
                                "mean_speed": 0.0,
                            })
        write_table(self.directory, "signal_phases", phases)
        write_table(self.directory, "signal_actions", actions)
        write_table(self.directory, "lane_states", lane_rows)
        write_table(self.directory, "vehicle_crossings", [])

    def _episode_directory(self, episode):
        return os.path.join(
            self.directory, "derived", "episode_{:05d}".format(episode)
        )

    def _read_json(self, directory, name):
        with open(os.path.join(directory, name), "r") as handle:
            return json.load(handle)

    def _assert_products_present(self, directory, names):
        for name in names:
            self.assertTrue(
                os.path.isfile(os.path.join(directory, name)),
                "{} missing from {}".format(name, directory),
            )

    def _assert_products_absent(self, directory, names):
        for name in names:
            self.assertFalse(
                os.path.isfile(os.path.join(directory, name)),
                "{} unexpectedly written to {}".format(name, directory),
            )

    def test_two_behavior_derivations_do_not_overwrite_each_other(self):
        self._write_source((0, 1))
        first = derive_behavior_metrics(self.directory, self.config, 0)
        second = derive_behavior_metrics(self.directory, self.config, 1)

        self.assertEqual(first["output_directory"], self._episode_directory(0))
        self.assertEqual(second["output_directory"], self._episode_directory(1))
        self.assertNotEqual(first["output_directory"], second["output_directory"])

        for episode in (0, 1):
            directory = self._episode_directory(episode)
            self._assert_products_present(directory, BEHAVIOR_PRODUCTS)
            written = self._read_json(directory, "behavior_summary.json")
            self.assertEqual(written["episode_index"], episode)
            self.assertEqual(written["episodes_in_source"], [0, 1])
            # The surviving numbers are the ones that episode produced, so the
            # second derivation did not silently replace the first.
            self.assertAlmostEqual(
                written["by_intersection"][WINDOW_FULL_EPISODE]["J1"][
                    "emergent_cycle_mean_s"
                ],
                self.EXPECTED_CYCLE[episode],
            )
        # Nothing was written beside the raw logs, where it could be mistaken
        # for a whole-run result.
        self._assert_products_absent(self.directory, BEHAVIOR_PRODUCTS)

    def test_two_coordination_derivations_do_not_overwrite_each_other(self):
        self._write_source((0, 1))
        first = derive_coordination_metrics(self.directory, self.config, 0)
        second = derive_coordination_metrics(self.directory, self.config, 1)

        self.assertEqual(first["output_directory"], self._episode_directory(0))
        self.assertEqual(second["output_directory"], self._episode_directory(1))

        for episode in (0, 1):
            directory = self._episode_directory(episode)
            self._assert_products_present(directory, COORDINATION_PRODUCTS)
            written = self._read_json(directory, "coordination_summary.json")
            self.assertEqual(written["episode_index"], episode)
            self.assertEqual(written["episodes_in_source"], [0, 1])
            with open(os.path.join(
                directory, "phase_lag_green_start_distribution.csv"
            )) as handle:
                stamped = set(
                    int(row["episode_index"]) for row in csv.DictReader(handle)
                )
            self.assertEqual(stamped, {episode})
        self._assert_products_absent(self.directory, COORDINATION_PRODUCTS)

    def test_the_two_derivations_share_a_run_directory_without_colliding(self):
        """Behaviour and coordination for both episodes coexist in one run."""
        self._write_source((0, 1))
        for episode in (0, 1):
            derive_behavior_metrics(self.directory, self.config, episode)
            derive_coordination_metrics(self.directory, self.config, episode)
        for episode in (0, 1):
            directory = self._episode_directory(episode)
            self._assert_products_present(
                directory, BEHAVIOR_PRODUCTS + COORDINATION_PRODUCTS
            )
            self.assertEqual(
                self._read_json(
                    directory, "behavior_summary.json"
                )["episode_index"],
                episode,
            )
            self.assertEqual(
                self._read_json(
                    directory, "coordination_summary.json"
                )["episode_index"],
                episode,
            )

    def test_a_single_episode_source_still_writes_beside_its_raw_logs(self):
        """Frozen-policy evaluation keeps the existing layout."""
        self._write_source((0,))
        behavior = derive_behavior_metrics(self.directory, self.config)
        coordination = derive_coordination_metrics(self.directory, self.config)
        self.assertEqual(behavior["output_directory"], self.directory)
        self.assertEqual(coordination["output_directory"], self.directory)
        self.assertEqual(behavior["episodes_in_source"], [0])
        self._assert_products_present(
            self.directory, BEHAVIOR_PRODUCTS + COORDINATION_PRODUCTS
        )
        self.assertFalse(
            os.path.isdir(os.path.join(self.directory, "derived")),
            "an unambiguous source needs no per-episode subdirectory",
        )

    def test_an_explicit_output_directory_overrides_both_layouts(self):
        self._write_source((0, 1))
        target = os.path.join(self.directory, "elsewhere")
        behavior = derive_behavior_metrics(
            self.directory, self.config, 1, output_directory=target
        )
        coordination = derive_coordination_metrics(
            self.directory, self.config, 1, output_directory=target
        )
        self.assertEqual(behavior["output_directory"], os.path.abspath(target))
        self.assertEqual(coordination["output_directory"], os.path.abspath(target))
        self._assert_products_present(
            target, BEHAVIOR_PRODUCTS + COORDINATION_PRODUCTS
        )
        self._assert_products_absent(self.directory, BEHAVIOR_PRODUCTS)
        self.assertFalse(os.path.isdir(self._episode_directory(1)))

    def test_available_episodes_reports_every_episode_in_the_source(self):
        self._write_source((0, 1))
        tables = read_raw_tables(
            self.directory, ("signal_phases", "signal_actions", "lane_states")
        )
        self.assertEqual(available_episodes(tables), [0, 1])

    def test_the_directory_rule_does_not_depend_on_the_files_existing(self):
        """The layout is decided by episode count alone, ambiguity being the risk."""
        single = derived_output_directory(self.directory, 1, 0)
        self.assertEqual(single, self.directory)
        multiple = derived_output_directory(self.directory, 2, 7)
        self.assertEqual(multiple, self._episode_directory(7))
        self.assertTrue(os.path.isdir(multiple))


class EpisodeCompletenessTests(unittest.TestCase):
    """A cadence label must never stand in for a complete window.

    The failure this guards against is concrete: a smoke episode stopped by
    the interaction budget at 1235 s was logged at a full 1 s cadence, so the
    summary said primary_window = demand_active and full_1s together, which
    reads as a complete 0-3600 s demand-active result. It was a correct
    1235 s prefix. These tests keep the two facts apart.

    The demand horizon is shortened to 20 s here so the fixtures stay
    hand-computable; the code reads it from the config either way.
    """

    HORIZON = 20.0

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = config_copy()
        self.config["demand"]["generation_end_s"] = self.HORIZON
        self.lanes = self.config["observation"]["lanes"]

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write_episode(self, status, seconds=len(HAND_TRACE),
                       episode_index=0, write_summary=True):
        """One episode whose logs stop after `seconds` seconds."""
        trace = HAND_TRACE[:seconds]
        phases, actions, lane_rows = [], [], []
        for intersection in ("J1", "J2"):
            phases.extend(phase_rows(trace, intersection, episode_index))
        for index in range(len(trace) // 5):
            for intersection in ("J1", "J2"):
                actions.append({
                    "episode_index": episode_index,
                    "decision_time": float(index * 5),
                    "decision_index": index,
                    "intersection": intersection,
                    "action": "EXTEND",
                })
        for time_value in range(1, len(trace) + 1):
            for intersection in ("J1", "J2"):
                for movement, queue, count in (("H", 1, 2), ("V", 10, 0)):
                    for lane in self.lanes[intersection][
                        "{}_in".format(movement)
                    ]:
                        lane_rows.append({
                            "episode_index": episode_index,
                            "time": float(time_value),
                            "lane": lane,
                            "queue": queue,
                            "vehicle_count": count,
                            "occupancy": 0.0,
                            "mean_speed": 0.0,
                        })
        write_table(self.directory, "signal_phases", phases)
        write_table(self.directory, "signal_actions", actions)
        write_table(self.directory, "lane_states", lane_rows)
        write_table(self.directory, "vehicle_crossings", [])
        if write_summary:
            write_table(self.directory, "episode_summary", [{
                "episode_index": episode_index,
                "status": status,
                "start_time": 0.0,
                "end_time": float(len(trace)),
                "elapsed_s": float(len(trace)),
                "scheduled": 2800,
                "completed": 2800 if status == "CLEARED" else 1000,
                "budget_truncated": status == "BUDGET_TRUNCATED",
                "timeout_truncated": False,
                "clearance_failure": status == "CLEARANCE_FAILURE",
                "transport_healed_subscriptions": 0,
            }])

    def _both_summaries(self):
        return (
            derive_behavior_metrics(self.directory, self.config),
            derive_coordination_metrics(self.directory, self.config),
        )

    def test_a_cleared_episode_covering_the_horizon_is_permitted(self):
        self._write_episode("CLEARED")
        for summary in self._both_summaries():
            self.assertEqual(summary["episode_status"], "CLEARED")
            self.assertTrue(summary["episode_is_cleared"])
            self.assertTrue(summary["demand_active_window_complete"])
            self.assertTrue(summary["full_clearance_complete"])
            self.assertTrue(summary["scientific_analysis_permitted"])
            self.assertEqual(summary["analysis_class"], "scientific")
            self.assertNotIn("DIAGNOSTIC ONLY", summary["completeness_note"])

    def test_a_truncated_episode_is_diagnostic_not_scientific(self):
        # Logs stop at 12 s, well short of the 20 s demand horizon.
        self._write_episode("BUDGET_TRUNCATED", seconds=12)
        for summary in self._both_summaries():
            self.assertEqual(summary["episode_status"], "BUDGET_TRUNCATED")
            self.assertFalse(summary["episode_is_cleared"])
            self.assertFalse(summary["demand_active_window_complete"])
            self.assertFalse(summary["full_clearance_complete"])
            self.assertFalse(summary["scientific_analysis_permitted"])
            self.assertEqual(summary["analysis_class"], "diagnostic_partial")
            self.assertIn("DIAGNOSTIC ONLY", summary["completeness_note"])
            self.assertIn("12 of the 20 seconds", summary["completeness_note"])

    def test_full_1s_sampling_does_not_imply_a_complete_window(self):
        """The exact pairing that caused this hardening."""
        self._write_episode("BUDGET_TRUNCATED", seconds=12)
        summary = derive_behavior_metrics(self.directory, self.config)
        # The cadence claim stays true: every logged second is 1 s resolution.
        self.assertEqual(summary["lane_state_sampling_cadence"], CADENCE_FULL_1S)
        self.assertTrue(summary["queue_metrics_sampling_is_full_1s"])
        # The officialness claim does not.
        self.assertFalse(summary["queue_metrics_are_official"])
        self.assertEqual(summary["primary_window"], WINDOW_DEMAND_ACTIVE)
        self.assertFalse(summary["primary_window_complete"])
        # The window under that name really is [0, 12], not [0, 20]: the
        # bounds are stated so the label cannot stand in for the horizon.
        self.assertEqual(
            summary["window_bounds_s"][WINDOW_DEMAND_ACTIVE], [0.0, 12.0]
        )
        self.assertEqual(
            summary["demand_active_window_required_end_s"], self.HORIZON
        )

    def test_truncation_labels_the_values_without_changing_them(self):
        """A partial episode still reports correct numbers for its seconds."""
        self._write_episode("BUDGET_TRUNCATED", seconds=12)
        truncated = derive_behavior_metrics(self.directory, self.config)
        path = os.path.join(
            self.directory, "behavior_metrics_by_intersection_movement.csv"
        )
        with open(path, "r") as handle:
            row = [
                item for item in csv.DictReader(handle)
                if item["intersection"] == "J1" and item["movement"] == "H"
                and item["window"] == WINDOW_FULL_EPISODE
            ][0]
        # H_in carries two vehicles per lane on every green second, so
        # utilisation is still 1.0 and emphatically not NaN: completeness
        # labels the result, it does not blank or reweight it.
        self.assertAlmostEqual(float(row["green_demand_utilisation"]), 1.0)
        self.assertEqual(row["queue_metrics_sampling_is_full_1s"], "True")
        self.assertEqual(row["queue_metrics_are_official"], "False")
        self.assertAlmostEqual(float(row["queue_mean"]), 4.0)
        self.assertFalse(truncated["scientific_analysis_permitted"])

    def test_a_clearance_failure_can_cover_the_window_yet_stay_impermitted(self):
        """The flags are separate facts, not synonyms for one another."""
        self._write_episode("CLEARANCE_FAILURE")
        for summary in self._both_summaries():
            # Every demand-active second is present, so that flag is true ...
            self.assertTrue(summary["demand_active_window_complete"])
            # ... but the episode never cleared, so inference is refused.
            self.assertFalse(summary["episode_is_cleared"])
            self.assertFalse(summary["full_clearance_complete"])
            self.assertFalse(summary["scientific_analysis_permitted"])

    def test_a_cleared_status_cannot_rescue_a_short_log(self):
        """Coverage is checked against the rows, not taken on the status."""
        self._write_episode("CLEARED", seconds=12)
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertTrue(summary["episode_is_cleared"])
        self.assertFalse(summary["demand_active_window_complete"])
        self.assertFalse(summary["scientific_analysis_permitted"])

    def test_a_missing_episode_summary_fails_closed(self):
        self._write_episode("CLEARED", write_summary=False)
        for summary in self._both_summaries():
            self.assertEqual(summary["episode_status"], "UNKNOWN")
            self.assertFalse(summary["scientific_analysis_permitted"])
            self.assertIn("episode_summary.csv",
                          summary["episode_status_reason"])

    def test_a_summary_without_the_selected_episode_fails_closed(self):
        self._write_episode("CLEARED", episode_index=0)
        write_table(self.directory, "episode_summary", [{
            "episode_index": 5, "status": "CLEARED",
        }])
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertEqual(summary["episode_status"], "UNKNOWN")
        self.assertFalse(summary["scientific_analysis_permitted"])

    def test_duplicate_summary_rows_for_one_episode_are_refused(self):
        self._write_episode("CLEARED")
        write_table(self.directory, "episode_summary", [
            {"episode_index": 0, "status": "CLEARED"},
            {"episode_index": 0, "status": "BUDGET_TRUNCATED"},
        ])
        with self.assertRaises(CompletenessError):
            derive_behavior_metrics(self.directory, self.config)

    def test_a_log_gap_inside_the_window_is_not_complete_coverage(self):
        """Reaching the horizon is not the same as covering it."""
        self._write_episode("CLEARED")
        path = os.path.join(self.directory, "signal_phases.csv")
        with open(path, "r") as handle:
            rows = list(csv.DictReader(handle))
        kept = [row for row in rows if float(row["time"]) != 7.0]
        with open(path, "w", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=SCHEMAS["signal_phases"],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(kept)
        summary = derive_behavior_metrics(self.directory, self.config)
        self.assertGreater(summary["observed_log_end_s"], self.HORIZON)
        self.assertFalse(summary["demand_active_window_complete"])
        self.assertEqual(summary["demand_active_seconds_logged"], 19)
        self.assertFalse(summary["scientific_analysis_permitted"])

    def test_completeness_travels_into_the_per_episode_directories(self):
        """Multi-episode sources keep each episode's verdict with its files."""
        for episode, status, seconds in ((0, "CLEARED", len(HAND_TRACE)),
                                         (1, "BUDGET_TRUNCATED", 12)):
            self._write_episode(status, seconds, episode_index=episode)
            # _write_episode rewrites the tables, so accumulate by appending.
            for name in ("signal_phases", "signal_actions", "lane_states",
                         "episode_summary", "vehicle_crossings"):
                path = os.path.join(self.directory, name + ".csv")
                store = os.path.join(self.directory, name + ".accum")
                with open(path, "r") as handle:
                    rows = list(csv.DictReader(handle))
                previous = []
                if os.path.isfile(store):
                    with open(store, "r") as handle:
                        previous = list(csv.DictReader(handle))
                with open(store, "w", newline="") as handle:
                    writer = csv.DictWriter(
                        handle, fieldnames=SCHEMAS[name], extrasaction="ignore"
                    )
                    writer.writeheader()
                    writer.writerows(previous + rows)
        for name in ("signal_phases", "signal_actions", "lane_states",
                     "episode_summary", "vehicle_crossings"):
            shutil.copyfile(
                os.path.join(self.directory, name + ".accum"),
                os.path.join(self.directory, name + ".csv"),
            )
        first = derive_behavior_metrics(self.directory, self.config, 0)
        second = derive_behavior_metrics(self.directory, self.config, 1)
        self.assertTrue(first["scientific_analysis_permitted"])
        self.assertFalse(second["scientific_analysis_permitted"])
        self.assertNotEqual(first["output_directory"],
                            second["output_directory"])
        for episode, permitted in ((0, True), (1, False)):
            path = os.path.join(
                self.directory, "derived",
                "episode_{:05d}".format(episode), "behavior_summary.json",
            )
            with open(path, "r") as handle:
                written = json.load(handle)
            self.assertEqual(written["scientific_analysis_permitted"], permitted)


class PhaseCorrelationIndependenceTests(unittest.TestCase):
    """M8 interpretation: two signals give one phase relationship, not two."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = config_copy()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write_offset_corridor(self, shift=3, period=20, cycles=12):
        base = ([1] * 10 + [0] * 10) * cycles
        j1 = base[:period * cycles]
        j2 = ([0] * shift + base)[:period * cycles]
        rows = []
        for series, intersection in ((j1, "J1"), (j2, "J2")):
            trace = ["H" if value else "V" for value in series]
            rows.extend(phase_rows(trace, intersection))
        write_table(self.directory, "signal_phases", rows)
        write_table(self.directory, "vehicle_crossings", [])

    def test_the_summary_states_the_reciprocity(self):
        self._write_offset_corridor()
        summary = derive_coordination_metrics(self.directory, self.config)
        self.assertEqual(
            summary["phase_correlation_reciprocity"], "C_WE(lag) = C_EW(-lag)"
        )
        self.assertEqual(summary["independent_phase_relationship_count"], 1)
        note = summary["phase_correlation_independence_note"]
        self.assertIn("must not be treated as two statistically", note)
        self.assertIn("C_WE(lag) = C_EW(-lag)", note)

    def test_the_reciprocity_actually_holds_in_the_written_distribution(self):
        """The note is checked against the numbers, not merely asserted."""
        self._write_offset_corridor()
        derive_coordination_metrics(self.directory, self.config)
        path = os.path.join(
            self.directory, "phase_cross_correlation_distribution.csv"
        )
        with open(path, "r") as handle:
            rows = list(csv.DictReader(handle))
        by_direction = {"WE": {}, "EW": {}}
        for row in rows:
            by_direction[row["direction"]][int(row["lag_s"])] = float(
                row["correlation"]
            )
        self.assertTrue(by_direction["WE"] and by_direction["EW"])
        compared = 0
        for lag, value in by_direction["WE"].items():
            mirrored = by_direction["EW"][-lag]
            if math.isnan(value) and math.isnan(mirrored):
                continue
            # Equal as algebra; the two corrcoef calls accumulate the swapped
            # arguments in a different order, so they agree to rounding.
            self.assertAlmostEqual(value, mirrored, places=12)
            compared += 1
        self.assertGreater(compared, 20)

    def test_the_note_separates_mirrored_from_direction_specific_metrics(self):
        self._write_offset_corridor()
        summary = derive_coordination_metrics(self.directory, self.config)
        self.assertIn(
            "dominant_cross_correlation_lag_s", summary["mirrored_phase_metrics"]
        )
        vehicle = summary["direction_specific_vehicle_metrics"]
        for name in ("GAD50_percent", "AOG_SL_projected_proxy_percent",
                     "downstream_stop_rate_percent",
                     "mean_detector_to_stop_line_s"):
            self.assertIn(name, vehicle)
            # Each named metric is genuinely reported per direction.
            for direction in DIRECTIONS:
                self.assertIn(name, summary["directions"][direction])
        self.assertFalse(
            set(vehicle) & set(summary["mirrored_phase_metrics"]),
            "a metric cannot be both mirrored and direction-specific",
        )


if __name__ == "__main__":
    unittest.main()
