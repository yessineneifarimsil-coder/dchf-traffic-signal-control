# Robustness validation of service on new traffics — ready to run, NOT launched (2026-10-29)

**Status:** prepared; not part of the 600 authorised evaluations.

**Code and tests:**
- code: `tools/robustness/`;
- tests (no SUMO): `tests/test_robustness.py` (6), `tests/test_robustness_analysis.py` (18),
  `tests/test_robustness_runner.py` (9), `tests/test_robustness_end_to_end.py` (2, synthetic chain plan → run →
  progress → analysis);
- engineering smoke check (4 short SUMO runs, outputs not interpreted): `D:\QMIX_Results\robustness_smoke_2026-10-29\smoke_report.json`.

**Plan fingerprint** (`robustness_runner.py plan`): printed by the runner; the runner refuses any other. It covers
the runner, the evaluator, the analysis and `cell_state.py`. **Any fingerprint printed before 2026-11-03 is void:
run `ETAPES.cmd robustness-plan` again** (correction of review points 2–4, section at the end).

**Question:** does service hold on demand patterns that really test it, and at what cost? It is
answered for:
- the selected learned checkpoints with and without protections;
- the old fixed plan, kept as the reference;
- comparators constrained to the same action domain.

## Traffics (family `robustness`, code 80, seeds never used before)

`tools/robustness/scenarios.json`:
- 6 streams on the frozen routes;
- generation window [0, 3,600) s; cut-off 7,200 s;
- exact counts per stream; time-varying intensity by piecewise-constant weights;
- 5 traffics per scenario.

| Scenario | Purpose | Main (WE/EW) | Secondary per stream | N (J denominator) | Seeds |
|---|---|---|---|---|---|
| R0 reference | control: qualification volumes on traffics never seen | 900/700 | 300 | 2,800 | 8001–8005 |
| R1 sparse secondary, heavy main | persistent low secondary demand while the main axis stays loaded | 1,100/900 | 60 | 2,240 | 8101–8105 |
| R2 single secondary trickle | one secondary stream per intersection, 30 veh/h: isolated arrivals all hour | 1,000/800 | 30 (N1S1, S2N2), 0 (others) | 1,860 | 8201–8205 |
| R3 time-varying | main peak in the middle half-hour; secondary peaks at start and end | 900/700 | 300 | 2,800 | 8301–8305 |
| R4 isolated tail | main axis stops at 3,000 s; secondary at a quarter of its rate in the last 600 s | 900/700 | 300 | 2,800 | 8401–8405 |

**Why these five:**
- R1 and R2 isolate the failure mechanism diagnosed in the frozen study: an isolated vehicle on a red
  approach while the observation hardly changes.
- R3 tests non-stationarity.
- R4 reproduces, by design, the post-demand situation of the observed failure.
- R0 links back to the development traffics.

**Fixed scenario parameters:**
- the network, vehicle type and observation normalisers are those of the frozen configuration;
- the volumes are fixed here and are not tuned on any result;
- **J uses N = the manifest's real total** (`n_adapter.py`), never 2,800 outside R0, R3 and R4.

## Controllers (per traffic)

| Controller | Role |
|---|---|
| Old fixed plan C19, 8/5 s, offset 9 s | historical reference (preserved), even though its 5 s secondary green violates the 7 s minimum |
| Min-7 fixed plan C25, 12/7 s, offset 0 | fixed plan under the common 7 s minimum |
| Canonical max pressure (1 s clock, minimum green 10 s) | classical adaptive reference (different action domain) |
| P5 pressure on the 5 s clock, arms `none` and `both` | **same action domain** as the learned methods; with `both` it carries the same constraints |
| 30 selected checkpoints × {`none`, `guarantee`, `both`} | learned policies (trained without protection) |

**Cells:** 5 scenarios × 5 traffics × (5 + 90) = **2,375 evaluations**.

**Estimated cost** (measured 13–14 s per evaluation with 4 parallel processes; a failure runs to
7,200 s):
- about 13 CPU-hours;
- 2.3–2.5 h wall on 4 processes;
- about 9.5 GB on D: (lanes logged at decisions only, counters per second).

## Indicators

The same definitions as the ablation (`tools/ablation_metrics.py`), with N per manifest:
- clearance;
- J_primary (cleared runs only), D̄ = D / N, P;
- maximum service counter, access to first green, open waits at the end;
- per-vehicle maximum waitingTime and timeLoss;
- unfinished vehicles;
- interventions during and after the demand;
- realised greens;
- SUMO signal mismatches (protected and P5 runs).

