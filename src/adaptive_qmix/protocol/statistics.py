"""The statistical protocol, fixed before any number is produced.

The design is CROSSED, not nested: ten training seeds are each evaluated on
the SAME ten final traffic seeds, so the data form a 10 x 10 matrix rather
than ten independent clusters of ten. Resampling it as if it were nested --
drawing training seeds, then drawing fresh episodes inside each one -- would
misstate the traffic factor, because a traffic seed that appears for one
training seed appears for all of them and its effect is shared, not
independent noise within a cluster.

So this is a PAIRED CROSSED TWO-FACTOR BOOTSTRAP. Each replicate draws one
sample of training-seed indices and one sample of traffic-seed indices, and
evaluates the full Cartesian product of the two: the same resampled traffic
columns apply to every resampled training row. Both sources of variation are
propagated, and neither is double-counted.

Pairing is preserved inside every (training seed, traffic seed) cell: the
difference between methods is formed there, before anything is averaged, so
the traffic realisation cancels rather than being averaged over.

Two comparator kinds, deliberately distinguished:

  LEARNED comparator (QMIX vs IDQN or VDN) -- both sides have ten training
  seeds, paired 101..110, and the difference is taken within the matching
  training seed as well as the matching traffic seed.

  DETERMINISTIC comparator (optimized fixed timing, canonical max pressure,
  P-5) -- it has no training seed. It contributes ONE value per final traffic
  seed, reused across the ten learned training seeds to form
  D_ij = J_learned(i, j) - J_baseline(j). It is emphatically NOT treated as
  ten independently trained samples: doing so would invent nine replications
  that were never run and shrink the interval accordingly.

Checkpoint selection sees only learner_validation. Selecting on final_test
would be choosing the answer, and selecting on the training seeds' own
episodes would reward overfitting. The tie-break ends at "earliest
checkpoint", which is the conservative direction: given equal validation
performance, less training is the smaller claim.

Training success is a PROCESS property, defined in TRAINING_SUCCESS_DEFINITION
and never a performance one: a seed counts as successful if its run completed
under contract and a checkpoint was validly selected, whatever the final
numbers turn out to be. How often the learned method actually beat its
comparator is reported separately, as
fraction_of_training_seeds_outperforming_comparator.
"""

from __future__ import absolute_import

import hashlib
import json
import math

import numpy as np


PROTOCOL_VERSION = "statistics-1.0"

TRAINING_SEEDS = tuple(range(101, 111))
LEARNER_VALIDATION_FAMILY = "learner_validation"
LEARNER_VALIDATION_SEEDS = (2201, 2202, 2203, 2204, 2205)
FINAL_FAMILY = "final_test"
FINAL_SEEDS = tuple(range(3001, 3011))

CHECKPOINT_TRANSITIONS = (
    50000, 75000, 100000, 125000, 150000, 175000, 200000, 225000, 250000,
    275000, 300000, 325000, 350000, 360000,
)

BOOTSTRAP_REPLICATES = 10000
CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_RNG_NAMESPACE = 0x53544154  # "STAT"

PRIMARY_FIELD = "J_primary_mean_scheduled_waiting_burden_s"
TIE_FIELD = "mean_completed_time_loss_s"

INFERENTIAL_UNIT = "training_seed"
RESAMPLING_DESIGN = "paired crossed two-factor bootstrap"

COMPARATOR_LEARNED = "learned"
COMPARATOR_DETERMINISTIC = "deterministic"

TRAINING_BUDGET_TRANSITIONS = 360000

TRAINING_SUCCESS_DEFINITION = {
    "definition_version": "training-success-1.0",
    "criteria": [
        "the full {} transition training run completed under "
        "contract".format(TRAINING_BUDGET_TRANSITIONS),
        "every required checkpoint exists",
        "exactly one checkpoint was validly selected on learner_validation "
        "seeds 2201-2205",
    ],
    "explicitly_not": (
        "Training success is never defined using final-test performance. How "
        "often a learned seed actually beat its comparator is reported "
        "separately as "
        "fraction_of_training_seeds_outperforming_comparator."
    ),
}

