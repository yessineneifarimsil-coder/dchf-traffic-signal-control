"""Development/feasibility/official entry point with scientific-run guard."""

from __future__ import print_function

import argparse
import json
import os
import sys


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.training import train_learned_controller  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", required=True, choices=("qmix", "vdn", "idqn"))
    parser.add_argument("--training-seed", required=True, type=int)
    parser.add_argument(
        "--run-kind", required=True,
        choices=("development", "compute_feasibility", "official_training")
    )
    parser.add_argument("--transition-limit", type=int)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--config", default=os.path.join(
        REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
    ))
    args = parser.parse_args()
    if args.run_kind == "compute_feasibility" and args.transition_limit is None:
        args.transition_limit = 20000
    config = load_config(args.config)
    import traci
    result = train_learned_controller(
        traci,
        config,
        REPOSITORY_ROOT,
        args.method,
        args.training_seed,
        args.output_directory,
        args.run_kind,
        args.transition_limit,
        args.device,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

