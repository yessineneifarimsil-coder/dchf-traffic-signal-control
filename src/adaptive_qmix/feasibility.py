"""Compute-only pre-scientific feasibility accounting."""

from __future__ import absolute_import

import json
import os
import time


class FeasibilityMeter(object):
    def __init__(self, method, transition_target=20000):
        self.method = str(method)
        self.transition_target = int(transition_target)
        self.started_at = None
        self.finished_at = None
        self.transitions = 0
        self.peak_rss_bytes = 0
        self.replay_bytes = 0
        self.log_bytes = 0

    def start(self):
        self.started_at = time.time()

    def record_transition(self, replay_bytes, run_directory):
        self.transitions += 1
        self.replay_bytes = max(self.replay_bytes, int(replay_bytes))
        self.log_bytes = max(self.log_bytes, directory_size(run_directory))
        self.peak_rss_bytes = max(self.peak_rss_bytes, resident_set_size_bytes())

    def finish(self):
        self.finished_at = time.time()
        elapsed = max(self.finished_at - self.started_at, 1e-9)
        projected = elapsed * 360000.0 / float(max(self.transitions, 1))
        return {
            "gate": "compute_only_non_inferential",
            "method": self.method,
            "target_transitions": self.transition_target,
            "observed_transitions": self.transitions,
            "elapsed_wall_seconds": elapsed,
            "transitions_per_second": float(self.transitions) / elapsed,
            "projected_360000_wall_seconds": projected,
            "peak_rss_bytes": self.peak_rss_bytes,
            "replay_allocated_bytes": self.replay_bytes,
            "observed_log_bytes": self.log_bytes,
            "projected_360000_log_bytes": int(
                self.log_bytes * 360000.0 / float(max(self.transitions, 1))
            ),
            "performance_metrics_permitted": False,
        }


def resident_set_size_bytes():
    try:
        import psutil
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        return 0


def directory_size(path):
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _directories, files in os.walk(path):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                pass
    return total


def write_feasibility_report(path, report):
    with open(path, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)

