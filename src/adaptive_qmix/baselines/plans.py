"""Pretimed signal plans, and the candidate grids the benchmark search walks.

A plan is two-phase, H then V, with a fixed 3 s yellow at both transitions:

    H green (g_H) -> yellow -> V green (g_V) -> yellow -> back to H

so a cycle satisfies g_H + g_V + 2*yellow = C exactly, and every plan is
representable at 1 s resolution. Nothing here goes through the QMIX 5 s
executor.

Offset convention, identical everywhere:

    Delta = t^{H,start}_{J2} - t^{H,start}_{J1}  (mod C)

J1 starts its H green at t = 0, so J1 carries offset 0 and J2 carries Delta. A
positive offset therefore means J2's H green starts AFTER J1's. J2 is a
periodic steady-state schedule evaluated at its own local phase from t = 0
onward: there is no startup all-red and no warm-up, so at t = 0 J2 simply sits
wherever its schedule says it sits.

The 5 s minimum green enforced in candidate_is_valid belongs to the classical
benchmark search alone. It is a plan-admissibility rule for pretimed plans and
is emphatically NOT a minimum green imposed on QMIX, which has none.
"""

from __future__ import absolute_import

from decimal import Decimal, ROUND_HALF_UP


YELLOW_S = 3
LOST_TIME_S = 2 * YELLOW_S

# The simultaneous reference plan, fixed by specification.
SIMULTANEOUS_CYCLE_S = 90
SIMULTANEOUS_GREEN_S = 42
SIMULTANEOUS_OFFSET_S = 0

# Classical-benchmark plan admissibility. Not a QMIX constraint.
MIN_GREEN_S = 5

# Coarse grid.
COARSE_CYCLES_S = tuple(range(40, 141, 10))
COARSE_SPLIT_THOUSANDTHS = tuple(range(300, 751, 50))
COARSE_OFFSET_STEP_S = 5

# Fine grid, expressed in the same integer units so candidates dedupe exactly.
FINE_CYCLE_DELTA_S = 10
FINE_CYCLE_STEP_S = 5
CYCLE_BOUNDS_S = (40, 140)
FINE_SPLIT_DELTA_THOUSANDTHS = 50
FINE_SPLIT_STEP_THOUSANDTHS = 25
SPLIT_BOUNDS_THOUSANDTHS = (250, 800)
FINE_OFFSET_DELTA_S = 10
FINE_OFFSET_STEP_S = 1

PHASE_ORDER = ("H", "H_TO_V_YELLOW", "V", "V_TO_H_YELLOW")


class PlanError(ValueError):
    pass


