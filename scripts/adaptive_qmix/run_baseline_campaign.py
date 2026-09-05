"""Run the frozen baseline search as the coordinator intends it to be run.

The workflow is explicit, because each step has a different safety property
and doing them in one command would blur all three:

    prepare    generate and verify the preregistered seed manifests, once,
               before any worker exists
    run-shard  execute one shard against those manifests, read-only, writing
               its own ledger
    finalise   aggregate every shard ledger, check the work is covered exactly
               once, then derive the shortlist (or the selected plan) from the
               complete verified result set, and complete the global protocol
               stage when both tracks are done
    freeze     build campaign stage 3 from the two verified selected-plan
               artefacts
    status     report where the campaign has got to

A worker never finalises. Finalisation reads every shard's results, so a
worker that finalised would be ranking on the fraction of the campaign it
happened to run.

    python scripts/adaptive_qmix/run_baseline_campaign.py \
        --action prepare --stage offset_design \
        --campaign-root results/raw/campaign/offset
    ... --action run-shard --shard-index 0 --shard-count 2
    ... --action run-shard --shard-index 1 --shard-count 2
    ... --action finalise --shard-count 2

Nothing here can reach final_test, and no stage may start before its
predecessor's artefact exists and verifies.
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
    CAMPAIGN_STAGES, GLOBAL_STAGE_TRACKS, PRUNING_POLICY, StageSequenceError,
    aggregate_ledgers, assert_campaign_stage_allowed, candidates_for_stage,
    complete_global_stage, execute_campaign, finalise_stage,
    freeze_baseline_plans, global_stage_track_status, plan_campaign,
    prepare_seed_manifests,
)
from adaptive_qmix.baselines.runner import run_baseline  # noqa: E402
from adaptive_qmix.baselines.search import required_seeds  # noqa: E402
from adaptive_qmix.config import load_config  # noqa: E402


BASELINE_CONFIG = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)
QUALIFICATION_CONFIG = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
)

ACTIONS = ("prepare", "run-shard", "finalise", "freeze", "status")


class Layout(object):
    """Where a campaign keeps its parts, derived from one root."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.runs = os.path.join(self.root, "runs")
        self.manifests = os.path.join(self.root, "manifests")
        self.shortlists = os.path.join(self.root, "artefacts")
        self.state = os.path.join(self.root, "campaign_state")


def action_prepare(args, layout, config):
    spec = CAMPAIGN_STAGES[args.stage]
    assert_campaign_stage_allowed(
        args.stage, layout.shortlists, layout.state
    )
    manifests = prepare_seed_manifests(
        layout.manifests, config, spec["family"]
    )
    print("prepared {} manifests for {}".format(
        len(manifests), spec["family"]))
    for seed in sorted(manifests):
        entry = manifests[seed]
        print("  seed {}: sumo_seed {} route {}".format(
            seed, entry["sumo_seed"], entry["route_xml_sha256"][:16]))
    return 0


def action_run_shard(args, layout, config):
    spec = CAMPAIGN_STAGES[args.stage]
    assert_campaign_stage_allowed(
        args.stage, layout.shortlists, layout.state
    )
    plans, source = candidates_for_stage(args.stage, layout.shortlists)
    import traci

    ledger = execute_campaign(
        run_baseline, spec["controller"], plans, spec["family"], config,
        layout.runs, layout.manifests, REPOSITORY_ROOT,
        shard_index=args.shard_index, shard_count=args.shard_count,
        traci_module=traci, allow_manifest_generation=False,
    )
    counts = {}
    for entry in ledger:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    print("shard {} of {}: {} runs".format(
        args.shard_index, args.shard_count, len(ledger)))
    for status in sorted(counts):
        print("  {:26s}: {}".format(status, counts[status]))
    print("  from: {}".format(
        "frozen grid" if source is None
        else "verified shortlist of {}".format(source["stage"])))
    return 0 if not counts.get("FAILED") else 1


def action_finalise(args, layout, config):
    spec = CAMPAIGN_STAGES[args.stage]
    plans, _source = candidates_for_stage(args.stage, layout.shortlists)
    expected = []
    for index in range(max(1, args.shard_count)):
        expected.extend(plan_campaign(
            spec["controller"], plans, spec["family"],
            shard_index=index, shard_count=max(1, args.shard_count),
        ))
    if args.shard_count > 1:
        aggregate = aggregate_ledgers(layout.runs, expected_work=expected)
        print("aggregated {} shard ledgers, {} runs covered exactly "
              "once".format(len(aggregate["shard_ledgers"]),
                            len(aggregate["entries"])))

    result = finalise_stage(
        args.stage, layout.runs, layout.manifests, layout.shortlists,
        config, REPOSITORY_ROOT, state_directory=layout.state,
    )
    print("finalised {}: {} from {} candidates x {} seeds".format(
        args.stage, result["kind"], result["candidate_count"],
        len(required_seeds(spec["family"]))))
    print("  artefact: {}".format(result["artefact"]))
    if result["kind"] == "shortlist":
        print("  retained: {}".format(result["retained_keys"]))
    else:
        print("  selected: {}".format(result["selected_key"]))

    global_stage = spec["protocol_stage"]
    completion = complete_global_stage(
        global_stage, layout.shortlists, layout.state
    )
    if completion["written"]:
        print("  global stage {} complete: {}".format(
            global_stage, completion["artefact"]))
    else:
        print("  global stage {} still needs: {}".format(
            global_stage, completion["outstanding"]))
    return 0


def action_freeze(args, layout, config):
    adaptive = load_config(args.adaptive_config)
    result = freeze_baseline_plans(
        layout.shortlists, layout.state, config, REPOSITORY_ROOT, adaptive
    )
    payload = result["payload"]
    print("froze the baseline plans: {}".format(result["artefact"]))
    print("  adaptive config : {}".format(payload["adaptive_config_sha256"]))
    print("  baseline config : {}".format(payload["baseline_config_sha256"]))
    for track in ("optimized_fixed_offset", "optimized_fixed_timing"):
        print("  {:22s}: {}".format(track, payload[track]["selected_key"]))
    return 0


def action_status(args, layout, config):
    print("campaign root: {}".format(layout.root))
    for global_stage, tracks in sorted(GLOBAL_STAGE_TRACKS.items()):
        status = global_stage_track_status(global_stage, layout.shortlists)
        done = [stage for stage in tracks if status[stage]["complete"]]
        print("  {:22s}: {} of {} tracks complete".format(
            global_stage, len(done), len(tracks)))
        for stage in tracks:
            mark = "done" if status[stage]["complete"] else "pending"
            print("    {:24s} {}".format(stage, mark))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=ACTIONS)
    parser.add_argument("--stage", choices=sorted(CAMPAIGN_STAGES))
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--config", default=BASELINE_CONFIG)
    parser.add_argument("--adaptive-config", default=QUALIFICATION_CONFIG)
    args = parser.parse_args()

    if args.action in ("prepare", "run-shard", "finalise") and not args.stage:
        raise StageSequenceError(
            "--stage is required for the {} action.".format(args.action)
        )
    layout = Layout(args.campaign_root)
    config = load_config(args.config)
    if args.stage:
        print("stage {} ({}), pruning: {}".format(
            args.stage, CAMPAIGN_STAGES[args.stage]["family"],
            PRUNING_POLICY))
    sys.stdout.flush()

    handler = {
        "prepare": action_prepare,
        "run-shard": action_run_shard,
        "finalise": action_finalise,
        "freeze": action_freeze,
        "status": action_status,
    }[args.action]
    return handler(args, layout, config)


if __name__ == "__main__":
    sys.exit(main())
