"""Check the numerical statements of the manuscript and ablation report."""
import csv, sys, statistics as st
D = sys.argv[1]
cells = list(csv.DictReader(open(D + "/analysis/ablation/cells.csv")))
pairs = list(csv.DictReader(open(D + "/analysis/ablation/pairs.csv")))
by = {(r["model"], r["traffic_seed"], r["arm"]): r for r in cells}
f = lambda v: None if v in ("", None) else float(v)
for m in ("qmix", "vdn", "idqn"):
    for a in ("guarantee", "min_green", "both"):
        ps = [p for p in pairs if p["method"] == m and p["arm"] == a]
        dj = [f(p["dJ_s"]) for p in ps if f(p["dJ_s"]) is not None]
        dd = [int(p["dD_veh_s"]) for p in ps]
        dtl = [f(p["dTimeLoss_s"]) for p in ps if f(p["dTimeLoss_s"]) is not None]
        print("{:5} {:10} dJ n={} zero={} pos={} min={:+.3f} med={:+.3f} max={:+.3f} | dD pos={} neg={} zero={} med={} min={} max={} | dTL n={} pos={} neg={}".format(
            m, a, len(dj), sum(x == 0 for x in dj), sum(x > 0 for x in dj), min(dj), st.median(dj), max(dj),
            sum(x > 0 for x in dd), sum(x < 0 for x in dd), sum(x == 0 for x in dd), st.median(dd), min(dd), max(dd),
            len(dtl), sum(x > 0 for x in dtl), sum(x < 0 for x in dtl)))
# interaction on J per block (all four cleared)
for m in ("qmix", "vdn", "idqn"):
    vals = []
    for (mo, t, a), r in by.items():
        if a != "none" or r["method"] != m: continue
        q = [by[(mo, t, x)] for x in ("none", "guarantee", "min_green", "both")]
        if all(c["status"] == "CLEARED" for c in q):
            j = [f(c["J_primary_s"]) for c in q]
            vals.append((j[3] - j[2]) - (j[1] - j[0]))
    print(m, "interaction J blocks", len(vals), "zero", sum(abs(v) < 1e-12 for v in vals), "max|.|", round(max(abs(v) for v in vals), 4))
# time loss table (none arm, over completed vehicles, per run then mean)
for m in ("qmix", "vdn", "idqn"):
    rs = [r for r in cells if r["method"] == m and r["arm"] == "none"]
    print(m, "none: mean time loss over all 50 runs", round(st.mean(f(r["mean_completed_time_loss_s"]) for r in rs), 3),
          "over cleared", round(st.mean(f(r["mean_completed_time_loss_s"]) for r in rs if r["status"] == "CLEARED"), 3))
r = by[("qmix_seed101_t350000", "9305", "none")]
print("failed qmix run: time loss", r["mean_completed_time_loss_s"], "max wait", r["max_vehicle_waiting_s"])
# guarantee interventions: per method in guarantee-only arm
for a in ("guarantee", "both"):
    print(a, {m: sum(int(r["interventions_guarantee"]) for r in cells if r["method"] == m and r["arm"] == a) for m in ("qmix", "vdn", "idqn")})
# median overrides per run qmix min_green
print("qmix min_green median overrides", st.median(int(r["interventions_min_green"]) for r in cells if r["method"] == "qmix" and r["arm"] == "min_green"))
print("share 2s greens none arm qmix/vdn", [round(st.mean(f(r["share_2s_greens"]) for r in cells if r["method"] == m and r["arm"] == "none"), 3) for m in ("qmix", "vdn")],
      "range", [ (round(min(f(r["share_2s_greens"]) for r in cells if r["method"] == m and r["arm"] == "none"),3), round(max(f(r["share_2s_greens"]) for r in cells if r["method"] == m and r["arm"] == "none"),3)) for m in ("qmix","vdn")])