## Success criteria (fixed before execution)

**Technical (all required):**
- every planned cell has a finished result: complete, or a scientific failure (clearance failure) with its
  residual state. A corrupted result is never counted as finished; a cell declared missing stays missing and
  makes the analysis INCOMPLETE (T1);
- 0 SUMO signal mismatches in protected and P5 runs;
- maximum counter ≤ 127 s and realised green ≥ 7 s in every `both` run;
- maximum counter ≤ 127 s in every `guarantee` run;
- manifests and checkpoints hash-verified.

**Scientific (descriptive, per scenario):**

| ID | Question | Criterion |
|---|---|---|
| S1 | service | "The guarantee prevented indefinite denial of service in these scenarios" **if and only if** every `guarantee` and `both` run the plan expects is present (750 per arm in total: every model and traffic of the scenario), the technical criteria T2–T5 hold, and there are 0 clearance failures with an open counter wait at the end. Expected counts and identities come from the plan, never from the runs present. Otherwise the statement is not made; failures and missing runs are listed. |
| S2 | latent defects | number of `none` runs with a failure, or with a vehicle waiting ≥ 300 s, per method and scenario |
| S3 | effects of the protections | paired differences against `none` for the same model and traffic. `guarantee − none` is the effect of the guarantee alone. `both − none` is the combined effect of the minimum green and the guarantee: it is **never** the cost of the guarantee itself, which would need `both − min_green` (not in this plan; no arm or simulation is added). ΔJ covers the whole episode (pairs where both clear); ΔD̄ covers the demand window [0, 3,600) s (all pairs). Activation of the guarantee during the demand is reported separately from the identification of its cost: EVALUATED only in `guarantee − none` with an intervention during the demand; NOT IDENTIFIED in `both − none` when it acted; NOT EVALUATED when it did not act during the demand. Pairs expected (from the plan) and present are shown. |
| S4 | comparison with the fixed plans | per method and scenario, model-level paired differences in J against the min-7 fixed plan (and the old plan) on the same traffics, only on pairs where both clear, with n; no superiority claim, no test on these 5 traffics |

**Hypotheses:** none is stated as a prediction.

**Interpretation rules:**
- Any statement about method ranking stays descriptive.
- These traffics are new, but the checkpoints were selected earlier. The study evaluates existing
  policies, not retraining.

## Commands (Windows, conda `traffic_rl`)

```bat
cd /d C:\research\qmix_protection_study
python tools\robustness\robustness_runner.py plan --root D:\QMIX_Results\robustness_validation_<date>
python tools\robustness\robustness_runner.py prepare --root D:\QMIX_Results\robustness_validation_<date> --approved-plan <fingerprint>
start "r0" python tools\robustness\robustness_runner.py run --root D:\QMIX_Results\robustness_validation_<date> --shard 0/4
start "r1" python tools\robustness\robustness_runner.py run --root D:\QMIX_Results\robustness_validation_<date> --shard 1/4
start "r2" python tools\robustness\robustness_runner.py run --root D:\QMIX_Results\robustness_validation_<date> --shard 2/4
start "r3" python tools\robustness\robustness_runner.py run --root D:\QMIX_Results\robustness_validation_<date> --shard 3/4
python tools\robustness\robustness_runner.py progress --root D:\QMIX_Results\robustness_validation_<date>
```

**Resumption:** rerun the same `run` commands. Cell states (`tools/robustness/cell_state.py`):
- **complete** (CLEARED) and **scientific failure** (CLEARANCE_FAILURE): finished, verified, never rerun;
- **corrupted**: `evaluation_metrics.json` unreadable, unknown status, identity different from the planned cell
  (scenario, controller, traffic seed, checkpoint SHA-256 stamped by `evaluate_any.py`) or a required file
  missing. Preserved as found, reported, never rerun automatically, never counted as finished;
- **interrupted** (directory without `evaluation_metrics.json`): renamed `.incomplete1` and run once more; a
  second interruption is left for diagnosis;
- **not started**.

Exit codes of `run` (per shard) and `progress` (whole plan): 0 every cell finished; 3 some cells not finished;
5 at least one corrupted result. `ETAPES.cmd robustness-run` only launches the 4 workers: its own code covers
the launch, not their success; check with `robustness-progress` and `logs\robustness_shard*.log`.

