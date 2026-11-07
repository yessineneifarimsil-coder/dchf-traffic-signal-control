"""Traffic seed registry of the robustness profiles (fixed before any comparator or confirmation run).

All seeds belong to the robustness family (code 80) and go through tools/robustness/scenario_traffic.py, whose
generator mixes the scenario code into the stream, so seed s of R0 and seed s of R1 are different traffics. Per
profile with scenario code c (R0..R4 -> 0..4):

  robustness evaluation   8c01-8c05   already used by the robustness validation: never used to design anything
  comparator design       8c11-8c15   rank candidates (A1, A2, A3)
  comparator validation   8c21-8c25   select one candidate per comparator (A1, A2, A3)
  confirmation (reserved) 8c51-8c60   plan B only; refused by every search and design entry point

Seeds 3001-3010 (old final traffics) and 3101-3120 stay refused by the generator itself.
"""
from __future__ import absolute_import

PROFILES = ("R0_reference", "R1_sparse_secondary_heavy_main", "R2_single_secondary_trickle", "R3_time_varying",
            "R4_isolated_tail")
CODES = dict((p, i) for i, p in enumerate(PROFILES))
ROLE_OFFSETS = {"robustness_evaluation": (1, 5), "comparator_design": (11, 15), "comparator_validation": (21, 25),
                "confirmation": (51, 60)}
SEARCH_ROLES = ("comparator_design", "comparator_validation")


class SeedError(RuntimeError):
    pass


def seeds(profile, role):
    code = CODES[profile]
    first, last = ROLE_OFFSETS[role]
    return tuple(8000 + 100 * code + k for k in range(first, last + 1))


def role_of(profile, seed):
    for role in ROLE_OFFSETS:
        if int(seed) in seeds(profile, role):
            return role
    return None


def assert_search_seed(profile, seed):
    """Search code may only touch design and validation seeds of the profile."""
    role = role_of(profile, seed)
    if role not in SEARCH_ROLES:
        raise SeedError("seed {} of {} has role {!r}: not usable by a comparator search".format(seed, profile, role))
    return role


def registry():
    return dict((p, dict((r, list(seeds(p, r))) for r in ROLE_OFFSETS)) for p in PROFILES)


def check_disjoint():
    every = [s for p in PROFILES for r in ROLE_OFFSETS for s in seeds(p, r)]
    if len(every) != len(set(every)):
        raise SeedError("seed registry overlaps")
    forbidden = set(range(3001, 3011)) | set(range(3101, 3121))
    if forbidden & set(every):
        raise SeedError("registry touches the final-test seeds")
    return True
