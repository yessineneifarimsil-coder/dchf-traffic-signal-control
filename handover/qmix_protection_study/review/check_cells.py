"""Independent recomputation of the ablation claims from cells.csv / pairs.csv."""
import csv, json, sys, collections, math
D = sys.argv[1]
cells = list(csv.DictReader(open(D + "/analysis/ablation/cells.csv")))
pairs = list(csv.DictReader(open(D + "/analysis/ablation/pairs.csv")))
f = lambda v: float(v) if v not in ("", None) else None
key = lambda r: (r["model"], r["traffic_seed"], r["arm"])
print("cells", len(cells), "unique", len(set(map(key, cells))))
models = collections.defaultdict(set)
for r in cells: models[r["method"]].add(r["model"])
print({m: len(v) for m, v in models.items()})
arms = sorted(set(r["arm"] for r in cells)); traffics = sorted(set(r["traffic_seed"] for r in cells))
print("arms", arms, "traffics", traffics)
grid = set((m, t, a) for ms in models.values() for m in ms for t in traffics for a in arms)
print("complete grid:", grid == set(map(key, cells)))
print("reused:", collections.Counter((r["method"], r["arm"]) for r in cells if r["reused"] == "True"))
# failures and J never imputed
fails = [r for r in cells if r["status"] != "CLEARED"]
print("failures", len(fails), [(r["model"], r["traffic_seed"], r["arm"], r["status"], r["J_primary_s"], r["unfinished_ids"]) for r in fails])
print("cleared with empty J:", sum(1 for r in cells if r["status"] == "CLEARED" and f(r["J_primary_s"]) is None))
# per method/arm table
for m in ("qmix", "vdn", "idqn"):
    for a in ("none", "guarantee", "min_green", "both"):
        rs = [r for r in cells if r["method"] == m and r["arm"] == a]
        js = [f(r["J_primary_s"]) for r in rs if r["status"] == "CLEARED"]
        print("{:5} {:10} cleared {}/{} Jmean {:.3f} (n={}) Dbar {:.3f} guar {} ({}) ming {} ({}) maxcounter {} maxwait {}".format(
            m, a, len(js), len(rs), sum(js) / len(js), len(js), sum(f(r["D_bar_s"]) for r in rs) / len(rs),
            sum(int(r["interventions_guarantee"]) for r in rs), sum(int(r["interventions_guarantee_demand"]) for r in rs),
            sum(int(r["interventions_min_green"]) for r in rs), sum(int(r["interventions_min_green_demand"]) for r in rs),
            max(int(r["max_counter_s"]) for r in rs), max(f(r["max_vehicle_waiting_s"]) for r in rs)))
# guarantee arms
g = [r for r in cells if r["arm"] in ("guarantee", "both")]
print("guarantee arms: interventions during demand", sum(int(r["interventions_guarantee_demand"]) for r in g),
      "| evaluations with >=1 intervention", sum(int(r["interventions_guarantee"]) > 0 for r in g),
      "| max per evaluation", max(int(r["interventions_guarantee"]) for r in g),
      "| max counter", max(int(r["max_counter_s"]) for r in g),
      "| max first-green", max(int(r["max_wait_to_first_green_s"]) for r in g),
      "| evals with vehicle wait >127", sum(f(r["max_vehicle_waiting_s"]) > 127 for r in g),
      "max", max(f(r["max_vehicle_waiting_s"]) for r in g))
ming = [r for r in cells if r["arm"] in ("min_green", "both")]
print("min-green arms: shortest green", min(int(r["shortest_green_s"]) for r in ming), "greens<7", sum(int(r["greens_below_7s"]) for r in ming),
      "sumo mismatch", sum(int(r["sumo_mismatch_s"] or 0) for r in cells if r["sumo_mismatch_s"] != ""),
      "cells w/o sumo check", sum(r["sumo_mismatch_s"] == "" for r in cells))
# pairs: same model and traffic; recompute dJ / dD
by = {key(r): r for r in cells}
bad = 0; comparable = collections.Counter(); dDzero = collections.Counter()
for p in pairs:
    a = by[(p["model"], p["traffic_seed"], p["arm"])]; n = by[(p["model"], p["traffic_seed"], "none")]
    dD = int(a["D_demand_veh_s"]) - int(n["D_demand_veh_s"])
    if dD != int(p["dD_veh_s"]): bad += 1
    both = a["status"] == "CLEARED" and n["status"] == "CLEARED"
    if both:
        comparable[(p["method"], p["arm"])] += 1
        if abs(f(a["J_primary_s"]) - f(n["J_primary_s"]) - f(p["dJ_s"])) > 1e-9: bad += 1
    elif p["dJ_s"] not in ("", None): bad += 1
    if dD == 0: dDzero[(p["method"], p["arm"])] += 1
print("pairs", len(pairs), "inconsistent", bad)
print("comparable J pairs", dict(comparable))
print("dD == 0", dict(dDzero))
