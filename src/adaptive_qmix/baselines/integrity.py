"""One guard for every way a baseline run can reach the wrong traffic.

Held-out protection is only real if it cannot be walked around, so all of it
lives here and every entry point calls it before anything is created, written
or opened. The checks are deliberately redundant, because each closes a
different hole:

  * the requested family and seed are checked, which stops
    --traffic-family benchmark_design --traffic-seed 3001;
  * the manifest's own metadata is checked, which stops a correctly-labelled
    command pointed at a final-test manifest someone already generated;
  * the metadata is required to agree exactly with the request, so the CLI
    labels can never override what the manifest actually is;
  * the files on disk are hashed against that metadata, because the .rou.xml
    is what SUMO executes and a CSV hash says nothing about it.

The last one matters more than it looks. The CSV is provenance; the route XML
is the experiment. A run whose route file was edited after the manifest was
written would carry a perfectly valid CSV hash and simulate different traffic.
"""

from __future__ import absolute_import

import hashlib
import json
import os


FINAL_FAMILY = "final_test"
FINAL_SEEDS = tuple(range(3001, 3011))
FORBIDDEN_SEEDS = frozenset(FINAL_SEEDS)

DEVELOPMENT_FAMILY = "development"
DESIGN_FAMILY = "benchmark_design"
VALIDATION_FAMILY = "benchmark_validation"

# Baselines are smoke-tested on development and searched on the two benchmark
# families. Everything else -- the learner's own families, the legacy sanity
# demand, and above all the held-out final test -- is refused rather than
# silently accepted.
ALLOWED_FAMILIES = (DEVELOPMENT_FAMILY, DESIGN_FAMILY, VALIDATION_FAMILY)

SCHEDULED_TOTAL = 2800


class HeldOutDataError(RuntimeError):
    """Raised when a run would touch held-out final-test traffic."""


class ManifestIntegrityError(RuntimeError):
    """Raised when a manifest is not what the caller declared it to be."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_seed_allowed(seed_value, where="request"):
    """No baseline run may use a final-test seed, whatever family it claims."""
    seed = int(seed_value)
    if seed in FORBIDDEN_SEEDS:
        raise HeldOutDataError(
            "Seed {} ({}) belongs to the held-out final test {}. Final seeds "
            "are untouchable until every plan is frozen and an official run "
            "is authorised; relabelling the family does not release "
            "them.".format(seed, where, sorted(FINAL_SEEDS))
        )
    return True


def assert_family_allowed(family, where="request"):
    if family == FINAL_FAMILY:
        raise HeldOutDataError(
            "Family {!r} ({}) is held out for final evaluation and may not be "
            "generated, opened or evaluated here.".format(family, where)
        )
    if family not in ALLOWED_FAMILIES:
        raise HeldOutDataError(
            "Family {!r} ({}) is not a baseline family; expected one of "
            "{}.".format(family, where, ALLOWED_FAMILIES)
        )
    return True


def assert_traffic_selection_allowed(family, seed_value, manifest_index=0):
    """The first gate: the request itself, before anything is created."""
    assert_family_allowed(family)
    assert_seed_allowed(seed_value)
    if int(manifest_index) < 0:
        raise ManifestIntegrityError(
            "manifest_index must be non-negative; got {}.".format(manifest_index)
        )
    return True


def metadata_path_for(manifest_prefix):
    return manifest_prefix + ".metadata.json"


def read_manifest_metadata(manifest_prefix):
    path = metadata_path_for(manifest_prefix)
    if not os.path.isfile(path):
        raise ManifestIntegrityError(
            "No manifest metadata at {}. A baseline run may not use a manifest "
            "whose provenance cannot be read.".format(path)
        )
    with open(path, "r") as handle:
        return json.load(handle)


def assert_metadata_not_held_out(metadata):
    """The manifest's own declaration, not the caller's label, decides."""
    assert_family_allowed(str(metadata.get("family")), where="manifest metadata")
    assert_seed_allowed(
        int(metadata.get("seed_value")), where="manifest metadata"
    )
    return True


def assert_metadata_matches_request(metadata, family, seed_value,
                                    manifest_index):
    """Exact agreement between what was asked for and what the manifest is."""
    assert_metadata_not_held_out(metadata)
    mismatches = []
    if str(metadata.get("family")) != str(family):
        mismatches.append(
            ("family", metadata.get("family"), family)
        )
    if int(metadata.get("seed_value")) != int(seed_value):
        mismatches.append(
            ("seed_value", metadata.get("seed_value"), seed_value)
        )
    if int(metadata.get("manifest_index")) != int(manifest_index):
        mismatches.append(
            ("manifest_index", metadata.get("manifest_index"), manifest_index)
        )
    if mismatches:
        raise ManifestIntegrityError(
            "The manifest is not what this run declared. Differences "
            "(field, manifest, requested): {}. The manifest metadata is "
            "authoritative; a command-line label never overrides it.".format(
                mismatches
            )
        )
    scheduled = int(metadata.get("scheduled_total", -1))
    if scheduled != SCHEDULED_TOTAL:
        raise ManifestIntegrityError(
            "Manifest declares {} scheduled vehicles; the contract requires "
            "exactly {}.".format(scheduled, SCHEDULED_TOTAL)
        )
    return True


def assert_manifest_files_match(manifest_prefix, metadata=None):
    """Hash the files SUMO will actually read, not just the CSV.

    Returns the two verified hashes so the caller can record them.
    """
    if metadata is None:
        metadata = read_manifest_metadata(manifest_prefix)
    csv_path = manifest_prefix + ".csv"
    route_path = manifest_prefix + ".rou.xml"
    verified = {}
    for label, path, field in (
        ("route manifest CSV", csv_path, "csv_sha256"),
        ("route XML executed by SUMO", route_path, "route_xml_sha256"),
    ):
        if not os.path.isfile(path):
            raise ManifestIntegrityError(
                "Missing {} at {}.".format(label, path)
            )
        expected = metadata.get(field)
        if not expected:
            raise ManifestIntegrityError(
                "Manifest metadata carries no {}; its integrity cannot be "
                "established.".format(field)
            )
        actual = sha256_file(path)
        if actual != expected:
            raise ManifestIntegrityError(
                "The {} has changed since the manifest was written.\n"
                "  path     : {}\n  recorded : {}\n  actual   : {}\n"
                "SUMO executes the route XML, so a run on an altered file "
                "would simulate traffic the provenance does not "
                "describe.".format(label, path, expected, actual)
            )
        verified[field] = actual
    return verified


def verify_manifest_for_run(manifest_prefix, family, seed_value,
                            manifest_index):
    """Every manifest check, in the order that fails earliest and cheapest."""
    assert_traffic_selection_allowed(family, seed_value, manifest_index)
    metadata = read_manifest_metadata(manifest_prefix)
    assert_metadata_matches_request(
        metadata, family, seed_value, manifest_index
    )
    hashes = assert_manifest_files_match(manifest_prefix, metadata)
    return metadata, hashes
