# Ablation of the two protections on the existing checkpoints — plan locked before the runs (2026-10-29)

**Nature:** exploratory development evaluation. The traffics 9301–9305 have already been inspected, so
this is neither a final test nor an independent validation.

**Question:** what does each protection, added at evaluation time, do to policies that were trained
**without** it? The ablation shows nothing about retraining with a protection, nor about cooperation.

## Design

**Models:** the 30 checkpoints selected by the campaign's validation rule (`selection_records.json`).
- QMIX, VDN and IDQN, training seeds 101–110.
- All 30 are verified by SHA-256 against the selection records.
- They come from `qualification_300m_medium_timing_amendment002r/learners`.

**Traffics:** development 9301–9305.
- Manifests are byte-identical between `protected_pilot_2026-10-24/manifests` and the min-7 study.
- 2,800 scheduled vehicles each.
- SUMO seeds come from the manifest metadata.

**Arms (inference time):**
- `none`;
- `guarantee`: threshold T = 120 s;
- `min_green`: G = 7 s;
- `both`.

**Parameters:** unchanged from `QMIX_PROTECTED` (`3611383`), whose frozen code is identical to `8c14f32`.
- Action mask outside the agents: the proposed greedy action is replaced by the other action only if
  it is forbidden.
- Weights, observations, reward, 5 s decisions, 3 s yellow and the executor are unchanged.

**Cells:** 30 × 5 × 4 = **600**.
- **50 QMIX cells in arm `none` are reused** from the min-7 study (`comparison/runs`).
  - They were produced by the frozen evaluator script, with the same checkpoints (hash), manifests
    (hash) and SUMO seeds, full logging and TraCI subscriptions.
  - Check S1 of `protected_checks_2026-10-24` showed the protected evaluator in arm `none` reproduces
    the frozen output files byte for byte.
  - These cells have no protection tables: their counters are reconstructed from `lane_states` and the
    executed phase.
  - The reconstruction is tested against the protected `ServiceCounters` (synthetic test) and against
    the logged counters of every new arm-`none` cell (check in the analysis).
  - They have no SUMO read-back of the signals.
- **550 new cells**, run with the protected evaluator: greedy, `lane_state_logging=full`,
  subscriptions.

**Fingerprint of the plan:** `c9a4c6d80fa2f954a1ebef6b443f7be5b6c387f6c9f15b6cd11aaba25650c23b`.
The runner refuses any other.

**Design change, recorded:**
- `PLAN_VERSION_PROTEGEE.md` §5 planned 10 new traffics, 9401–9410, for 1,200 evaluations.
- The study lead's instruction of 2026-10-29 fixes 9301–9305 (already inspected) and 600 evaluations,
  with QMIX/`none` reused.
- **No parameter may be changed from these results.**

## Indicators (`tools/ablation_metrics.py`, `tools/ablation_analysis.py`, both committed before the runs)

| Indicator | Definition |
|---|---|
| Clearance | `CLEARED` / `CLEARANCE_FAILURE` (7,200 s cut-off); a failure is a result, never rerun, J never imputed |
| J_primary | frozen: mean over the 2,800 scheduled vehicles of SUMO `waitingTime + departDelay`; cleared runs only |
| Time loss | frozen: mean `timeLoss` of completed vehicles (defined even for a failed run; flagged) |
| **D (cost during the demand)** | Σ over rows t = 1…3600 of (stopped vehicles + vehicles due but not inserted), in veh·s, from the frozen per-second reward log; window [0, 3600); D̄ = D / N_sched with N_sched = the manifest's scheduled total (2,800). Computable whether or not the run later clears |
| P (after the demand) | the same sum for t > 3600 until the end; censored at 7,200 s for failures |
| Service counter | protected definition (queue ≥ 1 on the red direction's observed incoming lanes; reset by green or an empty queue); the 127 s bound concerns this counter under its assumptions |
| Access to first green | longest interval from the start of an unserved wait to the next green of that direction (only a green closes it) |
| Stop-line crossing | `STOP_LINE_EXIT` events, logged for the main axis only (the secondary approaches have no crossing log) |
| Arrival | `tripinfo`: per-vehicle maximum of `waitingTime` (cumulative stopped time) and of `timeLoss`; unfinished vehicles listed |
| Realised greens | completed green spells of the executed phase (final censored spell excluded); shortest, share of 2 s greens and number below 7 s, during the demand |
| Interventions | `protection_decisions.csv`: by type, with decision time before / after 3,600 s |
| Signal check | SUMO phase index and state string versus expected (new cells only) |

## Comparisons (descriptive)

- **Pairing:** within each (model, traffic) block, each arm minus `none`, giving ΔD, ΔJ, Δ(time loss)
  and Δ(maximum vehicle wait).
- **ΔJ** only for pairs where both runs clear; the number of comparable pairs is always reported.
- **Interaction, per block:** (both − min_green) − (guarantee − none), for D on all blocks and for J on
  blocks where all four runs clear.
- **Summaries** per method × arm: counts, means with their n, medians, quartiles, ranges, and counts of
  positive, negative and zero differences.
- **Not done:** no hypothesis test; dependence between models and traffics is respected by reporting
  blocks, not pooled tests.

## Execution and recovery

- **Command:** `tools/ablation_runner.py run --shard i/4`, 4 parallel processes, on output root
  `D:\QMIX_Results\protection_ablation_2026-10-29`. The runner refuses an existing root at preparation.
- **Recovery:**
  - a finished cell (`protection_record.json`) is never rerun;
  - an interrupted cell is renamed `.incompleteN` and run once more;
  - a scientific failure is a finished cell.
- **Estimated cost:** about 20–45 s per cell; a failure runs to 7,200 s. 550 cells come to about 4–6
  CPU-hours, about 1–1.5 h wall on 4 processes. Disk about 7 GB on D: (33 GB free).
