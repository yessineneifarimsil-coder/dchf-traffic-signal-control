"""Robust start of the TraCI connection for the resumption of campaign B (incident of 2026-11-25).

Why this file exists, and why it is separate from the executor
---------------------------------------------------------------
The frozen environment (adaptive_qmix/environment.py, AdaptiveTrafficEnvironment.reset) calls
``self.traci.start(command)`` and only then sets ``connection_open = True``. In traci 1.25 (identical in 1.28):

(a) ``traci.start`` without a port takes ``sumolib.miscutils.getFreeSocketPort()``: bind to port 0, read the port the
    system chose (on Windows, in the dynamic range 49152-65535), CLOSE the socket, then launch SUMO with
    ``--remote-port``. Between the close and SUMO's own bind, the port is free for anyone; with 4 workers it can be
    taken ("Address already in use", SUMO quits). A port of the dynamic range can even be given to the client socket of
    traci itself: the client is then connected to ITSELF and reads its own getVersion request back, hence
    ``struct.error('unpack requires a buffer of 3 bytes')``.
(b) ``traci.init`` registers the connection under its label (``traci.connection._connections['default']``) BEFORE
    ``getVersion``; ``traci.start`` only catches TraCIException. Any other exception (struct.error here) leaves the label
    registered and the socket open, and the environment never calls close (connection_open is still False). Every later
    ``traci.start`` of the same process then fails with "Connection 'default' is already active.".

The executor files of B (b_runner.py, evaluate_any.py, ...) are sealed by freeze.json: changing them makes ``b-run``
refuse. This module is therefore NOT imported by them. ``resume_b_runner.py`` installs it in its own worker process,
replacing ``traci.start`` (the attribute the frozen environment calls) before the frozen ``b_runner.run`` executes.
Nothing of the simulation changes: same SUMO command, same seed, same controller; only the port and the handling of a
failed connection differ.

What the guarded start does
---------------------------
- Before starting: a connection still registered under the label (left by any earlier failure) is closed or removed,
  and every SUMO process this guard launched and that is still alive is terminated. Logged.
- Each attempt: a port of the worker's own range, outside the dynamic range of Windows, checked free (nothing listening,
  bind possible); SUMO launched with ``cmd + ["--remote-port", port]`` exactly as traci.start does; handshake with
  ``traci.init``; the SUMO process launched must still be running after the handshake.
- A failure of the START or of the HANDSHAKE (any exception, before the first simulation step) is cleaned up (label
  removed, socket closed, process terminated) and retried with another port: at most RETRIES = 3 new attempts, each
  logged. After the last one the error is raised: the frozen runner records the cell as INTERRUPTED.
- Failures after the start (during the simulation) are never retried here: they propagate unchanged.
"""
from __future__ import print_function

import json
import os
import socket
import subprocess
import sys
import time

RETRIES = 3                       # new attempts after a failed start: 4 attempts at most
FIRST_PORT = 21000                # worker k uses [FIRST_PORT + k * PORTS_PER_WORKER, ... + PORTS_PER_WORKER)
PORTS_PER_WORKER = 1000
WINDOWS_DYNAMIC = (49152, 65535)  # default dynamic (ephemeral) range of Windows since Vista


class StartFailure(RuntimeError):
    """The SUMO start or the TraCI handshake failed on every attempt."""


def worker_range(worker):
    lo = FIRST_PORT + int(worker) * PORTS_PER_WORKER
    return lo, lo + PORTS_PER_WORKER - 1


