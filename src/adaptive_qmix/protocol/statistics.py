"""The statistical protocol, fixed before any number is produced.

The inferential unit is the TRAINING SEED, not the evaluation episode. Ten
episodes of one policy are ten measurements of that policy, not ten
independent draws of "QMIX": treating them as independent would shrink the
interval by roughly the square root of ten and manufacture significance out of
evaluation noise. So the bootstrap resamples training seeds at the outer
level and, within each resampled seed, its final-test episodes at the inner
level -- a hierarchical paired bootstrap.

Pairing. Every method is evaluated on the same final-test seeds, so a
difference is taken WITHIN a seed before anything is averaged. That removes
the traffic realisation from the comparison, which is the largest nuisance
term; an unpaired comparison of the same data would be far noisier and would
not be the preregistered quantity.

Checkpoint selection sees only learner_validation. Selecting on final_test
would be choosing the answer, and selecting on the training seeds' own
episodes would reward overfitting. The tie-break ends at "earliest
checkpoint", which is the conservative direction: given equal validation
performance, less training is the smaller claim.
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
    "resampling": "hierarchical paired bootstrap",
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


def hierarchical_paired_bootstrap(treatment, comparator,
                                  replicates=BOOTSTRAP_REPLICATES,
                                  confidence=CONFIDENCE_LEVEL,
                                  rng_seed=BOOTSTRAP_RNG_NAMESPACE):
    """Paired CI for mean(treatment - comparator), resampling seeds then episodes.

    Both arguments map training seed -> {evaluation seed: metric}. The two must
    share their training seeds and evaluation seeds exactly, which is what
    makes the comparison paired; the difference is formed per evaluation seed
    before any averaging.
    """
    treatment_seeds, treatment_episodes = _check_panel(treatment, "treatment")
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
            "{}.".format(list(treatment_episodes), list(comparator_episodes))
        )
    left = _as_matrix(treatment, treatment_seeds, treatment_episodes)
    right = _as_matrix(comparator, comparator_seeds, comparator_episodes)
    if not (np.all(np.isfinite(left)) and np.all(np.isfinite(right))):
        raise StatisticsError(
            "Non-finite metrics reached the bootstrap. A failed run "
            "contributes NaN and must be excluded by the validity gates, not "
            "resampled."
        )

    # Difference within each (training seed, evaluation seed) cell: the
    # traffic realisation cancels before anything is averaged.
    differences = left - right
    per_seed_mean = differences.mean(axis=1)
    observed = float(per_seed_mean.mean())

    seed_count, episode_count = differences.shape
    generator = np.random.Generator(np.random.PCG64(
        np.random.SeedSequence([int(rng_seed), seed_count, episode_count])
    ))
    replicate_means = np.empty(int(replicates), dtype=np.float64)
    for index in range(int(replicates)):
        seed_draw = generator.integers(0, seed_count, size=seed_count)
        resampled = differences[seed_draw, :]
        episode_draw = generator.integers(
            0, episode_count, size=(seed_count, episode_count)
        )
        inner = np.take_along_axis(resampled, episode_draw, axis=1)
        replicate_means[index] = inner.mean(axis=1).mean()

    alpha = (1.0 - float(confidence)) / 2.0
    low = float(np.percentile(replicate_means, 100.0 * alpha))
    high = float(np.percentile(replicate_means, 100.0 * (1.0 - alpha)))
    return {
        "observed_mean_difference": observed,
        "ci_low": low,
        "ci_high": high,
        "confidence": float(confidence),
        "replicates": int(replicates),
        "training_seed_count": seed_count,
        "evaluation_seed_count": episode_count,
        "training_seeds": list(treatment_seeds),
        "evaluation_seeds": list(treatment_episodes),
        "entirely_below_zero": bool(high < 0.0),
        "per_training_seed_difference": [float(v) for v in per_seed_mean],
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


def summarise_comparison(name, treatment, comparator, training_success_count,
                         replicates=BOOTSTRAP_REPLICATES):
    """Everything the protocol requires reported for one comparison."""
    bootstrap = hierarchical_paired_bootstrap(
        treatment, comparator, replicates=replicates
    )
    per_seed = bootstrap["per_training_seed_difference"]
    treatment_means = [
        float(np.mean(list(treatment[seed].values())))
        for seed in bootstrap["training_seeds"]
    ]
    comparator_means = [
        float(np.mean(list(comparator[seed].values())))
        for seed in bootstrap["training_seeds"]
    ]
    outperforming = sum(1 for value in per_seed if value < 0.0)
    trials = len(bootstrap["training_seeds"])
    return {
        "comparison": name,
        "protocol_version": PROTOCOL_VERSION,
        "treatment_mean": float(np.mean(treatment_means)),
        "treatment_sd": (
            float(np.std(treatment_means, ddof=1))
            if len(treatment_means) > 1 else float("nan")
        ),
        "comparator_mean": float(np.mean(comparator_means)),
        "comparator_sd": (
            float(np.std(comparator_means, ddof=1))
            if len(comparator_means) > 1 else float("nan")
        ),
        "paired_difference": bootstrap["observed_mean_difference"],
        "ci_95": [bootstrap["ci_low"], bootstrap["ci_high"]],
        "entirely_below_zero": bootstrap["entirely_below_zero"],
        "paired_cohen_dz": paired_cohen_dz(per_seed),
        "training_success_count": int(training_success_count),
        "training_seed_total": len(TRAINING_SEEDS),
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
