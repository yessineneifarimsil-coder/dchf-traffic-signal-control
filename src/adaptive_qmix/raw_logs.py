"""Episode-safe reading of the raw run logs.

Simulation time restarts at zero in every episode, and a training run appends
all of its episodes to one CSV per table. Sorting such a file by time silently
interleaves unrelated episodes into a single apparently-continuous trace, which
would corrupt every time-dependent derivation built on top of it.

Every analysis therefore goes through select_episode, which fails closed: it
selects automatically only when the source contains exactly one episode, and
otherwise refuses to proceed until an episode is named.
"""

from __future__ import absolute_import

import csv
import os


EPISODE_FIELD = "episode_index"


class EpisodeSelectionError(RuntimeError):
    pass


def read_raw_csv(path):
    if not os.path.isfile(path):
        raise EpisodeSelectionError("Missing raw log: {}".format(path))
    with open(path, "r", newline="") as handle:
        return list(csv.DictReader(handle))


def read_raw_tables(run_directory, table_names):
    return dict(
        (name, read_raw_csv(os.path.join(run_directory, name + ".csv")))
        for name in table_names
    )


def episode_values(rows, table_name):
    """Episodes present in one table, or a clear error if it cannot say."""
    if not rows:
        return set()
    if EPISODE_FIELD not in rows[0]:
        raise EpisodeSelectionError(
            "Table '{}' has no '{}' column, so its rows cannot be attributed "
            "to an episode. This log predates raw-log schema 1.1. Re-run the "
            "episode rather than pooling rows by simulation time, which "
            "restarts at zero each episode.".format(table_name, EPISODE_FIELD)
        )
    values = set()
    for row in rows:
        raw = row[EPISODE_FIELD]
        if raw is None or raw == "":
            raise EpisodeSelectionError(
                "Table '{}' has a row with an empty '{}'.".format(
                    table_name, EPISODE_FIELD
                )
            )
        values.add(int(raw))
    return values


def available_episodes(tables):
    """Every episode present across the given tables, ascending."""
    present = set()
    for name in sorted(tables):
        present |= episode_values(tables[name], name)
    return sorted(present)


def derived_output_directory(run_directory, episode_count, episode_index,
                             explicit=None):
    """Where the derived products for one episode belong.

    A single-episode source -- a frozen-policy evaluation -- keeps writing
    alongside its raw logs, which is what every existing workflow expects. A
    multi-episode source gets one subdirectory per episode, so deriving
    episode 0 and then episode 1 in the same run directory cannot silently
    overwrite the first episode's products. An explicit directory always wins.
    """
    if explicit is not None:
        directory = os.path.abspath(explicit)
    elif int(episode_count) > 1:
        directory = os.path.join(
            run_directory, "derived",
            "episode_{:05d}".format(int(episode_index)),
        )
    else:
        directory = run_directory
    if not os.path.isdir(directory):
        os.makedirs(directory)
    return directory


def select_episode(tables, episode_index=None):
    """Return (episode_index, tables filtered to that episode).

    Automatic selection is allowed only when the source is unambiguous, so a
    single-episode frozen-policy evaluation needs no extra argument while a
    multi-episode training run cannot be analysed by accident.
    """
    present = set(available_episodes(tables))
    if not present:
        raise EpisodeSelectionError(
            "No rows found in {}; nothing to analyse.".format(sorted(tables))
        )

    if episode_index is None:
        if len(present) > 1:
            raise EpisodeSelectionError(
                "This source contains {} episodes ({}). Simulation time "
                "restarts at zero in each of them, so their rows must never "
                "be pooled. Re-run with an explicit episode_index "
                "(--episode-index N).".format(
                    len(present), sorted(present)
                )
            )
        chosen = sorted(present)[0]
    else:
        chosen = int(episode_index)
        if chosen not in present:
            raise EpisodeSelectionError(
                "Episode {} is not present; this source contains {}.".format(
                    chosen, sorted(present)
                )
            )

    filtered = {}
    for name in sorted(tables):
        filtered[name] = [
            row for row in tables[name]
            if row.get(EPISODE_FIELD) not in (None, "")
            and int(row[EPISODE_FIELD]) == chosen
        ]
    return chosen, filtered


def write_rows(path, rows, fieldnames=None):
    """Write derived rows, preserving an empty file when there are none."""
    if not rows:
        with open(path, "w") as handle:
            handle.write("")
        return
    fields = list(fieldnames) if fieldnames else list(rows[0])
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
