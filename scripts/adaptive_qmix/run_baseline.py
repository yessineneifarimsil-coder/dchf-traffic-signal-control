"""Run one classical or pressure baseline episode on an explicit manifest.

The controller is the only thing that varies. Network, demand, seeds, logging,
instrumentation and metrics are the adaptive framework's own.

    python scripts/adaptive_qmix/run_baseline.py \
        --controller simultaneous_fixed_time \
        --traffic-family development --traffic-seed 101 \
        --output-directory results/raw/baselines/simultaneous

A held-out final_test manifest cannot be generated from here: the family is
refused before anything is written.
"""

from __future__ import print_function

import argparse
import json
import os
import sys


REPOSITORY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.baselines.plans import (  # noqa: E402
    fixed_offset_plan, make_plan, simultaneous_plan,
)
from adaptive_qmix.baselines.runner import (  # noqa: E402
    BASELINE_CONTROLLERS, OPTIMIZED_FIXED_OFFSET, OPTIMIZED_FIXED_TIMING,
    PRETIMED_CONTROLLERS, SIMULTANEOUS_FIXED_TIME, run_baseline,
)
from adaptive_qmix.baselines.search import FINAL_FAMILY, LeakageError  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.logging import LANE_LOG_FULL  # noqa: E402
from adaptive_qmix.traci_access import DEFAULT_MODE, MODES  # noqa: E402
from adaptive_qmix.traffic import (  # noqa: E402
    derive_sumo_seed, generate_manifest_records, write_manifest,
)


BASELINE_CONFIG = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)
QUALIFICATION_CONFIG = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
)


def resolve_plan(args):
    if args.controller == SIMULTANEOUS_FIXED_TIME:
        return simultaneous_plan()
    if args.controller == OPTIMIZED_FIXED_OFFSET:
        if args.offset is None:
            raise SystemExit("--offset is required for optimized_fixed_offset.")
        return fixed_offset_plan(args.offset)
    if args.controller == OPTIMIZED_FIXED_TIMING:
        missing = [
            name for name, value in (
                ("--cycle", args.cycle), ("--split", args.split),
                ("--offset", args.offset),
            ) if value is None
        ]
        if missing:
            raise SystemExit(
                "optimized_fixed_timing needs {}.".format(", ".join(missing))
            )
        return make_plan(args.cycle, args.split, args.offset)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller", required=True,
                        choices=BASELINE_CONTROLLERS)
    parser.add_argument("--traffic-family", default="development")
    parser.add_argument("--traffic-seed", type=int, required=True)
    parser.add_argument("--manifest-index", type=int, default=0)
    parser.add_argument("--manifest-prefix", default=None,
                        help="reuse an existing manifest instead of writing one")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--cycle", type=int, default=None)
    parser.add_argument("--split", type=int, default=None,
                        help="H green share in thousandths, e.g. 500 for 0.50")
    parser.add_argument("--offset", type=int, default=None)
    parser.add_argument("--config", default=BASELINE_CONFIG)
    parser.add_argument("--traci-access-mode", default=DEFAULT_MODE,
                        choices=sorted(MODES))
    parser.add_argument("--run-kind", default="development_baseline")
    args = parser.parse_args()

    if args.traffic_family == FINAL_FAMILY:
        raise LeakageError(
            "final_test is held out. It may not be generated or opened until "
            "every baseline plan is frozen and an official run is authorised."
        )

    import traci

    config = load_config(args.config)
    plan = resolve_plan(args)
    output_directory = os.path.abspath(args.output_directory)
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)

    if args.manifest_prefix:
        prefix = os.path.abspath(args.manifest_prefix)
        with open(prefix + ".metadata.json") as handle:
            metadata = json.load(handle)
    else:
        records = generate_manifest_records(
            config, args.traffic_family, args.traffic_seed, args.manifest_index
        )
        prefix = os.path.join(output_directory, "manifest")
        metadata = write_manifest(
            records, config, prefix, args.traffic_family, args.traffic_seed,
            args.manifest_index,
        )
    sumo_seed = int(metadata.get(
        "sumo_seed",
        derive_sumo_seed(
            args.traffic_family, args.traffic_seed, args.manifest_index
        ),
    ))

    print("baseline run")
    print("  controller     : {}".format(args.controller))
    print("  plan           : {}".format(plan))
    print("  traffic family : {} seed {} index {}".format(
        args.traffic_family, args.traffic_seed, args.manifest_index))
    print("  SUMO seed      : {}".format(sumo_seed))
    print("  manifest sha256: {}".format(metadata["csv_sha256"]))
    sys.stdout.flush()

    metrics = run_baseline(
        traci, config, REPOSITORY_ROOT, args.controller,
        prefix + ".csv", prefix + ".rou.xml", args.traffic_family,
        args.traffic_seed, sumo_seed, output_directory, plan=plan,
        run_kind=args.run_kind, traci_access_mode=args.traci_access_mode,
        lane_state_logging=LANE_LOG_FULL,
        qualification_config_path=QUALIFICATION_CONFIG,
    )
    print("")
    print("  status         : {}".format(metrics["clearance_status"]))
    print("  scheduled      : {}".format(metrics["scheduled_count"]))
    print("  completed      : {}".format(metrics["completed_count"]))
    print("  J_primary      : {}".format(
        metrics["J_primary_mean_scheduled_waiting_burden_s"]))
    print("  decisions      : {}".format(metrics["controller_decision_count"]))
    return 0 if metrics["clearance_status"] == "CLEARED" else 1


if __name__ == "__main__":
    sys.exit(main())
