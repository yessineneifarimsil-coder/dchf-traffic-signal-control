"""Max-pressure movement mapping and the frozen empirical pressure score.

The pressure of phase p at intersection i is

    P_i(p, t) = sum over (l, m) in M_i(p) of [ n_l(t) - n_m(t) ]

where n_l(t) is the instantaneous number of vehicles on incoming lane l and
n_m(t) the instantaneous number on the outgoing lane m that this movement
feeds. Both come from LAST_STEP_VEHICLE_NUMBER, read through the same audited
data source the adaptive environment uses.

What this deliberately is NOT. The count is not the halting-vehicle number, not
occupancy, not the normalised queue feature of the QMIX observation, not the
reward, and not a predicted arrival rate. Substituting any of those changes the
controller into something else that would no longer be max pressure, so
lane_halting_number is never called here and the accessor used is stated in
LANE_COUNT_ACCESSOR for auditing.

The movement pairs are the straight-through pairs of the frozen corridor. They
are written out explicitly rather than derived, so that a reader can check them
by eye, and then validated against the network's own connectivity at startup:
a frozen pair that is not physically connected is a hard failure, never a
silently dropped term.

No stability claim is attached to this score. On a finite two-phase network
with switching losses and a minimum green, the idealised max-pressure
throughput-optimality argument does not carry over; this is a strong empirical
operational baseline and is described as one.
"""

from __future__ import absolute_import

import xml.etree.ElementTree as ET


LANE_COUNT_ACCESSOR = "lane_vehicle_number"
FORBIDDEN_ACCESSORS = ("lane_halting_number", "lane_occupancy")

MOVEMENTS = ("H", "V")

# Frozen straight-through movement pairs, (incoming lane, served outgoing lane).
FROZEN_MOVEMENT_PAIRS = {
    "J1": {
        "H": (
            ("E0_0", "E1_0"),
            ("E0_1", "E1_1"),
            ("-E1_0", "-E0_0"),
            ("-E1_1", "-E0_1"),
        ),
        "V": (
            ("E4_0", "-E5_0"),
            ("E4_1", "-E5_1"),
            ("E5_0", "-E4_0"),
            ("E5_1", "-E4_1"),
        ),
    },
    "J2": {
        "H": (
            ("E1_0", "-E2_0"),
            ("E1_1", "-E2_1"),
            ("E2_0", "-E1_0"),
            ("E2_1", "-E1_1"),
        ),
        "V": (
            ("E7_0", "-E6_0"),
            ("E7_1", "-E6_1"),
            ("E6_0", "-E7_0"),
            ("E6_1", "-E7_1"),
        ),
    },
}


class MovementMappingError(RuntimeError):
    pass


def network_lane_connections(network_path):
    """Every (from lane, to lane) pair the network physically provides."""
    root = ET.parse(network_path).getroot()
    pairs = set()
    for connection in root.findall("connection"):
        attributes = connection.attrib
        source = attributes["from"]
        target = attributes["to"]
        if source.startswith(":") or target.startswith(":"):
            # Internal junction lanes; the movement is named by its real edges.
            continue
        pairs.add((
            "{}_{}".format(source, attributes["fromLane"]),
            "{}_{}".format(target, attributes["toLane"]),
        ))
    return pairs


def validate_movement_pairs(network_path, pairs=None):
    """Fail unless every frozen pair is physically connected in the network."""
    mapping = FROZEN_MOVEMENT_PAIRS if pairs is None else pairs
    available = network_lane_connections(network_path)
    missing = []
    for intersection in sorted(mapping):
        for movement in MOVEMENTS:
            for incoming, outgoing in mapping[intersection][movement]:
                if (incoming, outgoing) not in available:
                    missing.append((intersection, movement, incoming, outgoing))
    if missing:
        raise MovementMappingError(
            "These frozen max-pressure movements are not physically connected "
            "in {}: {}. A pressure term must never be silently dropped.".format(
                network_path, missing
            )
        )
    return True


def validate_against_observation_topology(config, pairs=None):
    """Every incoming lane of a phase must be that phase's approach lane."""
    mapping = FROZEN_MOVEMENT_PAIRS if pairs is None else pairs
    lanes = config["observation"]["lanes"]
    problems = []
    for intersection in sorted(mapping):
        for movement in MOVEMENTS:
            expected_in = set(lanes[intersection]["{}_in".format(movement)])
            expected_out = set(lanes[intersection]["{}_out".format(movement)])
            for incoming, outgoing in mapping[intersection][movement]:
                if incoming not in expected_in:
                    problems.append(
                        (intersection, movement, "incoming", incoming)
                    )
                if outgoing not in expected_out:
                    problems.append(
                        (intersection, movement, "outgoing", outgoing)
                    )
    if problems:
        raise MovementMappingError(
            "Max-pressure movements disagree with the frozen observation "
            "topology: {}".format(problems)
        )
    return True


def phase_pressure(data_source, intersection, movement, pairs=None):
    """P_i(p, t) from instantaneous lane vehicle counts."""
    mapping = FROZEN_MOVEMENT_PAIRS if pairs is None else pairs
    total = 0
    for incoming, outgoing in mapping[intersection][movement]:
        total += (
            int(data_source.lane_vehicle_number(incoming))
            - int(data_source.lane_vehicle_number(outgoing))
        )
    return total


def local_pressures(data_source, intersection, pairs=None):
    """Both phase pressures at one intersection, as a plain dict."""
    return dict(
        (movement, phase_pressure(data_source, intersection, movement, pairs))
        for movement in MOVEMENTS
    )


def preferred_phase(pressures, current_phase):
    """The phase max pressure would serve, retaining the current one on a tie.

    An exact tie retains the current phase rather than switching, so the
    controller never pays a switching loss for no pressure gain. This rule is
    shared by the canonical controller and the P-5 diagnostic, which is what
    makes the two comparable at the level of the decision rule.
    """
    other = "V" if current_phase == "H" else "H"
    if pressures[other] > pressures[current_phase]:
        return other
    return current_phase
