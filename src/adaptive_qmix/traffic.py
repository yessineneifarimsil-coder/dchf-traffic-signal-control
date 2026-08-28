"""Exact 2800-vehicle manifest generation and hashing."""

from __future__ import absolute_import

import csv
import hashlib
import os
import xml.etree.ElementTree as ET

import numpy as np

from .rng import EXPERIMENT_NAMESPACE, MASTER_ENTROPY, NAMESPACE_CODES

FAMILY_CODES = {
    "training": 10,
    "development": 20,
    "benchmark_design": 30,
    "benchmark_validation": 40,
    "learner_validation": 50,
    "final_test": 60,
    "legacy_deterministic_sanity": 70,
}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stream_generator(family, seed_value, manifest_index, stream_rank):
    if family not in FAMILY_CODES:
        raise KeyError("Unknown traffic-manifest family: {}".format(family))
    entropy = [
        MASTER_ENTROPY,
        EXPERIMENT_NAMESPACE,
        NAMESPACE_CODES["traffic_manifest"],
        FAMILY_CODES[family],
        int(seed_value),
        int(manifest_index),
        int(stream_rank),
    ]
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))


def derive_sumo_seed(family, seed_value, manifest_index):
    entropy = [
        MASTER_ENTROPY,
        EXPERIMENT_NAMESPACE,
        NAMESPACE_CODES["sumo_episode"],
        FAMILY_CODES[family],
        int(seed_value),
        int(manifest_index),
        999,
    ]
    return int(np.random.SeedSequence(entropy).generate_state(1)[0])


def generate_manifest_records(config, family, seed_value, manifest_index=0):
    """Generate conditioned homogeneous multinomial one-second arrivals."""
    generation_end = int(config["demand"]["generation_end_s"])
    streams = config["demand"]["streams"]
    records = []

    for stream_name, stream in sorted(
        streams.items(), key=lambda item: int(item[1]["rank"])
    ):
        count = int(stream["count"])
        rank = int(stream["rank"])
        generator = _stream_generator(family, seed_value, manifest_index, rank)
        departure_seconds = generator.integers(
            0, generation_end, size=count, dtype=np.int64
        )
        ordered = sorted(
            ((int(second), draw_index) for draw_index, second in enumerate(departure_seconds)),
            key=lambda item: (item[0], item[1]),
        )
        for within_rank, (depart, _draw_index) in enumerate(ordered):
            vehicle_id = "{}_m{:03d}_{}_v{:04d}".format(
                family, int(manifest_index), stream_name, within_rank
            )
            records.append(
                {
                    "vehicle_id": vehicle_id,
                    "depart": depart,
                    "stream": stream_name,
                    "stream_rank": rank,
                    "within_stream_rank": within_rank,
                    "route_id": "route_{}".format(stream_name),
                    "route_edges": " ".join(stream["route"]),
                }
            )

    records.sort(
        key=lambda row: (
            int(row["depart"]),
            int(row["stream_rank"]),
            int(row["within_stream_rank"]),
        )
    )
    if len(records) != 2800 or len({row["vehicle_id"] for row in records}) != 2800:
        raise RuntimeError("Traffic manifest must contain 2800 unique vehicle IDs.")
    return records


def generate_legacy_sanity_records(config):
    """Generate equally spaced, explicitly non-inferential legacy demand."""
    records = []
    horizon = int(config["demand"]["generation_end_s"])
    streams = config["demand"]["streams"]
    for stream_name, stream in sorted(
        streams.items(), key=lambda item: int(item[1]["rank"])
    ):
        count = int(stream["count"])
        for within_rank in range(count):
            depart = int(np.floor(float(within_rank) * horizon / count))
            records.append(
                {
                    "vehicle_id": "legacy_m000_{}_v{:04d}".format(
                        stream_name, within_rank
                    ),
                    "depart": depart,
                    "stream": stream_name,
                    "stream_rank": int(stream["rank"]),
                    "within_stream_rank": within_rank,
                    "route_id": "route_{}".format(stream_name),
                    "route_edges": " ".join(stream["route"]),
                    "non_inferential": True,
                }
            )
    records.sort(
        key=lambda row: (
            int(row["depart"]),
            int(row["stream_rank"]),
            int(row["within_stream_rank"]),
        )
    )
    return records


def write_manifest(records, config, output_prefix, family, seed_value, manifest_index=0):
    directory = os.path.dirname(os.path.abspath(output_prefix))
    if not os.path.isdir(directory):
        os.makedirs(directory)

    csv_path = output_prefix + ".csv"
    xml_path = output_prefix + ".rou.xml"
    metadata_path = output_prefix + ".metadata.json"

    fieldnames = [
        "vehicle_id", "depart", "stream", "stream_rank",
        "within_stream_rank", "route_id", "route_edges",
    ]
    with open(csv_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    root = ET.Element("routes")
    vtype = config["demand"]["vehicle_type"]
    ET.SubElement(
        root,
        "vType",
        {
            "id": str(vtype["id"]),
            "length": str(vtype["length"]),
            "minGap": str(vtype["minGap"]),
            "accel": str(vtype["accel"]),
            "decel": str(vtype["decel"]),
            "sigma": str(vtype["sigma"]),
            "maxSpeed": str(vtype["maxSpeed"]),
        },
    )
    streams = config["demand"]["streams"]
    for stream_name, stream in sorted(
        streams.items(), key=lambda item: int(item[1]["rank"])
    ):
        ET.SubElement(
            root,
            "route",
            {"id": "route_{}".format(stream_name), "edges": " ".join(stream["route"])},
        )
    for record in records:
        ET.SubElement(
            root,
            "vehicle",
            {
                "id": str(record["vehicle_id"]),
                "type": str(vtype["id"]),
                "route": str(record["route_id"]),
                "depart": str(record["depart"]),
                "departLane": str(vtype["departLane"]),
                "departPos": str(vtype["departPos"]),
                "departSpeed": str(vtype["departSpeed"]),
            },
        )
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)

    import json

    metadata = {
        "family": family,
        "family_code": FAMILY_CODES[family],
        "master_entropy": MASTER_ENTROPY,
        "experiment_namespace": EXPERIMENT_NAMESPACE,
        "traffic_namespace_code": NAMESPACE_CODES["traffic_manifest"],
        "sumo_namespace_code": NAMESPACE_CODES["sumo_episode"],
        "seed_value": int(seed_value),
        "manifest_index": int(manifest_index),
        "scheduled_total": len(records),
        "sumo_seed": derive_sumo_seed(family, seed_value, manifest_index),
        "csv_sha256": sha256_file(csv_path),
        "route_xml_sha256": sha256_file(xml_path),
        "non_inferential": family == "legacy_deterministic_sanity",
    }
    with open(metadata_path, "w") as handle:
        json.dump(metadata, handle, sort_keys=True, indent=2)
    return metadata


def read_manifest_csv(path):
    records = []
    with open(path, "r", newline="") as handle:
        for row in csv.DictReader(handle):
            converted = dict(row)
            converted["depart"] = int(converted["depart"])
            converted["stream_rank"] = int(converted["stream_rank"])
            converted["within_stream_rank"] = int(converted["within_stream_rank"])
            records.append(converted)
    return records
