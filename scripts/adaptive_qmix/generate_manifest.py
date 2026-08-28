"""Generate one frozen stochastic traffic-manifest pair (CSV and SUMO XML)."""

from __future__ import print_function

import argparse
import json
import os
import sys


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.traffic import generate_manifest_records, write_manifest  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(
        REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
    ))
    parser.add_argument("--family", required=True, choices=(
        "training", "development", "benchmark_design", "benchmark_validation",
        "learner_validation", "final_test",
    ))
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--index", default=0, type=int)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    records = generate_manifest_records(config, args.family, args.seed, args.index)
    metadata = write_manifest(
        records, config, args.output_prefix, args.family, args.seed, args.index
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

