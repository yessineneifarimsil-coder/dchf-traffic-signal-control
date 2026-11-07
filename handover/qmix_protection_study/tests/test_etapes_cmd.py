"""Static checks of ETAPES.cmd (platform independent; the behavioural check is
tools/etapes_check/verify_etapes_cmd.cmd, to run on Windows).

Correction of 2026-11-07: "command & goto :eof" returned 0 under "cmd /c" on Windows when the command failed.
Every step must now end with an explicit "exit /b <code>" in a labelled block, in a CRLF file (labels and goto
are unreliable in LF batch files), and the steps that read ROB must stop with code 2 when the folder is absent.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "ETAPES.cmd")
ROB_READERS = ("robustness-run", "robustness-progress", "robustness-analyse", "comparators-verify-manifests",
               "mp-check-robustness", "guarantee-diagnostic")


class EtapesCmd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(PATH, "rb") as f:
            cls.raw = f.read()
        cls.lines = cls.raw.decode("ascii").split("\r\n")

    def test_crlf_only(self):
        self.assertEqual(self.raw.count(b"\n"), self.raw.count(b"\r\n"))

    def test_no_goto_eof_after_a_command(self):
        code = [l for l in self.lines if not l.lower().startswith("rem ")]
        self.assertFalse([l for l in code if "goto :eof" in l.lower()])

    def blocks(self):
        dispatch = dict(re.findall(r'^if "%~1"=="([a-z0-9-]+)" goto (s_[a-z0-9_]+)$', "\n".join(self.lines), re.M))
        labels, current = {}, None
        for line in self.lines:
            if line.startswith(":") and not line.startswith("::"):
                current = line[1:]
                labels[current] = []
            elif current is not None and line.strip():
                labels[current].append(line)
        return dispatch, labels

    def test_every_step_has_a_block_ending_with_an_explicit_exit(self):
        dispatch, labels = self.blocks()
        self.assertEqual(len(dispatch), 34)
        for step, label in dispatch.items():
            self.assertIn(label, labels, step)
            body = labels[label]
            self.assertTrue(body[-1].startswith("exit /b "), (step, body[-1]))
            for line in body[:-1]:
                if line.startswith("exit /b"):
                    self.fail("{}: exit before the end of the block".format(step))
            commands = [l for l in body if l.startswith(("python", "start", "%PDFLATEX%", "%BIBTEX%"))]
            self.assertTrue(commands, step)
            if any(l.startswith("python") for l in body):
                self.assertEqual(body[-1], "exit /b %errorlevel%", step)
        index = self.lines.index('echo Unknown step "%~1". See the header of this file and README.md.')
        self.assertEqual(self.lines[index + 1], "exit /b 2")

    def test_rob_default_and_guard(self):
        self.assertIn(r'if "%ROB%"=="" set ROB=%QMIX_RESULTS%\robustness_validation_2026-11-04', self.lines)
        dispatch, labels = self.blocks()
        for step in ROB_READERS:
            self.assertEqual(labels[dispatch[step]][0], 'if not exist "%ROB%\\" goto rob_missing', step)
        self.assertEqual(labels["rob_missing"][-1], "exit /b 2")
        for step, label in dispatch.items():
            if step not in ROB_READERS and step not in ("robustness-plan", "robustness-prepare"):
                self.assertFalse(any("%ROB%" in l for l in labels[label]), step)

    def test_parallel_steps_return_the_launch_code_and_say_so(self):
        dispatch, labels = self.blocks()
        for step in ("ablation-run", "robustness-run", "comparators-run"):
            body = labels[dispatch[step]]
            self.assertEqual(sum(1 for l in body if l.startswith("start ")), 4)
            self.assertEqual(sum(1 for l in body if l == 'if errorlevel 1 set "LAUNCH_RC=1"'), 4)
            self.assertTrue(any("covers the launch only" in l for l in body))
            self.assertEqual(body[-1], "exit /b %LAUNCH_RC%")


if __name__ == "__main__":
    unittest.main()
