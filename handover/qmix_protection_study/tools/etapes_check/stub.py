"""Stand-in for a study script, used only by verify_etapes_cmd.cmd: records how it was called and exits with
the code in FAKE_RC. It never runs on study data."""
import os
import sys

with open(os.environ["ETAPES_CALLS"], "a") as handle:
    handle.write("{} {}\n".format(os.path.basename(sys.argv[0]), " ".join(sys.argv[1:])))
sys.exit(int(os.environ.get("FAKE_RC", "0")))