REPORTED_QUANTITIES = (
    "mean", "sd", "paired_difference", "ci_95", "paired_cohen_dz",
    "training_success_count", "wilson_interval",
    "fraction_of_training_seeds_outperforming_comparator",
)


class StatisticsError(RuntimeError):
    pass


PROTOCOL = {
    "protocol_version": PROTOCOL_VERSION,
    "training_seeds": list(TRAINING_SEEDS),
    "checkpoint_transitions": list(CHECKPOINT_TRANSITIONS),
    "checkpoint_selection_family": LEARNER_VALIDATION_FAMILY,
    "checkpoint_selection_seeds": list(LEARNER_VALIDATION_SEEDS),
    "checkpoint_selection_rule": [
        "minimum mean validation J_primary",
        "minimum mean validation time loss",
        "earliest checkpoint",
    ],
    "final_family": FINAL_FAMILY,
    "final_seeds": list(FINAL_SEEDS),
    "inferential_unit": INFERENTIAL_UNIT,
    "resampling": RESAMPLING_DESIGN,
    "design": "crossed: 10 training seeds x the same 10 final traffic seeds",
    "comparator_kinds": {
        COMPARATOR_LEARNED: (
            "ten training seeds, paired 101-110 with the treatment"
        ),
        COMPARATOR_DETERMINISTIC: (
            "one value per final traffic seed, reused across the ten learned "
            "training seeds to form D_ij = J_learned(i,j) - J_baseline(j); "
            "never treated as ten independently trained samples"
        ),
    },
    "training_success_definition": TRAINING_SUCCESS_DEFINITION,
    "bootstrap_replicates": BOOTSTRAP_REPLICATES,
    "confidence_level": CONFIDENCE_LEVEL,
    "pairing": "all methods share the final-test seeds; differences are taken within a seed",
    "reported_quantities": list(REPORTED_QUANTITIES),
}


