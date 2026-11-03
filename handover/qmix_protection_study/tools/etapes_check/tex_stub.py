"""Stand-in for pdflatex / bibtex, used only by verify_etapes_cmd.cmd through PDFLATEX and BIBTEX:
    python tex_stub.py <pdflatex|bibtex> args
records "<program> args" and exits with FAKE_PDFLATEX_RC or FAKE_BIBTEX_RC (default 0). It compiles nothing."""
import os
import sys

program = sys.argv[1]
with open(os.environ["ETAPES_CALLS"], "a") as handle:
    handle.write("{} {}\n".format(program, " ".join(sys.argv[2:])))
sys.exit(int(os.environ.get("FAKE_{}_RC".format(program.upper()), "0") or 0))
