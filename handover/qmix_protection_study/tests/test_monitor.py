"""Tests of tools/monitor/b_watch.py (processes, backup-logs, watch) on stand-in roots."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "monitor"))
import b_watch as W  # noqa: E402


class Monitor(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.b, self.x = os.path.join(self.base, "b"), os.path.join(self.base, "x")
        jobs = [{"profile": "R0_reference", "directory": "cells/R0/{}".format(k)} for k in range(6)]
        os.makedirs(self.b)
        with open(os.path.join(self.b, "plan.json"), "w") as f:
            json.dump({"jobs": jobs}, f)
        for k in range(2):
            os.makedirs(os.path.join(self.b, "cells", "R0", str(k)))
            open(os.path.join(self.b, "cells", "R0", str(k), "evaluation_metrics.json"), "w").close()
        os.makedirs(os.path.join(self.x, "orders"))
        with open(os.path.join(self.x, "orders", "aext-design.json"), "w") as f:
            json.dump({"jobs": [{"directory": "runs/a"}, {"directory": "runs/a"}, {"directory": "runs/b"}]}, f)
        self.cwd = os.getcwd()
        os.chdir(self.base)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.base)

    def log(self, times):
        with open(os.path.join(self.b, "run_log_shard0of4.jsonl"), "w") as f:
            for t in times:
                f.write(json.dumps({"dir": "d", "state": "complete", "t_end": t}) + "\n")

    def test_snapshot_without_history_says_estimation_unavailable(self):
        self.log([time.time() - 4000])
        text = W.snapshot(self.b, self.x)
        self.assertRegex(text, r"A-ext aext-design\s+0/2\s+finished")       # duplicates counted once
        self.assertIn("B R0_reference", text)
        self.assertIn("2/6", text)
        self.assertIn("estimation indisponible", text)
        self.assertIn("free space on the volume of B", text)

    def test_snapshot_rate_over_the_last_30_minutes(self):
        now = time.time()
        self.log([now - 100, now - 200, now - 300, now - 5000])
        text = W.snapshot(self.b, self.x, now)
        self.assertIn("3 runs finished -> 6.0 runs/h", text)
        self.assertIn("remaining 6", text)                                    # 4 B + 2 A-ext

    def test_processes_lists_workers_and_never_itself(self):
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "b_runner.py", "run", "--shard", "2/4"])
        monitor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "b_watch.py", "watch", "b_runner.py"])
        try:
            time.sleep(0.5)
            procs, error = W.list_processes()
            self.assertIsNone(error)
            pids = [p["pid"] for p in procs]
            self.assertIn(worker.pid, pids)
            self.assertNotIn(monitor.pid, pids)
            self.assertNotIn(os.getpid(), pids)
            me = [p for p in procs if p["pid"] == worker.pid][0]
            self.assertEqual((me["campaign"], me["action"], me["shard"]), ("B", "run", "2/4"))
        finally:
            worker.kill()
            monitor.kill()

    def test_backup_logs_copies_and_deletes_nothing(self):
        os.makedirs("logs")
        for name in ("b_shard0.log", "aext_aext-design_shard1.log", "other.log"):
            with open(os.path.join("logs", name), "w") as f:
                f.write(name)
        self.log([time.time()])
        dest, copied = W.backup_logs(self.b, self.x)
        self.assertEqual(sorted(os.listdir(dest)), ["B", "aext_aext-design_shard1.log", "b_shard0.log"])
        self.assertTrue(os.path.isfile(os.path.join("logs", "b_shard0.log")))  # originals kept
        self.assertTrue(os.path.isfile(os.path.join(self.b, "run_log_shard0of4.jsonl")))
        self.assertEqual(len(copied), 3)


if __name__ == "__main__":
    unittest.main()
