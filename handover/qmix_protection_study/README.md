# QMIX / VDN / IDQN on a two-intersection corridor: protection ablation, diagnosis and manuscript

**Workspace:** `C:\research\qmix_protection_study`. It is separate from the frozen repositories, which are only read:
- `QMIX_Traffic_Coordination` at `8c14f32`;
- `QMIX_PROTECTED` at `3611383`, whose frozen code is identical to `8c14f32`.

**Raw outputs:** on `D:\QMIX_Results` (new folders only).

## Order of the steps (Windows, conda `traffic_rl`; `ETAPES.cmd <step>`)

| # | Step | Command | Status |
|---|---|---|---|
| 1 | Unit tests (synthetic data, no SUMO) | `ETAPES.cmd tests` | executed (see `logs/`) |
| 2 | Read-only diagnosis of the QMIX failure on 9305 | `ETAPES.cmd diagnose` | executed; `diagnosis/RAPPORT_DIAGNOSTIC_QMIX101_t350000_9305.md` |
| 3 | Ablation plan (checks, fingerprint) | `ETAPES.cmd ablation-plan` | executed; plan `c9a4c6d8…` |
| 4 | Ablation preparation | `ETAPES.cmd ablation-prepare <fingerprint>` | executed |
| 5 | Ablation runs (550 new, 4 processes) | `ETAPES.cmd ablation-run`, then `ablation-progress` | executed |
| 6 | Ablation analysis (applied once) | `ETAPES.cmd ablation-analyse` | executed; `docs/RAPPORT_ABLATION.md` |
| 7 | Figures and their data | `ETAPES.cmd figures` | executed; `figures/*.pdf`, `figures/data/*.csv` |
| 8 | Manuscript check / compile | `ETAPES.cmd latex-check`; `ETAPES.cmd latex` needs a TeX distribution | static check executed; PDF compiled during the handover review (TeX Live on Linux, 2026-10-30): `manuscript/main.pdf`, 12 pages, no undefined reference; to recompile on your side with `ETAPES.cmd latex`, which since 2026-11-03 stops and returns 1 at the first failing `pdflatex` or `bibtex` |
| 9 | Robustness validation | `ETAPES.cmd robustness-plan`, `robustness-prepare <fingerprint>`, `robustness-run`, `robustness-progress`, `robustness-analyse` (`plans/PLAN_ROBUSTESSE.md`) | **prepared, not launched**; analysis script written and tested on synthetic data on 2026-10-30, corrected on 2026-11-03 (review points 2–4: incomplete analyses, corrupted results, attribution of the guarantee's cost; `docs/REVUE_CORRECTIF_2026-11-03.md`); **plan fingerprints printed before 2026-11-03 are void**; before the plan, run `ETAPES.cmd robustness-check-smoke` |
| 10 | Retraining campaign | `plans/PLAN_CAMPAGNE_FUTURE.md` | **prepared, not launched** |
| 12 | Fair comparators per robustness profile (OFT g5 / min7 re-optimised per profile, actuated gap-out min 7 s, R3 plans by period) | `ETAPES.cmd comparators-measure`, `comparators-plan`, `comparators-prepare <fingerprint>`, `comparators-run <stage>`, `comparators-progress`, `comparators-finalise <stage>` (`plans/PLAN_COMPARATEURS.md`) | **prepared, tested, costed; not launched**. Decisions of 2026-11-07: search for R1-R3 only, coarse offsets every 10 s (declared deviation D1), R0 reuses C19/C25 (demand identical in law, `ETAPES.cmd check-r0-demand`), R4 frozen comparators only; 17,855 runs known before the fine stage |
| 13 | Read-only checks and analyses without simulation (A4 max pressure, J(cycle), guarantee diagnostic, Clopper-Pearson) | `ETAPES.cmd mp-check-static`, `mp-check-robustness`, `j-cycle`, `guarantee-diagnostic` (IDQN pairs: definition D2), `cp-ablation`, `cp-robustness` | A4 static and Clopper-Pearson on the ablation executed here; the others need `D:` (`docs/COMPLEMENTS_ARTICLE_2026-11-07.md`) |
| 14 | Pre-registered confirmation (new traffics 8c51-8c60) | `plans/PLAN_CONFIRMATION.md`, `tools/confirmation/` | **draft, not frozen, not launched**; margin max(0.05 J_val, 0.10 s); statistics reference A004 = statistics-1.2 (check with `ETAPES.cmd check-statistics <path>`); IDQN exclusion justified; 2,260 evaluations; analysis written and tested; evaluation runner to write after step 12 |
| 10b | Check of the step dispatch and exit codes of `ETAPES.cmd` (stand-in scripts, nothing real runs) | `tools\etapes_check\verify_etapes_cmd.cmd` | 2026-11-07: on Windows the "command & goto :eof" form returned 0 under cmd /c on failure (97 OK, 18 FAIL); `ETAPES.cmd` rewritten with labels and explicit `exit /b <code>` for every step (CRLF), `ROB` defaults to `robustness_validation_2026-11-04` and the steps reading it stop with code 2 if it is absent; static test `tests/test_etapes_cmd.py`; Wine 149/149 is not proof; **to rerun on Windows before any long search** (`docs/RETOURS_2026-11-07.md`) |
| 11 | Verified archive | `ETAPES.cmd archive` | executed: `D:\QMIX_Results\deliveries\qmix_protection_study_<commit>.zip` (+ `.sha256`; `MANIFEST_SHA256.txt` inside) |

## Contents

| Path | Content |
|---|---|
| `plans/` | plans fixed before execution (ablation, robustness, future campaign) |
| `tools/` | ablation runner, indicators, analysis, robustness tools, archive builder |
| `tests/` | `unittest` tests (stdlib; no pytest in `traffic_rl`) |
| `diagnosis/` | read-only diagnosis and its data |
| `analysis/ablation/` | per-cell indicators, pairs, summary, reconstruction check |
| `figures/` | figures (PDF / PNG), `make_figures.py`, plotted data in `figures/data/` |
| `manuscript/` | `main.tex`, `references.bib`, `check_latex.py` |
| `docs/` | ablation report, literature review and DOI verification, French summary; **`REVUE_PASSATION_2026-10-30.md`: handover review (checks, corrections, unverified items, prioritised next steps)**; `REVUE_COMPLEMENT_2026-10-31.md`; `REVUE_CORRECTIF_2026-11-03.md` (robustness tools, review points 2–4); `COMPLEMENTS_ARTICLE_2026-11-07.md` (comparators, confirmation, analyses without simulation: read / measured / reported / proposed); `RETOURS_2026-11-07.md` (ETAPES exit codes, measured cost, guarantee diagnostic versus the 35 pairs and 17 runs, Windows results read) |
| `review/` | independent recomputation scripts used by the handover review (outputs in `logs/revue_2026-10-30/`); `repro_robustness_defects.py` (review points 2–4, outputs in `logs/revue_2026-11-03/`) |
| `logs/` | logs of the runs and checks executed here |

## Status of each claim

See `docs/BILAN_FR.md`, § "Statut". It lists what was:
- executed and verified on your data;
- tested on synthetic data only;
- prepared but not executed;
- missing.
