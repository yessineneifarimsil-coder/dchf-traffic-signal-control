"""Derive behaviour, starvation and service metrics from raw logs.

Runs entirely on stored logs; SUMO is never restarted. A run containing more
than one episode must name the episode, because simulation time restarts at
zero in each of them.
"""

from __future__ import print_function

import argparse
import json
import os
import sys


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.behavior_analysis import derive_behavior_metrics  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory")
    parser.add_argument(
        "--episode-index", type=int, default=None,
        help="required when the run contains more than one episode")
    parser.add_argument(
        "--output-directory", default=None,
        help="where to write derived products; by default a single-episode "
             "source writes beside its raw logs and a multi-episode source "
             "writes to <run>/derived/episode_NNNNN/")
    parser.add_argument("--config", default=os.path.join(
        REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"))
    args = parser.parse_args()
    summary = derive_behavior_metrics(
        args.run_directory, load_config(args.config), args.episode_index,
        args.output_directory,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
