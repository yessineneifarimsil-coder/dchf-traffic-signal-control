"""Derive frozen GAD50/phase-lag/stop-line metrics without rerunning SUMO."""

from __future__ import print_function

import argparse
import json
import os
import sys


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.coordination_analysis import derive_coordination_metrics  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory")
    parser.add_argument("--config", default=os.path.join(
        REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
    ))
    args = parser.parse_args()
    summary = derive_coordination_metrics(args.run_directory, load_config(args.config))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