def round_half_up(value):
    """Round to the nearest integer, halves away from zero.

    Python's built-in round() is banker's rounding: round(2.5) is 2, not 3.
    The benchmark specification calls for half-up, so the decision is made in
    exact decimal arithmetic rather than in binary floating point, where
    0.35 * 34 is not exactly 11.9 and a boundary can fall the wrong way.
    """
    return int(
        Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def green_split(cycle_s, split_thousandths):
    """(g_H, g_V) for a cycle and an H share given in thousandths."""
    usable = int(cycle_s) - LOST_TIME_S
    exact = Decimal(int(split_thousandths)) * Decimal(usable) / Decimal(1000)
    g_h = int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return g_h, usable - g_h


def make_plan(cycle_s, split_thousandths, offset_s):
    """One candidate pretimed plan, with its exact green split."""
    cycle_s = int(cycle_s)
    g_h, g_v = green_split(cycle_s, split_thousandths)
    return {
        "cycle_s": cycle_s,
        "split_thousandths": int(split_thousandths),
        "f_H": round(int(split_thousandths) / 1000.0, 3),
        "green_H_s": g_h,
        "green_V_s": g_v,
        "yellow_s": YELLOW_S,
        "offset_s": int(offset_s) % cycle_s,
    }


def candidate_is_valid(plan):
    """Plan admissibility for the classical benchmark search only."""
    return (
        plan["green_H_s"] >= MIN_GREEN_S
        and plan["green_V_s"] >= MIN_GREEN_S
    )


def validate_plan(plan):
    """Structural checks every executed plan must satisfy."""
    if plan["yellow_s"] != YELLOW_S:
        raise PlanError("Yellow must be exactly {} s.".format(YELLOW_S))
    total = plan["green_H_s"] + plan["green_V_s"] + 2 * plan["yellow_s"]
    if total != plan["cycle_s"]:
        raise PlanError(
            "g_H + g_V + 2*yellow must equal C: {} + {} + {} != {}".format(
                plan["green_H_s"], plan["green_V_s"], 2 * plan["yellow_s"],
                plan["cycle_s"],
            )
        )
    if plan["green_H_s"] <= 0 or plan["green_V_s"] <= 0:
        raise PlanError("Both greens must be positive.")
    if not 0 <= plan["offset_s"] < plan["cycle_s"]:
        raise PlanError("Offset must be reduced modulo the cycle.")
    return True


def simultaneous_plan():
    """C = 90, g_H = g_V = 42, yellow 3, Delta = 0 at both intersections."""
    plan = {
        "cycle_s": SIMULTANEOUS_CYCLE_S,
        "split_thousandths": 500,
        "f_H": 0.5,
        "green_H_s": SIMULTANEOUS_GREEN_S,
        "green_V_s": SIMULTANEOUS_GREEN_S,
        "yellow_s": YELLOW_S,
        "offset_s": SIMULTANEOUS_OFFSET_S,
    }
    validate_plan(plan)
    return plan


def fixed_offset_plan(offset_s):
    """The simultaneous timing, moved to an explicit J2 offset."""
    plan = dict(simultaneous_plan())
    plan["offset_s"] = int(offset_s) % SIMULTANEOUS_CYCLE_S
    validate_plan(plan)
    return plan


def fixed_offset_candidates():
    """All 90 admissible offsets of the fixed-offset benchmark."""
    return [fixed_offset_plan(offset) for offset in range(SIMULTANEOUS_CYCLE_S)]


def candidate_key(plan):
    """Deterministic identity of a candidate, used for dedup and ordering."""
    return (plan["cycle_s"], plan["split_thousandths"], plan["offset_s"])


def coarse_timing_candidates(include_invalid=False):
    """The coarse (C, f_H, Delta) grid.

    The grid is 1980 candidates before any validity rejection: 11 cycles times
    10 splits times C/5 offsets, and sum over C of C/5 is 198.
    """
    candidates = []
    for cycle_s in COARSE_CYCLES_S:
        for split in COARSE_SPLIT_THOUSANDTHS:
            for offset_s in range(0, cycle_s, COARSE_OFFSET_STEP_S):
                plan = make_plan(cycle_s, split, offset_s)
                if include_invalid or candidate_is_valid(plan):
                    candidates.append(plan)
    return candidates


def _clipped_range(centre, delta, step, bounds):
    low, high = bounds
    values = []
    value = centre - delta
    while value <= centre + delta:
        if low <= value <= high:
            values.append(value)
        value += step
    return values


def fine_timing_candidates(winners, include_invalid=False):
    """The fine neighbourhoods of the coarse winners, deduplicated.

    Cycles move by 5 s within +/-10 s and are clipped to [40, 140]; splits move
    by 0.025 within +/-0.05 and are clipped to [0.25, 0.80]; offsets move by
    1 s within +/-10 s and are reduced modulo the candidate's own cycle, which
    is why the offset range is built per cycle rather than once.
    """
    seen = set()
    candidates = []
    for winner in winners:
        centre_cycle = int(winner["cycle_s"])
        centre_split = int(winner["split_thousandths"])
        centre_offset = int(winner["offset_s"])
        cycles = _clipped_range(
            centre_cycle, FINE_CYCLE_DELTA_S, FINE_CYCLE_STEP_S, CYCLE_BOUNDS_S
        )
        splits = _clipped_range(
            centre_split, FINE_SPLIT_DELTA_THOUSANDTHS,
            FINE_SPLIT_STEP_THOUSANDTHS, SPLIT_BOUNDS_THOUSANDTHS,
        )
        for cycle_s in cycles:
            for split in splits:
                for raw_offset in range(
                    centre_offset - FINE_OFFSET_DELTA_S,
                    centre_offset + FINE_OFFSET_DELTA_S + 1,
                    FINE_OFFSET_STEP_S,
                ):
                    plan = make_plan(cycle_s, split, raw_offset % cycle_s)
                    if not include_invalid and not candidate_is_valid(plan):
                        continue
                    key = candidate_key(plan)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(plan)
    return candidates


def schedule_segments(plan):
    """The four segments of one cycle as (start, end, actual, logical) tuples.

    A segment covers local seconds [start, end): the state applies to the
    simulated interval that begins at that local second. 'actual' is what the
    signal shows, 'logical' is the green being served or terminated, which is
    how the adaptive executor reports a phase during its yellow.
    """
    g_h, g_v, yellow = plan["green_H_s"], plan["green_V_s"], plan["yellow_s"]
    return (
        (0, g_h, "H", "H"),
        (g_h, g_h + yellow, "Y", "H"),
        (g_h + yellow, g_h + yellow + g_v, "V", "V"),
        (g_h + yellow + g_v, plan["cycle_s"], "Y", "V"),
    )


def state_at(plan, local_second):
    """(actual phase, logical green, seconds of this green already served)."""
    local = int(local_second) % plan["cycle_s"]
    for start, end, actual, logical in schedule_segments(plan):
        if start <= local < end:
            served = 0 if actual == "Y" else local - start
            return actual, logical, served
    raise PlanError("Local second {} fell outside the cycle.".format(local))


def local_second(plan, simulation_time, offset_s):
    """Local schedule time of an intersection carrying the given offset."""
    return (int(simulation_time) - int(offset_s)) % plan["cycle_s"]
