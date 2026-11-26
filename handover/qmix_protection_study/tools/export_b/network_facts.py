"""network_facts.json: the SUMO network of B and the detection zones of the actuated comparators, read-only.

    python tools/export_b/network_facts.py --root <BCONF> --out <EXPORT> [--config <json>] [--net <net.xml>]

Sources (read in the code):
- the configuration: <QMIX_PROTECTED_ROOT>/config/adaptive_qmix/qualification_300m_medium.json
  (evaluate_any.PROTECTED + evaluate_any.CONFIG_REL), the one every B cell loads;
- the network: its "network"."path", relative to the same repository root (adaptive_qmix.environment.build_sumo_command:
  "-n", os.path.join(repository_root, config["network"]["path"]));
- speeds, lengths, lanes: the <edge>/<lane> elements of that .net.xml (speed in m/s, length in m);
- approach lanes of J1 and J2: config "observation"."lanes" (H_in, V_in), as the controllers read them;
- detection of the actuated comparators: tools/comparators/controllers.py ActuatedGapOutExecutor (lines 10-12 and
  87-93): a virtual presence detector over the last zone_m metres before the stop line of every incoming lane of the
  green phase (vehicle lane position >= lane length - zone_m), with the lane lengths of
  config "observation"."expected_lane_lengths_m"; zone_m of each actuated comparator of B from <BCONF>/plan.json.
No induction loop or lane-area detector exists in the network for these comparators (counted below).
"""
from __future__ import absolute_import, division, print_function

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for p in (HERE, os.path.join(TOOLS, "robustness")):
    if p not in sys.path:
        sys.path.insert(0, p)

import common as C  # noqa: E402


def lanes_of(net_path):
    root = ET.parse(net_path).getroot()
    edges, internal, tls, junctions, detectors = {}, {}, [], {}, 0
    for e in root.iter("edge"):
        lanes = [{"id": l.get("id"), "index": int(l.get("index")), "speed_m_s": float(l.get("speed")),
                  "length_m": float(l.get("length"))} for l in e.iter("lane")]
        rec = {"id": e.get("id"), "from": e.get("from"), "to": e.get("to"), "function": e.get("function") or "normal",
               "number_of_lanes": len(lanes), "lanes": lanes}
        (internal if e.get("function") == "internal" else edges)[e.get("id")] = rec
    for j in root.iter("junction"):
        if j.get("type") != "internal":
            junctions[j.get("id")] = {"type": j.get("type"), "x": float(j.get("x")), "y": float(j.get("y")),
                                      "incoming_lanes": (j.get("incLanes") or "").split()}
    for t in root.iter("tlLogic"):
        tls.append({"id": t.get("id"), "type": t.get("type"), "programID": t.get("programID"),
                    "phases": [{"duration": p.get("duration"), "state": p.get("state")} for p in t.iter("phase")]})
    for tag in ("e1Detector", "inductionLoop", "e2Detector", "laneAreaDetector", "e3Detector"):
        detectors += len(list(root.iter(tag)))
    return edges, internal, junctions, tls, detectors


def actuated_specs(plan):
    out = {}
    for j in plan["jobs"]:
        if j["kind"] == "comparator" and j["spec"]["kind"] in ("actuated", "actuated_g5"):
            key = (j["profile"], j["spec_sha256"])
            out[key] = {"profile": j["profile"], "labels": j["labels"], "kind": j["spec"]["kind"],
                        "params": j["spec"].get("params")}
    return sorted(out.values(), key=lambda r: (r["profile"], ";".join(r["labels"])))


