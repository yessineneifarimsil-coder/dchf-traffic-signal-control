"""Learned evaluations vs the two fixed plans on the same traffic; failures kept apart."""
import csv, sys
D = sys.argv[1]
cells = list(csv.DictReader(open(D + "/analysis/ablation/cells.csv")))
fixed = {}
for r in csv.DictReader(open(D + "/figures/data/fig1_same_traffic_performance.csv")):
    if r["model"] in ("C19_gH8_gV5_D9", "C25_gH12_gV7_D0"):
        fixed[(r["model"], r["traffic_seed"])] = float(r["J_primary_s"])
print("fixed plan means", {m: round(sum(v for (k, t), v in fixed.items() if k == m) / 5, 3) for m in ("C19_gH8_gV5_D9", "C25_gH12_gV7_D0")})
for label, arms in (("contraintes (vert min, les deux)", ("min_green", "both")), ("tous bras", ("none", "guarantee", "min_green", "both"))):
    rs = [r for r in cells if r["arm"] in arms]
    for plan in ("C25_gH12_gV7_D0", "C19_gH8_gV5_D9"):
        valid = [r for r in rs if r["status"] == "CLEARED"]
        better = [r for r in valid if float(r["J_primary_s"]) < fixed[(plan, r["traffic_seed"])]]
        print("{:34} vs {:16}: evaluations {} | evacuees {} | echecs {} | J inferieur au plan fixe {}".format(
            label, plan, len(rs), len(valid), len(rs) - len(valid), len(better)))
