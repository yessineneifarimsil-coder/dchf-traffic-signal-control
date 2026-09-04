"""Benchmark plan optimisation: design first, validation second, final never.

The protocol is deliberately rigid, because a classical baseline that was
tuned on the same seeds it is reported on is not a baseline, it is an upper
bound fitted to the test set.

    design      benchmark_design      seeds 2001-2005   ranks candidates
    validation  benchmark_validation  seeds 2101-2105   selects one
    final       final_test            seeds 3001-3010   never touched here

The final family is refused by assert_family_allowed, which every entry point
in this module calls. There is no flag to override it: reaching final_test
requires a different call site, made after the plan is frozen.

Clearance failure. A candidate whose evaluation did not clear is not given a
finite J_primary to rank on -- imputing one would reward a plan for the
vehicles it never served. The rule is deterministic and applies at every
stage:

  * a candidate is VALID only if every one of its seed runs cleared and every
    run reports J_primary_valid;
  * valid candidates rank before invalid ones, always;
  * invalid candidates rank among themselves by how many seeds failed, then by
    their identity key, so the ordering is total and reproducible;
  * an invalid candidate is never selected while any valid candidate exists,
    and if none is valid the selection raises rather than returning a plan
    that cannot serve the demand.
"""

from __future__ import absolute_import

import math

from .plans import candidate_key


DESIGN_FAMILY = "benchmark_design"
VALIDATION_FAMILY = "benchmark_validation"
FINAL_FAMILY = "final_test"

DESIGN_SEEDS = (2001, 2002, 2003, 2004, 2005)
VALIDATION_SEEDS = (2101, 2102, 2103, 2104, 2105)
FINAL_SEEDS = (3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008, 3009, 3010)

FORBIDDEN_FAMILIES = (FINAL_FAMILY,)
FORBIDDEN_SEEDS = frozenset(FINAL_SEEDS)

SEARCH_FAMILIES = (DESIGN_FAMILY, VALIDATION_FAMILY)

COARSE_RETAINED = 5
FINE_RETAINED = 10
OFFSET_RETAINED = 10

PRIMARY_FIELD = "J_primary_mean_scheduled_waiting_burden_s"
TIME_LOSS_FIELD = "mean_completed_time_loss_s"


class LeakageError(RuntimeError):
    """Raised when search code reaches for a held-out family or seed."""


class SelectionError(RuntimeError):
    pass


def assert_family_allowed(family, seeds=None):
    """Refuse the held-out family, and any final-test seed, unconditionally."""
    if family in FORBIDDEN_FAMILIES:
        raise LeakageError(
            "Family {!r} is held out for final evaluation and must never be "
            "generated, opened or evaluated by search code. Freeze the plan "
            "first.".format(family)
        )
    if family not in SEARCH_FAMILIES:
        raise LeakageError(
            "Search may only use {}; got {!r}.".format(SEARCH_FAMILIES, family)
        )
    if seeds is not None:
        trespassing = sorted(FORBIDDEN_SEEDS.intersection(int(s) for s in seeds))
        if trespassing:
            raise LeakageError(
                "Seeds {} belong to the held-out final test.".format(trespassing)
            )
    return True


def seeds_for(family):
    assert_family_allowed(family)
    return DESIGN_SEEDS if family == DESIGN_FAMILY else VALIDATION_SEEDS


def _mean(values):
    finite = [float(v) for v in values if v is not None and math.isfinite(v)]
    if not finite:
        return float("nan")
    return sum(finite) / float(len(finite))


