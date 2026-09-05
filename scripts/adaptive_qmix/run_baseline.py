"""Run one classical or pressure baseline episode on an explicit manifest.

The controller is the only thing that varies. Network, demand, seeds, logging,
instrumentation and metrics are the adaptive framework's own.

    python scripts/adaptive_qmix/run_baseline.py \
        --controller simultaneous_fixed_time \
        --traffic-family development --traffic-seed 101 \
        --output-directory results/raw/baselines/simultaneous

A held-out final_test manifest cannot be generated from here, and neither can
a final-test seed borrowed under another family's label: both are refused by
adaptive_qmix.baselines.integrity before any directory or manifest exists. A
supplied --manifest-prefix is believed only after its own metadata agrees with
the request and its CSV and route XML hash to what that metadata records.
"""

from __future__ import print_function

import argparse
import os
import sys


REPOSITORY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.baselines.plans import (  # noqa: E402
    MIN_GREEN_S, candidate_is_valid, fixed_offset_plan, make_plan,
    simultaneous_plan,
)
from adaptive_qmix.baselines.runner import (  # noqa: E402
    BASELINE_CONTROLLERS, BaselineError, OPTIMIZED_FIXED_OFFSET,
    OPTIMIZED_FIXED_TIMING, SIMULTANEOUS_FIXED_TIME, run_baseline,
)
from adaptive_qmix.baselines.integrity import (  # noqa: E402
    assert_manifest_files_match,
    assert_traffic_selection_allowed,
    verify_manifest_for_run,
)
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
        plan = make_plan(args.cycle, args.split, args.offset)
        if not candidate_is_valid(plan):
            # Checked here as well as in run_baseline, so a refused plan never
            # gets as far as creating an output directory.
            raise BaselineError(
                "optimized_fixed_timing refuses a plan with a green below "
                "{} s: g_H = {}, g_V = {}, C = {}. This admissibility rule is "
                "classical only and is never applied to QMIX or P-5.".format(
                    MIN_GREEN_S, plan["green_H_s"], plan["green_V_s"],
                    plan["cycle_s"],
                )
            )
        return plan
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

    # Before anything is created, written or opened. A refused run must leave
    # no output directory and no manifest behind.
    assert_traffic_selection_allowed(
        args.traffic_family, args.traffic_seed, args.manifest_index
    )
    plan = resolve_plan(args)

    if args.manifest_prefix:
        # An existing manifest is trusted only after its own metadata agrees
        # with this request and its files hash to what that metadata records.
        prefix = os.path.abspath(args.manifest_prefix)
        metadata, verified = verify_manifest_for_run(
            prefix, args.traffic_family, args.traffic_seed,
            args.manifest_index,
            sumo_seed=derive_sumo_seed(
                args.traffic_family, args.traffic_seed, args.manifest_index
            ),
        )
    else:
        prefix = None

    import traci

    config = load_config(args.config)
    output_directory = os.path.abspath(args.output_directory)
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)

    if prefix is None:
        records = generate_manifest_records(
            config, args.traffic_family, args.traffic_seed, args.manifest_index
        )
        prefix = os.path.join(output_directory, "manifest")
        metadata = write_manifest(
            records, config, prefix, args.traffic_family, args.traffic_seed,
            args.manifest_index,
        )
        # A freshly written manifest is verified too: the hashes must describe
        # the files that were just produced, including the route XML.
        verified = assert_manifest_files_match(prefix, metadata)
    # The seed the selection derives, which the guard has already proved equal
    # to the manifest's own. The runner verifies it again independently.
    sumo_seed = derive_sumo_seed(
        args.traffic_family, args.traffic_seed, args.manifest_index
    )

    print("baseline run")
    print("  controller     : {}".format(args.controller))
    print("  plan           : {}".format(plan))
    print("  traffic family : {} seed {} index {}".format(
        args.traffic_family, args.traffic_seed, args.manifest_index))
    print("  SUMO seed      : {}".format(sumo_seed))
    print("  manifest sha256: {}".format(verified["csv_sha256"]))
    print("  route sha256   : {}".format(verified["route_xml_sha256"]))
    sys.stdout.flush()

    metrics = run_baseline(
        traci, config, REPOSITORY_ROOT, args.controller,
        prefix + ".csv", prefix + ".rou.xml", args.traffic_family,
        args.traffic_seed, sumo_seed, output_directory, plan=plan,
        run_kind=args.run_kind, traci_access_mode=args.traci_access_mode,
        lane_state_logging=LANE_LOG_FULL,
        qualification_config_path=QUALIFICATION_CONFIG,
        manifest_index=args.manifest_index, manifest_prefix=prefix,
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
