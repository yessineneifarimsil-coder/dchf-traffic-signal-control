"""Analysis of the robustness validation, written and tested BEFORE any robustness run.

    python tools/robustness/robustness_analysis.py --root <robustness root> --out analysis/robustness

Applied once, after `robustness_runner.py progress` reports every cell finished. It reads only the files
the runner writes; it simulates nothing and modifies nothing under --root. Its SHA-256 is part of the
robustness plan fingerprint (robustness_runner.py), so it cannot change after the plan is approved.

Indicators (definitions of tools/ablation_metrics.py, unchanged, with N per manifest):
  N            the manifest's scheduled_total (metadata), cross-checked against evaluation_metrics.json
               (scheduled_count, N_scheduled) and the number of tripinfo rows. Never the constant 2,800.
  J            J_primary of evaluation_metrics.json, for cleared runs only, never imputed; recomputed from
               tripinfo.xml as sum(waitingTime + departDelay) / N, all N trips arrived (tolerance 1e-9).
  D, D_bar     waiting burden during the generation window [0, 3600) from reward_seconds.csv (vehicle-s),
               D_bar = D / N. Defined for every run, including failures.
  P            the same after 3600 s; censored at 7200 s for a failure.
  counter      service counter per direction, from service_counters.csv (logged every second for every
               controller); recomputed from the logged queue and executed phase with the protected rule and
               compared with the logged value; max counter, access to first green, wait still open at the end.
  greens       completed green spells during the demand (signal_phases.csv), censored final spell excluded.
  vehicles     per-vehicle maximum waitingTime and timeLoss, unfinished ids, vehicles waiting >= 120 / 300 s.
  shield       interventions by type during the demand (decision time < 3600) and after it
               (protection_decisions.csv; learned and P5 runs), SUMO signal mismatches (protection_record.json).

Technical criteria (plans/PLAN_ROBUSTESSE.md; all required, otherwise no scientific statement is printed):
  T1 every planned cell has a result, or is declared missing in --declared-missing (then listed, not imputed);
  T2 0 SUMO signal mismatches in learned and P5 runs;
  T3 max counter <= 127 s in every guarantee and both run (learned and P5), realised green >= 7 s in every
     both run;
  T4 checkpoint copies and manifests equal to the hashes recorded at preparation;
  T5 consistency: N, J against tripinfo, logged counters against their recomputation, one counter row per
     second and intersection, executor state equal to the logged phase.

Scientific questions (descriptive; no test, no ranking claim):
  S1 service: per scenario, failures (with the open counter wait at the end) in the guarantee and both runs.
  S2 latent defects: per method and scenario, `none` runs that fail or leave a vehicle waiting >= 300 s.
  S3 cost of the protections: paired differences against `none` on the same model and traffic: dJ (pairs where
     both clear, n given), dD_bar (all pairs), interventions during the demand. If the guarantee never acted
     during the demand of a scenario, its cost there is reported as NOT EVALUATED, not as zero.
  S4 fixed plans: per method, scenario and arm, model-level means of (learned J - fixed-plan J) on the same
     traffics, over traffics where both clear, with the number of models and traffics behind each value.
"""
from __future__ import print_function

import argparse
import csv
import hashlib
import json
import math
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ablation_metrics as am  # noqa: E402

GENERATION_END_S = am.GENERATION_END_S
COUNTER_BOUND_S = 127
MIN_GREEN_S = 7
LATENT_WAIT_S = 300
J_TOLERANCE = 1e-9
FIXED = {"old": "fixed:old_C19_8_5_D9", "min7": "fixed:min7_C25_12_7_D0"}
GUARANTEED = ("learned:guarantee", "learned:both", "p5:guarantee", "p5:both")
BOTH = ("learned:both", "p5:both")
SHIELDED = ("learned", "p5")
METHODS = ("qmix", "vdn", "idqn")
LEARNED_ARMS = ("none", "guarantee", "both")


class AnalysisError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def rj(path):
    with open(path) as handle:
        return json.load(handle)


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def method_of(model):
    return model.split("_", 1)[0]


# ---------------------------------------------------------------------------
# Per-cell indicators.
# ---------------------------------------------------------------------------

