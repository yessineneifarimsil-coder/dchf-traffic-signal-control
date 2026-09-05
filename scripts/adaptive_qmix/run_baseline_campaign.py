"""Execute one shard of one frozen baseline search stage. Resumable, no pruning.

The search design was frozen in adaptive_qmix.baselines.search; this executes
it in the order the campaign stage graph fixes:

    offset_design         -> shortlist of 10 -> offset_validation
    timing_coarse_design  -> shortlist of  5 -> timing_fine_design (DESIGN)
    timing_fine_design    -> shortlist of 10 -> timing_validation

A stage never takes candidates from the command line. A design stage generates
them from the frozen grids; a later stage reads the hash-sealed shortlist
artefact its predecessor produced, and refuses one that is absent, edited or
the wrong size. There is deliberately no --shortlist option: a validation run
that could be pointed at a hand-written list would not be evidence that the
ten candidates were the ten design chose.

    python scripts/adaptive_qmix/run_baseline_campaign.py \
        --stage offset_design --output-root results/raw/campaign/offset \
        --campaign-state results/campaign_state --shard-count 4 --shard-index 0

Re-running the same command resumes: only runs whose completion marker,
manifest hashes and metrics all verify are skipped.
"""

from __future__ import print_function

import argparse
import os
import sys


REPOSITORY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.baselines.campaign import (  # noqa: E402
    CAMPAIGN_STAGES, PRUNING_POLICY, StageSequenceError,
    assert_campaign_stage_allowed, candidates_for_stage, execute_campaign,
    plan_campaign,
)
from adaptive_qmix.baselines.runner import run_baseline  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402


BASELINE_CONFIG = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True,
                        choices=sorted(CAMPAIGN_STAGES))
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--manifest-root", default=None)
    parser.add_argument(
        "--shortlist-directory", default=None,
        help="where stage shortlist artefacts live (default: alongside the "
             "campaign state)")
    parser.add_argument(
        "--campaign-state", default=None,
        help="campaign state directory; required unless --dry-run, so the "
             "protocol stage guard is consulted before anything executes")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--config", default=BASELINE_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = CAMPAIGN_STAGES[args.stage]
    output_root = os.path.abspath(args.output_root)
    shortlist_directory = os.path.abspath(
        args.shortlist_directory
        or (args.campaign_state or os.path.join(output_root, "shortlists"))
    )
    if not args.dry_run and not args.campaign_state:
        raise StageSequenceError(
            "--campaign-state is required: a real campaign stage must pass "
            "the protocol stage guard before it creates anything."
        )
    state_directory = (
        os.path.abspath(args.campaign_state) if args.campaign_state else None
    )

    # Refuses before any directory is created: a missing or tampered
    # predecessor artefact, or an out-of-order protocol stage, stops here.
    assert_campaign_stage_allowed(
        args.stage, shortlist_directory,
        None if args.dry_run else state_directory,
    )
    plans, source = candidates_for_stage(args.stage, shortlist_directory)

    work = plan_campaign(
        spec["controller"], plans, spec["family"],
        shard_index=args.shard_index, shard_count=args.shard_count,
    )
    print("baseline campaign stage {}".format(args.stage))
    print("  controller : {}".format(spec["controller"]))
    print("  family     : {}".format(spec["family"]))
    print("  candidates : {} ({})".format(len(plans), spec["candidates"]))
    print("  from       : {}".format(
        "frozen grid" if source is None
        else "verified shortlist of {}".format(source["stage"])))
    print("  shard      : {} of {} -> {} runs".format(
        args.shard_index, args.shard_count, len(work)))
    print("  retains    : {}".format(spec["retain"] or "nothing; it selects"))
    print("  pruning    : {}".format(PRUNING_POLICY))
    sys.stdout.flush()

    if args.dry_run:
        for item in work[:5]:
            print("    {} seed {}".format(item["key"], item["seed"]))
        if len(work) > 5:
            print("    ... {} more".format(len(work) - 5))
        return 0

    import traci

    config = load_config(args.config)
    manifest_root = os.path.abspath(
        args.manifest_root or os.path.join(output_root, "manifests")
    )
    ledger = execute_campaign(
        run_baseline, spec["controller"], plans, spec["family"], config,
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
