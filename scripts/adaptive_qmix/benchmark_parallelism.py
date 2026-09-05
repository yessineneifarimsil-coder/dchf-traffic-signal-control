"""Measure whether two concurrent SUMO processes are actually worth running.

Engineering only. Four-way parallelism is not assumed: this runs the SAME
small development workload sequentially and with two workers, and reports what
was actually observed rather than a projection. On a contended or
memory-limited machine the answer may well be that two workers buy little, and
that is a useful answer.

Correctness is checked as well as speed. The two modes must produce identical
per-run identity and identical metrics; a speedup obtained by changing the
numbers is not a speedup. Any metric that differs is reported as a hard
failure, because the baselines are meant to be deterministic given family,
seed and index.

It never touches final_test and never runs a campaign: the workload is a short
list of development runs given on the command line.
"""

from __future__ import print_function

import argparse
import json
import multiprocessing
import os
import sys
import time


REPOSITORY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))

from adaptive_qmix.baselines.integrity import (  # noqa: E402
    assert_traffic_selection_allowed,
)
from adaptive_qmix.baselines.plans import simultaneous_plan  # noqa: E402
from adaptive_qmix.baselines.runner import (  # noqa: E402
    SIMULTANEOUS_FIXED_TIME, run_baseline,
)
from adaptive_qmix.config import load_config  # noqa: E402
from adaptive_qmix.traffic import (  # noqa: E402
    derive_sumo_seed, generate_manifest_records, write_manifest,
)


BASELINE_CONFIG = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "baselines_300m_medium.json"
)

# Metrics compared between modes. Wall-clock and paths legitimately differ.
COMPARED_FIELDS = (
    "clearance_status", "scheduled_count", "completed_count",
    "J_primary_mean_scheduled_waiting_burden_s", "J_primary_valid",
    "mean_completed_time_loss_s", "mean_completed_travel_time_s",
    "mean_completed_waiting_time_s", "manifest_csv_sha256",
    "route_xml_sha256", "sumo_seed", "controller_decision_count",
)


def resource_snapshot():
    """Peak RSS for this process and its children, where the platform says."""
    try:
        import resource
    except ImportError:
        return {"available": False, "reason": "resource module unavailable"}
    usage_self = resource.getrusage(resource.RUSAGE_SELF)
    usage_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    scale = 1024 if sys.platform.startswith("linux") else 1
    return {
        "available": True,
        "peak_rss_parent_bytes": int(usage_self.ru_maxrss) * scale,
        "peak_rss_children_bytes": int(usage_children.ru_maxrss) * scale,
        "cpu_user_s": usage_self.ru_utime + usage_children.ru_utime,
        "cpu_system_s": usage_self.ru_stime + usage_children.ru_stime,
    }


def _one_run(task):
    """Executed in a worker process, so it must be importable and picklable."""
    import traci

    config = load_config(task["config_path"])
    metrics = run_baseline(
        traci, config, REPOSITORY_ROOT, SIMULTANEOUS_FIXED_TIME,
        task["prefix"] + ".csv", task["prefix"] + ".rou.xml",
        task["family"], task["seed"], task["sumo_seed"],
        task["output_directory"], plan=simultaneous_plan(),
        manifest_index=0, manifest_prefix=task["prefix"],
    )
    return {
        "identity": {
            "family": task["family"], "seed": task["seed"],
            "sumo_seed": task["sumo_seed"],
        },
        "metrics": dict(
            (field, metrics.get(field)) for field in COMPARED_FIELDS
        ),
    }


def run_sequential(tasks):
    started = time.time()
    results = [_one_run(task) for task in tasks]
    return results, time.time() - started


def run_concurrent(tasks, workers):
    started = time.time()
    pool = multiprocessing.Pool(processes=workers)
    try:
        results = pool.map(_one_run, tasks)
    finally:
        pool.close()
        pool.join()
    return results, time.time() - started


