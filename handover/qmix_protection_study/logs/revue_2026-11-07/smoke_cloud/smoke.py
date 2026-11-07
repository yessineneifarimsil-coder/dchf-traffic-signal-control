"""Local engineering smoke of the comparator evaluator (cloud, frozen code, stub for the absent protected
package so that the N adapter installs). Not results: design seeds only, outputs not interpreted."""
import json, os, sys, time, types
S = os.environ["SCRATCH"]
os.environ["QMIX_PROTECTED_ROOT"] = os.path.join(S, "frozen")
for name in ("adaptive_qmix_protected", "adaptive_qmix_protected.evaluation"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, os.path.join(S, "work", "tools", "comparators"))
sys.path.insert(0, os.path.join(S, "work", "tools", "robustness"))
import evaluate_comparator as ec
import scenario_traffic as st
from adaptive_qmix.config import load_config
config = load_config(os.path.join(S, "frozen", "config", "adaptive_qmix", "qualification_300m_medium.json"))
root = os.path.join(S, "cmp_smoke", "root")
spec = st.load_spec()
jobs = json.loads(sys.argv[1])
out = []
for scenario, seed, cspec, mode in jobs:
    prefix = os.path.join(root, "manifests", "{}_{}".format(scenario, seed))
    if not os.path.exists(prefix + ".metadata.json"):
        os.makedirs(os.path.dirname(prefix), exist_ok=True)
        st.write(spec, scenario, seed, st.generate(spec, scenario, seed), prefix, config["demand"]["vehicle_type"])
    d = os.path.join(root, "runs", scenario, str(seed), ec.label(cspec).replace(":", "__").replace("|", "+"), mode)
    m = ec.evaluate(cspec, prefix, d, counters=False, compact=(mode == "compact"))
    size = sum(os.path.getsize(os.path.join(a, f)) for a, _d, fs in os.walk(d) for f in fs)
    r = {"scenario": scenario, "seed": seed, "controller": m["controller"], "mode": mode,
         "status": m["clearance_status"], "J": m["J_primary_mean_scheduled_waiting_burden_s"],
         "N": m["N_scheduled"], "switch_events": m["executor_switch_events"], "wall_s": round(m["wall_s"], 1),
         "bytes": size}
    print(json.dumps(r), flush=True)
    out.append(r)
