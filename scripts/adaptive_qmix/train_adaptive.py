"""Development/feasibility/official entry point with scientific-run guard."""

from __future__ import print_function

import argparse
import json
import os
import sys


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.protocol.authorization import authorize_run  # noqa: E402
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
    # Evidence cadence: training and the compute-feasibility gate log lane
    # state once per joint decision; frozen-policy evaluation logs every
    # second. Neither setting affects control, observations or reward.
    parser.add_argument(
        "--lane-state-logging", choices=("decision", "full"), default="decision"
    )
    # Engineering transport switch. It exists for the A/B equivalence harness
    # and is not a scientific configuration.
    parser.add_argument(
        "--traci-access-mode", choices=("subscription", "getter"),
        default="subscription"
    )
    parser.add_argument(
        "--campaign-state", default=None,
        help="campaign state directory; required for official_training, "
             "which is authorised by the verified freeze_baseline_plans "
             "artefact rather than by any flag in the scientific config")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--config", default=os.path.join(
        REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
    ))
    args = parser.parse_args()
    if args.run_kind == "compute_feasibility" and args.transition_limit is None:
        args.transition_limit = 20000
    # Checked before the configuration is loaded, SUMO is imported or any
    # output directory is created, so an unauthorised official run leaves
    # nothing behind.
    authorization = authorize_run(args.run_kind, args.campaign_state)
    if authorization is not None:
        print("official training authorised by {} ({})".format(
            authorization["authorising_stage"],
            authorization["authorising_artefact_sha256"][:16],
        ))
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
        args.traci_access_mode,
        args.lane_state_logging,
        args.campaign_state,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

