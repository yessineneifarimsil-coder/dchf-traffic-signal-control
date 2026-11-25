"""Stand-in for a study script, used only by verify_etapes_cmd.cmd: records how it was called and exits with
the code in FAKE_RC (FAKE_PREFLIGHT_RC for "b_runner.py preflight" when set). It never runs on study data."""
import os
import sys

with open(os.environ["ETAPES_CALLS"], "a", encoding="utf-8") as handle:
    handle.write("{} {}\n".format(os.path.basename(sys.argv[0]), " ".join(sys.argv[1:])))
if "preflight" in sys.argv[1:2] and os.environ.get("FAKE_PREFLIGHT_RC"):
    sys.exit(int(os.environ["FAKE_PREFLIGHT_RC"]))     # b-run checks freeze and disk before launching workers
sys.exit(int(os.environ.get("FAKE_RC", "0")))
