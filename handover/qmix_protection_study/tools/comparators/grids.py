"""Candidate grids of the original optimized-fixed-timing (OFT) procedure, with the minimum green as parameter.

Reconstructed from the frozen code (adaptive_qmix.baselines.plans: make_plan, coarse grid, fine rule) and from
Amendment 002 / the min-7 study (amendments/fixed_timing_min7: short-cycle audit, structural-floor extension,
realized-plan identity, fine union around every alias). Nothing is tuned here; only the admissibility
threshold changes between the two versions:

  version "g5"  : the original admissibility g_H >= 5 and g_V >= 5 (the frozen classical-benchmark rule; there
                  is no other minimum green), structural floor C = 16 s;
  version "min7": g_H >= 7 and g_V >= 7, structural floor C = 20 s.

Stages: coarse = original grid C 40..140 step 10 (1980 labels) + short cycles {20, 25, 30, 35} + the floor
extension C in [2*g_min + 6, 20) (16..19 for g5, empty for min7), splits 0.30..0.75 step 0.05, offsets
0, s, 2s, .., < C with s = offset_step (5 in the original procedure; 10 in the reduced variant decided on
2026-11-07, before any result: plans/PLAN_COMPARATEURS.md, deviation D1); ranking unit = realized plan (C, g_H, g_V, offset mod C); top 5; fine = frozen rule (C +/-10
step 5 clipped to [floor, 140], split +/-0.050 step 0.025 in [0.25, 0.80], offset +/-10 step 1) around every
coarse alias of each winner, union collapsed to realized plans; top 10 on design; selection on validation.
"""
from __future__ import absolute_import

from adaptive_qmix.baselines import plans as P

VERSIONS = {"g5": 5, "min7": 7}
SHORT_CYCLES_S = (20, 25, 30, 35)
COARSE_RETAINED = 5
FINE_RETAINED = 10


def admissible(plan, min_green):
    return int(plan["green_H_s"]) >= min_green and int(plan["green_V_s"]) >= min_green


def floor_cycle(min_green):
    return 2 * int(min_green) + P.LOST_TIME_S


def realized_key(plan):
    cycle = int(plan["cycle_s"])
    return (cycle, int(plan["green_H_s"]), int(plan["green_V_s"]), int(plan["offset_s"]) % cycle)


def label_key(plan):
    return P.candidate_key(plan)


ORIGINAL_OFFSET_STEP_S = P.COARSE_OFFSET_STEP_S       # 5 s


def _grid(cycles, offset_step=ORIGINAL_OFFSET_STEP_S):
    out = []
    for cycle in cycles:
        for split in P.COARSE_SPLIT_THOUSANDTHS:
            for offset in range(0, cycle, int(offset_step)):
                out.append(P.make_plan(cycle, split, offset))
    return out


def coarse_parts(min_green, offset_step=ORIGINAL_OFFSET_STEP_S):
    floor = tuple(range(floor_cycle(min_green), min(SHORT_CYCLES_S)))
    parts = {"original": _grid(P.COARSE_CYCLES_S, offset_step), "short": _grid(SHORT_CYCLES_S, offset_step),
             "floor": _grid(floor, offset_step)}
    return dict((k, [p for p in v if admissible(p, min_green)]) for k, v in parts.items()), floor


def coarse_labels(min_green, offset_step=ORIGINAL_OFFSET_STEP_S):
    parts, _floor = coarse_parts(min_green, offset_step)
    return parts["original"] + parts["short"] + parts["floor"]


def groups(labels):
    """realized key -> its labels, lowest label first (the canonical name of the plan)."""
    out = {}
    for plan in labels:
        out.setdefault(realized_key(plan), []).append(dict(plan))
    for members in out.values():
        members.sort(key=label_key)
    return out


def canonical(labels):
    """One plan per realized key (its lowest label), ordered by realized key."""
    g = groups(labels)
    return [g[k][0] for k in sorted(g)]


def fine_candidates(winners, min_green):
    bounds = (floor_cycle(min_green), P.CYCLE_BOUNDS_S[1])
    seen, out = set(), []
    for winner in winners:
        cycles = P._clipped_range(int(winner["cycle_s"]), P.FINE_CYCLE_DELTA_S, P.FINE_CYCLE_STEP_S, bounds)
        splits = P._clipped_range(int(winner["split_thousandths"]), P.FINE_SPLIT_DELTA_THOUSANDTHS,
                                  P.FINE_SPLIT_STEP_THOUSANDTHS, P.SPLIT_BOUNDS_THOUSANDTHS)
        centre = int(winner["offset_s"])
        for cycle in cycles:
            for split in splits:
                for raw in range(centre - P.FINE_OFFSET_DELTA_S, centre + P.FINE_OFFSET_DELTA_S + 1,
                                 P.FINE_OFFSET_STEP_S):
                    plan = P.make_plan(cycle, split, raw % cycle)
                    if admissible(plan, min_green) and label_key(plan) not in seen:
                        seen.add(label_key(plan))
                        out.append(plan)
    return out


def fine_union(winner_keys, min_green, offset_step=ORIGINAL_OFFSET_STEP_S):
    """Realized plans of the fine union around EVERY coarse alias of every winning realized plan."""
    g = groups(coarse_labels(min_green, offset_step))
    seeds = []
    for key in winner_keys:
        if tuple(key) not in g:
            raise ValueError("winner {} is not a coarse plan".format(key))
        seeds.extend(g[tuple(key)])
    return canonical(fine_candidates(seeds, min_green))


def report(min_green, offset_step=ORIGINAL_OFFSET_STEP_S):
    parts, floor = coarse_parts(min_green, offset_step)
    combined = coarse_labels(min_green, offset_step)
    return {"min_green_s": min_green, "structural_floor_cycle_s": floor_cycle(min_green),
            "coarse_offset_step_s": int(offset_step),
            "floor_cycles_s": list(floor),
            "labels": dict((k, len(v)) for k, v in parts.items()),
            "realized_plans": dict((k, len(groups(v))) for k, v in parts.items()),
            "combined_labels": len(combined), "combined_realized_plans": len(groups(combined))}


def fine_bound(min_green, already=(), offset_step=ORIGINAL_OFFSET_STEP_S):
    """Upper bound on NEW fine plans for 5 winners (largest five single-winner unions minus `already`)."""
    g = groups(coarse_labels(min_green, offset_step))
    done = set(tuple(k) for k in already) | set(g)
    sizes = []
    by_cycle = {}
    for key, aliases in g.items():
        union = set(realized_key(p) for p in fine_candidates(aliases, min_green)) - done
        sizes.append(len(union))
        by_cycle.setdefault(key[0], []).append(len(union))
    sizes.sort(reverse=True)
    return {"upper_bound_new_plans": sum(sizes[:COARSE_RETAINED]),
            "max_one_winner_by_cycle": dict((c, max(v)) for c, v in sorted(by_cycle.items()))}
