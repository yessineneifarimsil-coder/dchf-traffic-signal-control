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
    is what SUMO executes and a CSV hash says nothing about it;
  * the SUMO seed is required to be the one the family, seed and index derive,
    so a run cannot be given an arbitrary or edited seed.

The route-file check matters more than it looks. The CSV is provenance; the
route XML is the experiment. A run whose route file was edited after the
manifest was written would carry a perfectly valid CSV hash and simulate
different traffic.

This module is also the single canonical statement of which traffic each
benchmark stage may use. Family, seed value and manifest index all feed the
manifest generator, so equal seed numbers under different families are
different traffic entirely: benchmark_design seed 2001 and
benchmark_validation seed 2001 have nothing in common. Binding the three
together here, and importing them everywhere else, is what stops the
optimisation stages and the guard from drifting apart into two different ideas
of what "the design seeds" are.
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

# The canonical mapping. Every other module imports these rather than
# restating them, so integrity.py and search.py cannot disagree.
DESIGN_SEEDS = (2001, 2002, 2003, 2004, 2005)
VALIDATION_SEEDS = (2101, 2102, 2103, 2104, 2105)
BENCHMARK_SEEDS = {
    DESIGN_FAMILY: DESIGN_SEEDS,
    VALIDATION_FAMILY: VALIDATION_SEEDS,
}
BENCHMARK_FAMILIES = (DESIGN_FAMILY, VALIDATION_FAMILY)

# Official benchmark traffic is manifest index 0 and nothing else. The index
# is an input to the generator, so index 1 of the same family and seed is a
# different realisation and would silently unpair the candidates.
BENCHMARK_MANIFEST_INDEX = 0

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


def assert_benchmark_binding(family, seed_value, manifest_index):
    """A benchmark stage may use only its own frozen traffic.

    development is left open for engineering smokes; the two benchmark
    families are bound to their preregistered seed set and to manifest index
    0, because family and index both feed the generator and a matching seed
    number alone proves nothing about the traffic.
    """
    if family not in BENCHMARK_FAMILIES:
        return True
    expected = BENCHMARK_SEEDS[family]
    seed = int(seed_value)
    if seed not in expected:
        other = [
            name for name in BENCHMARK_FAMILIES
            if seed in BENCHMARK_SEEDS[name]
        ]
        raise HeldOutDataError(
            "Seed {} does not belong to {}, whose seeds are {}{}. Family and "
            "seed together choose the traffic; the same number under another "
            "family is different traffic, not the same run.".format(
                seed, family, list(expected),
                "" if not other else
                " (it belongs to {})".format(other[0]),
            )
        )
    if int(manifest_index) != BENCHMARK_MANIFEST_INDEX:
        raise HeldOutDataError(
            "Official {} traffic is manifest index {}; got {}. The index is an "
            "input to the manifest generator, so another index is a different "
            "realisation and would unpair the candidates.".format(
                family, BENCHMARK_MANIFEST_INDEX, manifest_index
            )
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
    assert_benchmark_binding(family, seed_value, manifest_index)
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
    family = str(metadata.get("family"))
    assert_family_allowed(family, where="manifest metadata")
    assert_seed_allowed(
        int(metadata.get("seed_value")), where="manifest metadata"
    )
    assert_benchmark_binding(
        family, metadata.get("seed_value"), metadata.get("manifest_index", 0)
    )
    return True


def assert_sumo_seed_matches(metadata, sumo_seed, family, seed_value,
                             manifest_index):
    """The SUMO seed must be the one this traffic selection derives.

    Three values have to agree: what the caller passed, what the manifest
    recorded, and what the seed derivation produces from the family, seed and
    index. An edited metadata seed and an arbitrary runner seed are both
    refused, so the stochastic stream a run used is pinned to its provenance
    rather than merely reported alongside it.
    """
    from ..traffic import derive_sumo_seed

    derived = int(derive_sumo_seed(family, seed_value, manifest_index))
    recorded = metadata.get("sumo_seed")
    if recorded is None:
        raise ManifestIntegrityError(
            "Manifest metadata carries no sumo_seed; the simulation stream "
            "cannot be tied to this traffic selection."
        )
    if int(recorded) != derived:
        raise ManifestIntegrityError(
            "The manifest records SUMO seed {} but {} seed {} index {} derives "
            "{}. The recorded seed has been altered, or the metadata belongs "
            "to a different selection.".format(
                recorded, family, seed_value, manifest_index, derived
            )
        )
    if int(sumo_seed) != derived:
        raise ManifestIntegrityError(
            "This run was given SUMO seed {}, but {} seed {} index {} derives "
            "{}. A baseline may not choose its own simulation stream.".format(
                sumo_seed, family, seed_value, manifest_index, derived
            )
        )
    return derived


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
                            manifest_index, sumo_seed=None):
    """Every manifest check, in the order that fails earliest and cheapest.

    When a SUMO seed is supplied it is bound too, so the returned hashes and
    seed together describe exactly the files and stream the run may use.
    """
    assert_traffic_selection_allowed(family, seed_value, manifest_index)
    metadata = read_manifest_metadata(manifest_prefix)
    assert_metadata_matches_request(
        metadata, family, seed_value, manifest_index
    )
    hashes = assert_manifest_files_match(manifest_prefix, metadata)
    if sumo_seed is not None:
        hashes = dict(hashes)
        hashes["sumo_seed"] = assert_sumo_seed_matches(
            metadata, sumo_seed, family, seed_value, manifest_index
        )
    return metadata, hashes


def manifest_paths(manifest_prefix):
    """The two files a verified prefix authorises, and nothing else."""
    return {
        "csv": os.path.abspath(manifest_prefix + ".csv"),
        "route_xml": os.path.abspath(manifest_prefix + ".rou.xml"),
    }


def assert_paths_are_the_verified_ones(manifest_prefix, csv_path, route_path):
    """What was verified must be what SUMO is handed.

    Verifying one prefix and then executing a different route file would make
    the whole check ornamental, so the executed paths are required to be the
    verified ones after normalisation.
    """
    expected = manifest_paths(manifest_prefix)
    given = {
        "csv": os.path.realpath(csv_path),
        "route_xml": os.path.realpath(route_path),
    }
    mismatches = [
        (name, given[name], os.path.realpath(expected[name]))
        for name in sorted(expected)
        if given[name] != os.path.realpath(expected[name])
    ]
    if mismatches:
        raise ManifestIntegrityError(
            "The files this run would execute are not the ones that were "
            "verified. Differences (file, given, verified): {}. SUMO must be "
            "handed exactly the verified manifest.".format(mismatches)
        )
    return expected