def port_is_free(port, host="127.0.0.1"):
    """Nothing listens on the port and it can be bound now (no SO_REUSEADDR: an exclusive check)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        if probe.connect_ex((host, port)) == 0:
            return False                                 # someone is listening
    except OSError:
        pass
    finally:
        probe.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Guard(object):

    def __init__(self, traci_module, worker, log_path, port_range=None, retries=RETRIES, popen=None, clock=time.time):
        self.traci = traci_module
        self.worker = int(worker)
        self.lo, self.hi = port_range or worker_range(worker)
        self.cursor = self.lo
        self.retries = int(retries)
        self.log_path = log_path
        self.popen = popen or subprocess.Popen
        self.clock = clock
        self.cell = None
        self.launched = []               # SUMO processes started by this guard
        self.starts = 0                  # successful starts (per cell, reset by begin_cell)
        self.original_start = None

    # -- installation ------------------------------------------------------------------------------------------
    def install(self):
        """Replace traci.start (and traci.main.start) by the guarded start, in this process only."""
        self.original_start = self.traci.start
        self.traci.start = self.start
        main = getattr(self.traci, "main", None)
        if main is not None and hasattr(main, "start"):
            main.start = self.start
        self.log("installed", ports="{}-{}".format(self.lo, self.hi), retries=self.retries)
        return self

    def uninstall(self):
        if self.original_start is not None:
            self.traci.start = self.original_start
            main = getattr(self.traci, "main", None)
            if main is not None and hasattr(main, "start"):
                main.start = self.original_start

    # -- log ---------------------------------------------------------------------------------------------------
    def log(self, event, **fields):
        row = dict(fields, event=event, worker=self.worker, cell=self.cell, t=round(self.clock(), 3))
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")
        if event not in ("installed", "started"):
            print("TRACI GUARD: {}".format(json.dumps(row, sort_keys=True)))
            sys.stdout.flush()

    # -- connection registry of traci --------------------------------------------------------------------------
    def _registry(self):
        conn = getattr(self.traci, "connection", None)
        return getattr(conn, "_connections", None)

    def release(self, label="default", reason="cleanup"):
        """Close or remove the connection registered under label, then terminate the SUMO processes still alive.
        Never sends anything to the peer: after a failure it may not be our SUMO."""
        registry = self._registry()
        removed = False
        if registry is not None and label in registry:
            con = registry[label]
            sock = getattr(con, "_socket", None)
            try:
                if sock is not None:
                    sock.close()
            except Exception:  # noqa: BLE001 - best effort, the entry is removed below in every case
                pass
            try:
                con._socket = None
            except Exception:  # noqa: BLE001
                pass
            if registry.get("") is con:
                del registry[""]
            del registry[label]
            removed = True
        killed = self.terminate_launched()
        if removed or killed:
            self.log("released", label=label, reason=reason, connection_removed=removed, processes_terminated=killed)
        return removed, killed

    def terminate_launched(self):
        killed = 0
        for proc in self.launched:
            if proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=10)
                except OSError:
                    pass
                killed += 1
        self.launched = [p for p in self.launched if p.poll() is None]
        return killed

    # -- ports -------------------------------------------------------------------------------------------------
    def next_port(self):
        for _ in range(self.hi - self.lo + 1):
            port = self.cursor
            self.cursor = self.lo if self.cursor >= self.hi else self.cursor + 1
            if port_is_free(port):
                return port
        raise StartFailure("no free port in {}-{}".format(self.lo, self.hi))

    # -- the guarded start ---------------------------------------------------------------------------------------
    def start(self, cmd, port=None, numRetries=None, label="default", verbose=False, traceFile=None,
              traceGetters=True, stdout=None, doSwitch=True):
        """Same contract as traci.start (returns the result of getVersion), with the guard described above."""
        if numRetries is None:
            numRetries = getattr(getattr(self.traci, "constants", None), "DEFAULT_NUM_RETRIES", 60)
        if self._registry() is not None and label in self._registry():
            self.log("stale_connection", label=label)
        self.release(label, reason="before start")
        errors = []
        for attempt in range(1, self.retries + 2):
            use = self.next_port() if port is None else port
            proc = None
            t0 = self.clock()
            try:
                cmd2 = list(cmd) + ["--remote-port", str(use)]
                if verbose:
                    print("Calling " + " ".join(cmd2))
                proc = self.popen(cmd2, stdout=stdout)
                self.launched.append(proc)
                result = self.traci.init(use, numRetries, "localhost", label, proc, doSwitch, traceFile, traceGetters)
                if proc.poll() is not None:
                    raise StartFailure("the SUMO process launched on port {} has exited (code {}): the handshake was "
                                       "not with it".format(use, proc.returncode))
                self.starts += 1
                self.log("started", attempt=attempt, port=use, seconds=round(self.clock() - t0, 3))
                return result
            except Exception as error:  # noqa: BLE001 - any failure of the start or of the handshake
                errors.append("attempt {} port {}: {!r}".format(attempt, use, error))
                self.log("start_failed", attempt=attempt, of=self.retries + 1, port=use, error=repr(error),
                         sumo_exit=None if proc is None else proc.poll())
                self.release(label, reason="failed start")
                if port is not None:
                    break                                # an explicit port is never changed
        raise StartFailure("SUMO/TraCI start failed {} time(s): {}".format(len(errors), " | ".join(errors)))

    # -- per cell ----------------------------------------------------------------------------------------------
    def begin_cell(self, directory):
        self.cell = directory
        self.starts = 0

    def end_cell(self, ok):
        """After a cell, whatever happened: nothing may survive into the next cell."""
        removed, killed = self.release("default", reason="end of cell" if ok else "failed cell")
        return {"starts": self.starts, "connection_removed": removed, "processes_terminated": killed}


def dynamic_range_windows():
    """(start, end) of the TCP dynamic range of this Windows machine (netsh, read-only), or the default."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["netsh", "int", "ipv4", "show", "dynamicport", "tcp"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=60).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return WINDOWS_DYNAMIC
    nums = [int(w) for w in out.replace(":", " ").split() if w.isdigit()]
    if len(nums) >= 2:
        return nums[0], nums[0] + nums[1] - 1
    return WINDOWS_DYNAMIC


def excluded_ranges_windows():
    """Ranges reserved by Windows (Hyper-V, WinNAT...), read-only; [] elsewhere."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["netsh", "int", "ipv4", "show", "excludedportrange", "protocol=tcp"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    ranges = []
    for line in out.splitlines():
        words = line.split()
        if len(words) >= 2 and words[0].isdigit() and words[1].isdigit():
            ranges.append((int(words[0]), int(words[1])))
    return ranges


def overlaps(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def check_ranges(workers, dynamic=None, excluded=()):
    """Problems with the port ranges of the workers (each range must avoid the dynamic range; excluded ports are
    only reported: they are skipped at run time by the free-port check)."""
    problems, notes = [], []
    ranges = [worker_range(k) for k in range(workers)]
    if ranges[-1][1] >= 49152 or (dynamic and any(overlaps(r, dynamic) for r in ranges)):
        problems.append("worker port ranges {} meet the dynamic range {}".format(ranges, dynamic or WINDOWS_DYNAMIC))
    for k, r in enumerate(ranges):
        hit = [e for e in excluded if overlaps(r, e)]
        if hit:
            notes.append("worker {} range {} meets excluded ranges {} (those ports are skipped)".format(k, r, hit))
    return problems, notes


__all__ = ["Guard", "StartFailure", "RETRIES", "worker_range", "port_is_free", "check_ranges",
           "dynamic_range_windows", "excluded_ranges_windows"]