**Analysis script (added 2026-10-30, before any robustness run):** `tools/robustness/robustness_analysis.py`.
- Same indicator definitions as the ablation (`tools/ablation_metrics.py`, imported unchanged), N per manifest.
- The service counters come from `service_counters.csv`, which every controller logs every second. Lanes are
  logged at decisions only here, so the ablation's reconstruction from per-second lanes does not apply. Instead,
  each logged counter is recomputed from the logged queue and executed phase and must match (T5).
- It implements the technical criteria T1–T5 and the questions S1–S4 above. If an integrity criterion (T2–T5)
  fails, the report states that no scientific statement is made.
- A corrupted result, or a cell without result that is not declared missing, stops the analysis (exit 1).
  Declared missing cells (`--declared-missing`) give an INCOMPLETE report (exit 4): every count is shown as
  present/expected and no conclusion needing a missing cell is drawn. Exit 3: integrity criteria failed;
  exit 0: complete and verified.
- If the guarantee never acts during the demand of a scenario, its cost there is reported as **NOT EVALUATED**,
  not as zero; in `both − none` it is at most NOT IDENTIFIED (see S3).
- Applied once; refuses to run if its SHA-256 differs from the one recorded in the plan.
- Tests: `tests/test_robustness_analysis.py`, 10 tests at the time (18 since 2026-11-03), on synthetic runner outputs (N = 28 and 18, so a constant
  denominator would be detected), stdlib only, executed under Python 3.11 in the review environment; to be
  rerun under the Windows stack (`ETAPES.cmd tests`).

**Runner changes made with it (before any run):**
- the plan now records `analysis_sha256`: approving the plan fingerprint approves the analysis too. **Any
  fingerprint printed before 2026-10-30 is void; run `ETAPES.cmd robustness-plan` again;**
- `prepare` writes `manifests_sha256.json`, so criterion T4 ("manifests hash-verified") can be checked after the
  runs.

**Review points to keep in mind when reading the results (not changes to the design):**
- In R1 and R2 the two fixed plans were optimised for the qualification demand, not for these volumes; S4 then
  measures how the reference plans and the learned policies tolerate a demand change, not an optimised
  fixed-time reference for that demand.
- Nothing forces the guarantee to act during the demand: if the learned policies keep serving the secondary
  approaches often (2 s greens), S3 may again report the cost of the guarantee as NOT EVALUATED.
- Even when it acts, its own cost is identified only by `guarantee − none`; `both − none` measures the two
  protections together.
- The comparison with fixed plans remains descriptive: 5 traffics per scenario, checkpoints selected earlier.

**Commands:** `ETAPES.cmd robustness-plan`, `robustness-prepare <fingerprint>`, `robustness-run`,
`robustness-progress`, `robustness-analyse` (root: variable `ROB`, default `D:\QMIX_Results\robustness_validation`).

## Correction 2026-11-03 (review points 2–4; before any robustness run)

- **Point 2, incomplete analysis.** A declared missing cell no longer passes T1. The report is marked
  INCOMPLETE. S1, S2, S3, S4 and the classical table compare present against expected counts derived from the
  plan for every model and traffic. S1 is refused when any expected `guarantee` or `both` run is missing,
  including an entire arm.
- **Point 3, corrupted results.** New `tools/robustness/cell_state.py` shared by the runner and the analysis
  (states above). `evaluate_any.py` now stamps `traffic_seed`, `controller`, `scenario` and, for learned
  cells, `checkpoint_sha256` into `evaluation_metrics.json`, so the identity check does not depend on fields
  of the protected evaluator. The required files are those the smoke runs read or the ablation analysis
  read on the 600 real protected outputs (`protection_decisions.csv`, `protection_record.json`,
  `service_counters.csv`) plus the RunLogger tables. **To be confirmed on Windows before the plan:**
  `ETAPES.cmd robustness-check-smoke` on the 2026-10-29 smoke runs (files, scenario, controller, status),
  then a new smoke (`ETAPES.cmd robustness-smoke`, 4 short engineering runs, not results) followed by
  `python tools\robustness\cell_state.py check-smoke --root <new smoke root> --stamped`.
- **Point 4, cost attribution.** S3 as above; keys `dJ_whole_episode_s` and `dD_bar_demand_window_s`; fields
  `contrast`, `effect_measured`, `guarantee_activated_during_demand`.
- **ETAPES.cmd.** `latex` stops at the first failing `pdflatex`/`bibtex` and returns 1 (previously a bibtex
  failure was masked); `robustness-run` and `ablation-run` print that their code covers the launch only;
  new step `robustness-check-smoke`. No wait was added.
- Evidence: `logs/revue_2026-11-03/` and `docs/REVUE_CORRECTIF_2026-11-03.md`.