def trip_stats(path, n_expected):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    trips = [dict(re.findall(r'(\w+)="([^"]*)"', m)) for m in re.findall(r"<tripinfo ([^>]*)/>", text)]
    unfinished = [t["id"] for t in trips if float(t.get("arrival", -1)) < 0]
    waits = [float(t["waitingTime"]) for t in trips]
    j = None
    if len(trips) == n_expected and not unfinished:
        j = sum(float(t["waitingTime"]) + float(t["departDelay"]) for t in trips) / float(n_expected)
    worst = max(trips, key=lambda t: float(t["waitingTime"])) if trips else None
    return {"tripinfo_rows": len(trips), "unfinished_ids": unfinished,
            "J_from_tripinfo_s": j,
            "max_vehicle_waiting_s": max(waits) if waits else None,
            "max_waiting_vehicle": worst["id"] if worst else None,
            "vehicles_waiting_ge_120s": sum(w >= 120 for w in waits),
            "vehicles_waiting_ge_300s": sum(w >= LATENT_WAIT_S for w in waits),
            "max_vehicle_time_loss_s": max((float(t["timeLoss"]) for t in trips), default=None)}


def counter_indicators(counter_rows, phase_rows, end_time):
    """Service counters from the per-second counter log, re-derived with the ablation rule."""
    problems = []
    end = int(round(end_time))
    keys = sorted((int(round(float(r["time"]))), r["intersection"]) for r in counter_rows)
    expected = sorted((t, tl) for t in range(1, end + 1) for tl in ("J1", "J2"))
    if keys != expected:
        problems.append("service_counters.csv does not hold exactly one row per second and intersection "
                        "({} rows, {} expected)".format(len(keys), len(expected)))
    phase = dict(((int(round(float(r["time"]))), r["intersection"]), r["actual_phase"]) for r in phase_rows)
    lane_rows, logged = [], {}
    for r in counter_rows:
        t, tl = int(round(float(r["time"]))), r["intersection"]
        if phase.get((t, tl)) != r["executor_state"]:
            problems.append("t={} {}: counter log state {!r} differs from the logged phase {!r}".format(
                t, tl, r["executor_state"], phase.get((t, tl))))
        lane_rows.append({"time": t, "lane": am.H_IN[tl][0], "queue": int(r["q_H"])})
        lane_rows.append({"time": t, "lane": am.V_IN[tl][0], "queue": int(r["q_V"])})
        logged[(t, tl)] = (int(r["c_H"]), int(r["c_V"]))
    series, summary = am.counters_from_logs(lane_rows, phase_rows)
    differing = sum(1 for (t, tl), v in logged.items()
                    if t in series and (series[t][tl]["c_H"], series[t][tl]["c_V"]) != v)
    if differing:
        problems.append("{} counter rows differ from their recomputation".format(differing))
    open_waits = [summary[tl][d]["open_wait_at_end"] for tl in summary for d in ("H", "V")
                  if summary[tl][d]["open_wait_at_end"] is not None]
    return {"max_counter_s": max(max(v) for v in logged.values()) if logged else None,
            "max_counter_recomputed_s": max(summary[tl][d]["max_counter"] for tl in summary for d in ("H", "V")),
            "max_wait_to_first_green_s": max(summary[tl][d]["max_wait_to_first_green"]
                                             for tl in summary for d in ("H", "V")),
            "open_wait_at_end_s": max(open_waits) if open_waits else None,
            "counter_rows_differing": differing}, problems


