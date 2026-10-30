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
| 8 | Manuscript check / compile | `ETAPES.cmd latex-check`; `ETAPES.cmd latex` needs a TeX distribution | static check executed; PDF compiled during the handover review (TeX Live on Linux, 2026-10-30): `manuscript/main.pdf`, 12 pages, no undefined reference; to recompile on your side with `ETAPES.cmd latex` |
| 9 | Robustness validation | `ETAPES.cmd robustness-plan`, `robustness-prepare <fingerprint>`, `robustness-run`, `robustness-progress`, `robustness-analyse` (`plans/PLAN_ROBUSTESSE.md`) | **prepared, not launched**; analysis script written and tested on synthetic data on 2026-10-30, before any run; plan fingerprints printed before that date are void |
| 10 | Retraining campaign | `plans/PLAN_CAMPAGNE_FUTURE.md` | **prepared, not launched** |
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
| `docs/` | ablation report, literature review and DOI verification, French summary; **`REVUE_PASSATION_2026-10-30.md`: handover review (checks, corrections, unverified items, prioritised next steps)** |
| `review/` | independent recomputation scripts used by the handover review (outputs in `logs/revue_2026-10-30/`) |
| `logs/` | logs of the runs and checks executed here |

## Status of each claim

See `docs/BILAN_FR.md`, § "Statut". It lists what was:
- executed and verified on your data;
- tested on synthetic data only;
- prepared but not executed;
- missing.
