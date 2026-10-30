"""Per-run indicators for the protection ablation (pure functions; definitions fixed before any run).

Time convention of the frozen code: a per-second row stamped t describes [t-1, t).

D_demand (cost during the demand)   sum over rows t = 1..3600 of (stopped_active_count + pending_due_count)
                                    from reward_seconds.csv, in vehicle-seconds: the frozen reward's
                                    waiting burden restricted to the generation window [0, 3600). Defined
                                    whether or not the run later clears. D_bar = D_demand / N_sched with
                                    N_sched = the manifest's scheduled_total (2800 here), fixed per traffic.
P_post (after the demand)           same sum over rows t > 3600 up to the end of the run; censored at 7200 s
                                    for a run that fails to clear (flagged).
J_primary                           frozen definition (mean waitingTime + departDelay over all scheduled
                                    vehicles), only for runs that clear; never imputed.
Service counter c_d(i)              protected definition: per row, 0 if d is green, else c+1 if the halting
                                    number on d's observed incoming lanes is >= 1, else 0 (yellow = not green).
Access to first green               wait_start = first row of an unserved wait (queue >= 1 while red); only a
                                    green closes it; wait = (t-1) - start at the closing green row.
Green spells                        contiguous rows with the same green (H or V) in the executed phase; the
                                    spell still running at the end of the run is censored and excluded.
"""
GENERATION_END_S = 3600

V_IN = {"J1": ["E4_0", "E4_1", "E5_0", "E5_1"], "J2": ["E7_0", "E7_1", "E6_0", "E6_1"]}
H_IN = {"J1": ["-E1_0", "-E1_1", "E0_0", "E0_1"], "J2": ["E2_0", "E2_1", "E1_0", "E1_1"]}


def demand_and_post_cost(rows, end_time):
    """rows: dicts with time, stopped_active_count, pending_due_count. Returns (D_demand, P_post)."""
    seen = {}
    for r in rows:
        t = float(r["time"])
        if t != int(t) or t <= 0:
            raise ValueError("bad time stamp {}".format(r["time"]))
        t = int(t)
        if t in seen:
            raise ValueError("duplicate second {}".format(t))
        seen[t] = int(r["stopped_active_count"]) + int(r["pending_due_count"])
    end = int(round(float(end_time)))
    if sorted(seen) != list(range(1, end + 1)):
        raise ValueError("reward_seconds does not cover 1..{}".format(end))
    if end < GENERATION_END_S:
        raise ValueError("run ended before the end of the demand")
    d = sum(v for t, v in seen.items() if t <= GENERATION_END_S)
    p = sum(v for t, v in seen.items() if t > GENERATION_END_S)
    return d, p


def counters_from_logs(lane_rows, phase_rows, tls=("J1", "J2")):
    """Reconstruct per-second service counters from lane_states (queue = halting number) and the executed
    phase (signal_phases.actual_phase). Returns {time: {tl: {"c_H", "c_V", "q_H", "q_V"}}} and summary
    {tl: {d: {"max_counter", "max_wait_to_first_green", "open_wait_at_end"}}}."""
    q = {}
    for r in lane_rows:
        t = int(round(float(r["time"])))
        for tl in tls:
            for d, lanes in (("H", H_IN[tl]), ("V", V_IN[tl])):
                if r["lane"] in lanes:
                    q.setdefault(t, {}).setdefault(tl, {"H": 0, "V": 0})[d] += int(r["queue"])
    phase = {}
    for r in phase_rows:
        phase.setdefault(int(round(float(r["time"]))), {})[r["intersection"]] = r["actual_phase"]
    c = dict((tl, {"H": 0, "V": 0}) for tl in tls)
    mx = dict((tl, {"H": 0, "V": 0}) for tl in tls)
    start = dict((tl, {"H": None, "V": None}) for tl in tls)
    wmax = dict((tl, {"H": 0, "V": 0}) for tl in tls)
    series = {}
    last = 0
    for t in sorted(phase):
        last = t
        for tl in tls:
            for d in ("H", "V"):
                qq = q.get(t, {}).get(tl, {"H": 0, "V": 0})[d]
                if phase[t][tl] == d:
                    c[tl][d] = 0
                    if start[tl][d] is not None:
                        wmax[tl][d] = max(wmax[tl][d], (t - 1) - start[tl][d])
                        start[tl][d] = None
                elif qq >= 1:
                    c[tl][d] += 1
                    if start[tl][d] is None:
                        start[tl][d] = t - 1
                else:
                    c[tl][d] = 0
                mx[tl][d] = max(mx[tl][d], c[tl][d])
            series.setdefault(t, {})[tl] = {"c_H": c[tl]["H"], "c_V": c[tl]["V"],
                                           "q_H": q.get(t, {}).get(tl, {"H": 0, "V": 0})["H"],
                                           "q_V": q.get(t, {}).get(tl, {"H": 0, "V": 0})["V"]}
    summary = dict((tl, dict((d, {"max_counter": mx[tl][d], "max_wait_to_first_green": wmax[tl][d],
                                  "open_wait_at_end": None if start[tl][d] is None else last - start[tl][d]})
                             for d in ("H", "V"))) for tl in tls)
    return series, summary


def green_spells(phase_rows, tls=("J1", "J2")):
    """Completed green spells per intersection: list of (direction, length_s, start_row_time).
    The spell running at the last row is censored and excluded."""
    out = dict((tl, []) for tl in tls)
    for tl in tls:
        rows = sorted(((float(r["time"]), r["actual_phase"]) for r in phase_rows if r["intersection"] == tl))
        cur, n, st = None, 0, None
        for t, p in rows:
            if p in ("H", "V") and p == cur:
                n += 1
                continue
            if cur in ("H", "V") and n > 0:
                out[tl].append((cur, n, st))
            cur, n, st = (p, 1, t) if p in ("H", "V") else (None, 0, None)
    return out


def spell_stats(spells, demand_only=True):
    allv = [(d, n, st) for tl in spells for (d, n, st) in spells[tl] if (not demand_only or st <= GENERATION_END_S)]
    n = len(allv)
    return {"green_spells": n, "shortest_green_s": min((x[1] for x in allv), default=None),
            "share_2s_greens": (sum(1 for x in allv if x[1] == 2) / float(n)) if n else None,
            "greens_below_7s": sum(1 for x in allv if x[1] < 7)}
