"""One full-clearance evaluation of a NEW classical comparator on a robustness-format manifest.

Same stack and sequence as the non-learned branch of tools/robustness/evaluate_any.py (which is imported,
never modified: its hash is part of the robustness plan): frozen BaselineEnvironment, frozen RunLogger, frozen
scheduled_demand_metrics through the N adapter (J denominator = manifest total), full clearance up to the
frozen cut-off. Only the executor differs. Specs (JSON objects):

  {"kind": "fixed", "plan": {cycle_s, split_thousandths, f_H, green_H_s, green_V_s, yellow_s, offset_s}}
  {"kind": "tod", "periods": [[0, plan], [900, plan], [2700, plan]]}          (R3 plans by period)
  {"kind": "actuated", "params": {"gap_s": 3, "max_green_H_s": 45, "max_green_V_s": 25, "zone_m": 40}}
  {"kind": "canonical_mp"}                                                      (frozen, for A4 checks)

counters=True uses evaluate_any.counted_baseline_class (per-second service counters; needs QMIX_PROTECTED) and
is required for every evaluation that enters a comparison table (robustness or confirmation). Search stages
use counters=False and compact=True: the run is written in a scratch directory and only
evaluation_metrics.json (written last: completion marker), run_manifest.json, episode_summary.csv and
tripinfo.xml.gz are kept. The identity (scenario, traffic seed, controller label, spec SHA-256) is stamped in
evaluation_metrics.json and checked by comparator_search.py before a run is counted.
"""
from __future__ import absolute_import, print_function

import gzip
import hashlib
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "robustness"))
import evaluate_any as ea  # noqa: E402  (sets sys.path to QMIX_PROTECTED/src)

KEPT_COMPACT = ("run_manifest.json", "episode_summary.csv")


