"""Resumption of B after the TraCI incident of 2026-11-25 (traci_guard.py, resume_b_runner.py, verify_finished_b.py,
REPRISE_B.cmd).

The incident: worker 2/4, ``error('unpack requires a buffer of 3 bytes')`` during traci.start, then 562 cells with
"Connection 'default' is already active.". Cause (traci 1.25, identical in 1.28): traci.init registers the label
before getVersion, traci.start only catches TraCIException, and the frozen environment sets connection_open after the
start. These tests replay it with a stand-in traci (always) and with the real traci library and a fake TraCI server
(tests/fake_traci_server.py) when traci is importable.
"""
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import test_b_runner as TB  # noqa: E402  (also puts tools/confirmation and the frozen src on sys.path)

BR = TB.BR
import traci_guard as TG  # noqa: E402
import resume_b_runner as RB  # noqa: E402
import verify_finished_b as VF  # noqa: E402

FAKE_SERVER = os.path.join(HERE, "fake_traci_server.py")
RESET = "self.traci.start(command)\nself.connection_open = True\n"     # the frozen reset, as the guard requires
try:
    import importlib
    REAL_TRACI = importlib.import_module("traci")
    importlib.import_module("traci.connection")
except ImportError:
    REAL_TRACI = None

# SHA-256 of the files sealed by freeze.json, at commit 2467ddd (the frozen B). The resumption must not change them.
FROZEN_2467DDD = {
    "../ETAPES.cmd": "bb563c8cfe74777d76ebce0b96262e127b3fc7df83af0953a5ac289e2510d5f4",
    "ablation_metrics.py": "3ecff0b6b612584842458c7d61edc8129f5c462f1f2006351a43180d91e1134c",
    "article_analyses/clopper_pearson.py": "05659f8a799d9a7626825d1bd25785c14089c360d47bbd0405863f0140e5b54e",
    "comparators/comparator_search.py": "4f2ecf0e153bc548df45ed999c25b7a63a01356f8332f0c20dbc04c0570559ed",
    "comparators/controllers.py": "7ee74f0e228ca3bcf5ceaa3fe0b4600b909684a67e7bcfe6e63e20e44c7741ca",
    "comparators/evaluate_comparator.py": "e2800e04311c8156fa0d62b59d764f576c7f2d801e376dee4408f43381bee9bd",
    "comparators/seeds.py": "7979b54a3ae413aa1511023e80218aa0910b5b6c2e3be5bf8a2b2029d5f0853b",
    "comparators_ext/controllers_g5.py": "b1a88390aede8cb01019c2e9e5f43cf531d1dfae63d25e7895775c065a02945f",
    "comparators_ext/evaluate_ext.py": "8450396d1fdae5dd7876f6506c0c6de1d3006eeacd564b7b23f173eb39a2ab88",
    "confirmation/b_runner.py": "8882adc5c86a35e0e765013d733d5ab5caef2379e7d4f3d70da1d85e9a3a40e3",
    "confirmation/confirmation_analysis.py": "ad927e39a32485c5e9e7cfd3b0e71ece2d262d1cb3d99ca58cb4ee036e353b54",
    "confirmation/confirmation_plan.json": "a1382c6f4500d2941e58030f46164c14cc0cae0fc2cfb57d62d7d4fc812b7e43",
    "robustness/evaluate_any.py": "677cd368d2c827d1bdeaf99e2b53c12a43ffbe52e4f99c52578617b87934e26b",
    "robustness/n_adapter.py": "b0bc97bee0f26a5802577eb5c526d50864c94db98cf42bba7f5b8504b9c6a596",
    "robustness/robustness_analysis.py": "f48f12ec0ebcc8089cbe14b075047eb16f72891e45060366b0ec62ce0a2e0336",
    "robustness/scenario_traffic.py": "da4eafa97c50c6c736a170490fad111a64db46649f170d4bf454678c857db877",
}


# ---------------------------------------------------------------------------------------------------------------
# A stand-in traci with the registry semantics of traci 1.25 (connection._connections, init registers the label
# BEFORE getVersion, start only knows TraCIException).
# ---------------------------------------------------------------------------------------------------------------