def summarise_candidate(plan, runs, family):
    """Aggregate one candidate's per-seed runs into a rankable record.

    'runs' are the metrics dicts produced by run_baseline, one per seed.
    """
    assert_family_allowed(family, [run.get("traffic_seed") for run in runs])
    failures = [
        run for run in runs
        if run.get("clearance_status") != "CLEARED"
        or not run.get("J_primary_valid", False)
    ]
    valid = not failures and bool(runs)
    return {
        "plan": dict(plan),
        "key": candidate_key(plan),
        "family": family,
        "seeds": [int(run["traffic_seed"]) for run in runs],
        "run_count": len(runs),
        "valid": valid,
        "failed_seed_count": len(failures),
        "failed_seeds": sorted(int(run["traffic_seed"]) for run in failures),
        "clearance_statuses": [run.get("clearance_status") for run in runs],
        "mean_J_primary_s": (
            _mean([run.get(PRIMARY_FIELD) for run in runs])
            if valid else float("nan")
        ),
        "mean_time_loss_s": (
            _mean([run.get(TIME_LOSS_FIELD) for run in runs])
            if valid else float("nan")
        ),
    }


def _validity_rank(record):
    """Invalid candidates sort after every valid one, deterministically."""
    if record["valid"]:
        return (0, 0)
    return (1, record["failed_seed_count"])


def rank_by_design(records, retain):
    """Order by mean design J_primary and keep the best `retain` candidates."""
    ordered = sorted(
        records,
        key=lambda record: (
            _validity_rank(record),
            record["mean_J_primary_s"] if record["valid"] else float("inf"),
            record["key"],
        ),
    )
    return ordered[: int(retain)]


def select_offset_plan(validation_records):
    """Fixed-offset selection: J_primary, then time loss, then smallest Delta."""
    return _select(
        validation_records,
        lambda record: (
            record["mean_J_primary_s"],
            record["mean_time_loss_s"],
            record["plan"]["offset_s"],
        ),
        "fixed-offset",
    )


def select_timing_plan(validation_records):
    """Fixed-timing selection: J_primary, time loss, shorter cycle, then key."""
    return _select(
        validation_records,
        lambda record: (
            record["mean_J_primary_s"],
            record["mean_time_loss_s"],
            record["plan"]["cycle_s"],
            record["key"],
        ),
        "fixed-timing",
    )


def _select(validation_records, sort_key, label):
    if not validation_records:
        raise SelectionError("No {} candidates to select from.".format(label))
    for record in validation_records:
        if record["family"] != VALIDATION_FAMILY:
            raise SelectionError(
                "Final {} selection must use {} records; got {!r}. Design "
                "results rank candidates, they never select one.".format(
                    label, VALIDATION_FAMILY, record["family"]
                )
            )
    valid = [record for record in validation_records if record["valid"]]
    if not valid:
        raise SelectionError(
            "Every {} candidate failed to clear on validation; no plan may be "
            "selected. Failed seeds: {}".format(
                label,
                sorted(set(
                    seed for record in validation_records
                    for seed in record["failed_seeds"]
                )),
            )
        )
    return sorted(valid, key=sort_key)[0]


def run_selection_protocol(design_records, validation_evaluator, retain,
                           selector):
    """Rank on design, evaluate the survivors on validation, then select.

    validation_evaluator is called with the retained plans and must return
    validation records; it is the only place a validation run happens, which
    keeps the design-then-validation ordering structural rather than a
    convention someone has to remember.
    """
    for record in design_records:
        if record["family"] != DESIGN_FAMILY:
            raise SelectionError(
                "Candidate ranking must use {} records; got {!r}.".format(
                    DESIGN_FAMILY, record["family"]
                )
            )
    retained = rank_by_design(design_records, retain)
    if not retained:
        raise SelectionError("Design ranking retained no candidates.")
    validation_records = validation_evaluator(
        [record["plan"] for record in retained]
    )
    selected = selector(validation_records)
    return {
        "retained_design_keys": [record["key"] for record in retained],
        "design_record_count": len(design_records),
        "validation_record_count": len(validation_records),
        "selected": selected,
        "selected_plan": dict(selected["plan"]),
        "protocol": (
            "ranked on {} seeds {}; selected on {} seeds {}; {} untouched"
            .format(DESIGN_FAMILY, list(DESIGN_SEEDS), VALIDATION_FAMILY,
                    list(VALIDATION_SEEDS), FINAL_FAMILY)
        ),
    }