def spec_sha256(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def label(spec):
    kind = spec["kind"]
    if kind == "fixed":
        p = spec["plan"]
        return "fixed:C{}_{}_{}_D{}".format(p["cycle_s"], p["green_H_s"], p["green_V_s"], p["offset_s"])
    if kind == "tod":
        return "tod:" + "|".join("{}@C{}_{}_{}_D{}".format(s, p["cycle_s"], p["green_H_s"], p["green_V_s"],
                                                          p["offset_s"]) for s, p in spec["periods"])
    if kind == "actuated":
        q = spec["params"]
        return "actuated:gap{}_H{}_V{}_z{}".format(q["gap_s"], q["max_green_H_s"], q["max_green_V_s"],
                                                   int(q["zone_m"]))
    if kind == "canonical_mp":
        return "canonical_mp"
    raise ValueError("unknown comparator kind {!r}".format(kind))


def executor_factory(spec):
    from adaptive_qmix.baselines.executors import PretimedScheduleExecutor, CanonicalMaxPressureExecutor
    import controllers as C
    kind = spec["kind"]
    if kind == "fixed":
        plan = dict(spec["plan"])
        return lambda tr, cf, e: PretimedScheduleExecutor(tr, cf, plan=plan)
    if kind == "tod":
        periods = [(int(s), dict(p)) for s, p in spec["periods"]]
        return lambda tr, cf, e: C.TimeOfDayScheduleExecutor(tr, cf, periods=periods)
    if kind == "actuated":
        params = dict(spec["params"])
        return lambda tr, cf, e: C.ActuatedGapOutExecutor(tr, cf, data_source=e.source, **params)
    if kind == "canonical_mp":
        return lambda tr, cf, e: CanonicalMaxPressureExecutor(tr, cf, data_source=e.source)
    raise ValueError("unknown comparator kind {!r}".format(kind))


def evaluate(spec, prefix, out_dir, counters=False, compact=True, traci_module=None):
    import traci
    from adaptive_qmix.config import load_config
    import n_adapter
    n_adapter.install()
    import adaptive_qmix.metrics as M
    from adaptive_qmix.logging import RunLogger
    from adaptive_qmix.metrics import parse_tripinfo
    from adaptive_qmix.baselines.runner import BaselineEnvironment
    traci = traci_module or traci
    if os.path.exists(os.path.join(out_dir, "evaluation_metrics.json")):
        raise FileExistsError("{} already evaluated".format(out_dir))
    config = load_config(os.path.join(ea.PROTECTED, ea.CONFIG_REL))
    with open(prefix + ".metadata.json") as f:
        meta = json.load(f)
    sumo_seed, traffic_seed = int(meta["sumo_seed"]), int(meta["seed_value"])
    work = out_dir + ".tmp" if compact else out_dir
    if compact and os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work, exist_ok=True)
    t0 = time.time()
    tripinfo = os.path.join(work, "tripinfo.xml")
    controller = label(spec)
    run_manifest, _ = ea._manifest(prefix, controller, {"comparator_spec": spec, "comparator_spec_sha256":
                                                        spec_sha256(spec)})
    status, last_info = None, None
    with RunLogger(work, run_manifest) as logger:
        kwargs = dict(logger=logger, lane_state_logging=ea.LANE_LOGGING, executor_factory=executor_factory(spec))
        if counters:
            env = ea.counted_baseline_class()(traci, config, ea.PROTECTED, prefix + ".csv", prefix + ".rou.xml",
                                              tripinfo, sumo_seed, counter_csv=os.path.join(work, "service_counters.csv"),
                                              **kwargs)
        else:
            env = BaselineEnvironment(traci, config, ea.PROTECTED, prefix + ".csv", prefix + ".rou.xml", tripinfo,
                                      sumo_seed, **kwargs)
        try:
            env.reset(episode_index=0)
            while status is None:
                _l, _s, _r, terminated, info = env.step(None)
                last_info = info
                status = "CLEARED" if terminated else ("CLEARANCE_FAILURE" if info["timeout_truncated"] else None)
            summary = ea._finish(env, logger, status, last_info, work, {})
            ledger = env.ledger
            events = list(getattr(env.executor, "events", []))
        finally:
            env.close()
    metrics = M.scheduled_demand_metrics(ledger, parse_tripinfo(tripinfo), status)
    metrics["J_legacy_time_averaged_aggregate_waiting_state"] = summary["legacy_waiting_state_time_average"]
    switches = [e for e in events if e.get("decision") == "SWITCH" or "to_actual_phase" in e or "to_plan" in e]
    metrics.update({"clearance_status": status, "controller": controller, "comparator_spec": spec,
                    "comparator_spec_sha256": spec_sha256(spec), "traffic_seed": traffic_seed,
                    "sumo_seed": sumo_seed, "scenario": meta["scenario"], "N_scheduled": int(meta["scheduled_total"]),
                    "executor_switch_events": len(switches), "service_counters_logged": bool(counters),
                    "wall_s": time.time() - t0, "output_mode": "compact" if compact else "full"})
    if compact:
        os.makedirs(out_dir, exist_ok=True)
        for name in KEPT_COMPACT:
            shutil.copyfile(os.path.join(work, name), os.path.join(out_dir, name))
        with open(tripinfo, "rb") as src, gzip.open(os.path.join(out_dir, "tripinfo.xml.gz"), "wb") as dst:
            shutil.copyfileobj(src, dst)
    with open(os.path.join(out_dir, "evaluation_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, sort_keys=True, default=str)
    if compact:
        shutil.rmtree(work)
    return metrics


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spec", required=True, help="JSON spec or @file.json")
    ap.add_argument("--manifest-prefix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--counters", action="store_true")
    ap.add_argument("--full", action="store_true", help="keep every log (no compact mode)")
    a = ap.parse_args(argv)
    spec = json.load(open(a.spec[1:])) if a.spec.startswith("@") else json.loads(a.spec)
    m = evaluate(spec, a.manifest_prefix, a.out, counters=a.counters, compact=not a.full)
    print(json.dumps({k: m[k] for k in ("controller", "scenario", "traffic_seed", "clearance_status",
                                        "J_primary_mean_scheduled_waiting_burden_s", "wall_s")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
