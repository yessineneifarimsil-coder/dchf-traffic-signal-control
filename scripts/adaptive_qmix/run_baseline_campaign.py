"""Execute one shard of the frozen baseline search. Resumable, never pruning.

The search design was frozen in adaptive_qmix.baselines.search; this only
runs it. Re-running the same command resumes: runs whose completion marker,
manifest hashes and metrics all verify are skipped, and everything else is
redone.

    python scripts/adaptive_qmix/run_baseline_campaign.py \
        --controller optimized_fixed_offset --stage design \
        --output-root results/raw/campaign/offset_design \
        --shard-index 0 --shard-count 4 --dry-run

--dry-run prints the deterministic work list without executing anything, which
is how a shard split should be inspected before a long campaign starts.
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

from adaptive_qmix.baselines.campaign import (  # noqa: E402
    PRUNING_POLICY, execute_campaign, plan_campaign,
)
from adaptive_qmix.baselines.plans import (  # noqa: E402
    coarse_timing_candidates, fixed_offset_candidates,
)
from adaptive_qmix.baselines.runner import (  # noqa: E402
    OPTIMIZED_FIXED_OFFSET, OPTIMIZED_FIXED_TIMING, run_baseline,
)
from adaptive_qmix.baselines.search import (  # noqa: E402
    DESIGN_FAMILY, VALIDATION_FAMILY,
)
from adaptive_qmix.config import load_config  # noqa: E402


BASELINE_CONFIG = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)

STAGE_FAMILY = {"design": DESIGN_FAMILY, "validation": VALIDATION_FAMILY}


def candidates_for(controller, shortlist_path):
    if shortlist_path:
        # A validation stage runs only the shortlist the design stage retained.
        with open(shortlist_path, "r") as handle:
            return json.load(handle)["plans"]
    if controller == OPTIMIZED_FIXED_OFFSET:
        return fixed_offset_candidates()
    return coarse_timing_candidates()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller", required=True,
                        choices=(OPTIMIZED_FIXED_OFFSET,
                                 OPTIMIZED_FIXED_TIMING))
    parser.add_argument("--stage", required=True, choices=sorted(STAGE_FAMILY))
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--manifest-root", default=None)
    parser.add_argument("--shortlist", default=None,
                        help="JSON {'plans': [...]} for a validation stage")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--config", default=BASELINE_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    family = STAGE_FAMILY[args.stage]
    config = load_config(args.config)
    plans = candidates_for(args.controller, args.shortlist)
    output_root = os.path.abspath(args.output_root)
    manifest_root = os.path.abspath(
        args.manifest_root or os.path.join(output_root, "manifests")
    )

    work = plan_campaign(
        args.controller, plans, family,
        shard_index=args.shard_index, shard_count=args.shard_count,
    )
    print("baseline campaign shard {} of {}".format(
        args.shard_index, args.shard_count))
    print("  controller : {}".format(args.controller))
    print("  stage      : {} ({})".format(args.stage, family))
    print("  candidates : {}".format(len(plans)))
    print("  runs       : {}".format(len(work)))
    print("  pruning    : {}".format(PRUNING_POLICY))
    sys.stdout.flush()

    if args.dry_run:
        for item in work[:5]:
            print("    {} seed {}".format(item["key"], item["seed"]))
        if len(work) > 5:
            print("    ... {} more".format(len(work) - 5))
        return 0

    import traci

    ledger = execute_campaign(
        run_baseline, args.controller, plans, family, config,
        output_root, manifest_root, REPOSITORY_ROOT,
        shard_index=args.shard_index, shard_count=args.shard_count,
        traci_module=traci,
    )
    counts = {}
    for entry in ledger:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    print("")
    for status in sorted(counts):
        print("  {:26s}: {}".format(status, counts[status]))
    return 0 if not counts.get("FAILED") else 1


if __name__ == "__main__":
    sys.exit(main())