def compare(sequential, concurrent):
    """Identity and metrics must be identical; only timing may differ."""
    differences = []
    if len(sequential) != len(concurrent):
        return ["run counts differ: {} versus {}".format(
            len(sequential), len(concurrent)
        )]
    for index, (left, right) in enumerate(zip(sequential, concurrent)):
        if left["identity"] != right["identity"]:
            differences.append(
                "run {}: identity differs {} versus {}".format(
                    index, left["identity"], right["identity"]
                )
            )
            continue
        for field in COMPARED_FIELDS:
            if left["metrics"][field] != right["metrics"][field]:
                differences.append(
                    "run {} ({}): {} differs, sequential={!r} "
                    "concurrent={!r}".format(
                        index, left["identity"], field,
                        left["metrics"][field], right["metrics"][field],
                    )
                )
    return differences


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--traffic-family", default="development")
    parser.add_argument("--seeds", type=int, nargs="+", default=[101, 102])
    parser.add_argument(
        "--workers", type=int, default=2,
        help="concurrent SUMO processes (default: %(default)s); 4-way is not "
             "assumed, so measure before relying on it")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--config", default=BASELINE_CONFIG)
    args = parser.parse_args()

    for seed in args.seeds:
        assert_traffic_selection_allowed(args.traffic_family, seed, 0)

    config = load_config(args.config)
    root = os.path.abspath(args.output_directory)
    manifest_root = os.path.join(root, "manifests")
    if not os.path.isdir(manifest_root):
        os.makedirs(manifest_root)

    tasks_sequential, tasks_concurrent = [], []
    for seed in args.seeds:
        prefix = os.path.join(
            manifest_root, "{}_seed{:04d}".format(args.traffic_family, seed)
        )
        if not os.path.isfile(prefix + ".metadata.json"):
            write_manifest(
                generate_manifest_records(
                    config, args.traffic_family, seed, 0
                ),
                config, prefix, args.traffic_family, seed, 0,
            )
        sumo_seed = derive_sumo_seed(args.traffic_family, seed, 0)
        for mode, tasks in (("sequential", tasks_sequential),
                            ("concurrent", tasks_concurrent)):
            tasks.append({
                "config_path": os.path.abspath(args.config),
                "prefix": prefix,
                "family": args.traffic_family,
                "seed": seed,
                "sumo_seed": sumo_seed,
                "output_directory": os.path.join(
                    root, mode, "seed{:04d}".format(seed)
                ),
            })

    print("parallelism feasibility: {} runs, {} workers".format(
        len(args.seeds), args.workers))
    sys.stdout.flush()

    before = resource_snapshot()
    sequential_results, sequential_s = run_sequential(tasks_sequential)
    print("  sequential : {:.1f} s".format(sequential_s))
    sys.stdout.flush()
    concurrent_results, concurrent_s = run_concurrent(
        tasks_concurrent, args.workers
    )
    print("  concurrent : {:.1f} s".format(concurrent_s))
    after = resource_snapshot()

    differences = compare(sequential_results, concurrent_results)
    report = {
        "runs": len(args.seeds),
        "workers": args.workers,
        "traffic_family": args.traffic_family,
        "seeds": list(args.seeds),
        "sequential_wall_s": sequential_s,
        "concurrent_wall_s": concurrent_s,
        "speedup": (
            sequential_s / concurrent_s if concurrent_s > 0 else float("nan")
        ),
        "parallel_efficiency": (
            (sequential_s / concurrent_s) / args.workers
            if concurrent_s > 0 and args.workers else float("nan")
        ),
        "resources_before": before,
        "resources_after": after,
        "per_run_identity": [
            result["identity"] for result in sequential_results
        ],
        "outputs_identical": not differences,
        "differences": differences,
        "note": (
            "Engineering measurement only. Four-way parallelism is not "
            "assumed and no campaign is launched here."
        ),
    }
    path = os.path.join(root, "parallelism_report.json")
    with open(path, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)

    print("  speedup    : {:.2f}x  (efficiency {:.0%})".format(
        report["speedup"], report["parallel_efficiency"]))
    print("  identical  : {}".format(report["outputs_identical"]))
    for difference in differences[:5]:
        print("    {}".format(difference))
    print("  report     : {}".format(path))
    return 0 if report["outputs_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