def cell_metrics(cell, directory, n_manifest):
    problems = []
    m = rj(os.path.join(directory, "evaluation_metrics.json"))
    status = m.get("clearance_status")
    for field in ("scheduled_count", "N_scheduled"):
        if int(m.get(field, -1)) != n_manifest:
            problems.append("{} = {} but the manifest schedules {}".format(field, m.get(field), n_manifest))
    end = float(rows(os.path.join(directory, "episode_summary.csv"))[0]["end_time"])
    d_cost, p_cost = am.demand_and_post_cost(rows(os.path.join(directory, "reward_seconds.csv")), end)
    phase_rows = rows(os.path.join(directory, "signal_phases.csv"))
    spells = am.spell_stats(am.green_spells(phase_rows), demand_only=True)
    trips = trip_stats(os.path.join(directory, "tripinfo.xml"), n_manifest)
    if trips["tripinfo_rows"] != n_manifest:
        problems.append("tripinfo has {} rows for N = {}".format(trips["tripinfo_rows"], n_manifest))
    j = m.get("J_primary_mean_scheduled_waiting_burden_s") if m.get("J_primary_valid") else None
    if m.get("J_primary_valid"):
        if status != "CLEARED":
            problems.append("J declared valid for a {} run".format(status))
        if not finite(j):
            problems.append("J declared valid but not finite ({!r})".format(j))
        elif trips["J_from_tripinfo_s"] is None or abs(float(j) - trips["J_from_tripinfo_s"]) > J_TOLERANCE:
            problems.append("J {!r} differs from tripinfo ({!r}, N = {})".format(
                j, trips["J_from_tripinfo_s"], n_manifest))
    counters, counter_problems = counter_indicators(
        rows(os.path.join(directory, "service_counters.csv")), phase_rows, end)
    problems.extend(counter_problems)
    kind, _, arm = cell["controller"].partition(":")
    out = {"scenario": cell["scenario"], "seed": int(cell["seed"]), "controller": cell["controller"],
           "kind": kind, "arm": arm if kind in SHIELDED else "",
           "model": cell.get("model", ""), "method": method_of(cell["model"]) if cell.get("model") else kind,
           "N": n_manifest, "status": status, "end_time_s": end,
           "J_primary_s": float(j) if j is not None else None,
           "mean_completed_time_loss_s": m.get("mean_completed_time_loss_s"),
           "completed": m.get("completed_count"),
           "D_demand_veh_s": d_cost, "D_bar_s": d_cost / float(n_manifest), "P_post_veh_s": p_cost,
           "P_post_censored": status != "CLEARED"}
    out.update(spells)
    out.update(trips)
    out.update(counters)
    out.update({"interventions_guarantee_demand": None, "interventions_guarantee_after": None,
                "interventions_min_green_demand": None, "interventions_min_green_after": None,
                "sumo_mismatch_s": None})
    if kind in SHIELDED:
        decisions = rows(os.path.join(directory, "protection_decisions.csv"))
        for name in ("guarantee", "min_green"):
            during = [r for r in decisions if r["intervention"] == name
                      and float(r["decision_time"]) < GENERATION_END_S]
            after = [r for r in decisions if r["intervention"] == name
                     and float(r["decision_time"]) >= GENERATION_END_S]
            out["interventions_{}_demand".format(name)] = len(during)
            out["interventions_{}_after".format(name)] = len(after)
        record = rj(os.path.join(directory, "protection_record.json"))
        out["sumo_mismatch_s"] = int(record["sumo_index_mismatch_s"]) + int(record["sumo_state_mismatch_s"])
    return out, problems


# ---------------------------------------------------------------------------
# Summaries.
# ---------------------------------------------------------------------------

