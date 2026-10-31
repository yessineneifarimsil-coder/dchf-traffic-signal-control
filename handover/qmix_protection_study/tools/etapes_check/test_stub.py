"""Stand-in test module for verify_etapes_cmd.cmd: fails when FAKE_RC is not 0, so `python -m unittest`
returns 1, as a real failing test run would."""
import os
import unittest


class Stub(unittest.TestCase):
    def test_outcome_set_by_fake_rc(self):
        with open(os.environ["ETAPES_CALLS"], "a") as handle:
            handle.write("unittest-stub\n")
        self.assertEqual(os.environ.get("FAKE_RC", "0"), "0")


if __name__ == "__main__":
    unittest.main()