class TraCIException(Exception):
    pass


class FakeSocket(object):
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeProc(object):
    def __init__(self, cmd, mode):
        self.cmd, self.mode, self.returncode, self.terminated = cmd, mode, None, False
        if mode == "exit":
            self.returncode = 1

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, -15

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self.returncode


class Launcher(object):
    """popen stand-in: the n-th SUMO launched behaves as modes[n] ("ok", "short" or "exit"), then "ok"."""

    def __init__(self, modes=()):
        self.modes, self.procs = list(modes), []

    def __call__(self, cmd, stdout=None):
        proc = FakeProc(cmd, self.modes.pop(0) if self.modes else "ok")
        self.procs.append(proc)
        return proc


def stub_traci(launcher):
    m = types.ModuleType("traci_stub")
    conn = types.ModuleType("traci_stub.connection")
    conn._connections = {}
    conn.has = lambda label: label in conn._connections
    m.connection, m.constants, m.TraCIException = conn, types.SimpleNamespace(DEFAULT_NUM_RETRIES=0), TraCIException
    m.calls = []

    class Con(object):
        def __init__(self, label, proc):
            self._socket, self.label, self.proc = FakeSocket(), label, proc

    def init(port, numRetries=0, host="localhost", label="default", proc=None, doSwitch=True, traceFile=None,
             traceGetters=True):
        m.calls.append(("init", port))
        if proc is not None and proc.poll() is not None and proc.mode == "exit":
            raise TraCIException("TraCI server already finished")
        con = Con(label, proc)
        conn._connections[label] = con                    # registered BEFORE getVersion, as traci 1.25
        if doSwitch:
            conn._connections[""] = con
        if proc is not None and proc.mode == "short":
            raise struct.error("unpack requires a buffer of 3 bytes")
        return 21, "stub"

    def start(cmd, port=None, numRetries=0, label="default", **kw):     # the UNGUARDED traci.start
        if conn.has(label):
            raise TraCIException("Connection '%s' is already active." % label)
        proc = launcher(list(cmd) + ["--remote-port", str(port or 60000)])
        try:
            return init(port or 60000, numRetries, "localhost", label, proc)
        except TraCIException:
            raise

    def close(wait=True):
        con = conn._connections.get("")
        if con is None:
            raise TraCIException("Not connected.")
        con.proc.returncode = 0
        del conn._connections[con.label]
        del conn._connections[""]

    m.init, m.start, m.close = init, start, close
    return m


def quiet(fn, *args, **kw):
    with redirect_stdout(io.StringIO()):
        return fn(*args, **kw)


