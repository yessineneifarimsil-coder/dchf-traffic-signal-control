"""Evaluate one frozen learned checkpoint on one explicit common manifest."""

from __future__ import print_function

import argparse
import json
import os
import sys


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.evaluation import evaluate_checkpoint  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--manifest-csv", required=True)
    parser.add_argument("--route-xml", required=True)
    parser.add_argument("--traffic-seed", required=True, type=int)
    parser.add_argument("--sumo-seed", required=True, type=int)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument(
        "--run-kind", choices=("development_evaluation", "official_evaluation"),
        default="development_evaluation"
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--lane-state-logging", choices=("decision", "full"), default="full"
    )
    parser.add_argument(
        "--traci-access-mode", choices=("subscription", "getter"),
        default="subscription"
    )
    parser.add_argument("--config", default=os.path.join(
        REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
    ))
    args = parser.parse_args()
    config = load_config(args.config)
    import traci
    metrics = evaluate_checkpoint(
        traci, config, REPOSITORY_ROOT, args.checkpoint, args.manifest_csv,
        args.route_xml, args.traffic_seed, args.sumo_seed,
        args.output_directory, args.run_kind, args.device,
        args.traci_access_mode, args.lane_state_logging,
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

