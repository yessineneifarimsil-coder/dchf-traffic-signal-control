"""Cloud engineering diagnostic (design seed R0 8011, frozen MP unchanged): at every MP decision, record the
incoming and outgoing vehicle counts of both phases. The executor's decisions are not altered."""
import json, os, sys, types, statistics
S = os.environ["SCRATCH"]
os.environ["QMIX_PROTECTED_ROOT"] = os.path.join(S, "frozen")
for name in ("adaptive_qmix_protected", "adaptive_qmix_protected.evaluation"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, os.path.join(S, "work", "tools", "comparators"))
import evaluate_comparator as ec
from adaptive_qmix.baselines import executors as EX, pressure as PR
records = []
original = EX.CanonicalMaxPressureExecutor._decide
def recording(self, tl, t, served):
    row = {"t": t, "tl": tl, "current": self.current_phase[tl], "served": served}
    for m in ("H", "V"):
        pairs = PR.FROZEN_MOVEMENT_PAIRS[tl][m]
        row[m + "_in"] = sum(int(self.source.lane_vehicle_number(a)) for a, _b in pairs)
        row[m + "_out"] = sum(int(self.source.lane_vehicle_number(b)) for _a, b in pairs)
        row[m + "_in_halting"] = sum(int(self.source.lane_halting_number(a)) for a, _b in pairs)
    out = original(self, tl, t, served)
    row["switch"] = out[0] == "Y"
    records.append(row)
    return out
EX.CanonicalMaxPressureExecutor._decide = recording
prefix = os.path.join(S, "cmp_smoke", "root", "manifests", "R0_reference_8011")
d = os.path.join(S, "cmp_smoke", "root", "diag", "mp_decompose_R0_8011")
m = ec.evaluate({"kind": "canonical_mp"}, prefix, d, compact=True)
dem = [r for r in records if r["t"] < 3600]
def mean(k, rows): return round(statistics.mean(r[k] for r in rows), 2)
out = {"J": m["J_primary_mean_scheduled_waiting_burden_s"], "decisions_in_demand": len(dem)}
for tl in ("J1", "J2"):
    for phase in ("H", "V"):
        rows = [r for r in dem if r["tl"] == tl and r["current"] == phase]
        sw = [r for r in rows if r["switch"]]
        other = "V" if phase == "H" else "H"
        out["{} green {}".format(tl, phase)] = {
            "decisions": len(rows), "switch_share": round(len(sw) / float(len(rows)), 3),
            "at_switch_mean": {k: mean(k, sw) for k in (phase + "_in", phase + "_out", phase + "_in_halting",
                                                       other + "_in", other + "_out", other + "_in_halting")}}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(S, "work", "logs", "revue_2026-11-07", "mp_pressure_decomposition_R0_8011_cloud.json"), "w"), indent=1)
