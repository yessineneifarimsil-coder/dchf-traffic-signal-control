"""Robustness traffic manifests (family "robustness", code 80, distinct from every frozen family).

Generator: for each stream, `count` departures drawn independently over the integer seconds
[0, generation_end) with probability proportional to the stream's piecewise-constant profile (weight 1
everywhere when no profile is given), i.e. the frozen "conditioned" design (exact counts) with a
time-varying intensity. Seeds: numpy SeedSequence over (MASTER_ENTROPY, EXPERIMENT_NAMESPACE,
traffic namespace code, 80, scenario code, seed, stream rank); the SUMO seed uses the frozen derivation
scheme with family code 80. Files are written in the frozen manifest format (CSV, route XML, metadata);
metadata adds the scenario, its spec hash and the scheduled total N used as J's denominator.
"""
import csv
import hashlib
import json
import os
import xml.etree.ElementTree as ET

import numpy as np

MASTER_ENTROPY = 20260828          # frozen adaptive_qmix.rng values (checked by the test against the module)
EXPERIMENT_NAMESPACE = 1301
TRAFFIC_NAMESPACE = 401
SUMO_NAMESPACE = 402
FAMILY_CODE = 80
SUMO_MAX_SEED = 2 ** 31 - 1
FORBIDDEN_SEEDS = set(range(3001, 3011)) | set(range(3101, 3121))       # final tests (old and reserved)
USED_SEEDS = (set(range(9002, 9008)) | set(range(9201, 9221)) | set(range(9301, 9306)) | set(range(9401, 9411))
              | set(range(2001, 2006)) | set(range(2101, 2106)) | set(range(2011, 2016)) | set(range(2111, 2116))
              | set(range(2201, 2206)) | set(range(2301, 2306)))
HERE = os.path.dirname(os.path.abspath(__file__))


def load_spec(path=os.path.join(HERE, "scenarios.json")):
    with open(path) as f:
        spec = json.load(f)
    spec["_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in spec.items() if k != "_sha256"},
                                                sort_keys=True).encode()).hexdigest()
    return spec


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def profile_weights(stream, generation_end):
    w = np.ones(generation_end, dtype=np.float64)
    if "profile" in stream:
        w[:] = 0.0
        covered = np.zeros(generation_end, dtype=bool)
        for start, end, weight in stream["profile"]:
            if not (0 <= start < end <= generation_end) or weight < 0 or covered[start:end].any():
                raise ValueError("invalid profile segment {}".format((start, end, weight)))
            w[start:end] = weight
            covered[start:end] = True
        if not covered.all():
            raise ValueError("profile does not cover [0, {})".format(generation_end))
    if stream["count"] > 0 and w.sum() <= 0:
        raise ValueError("zero-weight profile with positive count")
    return w


def sumo_seed(scenario_code, seed):
    ss = np.random.SeedSequence([MASTER_ENTROPY, EXPERIMENT_NAMESPACE, SUMO_NAMESPACE, FAMILY_CODE,
                                 int(scenario_code), int(seed), 999])
    return int(ss.generate_state(1)[0]) & SUMO_MAX_SEED


def generate(spec, scenario, seed):
    sc = spec["scenarios"][scenario]
    if seed in FORBIDDEN_SEEDS or seed in USED_SEEDS:
        raise ValueError("seed {} is reserved or already used".format(seed))
    end = int(spec["generation_end_s"])
    records = []
    for name in sorted(sc["streams"], key=lambda n: spec["stream_rank"][n]):
        st, rank = sc["streams"][name], spec["stream_rank"][name]
        count = int(st["count"])
        if count == 0:
            continue
        w = profile_weights(st, end)
        rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(
            [MASTER_ENTROPY, EXPERIMENT_NAMESPACE, TRAFFIC_NAMESPACE, FAMILY_CODE, int(sc["code"]), int(seed), rank])))
        departs = sorted(int(x) for x in rng.choice(end, size=count, replace=True, p=w / w.sum()))
        for k, d in enumerate(departs):
            records.append({"vehicle_id": "robustness_{}_s{}_{}_v{:04d}".format(sc["code"], seed, name, k),
                            "depart": d, "stream": name, "stream_rank": rank, "within_stream_rank": k,
                            "route_id": "route_{}".format(name), "route_edges": " ".join(spec["routes"][name])})
    records.sort(key=lambda r: (r["depart"], r["stream_rank"], r["within_stream_rank"]))
    if len({r["vehicle_id"] for r in records}) != len(records):
        raise RuntimeError("duplicate vehicle ids")
    return records


def write(spec, scenario, seed, records, prefix, vehicle_type):
    if any(os.path.exists(prefix + e) for e in (".csv", ".rou.xml", ".metadata.json")):
        raise FileExistsError("manifest {} exists".format(prefix))
    os.makedirs(os.path.dirname(os.path.abspath(prefix)), exist_ok=True)
    fields = ["vehicle_id", "depart", "stream", "stream_rank", "within_stream_rank", "route_id", "route_edges"]
    with open(prefix + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    root = ET.Element("routes")
    ET.SubElement(root, "vType", {k: str(vehicle_type[k2]) for k, k2 in
                                  (("id", "id"), ("length", "length"), ("minGap", "minGap"), ("accel", "accel"),
                                   ("decel", "decel"), ("sigma", "sigma"), ("maxSpeed", "maxSpeed"))})
    for name in sorted(spec["routes"], key=lambda n: spec["stream_rank"][n]):
        ET.SubElement(root, "route", {"id": "route_{}".format(name), "edges": " ".join(spec["routes"][name])})
    for r in records:
        ET.SubElement(root, "vehicle", {"id": r["vehicle_id"], "type": str(vehicle_type["id"]), "route": r["route_id"],
                                        "depart": str(r["depart"]), "departLane": str(vehicle_type["departLane"]),
                                        "departPos": str(vehicle_type["departPos"]),
                                        "departSpeed": str(vehicle_type["departSpeed"])})
    ET.ElementTree(root).write(prefix + ".rou.xml", encoding="utf-8", xml_declaration=True)
    sc = spec["scenarios"][scenario]
    meta = {"family": spec["family"], "family_code": FAMILY_CODE, "scenario": scenario, "scenario_code": sc["code"],
            "scenario_spec_sha256": spec["_sha256"], "seed_value": int(seed), "manifest_index": 0,
            "master_entropy": MASTER_ENTROPY, "experiment_namespace": EXPERIMENT_NAMESPACE,
            "traffic_namespace_code": TRAFFIC_NAMESPACE, "sumo_namespace_code": SUMO_NAMESPACE,
            "scheduled_total": len(records), "stream_counts": {n: int(s["count"]) for n, s in sc["streams"].items()},
            "sumo_seed": sumo_seed(sc["code"], seed), "csv_sha256": sha256_file(prefix + ".csv"),
            "route_xml_sha256": sha256_file(prefix + ".rou.xml"), "non_inferential": False}
    with open(prefix + ".metadata.json", "w") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
    return meta