def facts(config_path, net_path, plan):
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    edges, internal, junctions, tls, detectors = lanes_of(net_path)
    obs = config["observation"]
    expected = dict((k, float(v)) for k, v in obs["expected_lane_lengths_m"].items())
    approaches = {}
    for tl in ("J1", "J2"):
        approaches[tl] = {}
        for phase in ("H_in", "V_in"):
            approaches[tl][phase] = []
            for lane in obs["lanes"][tl][phase]:
                edge = lane.rsplit("_", 1)[0]
                rec = next((l for l in edges.get(edge, {}).get("lanes", []) if l["id"] == lane), None)
                approaches[tl][phase].append({"lane": lane, "edge": edge,
                                              "net_length_m": rec["length_m"] if rec else "non disponible",
                                              "net_speed_m_s": rec["speed_m_s"] if rec else "non disponible",
                                              "config_expected_length_m": expected.get(lane, "non disponible")})
    between = [e for e in edges.values() if {e["from"], e["to"]} == {"J1", "J2"}]
    j1, j2 = junctions.get("J1"), junctions.get("J2")
    zones = []
    for spec in actuated_specs(plan):
        zone = float(spec["params"]["zone_m"])
        per_lane = []
        for tl in ("J1", "J2"):
            for phase in ("H_in", "V_in"):
                for lane in obs["lanes"][tl][phase]:
                    L = expected[lane]
                    per_lane.append({"junction": tl, "phase": phase[0], "lane": lane, "lane_length_m": L,
                                     "zone_from_lane_start_m": L - zone, "zone_to_m": L, "zone_length_m": zone})
        zones.append(dict(spec, zone_m=zone, lanes=per_lane))
    vt = config["demand"]["vehicle_type"]
    return {
        "sources": {"config": config_path, "config_sha256": C.sha256_file(config_path), "network": net_path,
                    "network_sha256": C.sha256_file(net_path),
                    "detection_rule": "tools/comparators/controllers.py ActuatedGapOutExecutor, lines 10-12 and 87-93"},
        "junctions": junctions,
        "edges": sorted(edges.values(), key=lambda e: e["id"]),
        "internal_edges_count": len(internal),
        "traffic_light_programs_in_net": tls,
        "approach_lanes": approaches,
        "storage_between_J1_and_J2": {
            "edges": [{"id": e["id"], "from": e["from"], "to": e["to"], "number_of_lanes": e["number_of_lanes"],
                       "lane_lengths_m": [l["length_m"] for l in e["lanes"]], "speeds_m_s": [l["speed_m_s"] for l in e["lanes"]]}
                      for e in sorted(between, key=lambda e: e["id"])],
            "junction_distance_m": (abs(j2["x"] - j1["x"]) + abs(j2["y"] - j1["y"])) if j1 and j2 else "non disponible",
            "vehicles_per_lane_if_queued_at_length_plus_min_gap (derived, not measured)": {
                e["id"]: [int(l["length_m"] // (float(vt["length"]) + float(vt["minGap"]))) for l in e["lanes"]]
                for e in between},
            "vehicle_length_m": vt["length"], "min_gap_m": vt["minGap"]},
        "vehicle_type": vt,
        "detectors_defined_in_net_or_additional": detectors,
        "actuated_detection_zones": zones or "non disponible (no actuated comparator in plan.json)",
        "coordination_detector_of_the_frozen_analysis (not used by the controllers)": config.get("coordination"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config")
    ap.add_argument("--net")
    a = ap.parse_args(argv)
    import evaluate_any as ea
    config_path = a.config or os.path.join(ea.PROTECTED, ea.CONFIG_REL)
    with open(config_path, encoding="utf-8") as f:
        net_rel = json.load(f)["network"]["path"]
    net_path = a.net or os.path.join(ea.PROTECTED, net_rel)
    with open(os.path.join(a.root, "plan.json"), encoding="utf-8") as f:
        plan = json.load(f)
    out = facts(config_path, net_path, plan)
    scrub = C.Scrubber(a.root, a.out, extra=((ea.PROTECTED, "<PROTECTED>"),))
    C.write_json_once(os.path.join(a.out, "network_facts.json"), out, scrub)
    s = out["storage_between_J1_and_J2"]
    print("network {} ({} edges, {} lanes per edge) | J1-J2: {} m apart, edges {} | actuated zones: {}".format(
        os.path.basename(net_path), len(out["edges"]), sorted(set(e["number_of_lanes"] for e in out["edges"])),
        s["junction_distance_m"], [(e["id"], e["lane_lengths_m"]) for e in s["edges"]],
        sorted(set(z["zone_m"] for z in out["actuated_detection_zones"])) if isinstance(out["actuated_detection_zones"], list) else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
