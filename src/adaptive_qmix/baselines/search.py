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

from .plans import (
    candidate_is_valid as candidate_is_admissible,
    candidate_key,
    coarse_timing_candidates,
    fine_timing_candidates,
    fixed_offset_candidates,
)


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


def required_seeds(family):
    """The exact preregistered seed set a candidate must be evaluated on."""
    assert_family_allowed(family)
    return DESIGN_SEEDS if family == DESIGN_FAMILY else VALIDATION_SEEDS


def assert_exact_seed_set(runs, family):
    """Fail closed unless there is exactly one run per preregistered seed.

    A four-seed mean is not a five-seed mean, and the difference is invisible
    once it has been averaged. Missing, duplicated, extra and foreign seeds are
    all refused here rather than quietly changing what the reported number is.
    """
    expected = required_seeds(family)
    seeds = [int(run["traffic_seed"]) for run in runs]
    seen = {}
    for seed in seeds:
        seen[seed] = seen.get(seed, 0) + 1
    duplicates = sorted(seed for seed, count in seen.items() if count > 1)
    missing = sorted(set(expected) - set(seeds))
    extra = sorted(set(seeds) - set(expected))
    if duplicates or missing or extra or len(runs) != len(expected):
        raise SelectionError(
            "Candidate evaluation on {} must contain exactly one run for each "
            "of {}. Got {} runs {}; missing {}, duplicated {}, unexpected {}. "
            "A mean over the wrong seed set is not the preregistered "
            "quantity.".format(
                family, list(expected), len(runs), sorted(seeds), missing,
                duplicates, extra,
            )
        )
    return tuple(sorted(seeds))


def summarise_candidate(plan, runs, family):
    """Aggregate one candidate's per-seed runs into a rankable record.

    'runs' are the metrics dicts produced by run_baseline, one per seed.
    """
    assert_family_allowed(family, [run.get("traffic_seed") for run in runs])
    seed_set = assert_exact_seed_set(runs, family)
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
        "seeds": list(seed_set),
        "required_seeds": list(required_seeds(family)),
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


def rank_by_design(records, retain):
    """Order valid candidates by mean design J_primary and keep the best N.

    Invalid candidates are excluded outright rather than sorted to the back,
    because a shortlist is a set of candidates that will be evaluated further:
    padding it with plans that could not clear would carry a failure into the
    validation stage and, at the end, into a selection. When too few valid
    candidates exist the shortlist is short by definition, so this raises
    instead of returning one.
    """
    retain = int(retain)
    valid = [record for record in records if record["valid"]]
    if len(valid) < retain:
        invalid = [record for record in records if not record["valid"]]
        raise SelectionError(
            "Design ranking needs {} valid candidates but only {} of {} "
            "cleared on every preregistered seed ({} failed). The shortlist "
            "is never padded with invalid candidates; investigate the failing "
            "runs instead. Failing keys: {}".format(
                retain, len(valid), len(records), len(invalid),
                [record["key"] for record in invalid][:10],
            )
        )
    ordered = sorted(
        valid,
        key=lambda record: (record["mean_J_primary_s"], record["key"]),
    )
    return ordered[:retain]


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


# Stage names, recorded in the protocol output so a later campaign log can be
# read back without knowing the code.
STAGE_COARSE_DESIGN = "coarse_design"
STAGE_FINE_DESIGN = "fine_design"
STAGE_VALIDATION = "validation"
STAGE_SELECTION = "selection"

COARSE_CANDIDATE_COUNT = 1980


def _evaluate_stage(evaluator, candidate_plans, family, stage):
    """Run one evaluation stage and turn it into checked candidate records.

    The evaluator only produces runs; every record is built here through
    summarise_candidate, so the exact-seed rule cannot be bypassed by an
    evaluator that returns a convenient summary of its own.
    """
    assert_family_allowed(family)
    seeds = required_seeds(family)
    run_lists = evaluator(list(candidate_plans), family, list(seeds))
    if len(run_lists) != len(candidate_plans):
        raise SelectionError(
            "Stage {!r} evaluated {} candidates but {} were submitted.".format(
                stage, len(run_lists), len(candidate_plans)
            )
        )
    records = []
    for plan, runs in zip(candidate_plans, run_lists):
        record = summarise_candidate(plan, runs, family)
        record["stage"] = stage
        records.append(record)
    return records


def _stage_report(stage, family, records, retained=None):
    """An auditable trace of one stage: identities, seeds and scores."""
    return {
        "stage": stage,
        "family": family,
        "seeds": list(required_seeds(family)),
        "candidate_count": len(records),
        "valid_count": sum(1 for record in records if record["valid"]),
        "scores": [
            {
                "key": record["key"],
                "plan": dict(record["plan"]),
                "seeds": list(record["seeds"]),
                "valid": record["valid"],
                "failed_seeds": list(record["failed_seeds"]),
                "mean_J_primary_s": record["mean_J_primary_s"],
                "mean_time_loss_s": record["mean_time_loss_s"],
            }
            for record in records
        ],
        "retained_keys": (
            None if retained is None else [record["key"] for record in retained]
        ),
    }


