"""One full-clearance evaluation of any robustness controller on a robustness manifest.

Controllers (all on the frozen environment, network, observation, reward and logging of QMIX_PROTECTED):
  fixed:<name>         pretimed plan (frozen PretimedScheduleExecutor), e.g. the old plan C19 8/5 D9 and the
                       min-7 plan C25 12/7 D0;
  canonical_mp         frozen canonical max pressure (1 s clock, minimum green 10 s);
  p5:<arm>             frozen matched-interval pressure policy (5 s clock, 3 s yellow + 2 s green: the learned
                       methods' action domain) with the protection shield of arm <arm> (none|guarantee|min_green|both);
  learned:<arm>        a checkpoint under the frozen protected evaluator, arm <arm>.
Manifests with N != 2800 go through tools/robustness/n_adapter.py (J denominator = N).
"""
import json
import os
import sys
import time

PROTECTED = os.environ.get("QMIX_PROTECTED_ROOT", r"C:\Users\LENOVO\QMIX_PROTECTED")
sys.path.insert(0, os.path.join(PROTECTED, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIG_REL = os.path.join("config", "adaptive_qmix", "qualification_300m_medium.json")
PLANS = {"old_C19_8_5_D9": {"cycle_s": 19, "split_thousandths": 577, "f_H": 0.577, "green_H_s": 8, "green_V_s": 5,
                            "yellow_s": 3, "offset_s": 9},
         "min7_C25_12_7_D0": {"cycle_s": 25, "split_thousandths": 606, "f_H": 0.606, "green_H_s": 12, "green_V_s": 7,
                              "yellow_s": 3, "offset_s": 0}}


LANE_LOGGING = "decision"   # per-second lane states are not needed: service counters are logged per second


def counted_baseline_class():
    """BaselineEnvironment plus the protected service counters and green-spell tracker, updated every second
    from the executed phase exactly as in ProtectedEnvironment (no shield, no change to the controller)."""
    from adaptive_qmix.baselines.runner import BaselineEnvironment
    from adaptive_qmix_protected.environment import COUNTER_FIELDS
    from adaptive_qmix_protected.protection import CsvOut, GreenSpellTracker, ServiceCounters

    class CountedBaselineEnvironment(BaselineEnvironment):
        def __init__(self, *args, **kwargs):
            self.counter_csv = kwargs.pop("counter_csv")
            super(CountedBaselineEnvironment, self).__init__(*args, **kwargs)
            self.counter_out = CsvOut(self.counter_csv, COUNTER_FIELDS)

        def reset(self, episode_index=0):
            out = super(CountedBaselineEnvironment, self).reset(episode_index)
            self.counters = ServiceCounters(self.config, self.source)
            self.spells = GreenSpellTracker(self.config["network"]["traffic_lights"])
            return out

        def _after_second(self, second_offset, phase_states, actual_green_elapsed):
            result = super(CountedBaselineEnvironment, self)._after_second(second_offset, phase_states,
                                                                           actual_green_elapsed)
            t = int(round(result["time"]))
            self.counters.update(phase_states, t)
            self.spells.update(phase_states)
            for tl in self.counters.tls:
                self.counter_out.write({"episode_index": self.episode_index, "time": t, "intersection": tl,
                                        "executor_state": phase_states[tl], "q_H": self.counters.queues[tl]["H"],
                                        "q_V": self.counters.queues[tl]["V"], "c_H": self.counters.counter[tl]["H"],
                                        "c_V": self.counters.counter[tl]["V"],
                                        "wait_start_H": self.counters.wait_start[tl]["H"],
                                        "wait_start_V": self.counters.wait_start[tl]["V"]})
            return result

        def close(self):
            try:
                self.counter_out.close()
            finally:
                super(CountedBaselineEnvironment, self).close()
    return CountedBaselineEnvironment


def _manifest(prefix, controller, extra):
    with open(prefix + ".metadata.json") as f:
        meta = json.load(f)
    m = {"study": "robustness_validation", "controller": controller, "manifest_metadata": meta,
         "protected_root": PROTECTED, "python": sys.executable}
    m.update(extra)
    return m, meta


def _finish(env, logger, status, last_info, out_dir, extra_metrics):
    from adaptive_qmix.metrics import parse_tripinfo
    import adaptive_qmix.metrics as M
    summary = env.episode_summary(status, timeout_truncated=last_info["timeout_truncated"])
    logger.write("episode_summary", summary)
    if status == "CLEARANCE_FAILURE":
        logger.write_clearance_failure(env.complete_residual_state())
    logger.flush()
    return summary


def evaluate(controller, prefix, out_dir, checkpoint=None, traci_module=None):
    import traci
    from adaptive_qmix.config import load_config
    import n_adapter
    n_adapter.install()
    import adaptive_qmix.metrics as M
    from adaptive_qmix.logging import LANE_LOG_FULL, RunLogger
    from adaptive_qmix.metrics import parse_tripinfo
    from adaptive_qmix.baselines.runner import BaselineEnvironment, MatchedIntervalPressurePolicy
    from adaptive_qmix.baselines.executors import PretimedScheduleExecutor, CanonicalMaxPressureExecutor
    from adaptive_qmix_protected.environment import ProtectedEnvironment, ProtectionLogs
    from adaptive_qmix_protected.evaluation import evaluate_protected
    from adaptive_qmix_protected.protection import ProtectionSpec, frozen_signal_programs
    traci = traci_module or traci
    config = load_config(os.path.join(PROTECTED, CONFIG_REL))
    kind, _, param = controller.partition(":")
    if os.path.exists(os.path.join(out_dir, "evaluation_metrics.json")):
        raise FileExistsError("{} already evaluated".format(out_dir))
    with open(prefix + ".metadata.json") as f:
        meta = json.load(f)
    sumo_seed, traffic_seed = int(meta["sumo_seed"]), int(meta["seed_value"])
    csv_path, rou_path = prefix + ".csv", prefix + ".rou.xml"
    t0 = time.time()
    if kind == "learned":
        metrics, record = evaluate_protected(traci, config, PROTECTED, checkpoint, csv_path, rou_path, traffic_seed,
                                             sumo_seed, out_dir, ProtectionSpec(param), run_kind="development_evaluation",
                                             lane_state_logging=LANE_LOGGING)
        metrics["controller"] = controller
    else:
        os.makedirs(out_dir, exist_ok=True)
        tripinfo = os.path.join(out_dir, "tripinfo.xml")
        run_manifest, _ = _manifest(prefix, controller, {"plan": PLANS.get(param)})
        status, last_info, record = None, None, None
        with RunLogger(out_dir, run_manifest) as logger:
            if kind == "p5":
                spec = ProtectionSpec(param)
                logs = ProtectionLogs(out_dir, per_second=True)
                env = ProtectedEnvironment(traci, config, PROTECTED, csv_path, rou_path, tripinfo, sumo_seed, spec,
                                           frozen_signal_programs(PROTECTED, config), protection_logs=logs,
                                           logger=logger, lane_state_logging=LANE_LOGGING)
            else:
                if kind == "fixed":
                    plan = PLANS[param]
                    factory = lambda tr, cf, e: PretimedScheduleExecutor(tr, cf, plan=plan)  # noqa: E731
                elif kind == "canonical_mp":
                    factory = lambda tr, cf, e: CanonicalMaxPressureExecutor(tr, cf, data_source=e.source)  # noqa: E731
                else:
                    raise ValueError(controller)
                env = counted_baseline_class()(traci, config, PROTECTED, csv_path, rou_path, tripinfo, sumo_seed,
                                               logger=logger, lane_state_logging=LANE_LOGGING, executor_factory=factory,
                                               counter_csv=os.path.join(out_dir, "service_counters.csv"))
            try:
                env.reset(episode_index=0)
                policy = MatchedIntervalPressurePolicy(config, env.source) if kind == "p5" else None
                k = 0
                while status is None:
                    if policy is not None:
                        proposed = policy.decide(env.time, env.executor.current_phase, env.executor.green_elapsed)
                        details = [{"explore": False, "q_extend": None, "q_switch": None}] * 2
                        _l, _s, _r, terminated, info = env.step(proposed, decision_details=details)
                        for i, tl in enumerate(("J1", "J2")):
                            logger.write("signal_actions", {
                                "episode_index": 0, "decision_time": info["start_time"], "decision_index": k,
                                "intersection": tl, "action": "EXTEND" if info["executed_actions"][i] == 0 else "SWITCH",
                                "epsilon": 0.0, "explore": False, "elapsed_seconds": info["elapsed_seconds"],
                                "terminated": terminated, "budget_truncated": False,
                                "timeout_truncated": info["timeout_truncated"]})
                    else:
                        _l, _s, _r, terminated, info = env.step(None)
                    k += 1
                    last_info = info
                    status = "CLEARED" if terminated else ("CLEARANCE_FAILURE" if info["timeout_truncated"] else None)
                summary = _finish(env, logger, status, last_info, out_dir, {})
                if kind == "p5":
                    record = env.finish_episode()
                ledger = env.ledger
            finally:
                env.close()
                if kind == "p5":
                    logs.close()
        metrics = M.scheduled_demand_metrics(ledger, parse_tripinfo(tripinfo), status)
        metrics["J_legacy_time_averaged_aggregate_waiting_state"] = summary["legacy_waiting_state_time_average"]
        metrics.update({"clearance_status": status, "controller": controller, "traffic_seed": traffic_seed,
                        "sumo_seed": sumo_seed, "method": controller})
        if record is not None:
            rec = dict(record)
            rec.update({"status": status, "protection": ProtectionSpec(param).to_dict()})
            with open(os.path.join(out_dir, "protection_record.json"), "w") as f:
                json.dump(rec, f, indent=2, sort_keys=True)
    metrics["scenario"] = meta["scenario"]
    metrics["N_scheduled"] = int(meta["scheduled_total"])
    metrics["wall_s"] = time.time() - t0
    with open(os.path.join(out_dir, "evaluation_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, sort_keys=True, default=str)
    return metrics