def protocol_sha256():
    payload = json.dumps(
        PROTOCOL, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def select_checkpoint(validation_records):
    """Minimum mean J_primary, then mean time loss, then earliest checkpoint.

    'validation_records' are per-checkpoint dicts carrying 'transition_index',
    'mean_J_primary_s', 'mean_time_loss_s' and the seeds they were measured on.
    """
    if not validation_records:
        raise StatisticsError("No validation records to select a checkpoint.")
    for record in validation_records:
        family = record.get("family", LEARNER_VALIDATION_FAMILY)
        if family != LEARNER_VALIDATION_FAMILY:
            raise StatisticsError(
                "Checkpoint selection may use only {}; got {!r}. Selecting on "
                "final_test would be choosing the answer.".format(
                    LEARNER_VALIDATION_FAMILY, family
                )
            )
        seeds = tuple(sorted(record.get("seeds", LEARNER_VALIDATION_SEEDS)))
        if seeds != LEARNER_VALIDATION_SEEDS:
            raise StatisticsError(
                "Checkpoint selection requires exactly the seeds {}; got "
                "{}.".format(list(LEARNER_VALIDATION_SEEDS), list(seeds))
            )
        if int(record["transition_index"]) not in CHECKPOINT_TRANSITIONS:
            raise StatisticsError(
                "Checkpoint {} is not one of the preregistered "
                "checkpoints.".format(record["transition_index"])
            )
    ordered = sorted(
        validation_records,
        key=lambda record: (
            float(record["mean_J_primary_s"]),
            float(record["mean_time_loss_s"]),
            int(record["transition_index"]),
        ),
    )
    chosen = dict(ordered[0])
    chosen["selection_rule"] = PROTOCOL["checkpoint_selection_rule"]
    chosen["selected_on_family"] = LEARNER_VALIDATION_FAMILY
    return chosen


def _as_matrix(values_by_seed, seeds, episodes):
    matrix = np.empty((len(seeds), len(episodes)), dtype=np.float64)
    for row, seed in enumerate(seeds):
        per_episode = values_by_seed[seed]
        for column, episode in enumerate(episodes):
            matrix[row, column] = float(per_episode[episode])
    return matrix


def _check_panel(values_by_seed, name):
    if not values_by_seed:
        raise StatisticsError("{} carries no training seeds.".format(name))
    seeds = tuple(sorted(values_by_seed))
    episodes = tuple(sorted(values_by_seed[seeds[0]]))
    for seed in seeds:
        if tuple(sorted(values_by_seed[seed])) != episodes:
            raise StatisticsError(
                "{}: training seed {} was evaluated on {} but seed {} on {}. "
                "Pairing requires the same evaluation seeds "
                "throughout.".format(
                    name, seed, sorted(values_by_seed[seed]), seeds[0],
                    list(episodes),
                )
            )
    return seeds, episodes


def difference_matrix(treatment, comparator, comparator_kind=None):
    """The (training seed x traffic seed) matrix of paired differences.

    A learned comparator supplies its own training seeds, paired one to one.
    A deterministic comparator supplies one value per traffic seed, which is
    broadcast down the training-seed axis to form D_ij = J_learned(i,j) -
    J_baseline(j); the broadcast is a statement that the baseline was measured
    once per traffic realisation, not ten times.
    """
    treatment_seeds, treatment_episodes = _check_panel(treatment, "treatment")
    left = _as_matrix(treatment, treatment_seeds, treatment_episodes)

    if _looks_deterministic(comparator):
        if comparator_kind == COMPARATOR_LEARNED:
            raise StatisticsError(
                "comparator_kind is 'learned' but the comparator supplies one "
                "value per traffic seed."
            )
        missing = [
            episode for episode in treatment_episodes
            if episode not in comparator
        ]
        if missing or len(comparator) != len(treatment_episodes):
            raise StatisticsError(
                "A deterministic comparator needs exactly one value for each "
                "of the traffic seeds {}; got {}.".format(
                    list(treatment_episodes), sorted(comparator)
                )
            )
        row = np.asarray(
            [float(comparator[episode]) for episode in treatment_episodes],
            dtype=np.float64,
        )
        # One row, broadcast: the baseline is not ten trained samples.
        right = np.broadcast_to(row, left.shape)
        kind = COMPARATOR_DETERMINISTIC
        comparator_seeds = None
    else:
        if comparator_kind == COMPARATOR_DETERMINISTIC:
            raise StatisticsError(
                "comparator_kind is 'deterministic' but the comparator "
                "supplies per-training-seed panels."
            )
        comparator_seeds, comparator_episodes = _check_panel(
            comparator, "comparator"
        )
        if treatment_seeds != comparator_seeds:
            raise StatisticsError(
                "Unpaired training seeds: treatment {} versus comparator "
                "{}.".format(list(treatment_seeds), list(comparator_seeds))
            )
        if treatment_episodes != comparator_episodes:
            raise StatisticsError(
                "Unpaired evaluation seeds: treatment {} versus comparator "
                "{}.".format(
                    list(treatment_episodes), list(comparator_episodes)
                )
            )
        right = _as_matrix(comparator, comparator_seeds, treatment_episodes)
        kind = COMPARATOR_LEARNED

    if not (np.all(np.isfinite(left)) and np.all(np.isfinite(right))):
        raise StatisticsError(
            "Non-finite metrics reached the bootstrap. A failed run "
            "contributes NaN and must be excluded by the validity gates, not "
            "resampled."
        )
    return {
        "differences": left - right,
        "training_seeds": treatment_seeds,
        "traffic_seeds": treatment_episodes,
        "comparator_kind": kind,
        "comparator_training_seeds": (
            None if comparator_seeds is None else list(comparator_seeds)
        ),
    }


def _looks_deterministic(comparator):
    """A flat {traffic seed: value} mapping rather than nested panels."""
    if not comparator:
        raise StatisticsError("The comparator carries no values.")
    first = next(iter(comparator.values()))
    return not isinstance(first, dict)


def replicate_indices(generator, row_count, column_count):
    """One draw of training-seed rows and one of traffic-seed columns.

    Drawn once per replicate each, never once per row: the same resampled
    traffic seeds must apply to every resampled training seed, because in the
    real design every training seed met the same ten traffic realisations.
    """
    rows = generator.integers(0, row_count, size=row_count)
    columns = generator.integers(0, column_count, size=column_count)
    return rows, columns


def crossed_replicate_mean(differences, rows, columns):
    """Mean over the Cartesian product of the sampled rows and columns."""
    return float(differences[np.ix_(rows, columns)].mean())


def paired_crossed_bootstrap(treatment, comparator,
                             replicates=BOOTSTRAP_REPLICATES,
                             confidence=CONFIDENCE_LEVEL,
                             rng_seed=BOOTSTRAP_RNG_NAMESPACE,
                             comparator_kind=None, draw_log=None):
    """Paired CI for mean(treatment - comparator) on the crossed design.

    Each replicate resamples training-seed indices once and traffic-seed
    indices once, then evaluates the whole sampled matrix. Pass a list as
    draw_log to capture the draws actually used, which is how the crossed
    structure is checked rather than assumed.
    """
    built = difference_matrix(treatment, comparator, comparator_kind)
    differences = built["differences"]
    observed = float(differences.mean())
    per_training_seed = differences.mean(axis=1)
    per_traffic_seed = differences.mean(axis=0)

    row_count, column_count = differences.shape
    generator = np.random.Generator(np.random.PCG64(
        np.random.SeedSequence([int(rng_seed), row_count, column_count])
    ))
    replicate_means = np.empty(int(replicates), dtype=np.float64)
    for index in range(int(replicates)):
        rows, columns = replicate_indices(generator, row_count, column_count)
        if draw_log is not None:
            draw_log.append(
                {"rows": rows.tolist(), "columns": columns.tolist()}
            )
        replicate_means[index] = crossed_replicate_mean(
            differences, rows, columns
        )

    alpha = (1.0 - float(confidence)) / 2.0
    low = float(np.percentile(replicate_means, 100.0 * alpha))
    high = float(np.percentile(replicate_means, 100.0 * (1.0 - alpha)))
    return {
        "observed_mean_difference": observed,
        "ci_low": low,
        "ci_high": high,
        "confidence": float(confidence),
        "replicates": int(replicates),
        "resampling": RESAMPLING_DESIGN,
        "comparator_kind": built["comparator_kind"],
        "training_seed_count": row_count,
        "evaluation_seed_count": column_count,
        "training_seeds": list(built["training_seeds"]),
        "evaluation_seeds": list(built["traffic_seeds"]),
        "entirely_below_zero": bool(high < 0.0),
        "per_training_seed_difference": [
            float(value) for value in per_training_seed
        ],
        "per_traffic_seed_difference": [
            float(value) for value in per_traffic_seed
        ],
        "inferential_unit": INFERENTIAL_UNIT,
    }


def paired_cohen_dz(per_seed_differences):
    """Cohen's d_z: mean paired difference over its SD, across training seeds."""
    values = np.asarray(list(per_seed_differences), dtype=np.float64)
    if values.size < 2:
        return float("nan")
    sd = float(values.std(ddof=1))
    if sd == 0.0:
        return float("inf") if values.mean() != 0 else 0.0
    return float(values.mean() / sd)


def wilson_interval(successes, trials, confidence=CONFIDENCE_LEVEL):
    """Wilson score interval, which behaves at 0/10 and 10/10 where Wald does not."""
    successes, trials = int(successes), int(trials)
    if trials <= 0:
        raise StatisticsError("Wilson interval needs at least one trial.")
    if not 0 <= successes <= trials:
        raise StatisticsError(
            "successes must lie in [0, trials]; got {}/{}.".format(
                successes, trials
            )
        )
    # Two-sided normal quantile for the requested confidence.
    z = {0.90: 1.6448536269514722,
         0.95: 1.959963984540054,
         0.99: 2.5758293035489004}.get(float(confidence))
    if z is None:
        raise StatisticsError(
            "Unsupported confidence {!r} for the Wilson interval.".format(
                confidence
            )
        )
    proportion = successes / float(trials)
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2.0 * trials)) / denominator
    spread = (
        z * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z * z / (4.0 * trials * trials)
        ) / denominator
    )
    return {
        "successes": successes,
        "trials": trials,
        "proportion": proportion,
        "ci_low": max(0.0, centre - spread),
        "ci_high": min(1.0, centre + spread),
        "confidence": float(confidence),
        "method": "wilson_score",
    }