def _frozen_selection(selected, stages, protocol_name):
    return {
        "protocol": protocol_name,
        "selected_plan": dict(selected["plan"]),
        "selected_key": selected["key"],
        "selected_validation_mean_J_primary_s": selected["mean_J_primary_s"],
        "selected_validation_mean_time_loss_s": selected["mean_time_loss_s"],
        "selected_validation_seeds": list(selected["seeds"]),
        "stages": stages,
        "design_family": DESIGN_FAMILY,
        "design_seeds": list(DESIGN_SEEDS),
        "validation_family": VALIDATION_FAMILY,
        "validation_seeds": list(VALIDATION_SEEDS),
        "final_family": FINAL_FAMILY,
        "final_seeds_touched": False,
        "frozen": True,
        "freeze_note": (
            "This plan is frozen. {} seeds {} may be generated or opened only "
            "after this record exists, and never by search code.".format(
                FINAL_FAMILY, list(FINAL_SEEDS)
            )
        ),
    }


def run_fixed_offset_protocol(design_evaluator, validation_evaluator):
    """90 offsets on design, best 10 on validation, then the frozen tie-break.

    The evaluators receive (plans, family, seeds) and return one list of run
    dicts per plan. No SUMO campaign is launched here: this function is the
    protocol, and the campaign is whatever the evaluators do.
    """
    candidates = fixed_offset_candidates()
    if len(candidates) != 90:
        raise SelectionError(
            "The fixed-offset grid must contain 90 candidates; got {}.".format(
                len(candidates)
            )
        )
    design_records = _evaluate_stage(
        design_evaluator, candidates, DESIGN_FAMILY, STAGE_COARSE_DESIGN
    )
    retained = rank_by_design(design_records, OFFSET_RETAINED)
    stages = [
        _stage_report(
            STAGE_COARSE_DESIGN, DESIGN_FAMILY, design_records, retained
        )
    ]
    validation_records = _evaluate_stage(
        validation_evaluator, [record["plan"] for record in retained],
        VALIDATION_FAMILY, STAGE_VALIDATION,
    )
    stages.append(
        _stage_report(STAGE_VALIDATION, VALIDATION_FAMILY, validation_records)
    )
    selected = select_offset_plan(validation_records)
    return _frozen_selection(selected, stages, "optimized_fixed_offset")


def run_fixed_timing_protocol(design_evaluator, validation_evaluator):
    """Coarse design, fine design, validation, selection -- in that order.

    Each stage's gate is structural rather than conventional: the coarse grid
    must be the preregistered 1980 candidates, every candidate must carry the
    exact design seed set, exactly five coarse winners seed the fine
    neighbourhood, exactly ten fine winners reach validation, and only those
    ten are ever evaluated there. The held-out family is never named.
    """
    coarse = coarse_timing_candidates(include_invalid=True)
    if len(coarse) != COARSE_CANDIDATE_COUNT:
        raise SelectionError(
            "The coarse grid must contain {} candidates before rejection; got "
            "{}.".format(COARSE_CANDIDATE_COUNT, len(coarse))
        )
    admissible = [plan for plan in coarse if candidate_is_admissible(plan)]
    coarse_records = _evaluate_stage(
        design_evaluator, admissible, DESIGN_FAMILY, STAGE_COARSE_DESIGN
    )
    coarse_winners = rank_by_design(coarse_records, COARSE_RETAINED)
    if len(coarse_winners) != COARSE_RETAINED:
        raise SelectionError(
            "Exactly {} coarse winners must seed the fine grid.".format(
                COARSE_RETAINED
            )
        )
    stages = [
        _stage_report(
            STAGE_COARSE_DESIGN, DESIGN_FAMILY, coarse_records, coarse_winners
        )
    ]

    fine = fine_timing_candidates([record["plan"] for record in coarse_winners])
    keys = [candidate_key(plan) for plan in fine]
    if len(keys) != len(set(keys)):
        raise SelectionError("The fine grid contains duplicate candidates.")
    fine_records = _evaluate_stage(
        design_evaluator, fine, DESIGN_FAMILY, STAGE_FINE_DESIGN
    )
    fine_winners = rank_by_design(fine_records, FINE_RETAINED)
    stages.append(
        _stage_report(
            STAGE_FINE_DESIGN, DESIGN_FAMILY, fine_records, fine_winners
        )
    )

    validation_records = _evaluate_stage(
        validation_evaluator, [record["plan"] for record in fine_winners],
        VALIDATION_FAMILY, STAGE_VALIDATION,
    )
    if len(validation_records) != FINE_RETAINED:
        raise SelectionError(
            "Exactly {} candidates may reach validation; got {}.".format(
                FINE_RETAINED, len(validation_records)
            )
        )
    stages.append(
        _stage_report(STAGE_VALIDATION, VALIDATION_FAMILY, validation_records)
    )
    selected = select_timing_plan(validation_records)
    result = _frozen_selection(selected, stages, "optimized_fixed_timing")
    result["coarse_candidate_count"] = len(coarse)
    result["coarse_admissible_count"] = len(admissible)
    result["fine_candidate_count"] = len(fine)
    return result