def describe(values):
    v = sorted(x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not v:
        return {"n": 0}

    def q(p):
        k = (len(v) - 1) * p
        lo = int(math.floor(k))
        hi = min(lo + 1, len(v) - 1)
        return v[lo] + (v[hi] - v[lo]) * (k - lo)
    return {"n": len(v), "mean": statistics.mean(v), "median": q(0.5), "q25": q(0.25), "q75": q(0.75),
            "min": v[0], "max": v[-1], "n_pos": sum(x > 0 for x in v), "n_neg": sum(x < 0 for x in v),
            "n_zero": sum(x == 0 for x in v)}


def technical_checks(cells, plan, missing, declared, cell_problems, hash_problems):
    checks = {}
    undeclared = sorted(set(missing) - set(declared))
    checks["T1_complete"] = {"ok": not undeclared, "missing_undeclared": undeclared,
                             "missing_declared": sorted(set(missing) & set(declared)),
                             "planned": len(plan["cells"]), "analysed": len(cells)}
    mism = [(c["scenario"], c["seed"], c["controller"], c["model"], c["sumo_mismatch_s"]) for c in cells
            if c["kind"] in SHIELDED and c["sumo_mismatch_s"] != 0]
    checks["T2_sumo_signals"] = {"ok": not mism, "runs_with_mismatch": mism}
    over = [(c["scenario"], c["seed"], c["controller"], c["model"], c["max_counter_s"]) for c in cells
            if c["controller"] in GUARANTEED and c["max_counter_s"] > COUNTER_BOUND_S]
    short = [(c["scenario"], c["seed"], c["controller"], c["model"], c["shortest_green_s"]) for c in cells
             if c["controller"] in BOTH and c["shortest_green_s"] is not None and c["shortest_green_s"] < MIN_GREEN_S]
    checks["T3_protection_contracts"] = {"ok": not over and not short, "counter_above_127": over,
                                         "green_below_7_in_both": short}
    checks["T4_hashes"] = {"ok": not hash_problems, "problems": hash_problems}
    checks["T5_consistency"] = {"ok": not cell_problems, "cells_with_problems": cell_problems}
    checks["all_ok"] = all(v["ok"] for k, v in checks.items() if k.startswith("T"))
    return checks


def s1_service(cells):
    out = {}
    for scenario in sorted({c["scenario"] for c in cells}):
        entry = {}
        for controller in GUARANTEED:
            runs = [c for c in cells if c["scenario"] == scenario and c["controller"] == controller]
            if not runs:
                continue
            failed = [{"seed": c["seed"], "model": c["model"], "unfinished_ids": c["unfinished_ids"],
                       "open_wait_at_end_s": c["open_wait_at_end_s"]} for c in runs if c["status"] != "CLEARED"]
            entry[controller] = {"runs": len(runs), "cleared": len(runs) - len(failed), "failures": failed,
                                 "failures_with_open_wait": sum(f["open_wait_at_end_s"] is not None for f in failed)}
        learned = [entry[k] for k in ("learned:guarantee", "learned:both") if k in entry]
        entry["S1_statement_allowed"] = bool(learned) and all(e["failures_with_open_wait"] == 0 for e in learned)
        out[scenario] = entry
    return out


def s2_latent(cells):
    out = []
    for scenario in sorted({c["scenario"] for c in cells}):
        for method in METHODS:
            runs = [c for c in cells if c["scenario"] == scenario and c["controller"] == "learned:none"
                    and c["method"] == method]
            if not runs:
                continue
            flagged = [c for c in runs if c["status"] != "CLEARED" or c["vehicles_waiting_ge_300s"] > 0]
            out.append({"scenario": scenario, "method": method, "runs": len(runs),
                        "failures": sum(c["status"] != "CLEARED" for c in runs),
                        "runs_with_vehicle_wait_ge_300s": sum(c["vehicles_waiting_ge_300s"] > 0 for c in runs),
                        "runs_flagged": len(flagged),
                        "flagged": ["{} {}".format(c["model"], c["seed"]) for c in flagged]})
    return out


def learned_pairs(cells):
    idx = dict(((c["scenario"], c["seed"], c["model"], c["arm"]), c) for c in cells if c["kind"] == "learned")
    pairs = []
    for (scenario, seed, model, arm), c in sorted(idx.items()):
        if arm == "none":
            continue
        base = idx.get((scenario, seed, model, "none"))
        if base is None:
            continue
        both_clear = c["J_primary_s"] is not None and base["J_primary_s"] is not None
        pairs.append({"scenario": scenario, "seed": seed, "model": model, "method": c["method"], "arm": arm,
                      "status_none": base["status"], "status_arm": c["status"],
                      "dJ_s": c["J_primary_s"] - base["J_primary_s"] if both_clear else None,
                      "dD_bar_s": c["D_bar_s"] - base["D_bar_s"],
                      "dTimeLoss_s": (c["mean_completed_time_loss_s"] - base["mean_completed_time_loss_s"]
                                      if both_clear else None),
                      "dMaxVehicleWait_s": c["max_vehicle_waiting_s"] - base["max_vehicle_waiting_s"],
                      "interventions_guarantee_demand": c["interventions_guarantee_demand"],
                      "interventions_min_green_demand": c["interventions_min_green_demand"]})
    return pairs


def s3_costs(pairs):
    out = []
    for scenario in sorted({p["scenario"] for p in pairs}):
        for method in METHODS:
            for arm in ("guarantee", "both"):
                ps = [p for p in pairs if p["scenario"] == scenario and p["method"] == method and p["arm"] == arm]
                if not ps:
                    continue
                g_demand = sum(p["interventions_guarantee_demand"] or 0 for p in ps)
                out.append({"scenario": scenario, "method": method, "arm": arm, "pairs": len(ps),
                            "J_comparable_pairs": sum(p["dJ_s"] is not None for p in ps),
                            "dJ_s": describe([p["dJ_s"] for p in ps]),
                            "dD_bar_s": describe([p["dD_bar_s"] for p in ps]),
                            "guarantee_interventions_demand": g_demand,
                            "pairs_with_guarantee_demand_intervention":
                                sum((p["interventions_guarantee_demand"] or 0) > 0 for p in ps),
                            "min_green_interventions_demand": sum(p["interventions_min_green_demand"] or 0 for p in ps),
                            "guarantee_cost_during_demand": ("EVALUATED" if g_demand > 0 else
                                                             "NOT EVALUATED (no intervention during the demand)")})
    return out


def s4_fixed(cells):
    fixed = dict(((c["scenario"], c["seed"], c["controller"]), c) for c in cells if c["kind"] == "fixed")
    out = []
    for scenario in sorted({c["scenario"] for c in cells}):
        for method in METHODS:
            for arm in LEARNED_ARMS:
                runs = [c for c in cells if c["scenario"] == scenario and c["kind"] == "learned"
                        and c["method"] == method and c["arm"] == arm]
                if not runs:
                    continue
                for plan_name, controller in sorted(FIXED.items()):
                    per_model = {}
                    excluded = 0
                    for c in runs:
                        f = fixed.get((scenario, c["seed"], controller))
                        if f is None or c["J_primary_s"] is None or f["J_primary_s"] is None:
                            excluded += 1
                            continue
                        per_model.setdefault(c["model"], []).append(c["J_primary_s"] - f["J_primary_s"])
                    means = [statistics.mean(v) for v in per_model.values()]
                    out.append({"scenario": scenario, "method": method, "arm": arm, "fixed_plan": plan_name,
                                "learned_runs": len(runs), "pairs_excluded_not_both_cleared": excluded,
                                "models_with_a_pair": len(per_model),
                                "models_all_traffics": sum(len(v) == len({c["seed"] for c in runs})
                                                           for v in per_model.values()),
                                "pairs_learned_J_lower": sum(x < 0 for v in per_model.values() for x in v),
                                "pairs": sum(len(v) for v in per_model.values()),
                                "model_mean_dJ_s": describe(means)})
    return out


def classical_summary(cells):
    out = []
    for scenario in sorted({c["scenario"] for c in cells}):
        for controller in sorted({c["controller"] for c in cells if c["kind"] not in ("learned",)}):
            runs = [c for c in cells if c["scenario"] == scenario and c["controller"] == controller]
            js = [c["J_primary_s"] for c in runs if c["J_primary_s"] is not None]
            out.append({"scenario": scenario, "controller": controller, "runs": len(runs),
                        "cleared": sum(c["status"] == "CLEARED" for c in runs),
                        "J_mean_over_cleared": statistics.mean(js) if js else None, "J_n": len(js),
                        "D_bar_mean": statistics.mean(c["D_bar_s"] for c in runs),
                        "max_counter_s": max(c["max_counter_s"] for c in runs),
                        "max_vehicle_waiting_s": max(c["max_vehicle_waiting_s"] for c in runs)})
    return out


# ---------------------------------------------------------------------------
# Hashes recorded at preparation.
# ---------------------------------------------------------------------------

def hash_problems(plan, root):
    problems = []
    for m in plan.get("models", []):
        path = os.path.join(root, "checkpoints", m["tag"] + ".pth")
        if not os.path.isfile(path) or sha256_file(path) != m["sha256"]:
            problems.append("checkpoint {} absent or changed".format(m["tag"]))
    recorded_path = os.path.join(root, "manifests_sha256.json")
    if not os.path.isfile(recorded_path):
        problems.append("manifests_sha256.json absent: the manifests were not hashed at preparation")
        return problems
    recorded = rj(recorded_path)
    for name, digest in sorted(recorded.items()):
        path = os.path.join(root, "manifests", name)
        if not os.path.isfile(path) or sha256_file(path) != digest:
            problems.append("manifest {} absent or changed".format(name))
    return problems


def manifest_n(root, scenario, seed, cache):
    key = (scenario, int(seed))
    if key not in cache:
        meta = rj(os.path.join(root, "manifests", "{}_{}.metadata.json".format(scenario, seed)))
        if meta.get("scenario") != scenario or int(meta.get("seed_value", -1)) != int(seed):
            raise AnalysisError("manifest metadata of {} {} names {} {}".format(
                scenario, seed, meta.get("scenario"), meta.get("seed_value")))
        cache[key] = int(meta["scheduled_total"])
    return cache[key]


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------

def fmt(x, digits=3):
    if x is None:
        return "-"
    if isinstance(x, float):
        return "{:.{}f}".format(x, digits)
    return str(x)


def write_report(path, plan, checks, s1, s2, s3, s4, classical):
    lines = ["# Robustness validation: analysis (applied once)", "",
             "Plan fingerprint: `{}`".format(plan.get("fingerprint")), "",
             "## Technical criteria", ""]
    for key in sorted(k for k in checks if k.startswith("T")):
        lines.append("- {}: {}".format(key, "OK" if checks[key]["ok"] else "FAILED"))
    if not checks["all_ok"]:
        lines += ["", "**Technical criteria failed: no scientific statement is made.** The tables below are "
                      "kept for diagnosis only.", ""]
    lines += ["", "## Classical and diagnostic controllers (J over cleared runs; n shown)", "",
              "| Scenario | Controller | Cleared | J mean (n) | D_bar mean | Max counter | Max vehicle wait |",
              "|---|---|---|---|---|---|---|"]
    for r in classical:
        lines.append("| {} | {} | {}/{} | {} ({}) | {} | {} | {} |".format(
            r["scenario"], r["controller"], r["cleared"], r["runs"], fmt(r["J_mean_over_cleared"]), r["J_n"],
            fmt(r["D_bar_mean"]), r["max_counter_s"], fmt(r["max_vehicle_waiting_s"], 0)))
    lines += ["", "## S1 Service under the guarantee", ""]
    for scenario, entry in sorted(s1.items()):
        parts = ["{} {}/{}".format(k, v["cleared"], v["runs"]) for k, v in sorted(entry.items())
                 if isinstance(v, dict)]
        verdict = ("no indefinite denial of service in the learned guarantee and both runs of this scenario"
                   if entry["S1_statement_allowed"] and checks["all_ok"] else
                   "statement NOT allowed: failures listed in s1_service.json" if checks["all_ok"] else
                   "not interpretable (technical criteria failed)")
        lines.append("- {}: {}; {}".format(scenario, "; ".join(parts), verdict))
    lines += ["", "## S2 Latent defects without protection", "",
              "| Scenario | Method | Runs | Failures | Runs with a vehicle waiting >= 300 s |", "|---|---|---|---|---|"]
    for r in s2:
        lines.append("| {} | {} | {} | {} | {} |".format(r["scenario"], r["method"], r["runs"], r["failures"],
                                                         r["runs_with_vehicle_wait_ge_300s"]))
    lines += ["", "## S3 Paired cost of the protections (same model and traffic)", "",
              "| Scenario | Method | Arm | Pairs | dJ median [min, max] (n comparable) | dD_bar median [min, max] | "
              "Guarantee interventions during demand | Cost of the guarantee during demand |",
              "|---|---|---|---|---|---|---|---|"]
    for r in s3:
        dj, dd = r["dJ_s"], r["dD_bar_s"]
        lines.append("| {} | {} | {} | {} | {} [{}, {}] ({}) | {} [{}, {}] | {} | {} |".format(
            r["scenario"], r["method"], r["arm"], r["pairs"], fmt(dj.get("median")), fmt(dj.get("min")),
            fmt(dj.get("max")), r["J_comparable_pairs"], fmt(dd.get("median")), fmt(dd.get("min")),
            fmt(dd.get("max")), r["guarantee_interventions_demand"], r["guarantee_cost_during_demand"]))
    lines += ["", "## S4 Learned minus fixed plan, model-level means (pairs where both clear)", "",
              "| Scenario | Method | Arm | Fixed plan | Models (all 5 traffics) | Pairs (excluded) | "
              "Pairs with learned J lower | Model mean dJ median [min, max] |", "|---|---|---|---|---|---|---|---|"]
    for r in s4:
        d = r["model_mean_dJ_s"]
        lines.append("| {} | {} | {} | {} | {} ({}) | {} ({}) | {} | {} [{}, {}] |".format(
            r["scenario"], r["method"], r["arm"], r["fixed_plan"], r["models_with_a_pair"],
            r["models_all_traffics"], r["pairs"], r["pairs_excluded_not_both_cleared"],
            r["pairs_learned_J_lower"], fmt(d.get("median")), fmt(d.get("min")), fmt(d.get("max"))))
    lines += ["", "Descriptive only: five traffics per scenario, checkpoints selected earlier, no retraining, "
                  "no hypothesis test, no ranking claim. Failures are never given a J."]
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")


def write_csv(path, records):
    keys = []
    for r in records:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for r in records:
            writer.writerow(dict((k, json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()))


def analyse(root, out, declared_missing=()):
    plan = rj(os.path.join(root, "plan.json"))
    if plan.get("analysis_sha256") not in (None, sha256_file(os.path.abspath(__file__))):
        raise AnalysisError("this analysis script differs from the one fixed in the plan")
    if plan.get("analysis_sha256") is None:
        raise AnalysisError("the plan does not record the analysis script; it was prepared without it")
    if os.path.exists(os.path.join(out, "summary.json")):
        raise AnalysisError("analysis already written (applied once): {}".format(out))
    cells, missing, problems, cache = [], [], [], {}
    for cell in plan["cells"]:
        directory = os.path.join(root, cell["directory"])
        if not os.path.isfile(os.path.join(directory, "evaluation_metrics.json")):
            missing.append(cell["directory"])
            continue
        n = manifest_n(root, cell["scenario"], cell["seed"], cache)
        record, cell_problems = cell_metrics(cell, directory, n)
        cells.append(record)
        if cell_problems:
            problems.append({"cell": cell["directory"], "problems": cell_problems})
    undeclared = sorted(set(missing) - set(declared_missing))
    if undeclared:
        raise AnalysisError("{} cells have no result and are not declared missing, e.g. {}".format(
            len(undeclared), undeclared[:3]))
    checks = technical_checks(cells, plan, missing, declared_missing, problems, hash_problems(plan, root))
    pairs = learned_pairs(cells)
    s1, s2, s3, s4 = s1_service(cells), s2_latent(cells), s3_costs(pairs), s4_fixed(cells)
    classical = classical_summary(cells)
    if not os.path.isdir(out):
        os.makedirs(out)
    write_csv(os.path.join(out, "cells.csv"), cells)
    write_csv(os.path.join(out, "pairs.csv"), pairs)
    for name, payload in (("technical_checks.json", checks), ("s1_service.json", s1), ("s2_latent.json", s2),
                          ("s3_costs.json", s3), ("s4_fixed_plans.json", s4), ("classical.json", classical)):
        with open(os.path.join(out, name), "w") as handle:
            json.dump(payload, handle, indent=1, default=str)
    write_report(os.path.join(out, "REPORT.md"), plan, checks, s1, s2, s3, s4, classical)
    summary = {"plan_fingerprint": plan.get("fingerprint"), "cells_planned": len(plan["cells"]),
               "cells_analysed": len(cells), "cells_missing_declared": sorted(missing),
               "technical_all_ok": checks["all_ok"],
               "analysis_sha256": sha256_file(os.path.abspath(__file__))}
    with open(os.path.join(out, "summary.json"), "w") as handle:
        json.dump(summary, handle, indent=1)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--declared-missing", help="text file, one cell directory per line, declared "
                                                   "technically missing after the runner's single retry")
    args = parser.parse_args(argv)
    declared = []
    if args.declared_missing:
        with open(args.declared_missing) as handle:
            declared = [line.strip() for line in handle if line.strip()]
    try:
        summary = analyse(args.root, args.out, declared)
    except AnalysisError as error:
        print("STOP:", error)
        return 1
    print(json.dumps(summary, indent=1))
    return 0 if summary["technical_all_ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