def read_log(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class Guard(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.log = os.path.join(self.base, "guard.jsonl")

    def tearDown(self):
        shutil.rmtree(self.base)

    def guard(self, launcher, traci=None, retries=TG.RETRIES):
        traci = traci or stub_traci(launcher)
        return traci, TG.Guard(traci, 0, self.log, port_range=(25000, 25999), retries=retries, popen=launcher).install()

    def test_the_incident_without_the_guard(self):
        """struct.error at the first start, then 'already active' for every later start (cause b)."""
        launcher = Launcher(["short", "ok"])
        traci = stub_traci(launcher)
        with self.assertRaises(struct.error):
            traci.start(["sumo"])
        self.assertTrue(traci.connection.has("default"))
        with self.assertRaisesRegex(TraCIException, "already active"):
            traci.start(["sumo"])

    def test_a_struct_error_at_start_is_cleaned_and_retried_on_another_port(self):
        launcher = Launcher(["short"])
        traci, g = self.guard(launcher)
        self.assertEqual(quiet(traci.start, ["sumo", "-n", "x"]), (21, "stub"))
        self.assertEqual(len(launcher.procs), 2)
        first, second = launcher.procs
        self.assertTrue(first.terminated)                                 # the SUMO of the failed attempt is ended
        p1, p2 = int(first.cmd[-1]), int(second.cmd[-1])
        self.assertNotEqual(p1, p2)
        for p in (p1, p2):
            self.assertTrue(25000 <= p <= 25999 and p < 49152)               # the test range, outside the dynamic range
        self.assertEqual(first.cmd[:-2], ["sumo", "-n", "x"])              # same command, only the port added
        rows = read_log(self.log)
        failed = [r for r in rows if r["event"] == "start_failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("unpack requires a buffer of 3 bytes", failed[0]["error"])
        self.assertEqual([r["attempt"] for r in rows if r["event"] == "started"], [2])
        traci.close()
        self.assertFalse(traci.connection.has("default"))
        self.assertEqual(quiet(traci.start, ["sumo"]), (21, "stub"))      # the next task starts normally

    def test_at_most_three_new_attempts_then_the_error_is_raised_and_nothing_is_left(self):
        launcher = Launcher(["short", "exit", "short", "short", "ok"])
        traci, g = self.guard(launcher)
        with self.assertRaises(TG.StartFailure) as ctx:
            quiet(traci.start, ["sumo"])
        self.assertIn("4 time(s)", str(ctx.exception))
        self.assertEqual(len(launcher.procs), 4)                            # 1 + 3 new attempts, never a fifth
        self.assertEqual(len(set(int(p.cmd[-1]) for p in launcher.procs)), 4)
        self.assertFalse(traci.connection.has("default"))
        self.assertFalse(traci.connection._connections)
        self.assertTrue(all(p.poll() is not None for p in launcher.procs))
        self.assertEqual(len([r for r in read_log(self.log) if r["event"] == "start_failed"]), 4)
        self.assertEqual(quiet(traci.start, ["sumo"]), (21, "stub"))      # and the next task starts

    def test_a_handshake_with_a_process_that_has_exited_is_refused(self):
        """The handshake answered, but the SUMO launched is already gone: it was not our SUMO (self-connection or
        another listener on the port). The guard refuses it and retries."""
        launcher = Launcher()
        traci = stub_traci(launcher)
        real_init = traci.init

        def init(port, *a, **kw):
            result = real_init(port, *a, **kw)
            if len(launcher.procs) == 1:
                launcher.procs[0].returncode = 1                            # our SUMO quit (Address already in use)
            return result
        traci.init = init
        traci, g = self.guard(launcher, traci)
        quiet(traci.start, ["sumo"])
        rows = read_log(self.log)
        self.assertIn("has exited", [r for r in rows if r["event"] == "start_failed"][0]["error"])
        self.assertEqual(len(launcher.procs), 2)

    def test_a_label_left_by_an_earlier_failure_is_released_before_the_start(self):
        launcher = Launcher(["short"])
        traci = stub_traci(launcher)
        with self.assertRaises(struct.error):
            traci.start(["sumo"])                                           # unguarded: the label stays
        traci, g = self.guard(launcher, traci)
        self.assertEqual(quiet(traci.start, ["sumo"]), (21, "stub"))
        self.assertIn("stale_connection", [r["event"] for r in read_log(self.log)])

    def test_end_of_cell_closes_whatever_is_left(self):
        launcher = Launcher()
        traci, g = self.guard(launcher)
        g.begin_cell("cells/x")
        quiet(traci.start, ["sumo"])                                        # the simulation then fails: no close
        info = quiet(g.end_cell, False)
        self.assertEqual(info, {"starts": 1, "connection_removed": True, "processes_terminated": 1})
        self.assertFalse(traci.connection._connections)

    def test_port_ranges_are_distinct_and_outside_the_dynamic_range(self):
        ranges = [TG.worker_range(k) for k in range(4)]
        self.assertEqual(ranges, [(21000, 21999), (22000, 22999), (23000, 23999), (24000, 24999)])
        self.assertEqual(TG.check_ranges(4, (49152, 65535))[0], [])
        self.assertTrue(TG.check_ranges(4, (20000, 30000))[0])              # a non-default dynamic range is refused


@unittest.skipIf(REAL_TRACI is None, "traci is not importable here")
class RealTraci(unittest.TestCase):
    """The same, with the real traci library (1.25 on Windows) and a fake TraCI server. Ports 25000-25999 only:
    never the dynamic range, never the ports of the resume workers (21000-24999)."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.log = os.path.join(self.base, "guard.jsonl")
        self.state = os.path.join(self.base, "state")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        reg = REAL_TRACI.connection._connections
        for label in [k for k in reg if k]:
            con = reg[label]
            try:
                con._socket.close()
            except Exception:  # noqa: BLE001
                pass
            proc = getattr(con, "_process", None)
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
        reg.clear()
        shutil.rmtree(self.base, ignore_errors=True)

    def cmd(self, mode):
        return [sys.executable, FAKE_SERVER, mode, self.state]

    def test_the_incident_is_reproduced_by_the_real_library(self):
        port = next(p for p in range(25900, 26000) if TG.port_is_free(p))   # test range: never a campaign port
        with self.assertRaises(struct.error) as ctx:
            quiet(REAL_TRACI.start, self.cmd("short"), port=port)
        self.assertIn("unpack requires a buffer of 3 bytes", str(ctx.exception))
        self.assertTrue(REAL_TRACI.connection.has("default"))
        with self.assertRaisesRegex(REAL_TRACI.TraCIException, "already active"):
            quiet(REAL_TRACI.start, self.cmd("ok"), port=port + 1)

    def test_the_guard_retries_after_the_struct_error_and_the_next_task_starts(self):
        g = TG.Guard(REAL_TRACI, 3, self.log, port_range=(25000, 25449)).install()
        self.addCleanup(g.uninstall)
        self.assertEqual(quiet(REAL_TRACI.start, self.cmd("flaky:1"))[0], 21)
        REAL_TRACI.close()
        self.assertFalse(REAL_TRACI.connection.has("default"))
        self.assertEqual(quiet(REAL_TRACI.start, self.cmd("ok"))[0], 21)      # next task
        REAL_TRACI.close()
        rows = read_log(self.log)
        failed = [r for r in rows if r["event"] == "start_failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("unpack requires a buffer of 3 bytes", failed[0]["error"])
        ports = [r["port"] for r in rows if r["event"] in ("start_failed", "started")]
        self.assertEqual(len(ports), 3)
        self.assertNotEqual(ports[0], ports[1])
        self.assertTrue(all(25000 <= p <= 25449 for p in ports))
        self.assertTrue(all(p.poll() is not None for p in g.launched) or not g.launched)

    def test_four_failed_starts_raise_and_leave_no_label_and_no_process(self):
        g = TG.Guard(REAL_TRACI, 1, self.log, port_range=(25450, 25899)).install()
        self.addCleanup(g.uninstall)
        with self.assertRaises(TG.StartFailure):
            quiet(REAL_TRACI.start, self.cmd("flaky:9"))
        self.assertFalse(REAL_TRACI.connection.has("default"))
        self.assertEqual(g.terminate_launched(), 0)
        self.assertEqual(quiet(REAL_TRACI.start, self.cmd("ok"))[0], 21)


# ---------------------------------------------------------------------------------------------------------------
# Resumption on the frozen b_runner (Base fixture of test_b_runner: frozen, prepared plan of 2470 jobs).
# ---------------------------------------------------------------------------------------------------------------

def no_process():
    return [], None


def sha_tree(path):
    out = {}
    for d, _dirs, names in os.walk(path):
        for n in names:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, path)] = hashlib.sha256(f.read()).hexdigest()
    return out


class TraciEvaluator(TB.FakeEvaluator):
    """A cell as the frozen environment does it: traci.start, the simulation, close, then the run files."""

    def __init__(self, traci, fail_in_simulation=(), **kw):
        TB.FakeEvaluator.__init__(self, **kw)
        self.traci, self.fail_in_simulation, self.started = traci, set(fail_in_simulation), []

    def __call__(self, root, j, prefix, work):
        self.started.append(j["directory"])
        os.makedirs(work, exist_ok=True)
        self.traci.start(["sumo", "-r", prefix + ".rou.xml"])
        if j["directory"] in self.fail_in_simulation:
            raise RuntimeError("TraCI error during the simulation")            # no close: the guard must clean up
        self.traci.close()
        shutil.rmtree(work)
        TB.FakeEvaluator.__call__(self, root, j, prefix, work)


@unittest.skipUnless(TB.HAVE_STATS, "frozen statistics module not available")
class Resume(TB.Base):

    def setUp(self):
        TB.Base.setUp(self)
        self.plan = self.frozen_and_prepared()
        jobs = BR.unique_jobs(self.plan["jobs"])
        self.shard2 = [j["directory"] for pos, j in enumerate(jobs) if pos % 4 == 2]
        # the first launch: shard 2 loses its connection label at its 1st job and every later job fails
        ev = TB.FakeEvaluator(fail=set(self.shard2))
        for i in range(4):
            self.q(BR.run, self.root, "{}/4".format(i), evaluator=ev, free=10 ** 13)
        self.finished_before = dict((j["directory"], sha_tree(os.path.join(self.root, j["directory"])))
                                    for j in jobs[:40] if j["directory"] not in self.shard2)

    def sealed(self):
        return dict((n, BR.sha256_file(os.path.join(self.root, n))) for n in ("plan.json", "freeze.json", "margins.json"))

    def test_the_frozen_runner_alone_would_keep_shard_2_on_one_process(self):
        """Point 3: b_runner.run --shard i/4 deals ALL the jobs by position, so the 563 jobs of shard 2 would all be
        resumed by worker 2/4 (or by a single 0/1 process): no spreading over 4 processes without the launcher."""
        jobs = BR.unique_jobs(self.plan["jobs"])
        per_shard = [len([j for j in BR.shard(self.plan["jobs"], "{}/4".format(i))
                          if BR.classify(self.root, j)[0] not in BR.FINISHED]) for i in range(4)]
        self.assertEqual(per_shard, [0, 0, len(self.shard2), 0])
        self.assertEqual(len(jobs), 2470)

    def test_assign_spreads_only_the_unfinished_jobs_over_4_workers_and_changes_nothing_else(self):
        before = self.sealed()
        path, a = quiet(RB.assign, self.root, 4, lister=no_process)
        flat = [d for lst in a["jobs"] for d in lst]
        self.assertEqual(sorted(flat), sorted(self.shard2))
        self.assertEqual(len(flat), len(set(flat)))
        sizes = [len(lst) for lst in a["jobs"]]
        self.assertLessEqual(max(sizes) - min(sizes), 1)
        self.assertEqual(a["plan_fingerprint"], self.plan["fingerprint"])
        self.assertEqual(self.sealed(), before)                             # plan, freeze, margins untouched
        with self.assertRaises(FileExistsError):
            RB.write_json_once(path, {})                                    # written once
        self.assertEqual([list(r) for r in a["port_ranges"]], [[21000, 21999], [22000, 22999], [23000, 23999], [24000, 24999]])

    def test_assign_and_preflight_are_refused_while_a_B_process_runs(self):
        busy = lambda: ([{"pid": 4242, "campaign": "B", "action": "run", "shard": "0/4"}], None)  # noqa: E731
        with self.assertRaisesRegex(RB.ResumeError, "still running"):
            RB.assign(self.root, 4, lister=busy)
        self.assertEqual(RB.assignments(self.root), [])
        quiet(RB.assign, self.root, 4, lister=no_process)
        with self.assertRaisesRegex(RB.ResumeError, "still running"):
            RB.preflight(self.root, lister=busy, free=10 ** 13, dirs=[], reset_source=RESET)
        unlisted = lambda: (None, "process listing unavailable")  # noqa: E731
        with self.assertRaisesRegex(RB.ResumeError, "cannot list"):
            RB.assign(self.root, 4, lister=unlisted)
        self.assertEqual(quiet(RB.preflight, self.root, lister=no_process, free=10 ** 13, dirs=[], reset_source=RESET), 0)

    def test_the_resume_runs_each_job_once_over_4_workers_and_keeps_the_partial_folders(self):
        quiet(RB.assign, self.root, 4, lister=no_process)
        _p, a = RB.load_assignment(self.root)
        launcher = Launcher(["short"])                       # the very first start of the resumption fails (struct.error)
        traci = stub_traci(launcher)
        ev = TraciEvaluator(traci)
        codes = [quiet(RB.run, self.root, k, evaluator=ev, traci_module=traci, free=10 ** 13, dirs=[],
                       reset_source=RESET, popen=launcher) for k in range(4)]
        self.assertEqual(codes, [0, 0, 0, 0])
        self.assertEqual(sorted(ev.calls), sorted(self.shard2))             # each unfinished job once, nothing else
        for k in range(4):
            self.assertTrue(set(a["jobs"][k]) >= set(d for d in ev.calls if d in a["jobs"][k]))
        self.assertEqual(self.q(BR.progress, self.root), 0)                 # 2470/2470
        for d in self.shard2[:20]:
            self.assertTrue(os.path.isdir(os.path.join(self.root, d + ".incomplete1")))   # partial folder kept
            self.assertEqual(BR.classify(self.root, {"directory": d, **[j for j in self.plan["jobs"]
                                                                        if j["directory"] == d][0]})[0], "complete")
        for d, tree in self.finished_before.items():                       # finished cells untouched
            self.assertEqual(sha_tree(os.path.join(self.root, d)), tree)
        logs = [read_log(p) for p in sorted(glob_logs(self.root))]
        failed = [r for rows in logs for r in rows if r["event"] == "start_failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("unpack requires a buffer of 3 bytes", failed[0]["error"])
        self.assertFalse(traci.connection._connections)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "run_log_shardr01w2of4.jsonl")))

    def test_a_cell_whose_start_always_fails_is_interrupted_and_the_next_one_runs(self):
        """Point 5: four failed starts (struct.error) -> that cell is INTERRUPTED; the next cell starts normally."""
        quiet(RB.assign, self.root, 4, lister=no_process)
        _p, a = RB.load_assignment(self.root)
        launcher = Launcher(["short"] * 4)
        traci = stub_traci(launcher)
        ev = TraciEvaluator(traci)
        code = quiet(RB.run, self.root, 0, evaluator=ev, traci_module=traci, free=10 ** 13, dirs=[], reset_source=RESET,
                     popen=launcher)
        self.assertEqual(code, 3)
        first, rest = a["jobs"][0][0], a["jobs"][0][1:]
        job = dict((j["directory"], j) for j in self.plan["jobs"])
        self.assertEqual(BR.classify(self.root, job[first])[0], "interrupted")
        self.assertTrue(all(BR.classify(self.root, job[d])[0] == "complete" for d in rest))
        self.assertEqual(len(launcher.procs), 4 + len(rest))
        self.assertFalse(traci.connection._connections)

    def test_an_error_during_the_simulation_stays_interrupted_without_a_new_attempt(self):
        quiet(RB.assign, self.root, 4, lister=no_process)
        _p, a = RB.load_assignment(self.root)
        victim = a["jobs"][1][0]
        launcher = Launcher()
        traci = stub_traci(launcher)
        ev = TraciEvaluator(traci, fail_in_simulation={victim})
        self.assertEqual(quiet(RB.run, self.root, 1, evaluator=ev, traci_module=traci, free=10 ** 13, dirs=[],
                               reset_source=RESET, popen=launcher), 3)
        self.assertEqual(ev.started.count(victim), 1)
        self.assertEqual(len(launcher.procs), len(a["jobs"][1]))              # one SUMO per cell, no retry
        self.assertTrue(launcher.procs[0].terminated)                          # the SUMO of the failed cell is ended
        self.assertFalse(traci.connection._connections)
        job = dict((j["directory"], j) for j in self.plan["jobs"])
        self.assertEqual(BR.classify(self.root, job[victim])[0], "interrupted")
        self.assertEqual(BR.classify(self.root, job[a["jobs"][1][1]])[0], "complete")

    def test_a_changed_guard_or_plan_is_refused(self):
        path, a = quiet(RB.assign, self.root, 4, lister=no_process)
        a["guard_sha256"]["traci_guard.py"] = "0" * 64
        os.chmod(path, 0o644)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(a, f)
        with self.assertRaisesRegex(RB.ResumeError, "differ from the assignment"):
            RB.load_assignment(self.root)

    def test_a_start_path_the_guard_does_not_cover_is_refused(self):
        problems, _ = RB.start_path_report([], "traci.start(command)")
        self.assertTrue(any("does not call self.traci.start" in p for p in problems))
        d = os.path.join(self.base, "pkg")
        os.makedirs(d)
        with open(os.path.join(d, "env.py"), "w", encoding="utf-8") as f:
            f.write("import traci\ntraci.init(8813)\n")
        problems, _ = RB.start_path_report([d], RESET)
        self.assertTrue(any("traci.init" in p for p in problems))
        self.assertEqual(RB.start_path_report([], RESET)[0], [])


def glob_logs(root):
    import glob
    return glob.glob(os.path.join(root, "resume", "traci_guard_*.jsonl"))


# ---------------------------------------------------------------------------------------------------------------
# Point 4: finished cells ran their own SUMO (read-only check).
# ---------------------------------------------------------------------------------------------------------------

def manifest_with_routes(profile, seed, prefix):
    with open(prefix + ".metadata.json", "w", encoding="utf-8") as f:
        json.dump({"scenario": profile, "seed_value": seed, "scheduled_total": 100, "sumo_seed": 7000 + int(seed)}, f)
    with open(prefix + ".rou.xml", "w", encoding="utf-8") as f:
        f.write('<routes>\n' + "".join('<vehicle id="{}_v{:03d}" depart="{}"/>\n'.format(seed, k, k) for k in range(100))
                + '</routes>\n')


class TripinfoEvaluator(TB.FakeEvaluator):
    """Writes a tripinfo.xml as SUMO does, header with the options of its own command line."""

    def __init__(self, port_of=None, foreign=None, **kw):
        TB.FakeEvaluator.__init__(self, **kw)
        self.port_of, self.foreign, self.n = port_of or {}, foreign or {}, 0

    def __call__(self, root, j, prefix, work):
        TB.FakeEvaluator.__call__(self, root, j, prefix, work)
        self.n += 1
        with open(prefix + ".metadata.json", encoding="utf-8") as f:
            meta = json.load(f)
        route = self.foreign.get(j["directory"], prefix + ".rou.xml")
        seed = os.path.basename(route).rsplit("_", 1)[1].split(".")[0]
        port = self.port_of.get(j["directory"], 21000 + self.n)
        head = ('<?xml version="1.0" encoding="UTF-8"?>\n<!-- generated on 2026-11-25T10:{:02d}:00.000000+00:00 by '
                'Eclipse SUMO sumo 1.25.0\n<sumoConfiguration>\n    <input>\n        <route-files value="{}"/>\n'
                '    </input>\n    <output>\n        <tripinfo-output value="{}"/>\n    </output>\n'
                '    <traci_server>\n        <remote-port value="{}"/>\n    </traci_server>\n    <random_number>\n'
                '        <seed value="{}"/>\n    </random_number>\n</sumoConfiguration>\n-->\n').format(
            self.n % 60, os.path.abspath(route), os.path.abspath(os.path.join(work, "tripinfo.xml")), port,
            meta["sumo_seed"])
        body = "<tripinfos>\n" + "".join('    <tripinfo id="{}_v{:03d}"/>\n'.format(seed, k) for k in range(100)) + "</tripinfos>\n"
        with open(os.path.join(work, "tripinfo.xml"), "w", encoding="utf-8") as f:
            f.write(head + body)


@unittest.skipUnless(TB.HAVE_STATS, "frozen statistics module not available")
class VerifyFinished(TB.Base):

    def setUp(self):
        TB.Base.setUp(self)
        saved = BR.manifest_writer
        BR.manifest_writer = manifest_with_routes
        self.addCleanup(setattr, BR, "manifest_writer", saved)
        self.plan = self.frozen_and_prepared()
        self.jobs = [j for j in BR.shard(self.plan["jobs"], "0/60")]

    def run_cells(self, ev):
        self.q(BR.run, self.root, "0/60", evaluator=ev, free=10 ** 13)

    def test_clean_cells_are_verified(self):
        self.run_cells(TripinfoEvaluator())
        report = VF.verify(self.root)
        self.assertEqual(report["verdict"], "VERIFIED", report["problems"][:2])
        self.assertEqual(report["counts"]["verified"], len(self.jobs))
        self.assertEqual(report["port_overlaps"], [])

    def test_a_cell_that_ran_another_cells_sumo_is_reported(self):
        a, b = self.jobs[0], next(j for j in self.jobs if j["seed"] != self.jobs[0]["seed"])
        other = os.path.join(self.root, "manifests", "{}_{}.rou.xml".format(b["profile"], b["seed"]))
        self.run_cells(TripinfoEvaluator(foreign={a["directory"]: other}))
        report = VF.verify(self.root)
        self.assertEqual(report["verdict"], "PROBLEMS")
        bad = dict((p["dir"], " ".join(p["problems"])) for p in report["problems"])
        self.assertIn(a["directory"], bad)
        self.assertIn("route-files", bad[a["directory"]])
        self.assertIn("foreign ids", bad[a["directory"]])

    def test_the_same_port_at_overlapping_times_is_reported(self):
        a, b = self.jobs[0]["directory"], self.jobs[1]["directory"]
        self.run_cells(TripinfoEvaluator(port_of={a: 65533, b: 65533}))
        report = VF.verify(self.root)
        self.assertEqual(len(report["port_overlaps"]), 1)
        self.assertEqual(sorted(report["port_overlaps"][0]["cells"]), sorted([a, b]))

    def test_without_header_the_check_says_so(self):
        self.run_cells(TB.FakeEvaluator())                 # its tripinfo is not a SUMO output at all
        with redirect_stdout(io.StringIO()) as out:
            code = VF.main(["--root", self.root, "--out", os.path.join(self.base, "v.json")])
        self.assertEqual(code, 1)
        report = VF.verify(self.root)
        self.assertEqual(len(report["without_header"]), len(self.jobs))
        self.assertIn("without a SUMO header", out.getvalue())
        self.assertTrue(all("unreadable" in " ".join(p["problems"]) for p in report["problems"]))

    def test_the_check_writes_nothing_in_the_campaign_root(self):
        self.run_cells(TripinfoEvaluator())
        before = sha_tree(self.root)
        quiet(VF.main, ["--root", self.root, "--out", os.path.join(self.base, "v.json")])
        self.assertEqual(sha_tree(self.root), before)


# ---------------------------------------------------------------------------------------------------------------
# Static: REPRISE_B.cmd and the sealed files.
# ---------------------------------------------------------------------------------------------------------------

class Static(unittest.TestCase):

    def test_reprise_cmd_is_crlf_ascii_with_an_exit_at_the_end_of_every_block(self):
        with open(os.path.join(ROOT, "REPRISE_B.cmd"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        lines = raw.decode("ascii").split("\r\n")
        labels, current = {}, None
        for line in lines:
            if line.startswith(":"):
                current = line[1:]
                labels[current] = []
            elif current and line.strip():
                labels[current].append(line)
        self.assertEqual(sorted(labels), ["r_assign", "r_check", "r_run", "r_run_refused", "r_verify"])
        for label, body in labels.items():
            self.assertTrue(body[-1].startswith("exit /b "), label)
        run = labels["r_run"]
        self.assertTrue(run[0].startswith("python tools\\confirmation\\resume_b_runner.py preflight"))
        self.assertEqual(run[1], "if errorlevel 1 goto r_run_refused")
        self.assertEqual(len([l for l in run if l.startswith("start ")]), 4)
        self.assertEqual(run[-1], "exit /b %LAUNCH_RC%")
        for word in ("del ", "rmdir", "rd ", "erase ", "move "):
            self.assertFalse([l for l in lines if l.lower().startswith(word) and not l.lower().startswith("rem")], word)

    def test_the_files_sealed_by_the_freeze_are_those_of_2467ddd(self):
        """The resumption adds files and changes none of the executor files hashed in freeze.json."""
        got = BR.code_hashes()
        self.assertEqual(sorted(got), sorted(FROZEN_2467DDD))
        self.assertEqual(got, FROZEN_2467DDD)
        for name in ("resume_b_runner.py", "traci_guard.py", "verify_finished_b.py"):
            self.assertNotIn("confirmation/" + name, got)


if __name__ == "__main__":
    unittest.main()
