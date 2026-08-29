"""Compute-only pre-scientific feasibility accounting."""

from __future__ import absolute_import

import json
import os
import sys
import time


class FeasibilityMeter(object):
    def __init__(self, method, transition_target=20000):
        self.method = str(method)
        self.transition_target = int(transition_target)
        self.started_at = None
        self.finished_at = None
        self.transitions = 0
        self.peak_rss_bytes = None
        self.peak_rss_source = "not_sampled"
        self.replay_bytes = 0
        self.log_bytes = 0

    def start(self):
        self.started_at = time.time()

    def record_transition(self, replay_bytes, run_directory):
        self.transitions += 1
        self.replay_bytes = max(self.replay_bytes, int(replay_bytes))
        self.log_bytes = max(self.log_bytes, directory_size(run_directory))
        observed, source = resident_set_size_bytes()
        self.peak_rss_source = source
        if observed is not None:
            self.peak_rss_bytes = (
                observed if self.peak_rss_bytes is None
                else max(self.peak_rss_bytes, observed)
            )

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
            "peak_rss_source": self.peak_rss_source,
            "peak_rss_available": self.peak_rss_bytes is not None,
            "replay_allocated_bytes": self.replay_bytes,
            "observed_log_bytes": self.log_bytes,
            "projected_360000_log_bytes": int(
                self.log_bytes * 360000.0 / float(max(self.transitions, 1))
            ),
            "performance_metrics_permitted": False,
        }


def _windows_peak_working_set_bytes():
    """Peak working set via PSAPI, so Windows needs no third-party package."""
    import ctypes
    from ctypes import wintypes

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), counters.cb
    )
    if not ok:
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.PeakWorkingSetSize)


def resident_set_size_bytes():
    """Return (bytes, source), or (None, reason) when genuinely unavailable.

    A missing measurement must never be reported as zero: the 20k gate did
    exactly that and the resulting peak_rss_bytes=0 was indistinguishable from
    a real reading. Three paths are tried so the common stacks are covered
    without adding a dependency: psutil where installed, PSAPI on Windows, and
    getrusage elsewhere. Only if all three fail is the value reported absent.
    """
    try:
        import psutil
        return int(psutil.Process(os.getpid()).memory_info().rss), "psutil.rss"
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            return (
                _windows_peak_working_set_bytes(),
                "windows_psapi.PeakWorkingSetSize",
            )
        except Exception:
            pass

    try:
        import resource
        maxrss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # ru_maxrss is kilobytes on Linux and bytes on macOS.
        scale = 1 if sys.platform == "darwin" else 1024
        return maxrss * scale, "resource.ru_maxrss"
    except Exception:
        pass

    return None, "unavailable"


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