def training_seed_succeeded(record):
    """Process-only success, per TRAINING_SUCCESS_DEFINITION."""
    if int(record.get("transitions_completed", -1)) != (
        TRAINING_BUDGET_TRANSITIONS
    ):
        return False
    if not bool(record.get("completed_under_contract", False)):
        return False
    present = set(int(value) for value in record.get("checkpoints_present", []))
    if not set(CHECKPOINT_TRANSITIONS) <= present:
        return False
    selected = record.get("selected_checkpoint") or {}
    if int(selected.get("transition_index", -1)) not in CHECKPOINT_TRANSITIONS:
        return False
    if selected.get("selected_on_family") != LEARNER_VALIDATION_FAMILY:
        return False
    seeds = tuple(sorted(selected.get("selected_on_seeds", ())))
    return seeds == LEARNER_VALIDATION_SEEDS


def count_training_successes(records):
    """How many training seeds completed the process, not how many won."""
    seeds = sorted(int(record["training_seed"]) for record in records)
    if seeds != sorted(TRAINING_SEEDS):
        raise StatisticsError(
            "Training success is counted over exactly the training seeds {}; "
            "got {}.".format(list(TRAINING_SEEDS), seeds)
        )
    return sum(1 for record in records if training_seed_succeeded(record))


def summarise_comparison(name, treatment, comparator, training_success_count,
                         replicates=BOOTSTRAP_REPLICATES,
                         comparator_kind=None):
    """Everything the protocol requires reported for one comparison."""
    bootstrap = paired_crossed_bootstrap(
        treatment, comparator, replicates=replicates,
        comparator_kind=comparator_kind,
    )
    per_seed = bootstrap["per_training_seed_difference"]
    treatment_means = [
        float(np.mean(list(treatment[seed].values())))
        for seed in bootstrap["training_seeds"]
    ]
    if bootstrap["comparator_kind"] == COMPARATOR_DETERMINISTIC:
        # One value per traffic seed; its mean is a single number, and its SD
        # is across traffic seeds rather than across training seeds.
        comparator_values = [
            float(comparator[episode])
            for episode in bootstrap["evaluation_seeds"]
        ]
    else:
        comparator_values = [
            float(np.mean(list(comparator[seed].values())))
            for seed in bootstrap["training_seeds"]
        ]
    outperforming = sum(1 for value in per_seed if value < 0.0)
    trials = len(bootstrap["training_seeds"])
    return {
        "comparison": name,
        "protocol_version": PROTOCOL_VERSION,
        "resampling": RESAMPLING_DESIGN,
        "comparator_kind": bootstrap["comparator_kind"],
        "treatment_mean": float(np.mean(treatment_means)),
        "treatment_sd": (
            float(np.std(treatment_means, ddof=1))
            if len(treatment_means) > 1 else float("nan")
        ),
        "comparator_mean": float(np.mean(comparator_values)),
        "comparator_sd": (
            float(np.std(comparator_values, ddof=1))
            if len(comparator_values) > 1 else float("nan")
        ),
        "comparator_sd_axis": (
            "traffic_seed"
            if bootstrap["comparator_kind"] == COMPARATOR_DETERMINISTIC
            else "training_seed"
        ),
        "paired_difference": bootstrap["observed_mean_difference"],
        "ci_95": [bootstrap["ci_low"], bootstrap["ci_high"]],
        "entirely_below_zero": bootstrap["entirely_below_zero"],
        "paired_cohen_dz": paired_cohen_dz(per_seed),
        "training_success_count": int(training_success_count),
        "training_seed_total": len(TRAINING_SEEDS),
        "training_success_definition": TRAINING_SUCCESS_DEFINITION,
        "wilson_interval": wilson_interval(
            training_success_count, len(TRAINING_SEEDS)
        ),
        "training_seeds_outperforming_comparator": outperforming,
        "fraction_of_training_seeds_outperforming_comparator": (
            outperforming / float(trials) if trials else float("nan")
        ),
        "per_training_seed_difference": per_seed,
        "bootstrap": bootstrap,
    }
