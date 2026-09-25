# Protocol Amendment 002 (revised): optimized-fixed-timing track

**Status:** DRAFT until `prepare-floor` hashes this file into the sealed floor work order. That must happen before any C < 20 simulation exists. The precheck proves none exists.

**Scope:** the optimized-fixed-timing track only. The fixed-offset plan (90,500,41) is reused unchanged.

**Supersedes:**
* The first Amendment 002 (`amended_timing_campaign.py`, `protocol_amendment_002.md`). It is withdrawn and archived; see `withdrawn_v1/README.md`.
* The draft addendum in commit `507a1c2`. It was never sealed or executed. Its counts (834/99/735/486/396/1,980) and its advice not to go below C = 20 are withdrawn.
* The version in commit `814b684`. It was never approved, sealed or executed. It generated each fine neighbourhood around one alias (the lowest label) of each winning plan. For the winner (20,550,10) = (20,600,10), that excluded the greens (9,5) at C = 20, which are the greens of the current best plan. It also let the frozen tie-breaks read the split label.

## 0. Provenance strategy (a)

* **Execution checkout:** every stage runs from a checkout of `8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d`. The driver checks that `git status --porcelain` is empty before every stage. All commands use `python -B`, so no bytecode is written into the checkout.
* **Driver:** `amendment002.py` is an external file, and the driver refuses to run from inside the checkout. Its SHA-256 is recorded in:
  * the floor and fine work orders;
  * the outcome marker of every new run;
  * every derived artefact;
  * the freeze.

  From `prepare-floor` on, every stage refuses to run under a different driver hash.
* **Reuse check:** reuse goes through the frozen `completion_problems(..., environment)`. That function compares `source_commit` (`git rev-parse HEAD`), `baseline_config_sha256`, `network_sha256`, `network_git_blob`, `campaign_version` and `raw_log_schema_version` with the current checkout. The check is not loosened.
* **Per-run manifest check:** in addition, every reused or new run's `run_manifest.json` must record:
  * `git_commit` = the frozen commit;
  * an empty `git_status_porcelain`;
  * a `git_describe` that does not end in `-dirty`;
  * the runtime versions `python`, `numpy`, `pytorch` and `sumo`.

  All runs entering one ranking must share one stack, and it must be the current process's stack.

## 1. R1: a candidate is a realized plan

The realized key is `(C, g_H, g_V, Δ mod C)`; yellow is fixed at 3 s and checked.

* Labels `(C, split_thousandths, Δ)` with the same realized key are one candidate.
* Every top 5 and top 10 counts realized plans. Each realized plan is simulated once.
* Labels have **no scientific role** (§3a). A label only names a plan, says where its runs are stored and where to look them up, and carries provenance.
* Labels of one plan that have runs must agree per seed on clearance status and validity, and on J_primary and time loss to within 1e-12. Otherwise the stage stops.

**Verified no-op where the original campaign ran:** original coarse 1980 labels = 1980 plans; original fine 621 = 621; original coarse ∪ fine 2547 = 2547; fixed offset 90 = 90.

## 2. R2: structural-floor audit, C ∈ {16, 17, 18, 19}

* **Cycle floor:** 16 s = 5 + 5 + 3 + 3.
* **Splits:** the frozen coarse splits 0.30, 0.35, …, 0.75.
* **Rounding and validity:** frozen `make_plan` (half-up) and frozen `candidate_is_valid` (g_H ≥ 5, g_V ≥ 5).
* **Seeds:** design seeds 2001–2005 only.
* **Deduplication:** by realized plan, before execution.

**Offset rule (frozen here):** Δ ∈ {0, 5, 10, …} with Δ < C. Only this reading needs no choice, because it is exactly what the frozen generator computes for any integer C: `coarse_timing_candidates` uses `range(0, cycle_s, 5)`. It keeps the 5 s absolute resolution anchored at Δ = 0 used for every other cycle. The wrap-around gap (C − 15 = 1–4 s) is never coarser than 5 s.

Two other readings of the prose "Δ = 0, 5, …, C−5" were considered and rejected before any result:
* a grid anchored at C − 5 (e.g. C = 18 → 3, 8, 13) abandons the Δ = 0 anchor;
* C/5 equally spaced offsets are not integers, so they break the 1 s plan resolution.

| C | offsets Δ | admissible labels | realized plans (g_H, g_V) | runs |
|---|---|---|---|---|
| 16 | 0, 5, 10, 15 | 8 | 4: (5,5) | 20 |
| 17 | 0, 5, 10, 15 | 12 | 8: (5,6), (6,5) | 40 |
| 18 | 0, 5, 10, 15 | 20 | 12: (5,7), (6,6), (7,5) | 60 |
| 19 | 0, 5, 10, 15 | 28 | 16: (5,8), (6,7), (7,6), (8,5) | 80 |
| **total** | | **68** (92 more rejected by the min green) | **40** | **200** |

The floor results enter the combined coarse ranking (1980 + 208 + 68 labels) **before** the top 5 realized plans are taken.

## 3. R3: fine rule for any centre

The fine rule is unchanged:
* cycles C0 ± 10 in 5 s steps;
* splits f0 ± 0.05 in 0.025 steps, bounded to [0.25, 0.80];
* offsets Δ0 ± 10 in 1 s steps, modulo the candidate cycle;
* the frozen 5 s min green.

Two things change, and nothing else.

**(i) Cycle clip: [16, 140].** Example: a centre at C0 = 18 gives cycles {18, 23, 28}. For centres on the 5 s lattice the clip changes nothing, because C = 15 cannot hold two 5 s greens.

**(ii) Union of aliases.** A winning realized plan has no single centre. The fine search around it is built in three steps:
1. Take **every** label of the combined coarse grid (original 1,980 + boundary 208 + floor 68) that realizes the plan. This is not restricted to one evidence root, to simulated labels, or to the label whose runs are reused.
2. Apply the frozen neighbourhood above independently around each such label, with the frozen min-green rule.
3. Take the union of those neighbourhoods and deduplicate it by realized key **before** execution.

The result is the same whichever alias names the plan (tested for all 41 alias groups of the combined grid). It is a no-op for the original C ≥ 40 campaign, where every alias group has one label; with the frozen [40, 140] clip it reproduces the frozen `fine_timing_candidates` output exactly.

Example: (20,550,10) and (20,600,10) both realize C = 20, g_H 8, g_V 6, Δ 10. Their neighbourhoods reach, by cycle:

| C | from 550 | from 600 | union |
|---|---|---|---|
| 20 | (7,7), (8,6) | (8,6), (9,5) | (7,7), (8,6), (9,5) |
| 25 | (10,9), (11,8) | (10,9), (11,8), (12,7) | (10,9), (11,8), (12,7) |
| 30 | (12,12), (13,11), (14,10) | (13,11), (14,10), (15,9), (16,8) | (12,12) … (16,8) |

The fine run count is **not** fixed here. `finalise-coarse` derives it after the floor audit, from the true top 5 realized plans. For each winner it prints:
* the realized key and its active constraints;
* all of its coarse aliases;
* the number of realized fine plans from each alias alone, and from their union;
* reused plans, new plans and new runs.

It then prints the totals over the global union.

## 3a. Labels and tie-breaks

The frozen tie-breaks read the label (`search.py` at `8c14f32`):
* `rank_by_design`: `key=lambda record: (record["mean_J_primary_s"], record["key"])`;
* `select_timing_plan`: `(mean_J_primary_s, mean_time_loss_s, plan["cycle_s"], key)`;
* the shortlist verifier `campaign._verify_derivation` re-sorts by `(mean_J_primary_s, tuple(key))`.

Here `key = (C, split_thousandths, Δ)`. J_primary is a sum of whole SUMO seconds over 2,800 vehicles and 5 seeds, so exact ties between different plans are realistic. Under such a tie, the split of whichever alias was simulated could decide the order.

**Rule:**
* Every scored realized plan is named by its **canonical label**: the lowest split, in thousandths, that the frozen `make_plan` rounds to its g_H.
* For one cycle, g_H cannot decrease as the split grows, so canonical labels sort exactly like realized keys (C, g_H, g_V, Δ).
* The frozen `rank_by_design`, `select_timing_plan` and shortlist verifier therefore break every tie on the realized key, identically in the coarse, fine and validation stages. The driver re-sorts on the realized key at each of these points and stops if the orders differ.
* The run that is actually reused is looked up under its own label and cross-checked against every other evaluated alias to 1e-12. After that, the label plays no further part.
* Plans never run before are simulated and stored under their canonical label.

**No-op for C ≥ 40:** on the original 2,547 coarse and fine labels, label order equals realized order, so every original tie-break is unchanged.

## 4. R4: clearance failure is a terminal outcome

* Every new run gets a sealed outcome marker. It records the driver SHA-256, this addendum's SHA-256, the stage, the realized key, the manifest hashes, the environment and the metrics hash.
* A `CLEARANCE_FAILURE` is recorded once and never re-simulated. Crashes and exceptions are re-run.
* A plan with any failed design run is INVALID and excluded (frozen `summarise_candidate` / `rank_by_design`). If fewer than 5 (coarse) or 10 (fine) valid plans exist, the stage fails closed.
* Historical markers and original code are not touched.

## 5. R5: evidence roots

Each evaluated label has one evidence root, fixed by the grid that defined it, never by scanning:
* original coarse and fine labels → the original root;
* the 208 boundary labels → the audit root;
* floor plans (stored under canonical labels) → the amendment root.

All runs are verified against the original campaign's manifests, read-only.

## 6. R6: seed isolation

* Floor, coarse and fine stages open only benchmark_design 2001–2005.
* benchmark_validation 2101–2105 opens only after the fine stage is finalised and `baseline_design` is sealed in the amended state. It is read only from this amendment's own runs, so no C = 40 validation result can enter the selection.
* Learner validation 2201–2205 and final test 3001–3010 are refused by the frozen guards and by a name scan of all three roots.
* The audit root must hold no benchmark_validation run.

## 7. R7: freeze and learners

* The freeze goes in `<amendment root>\campaign_state`, and only once. It uses the frozen `build_baseline_freeze_payload`. The two offset artefacts are byte-identical copies, re-hashed against the originals at freeze time.
* The freeze records what it supersedes: the original freeze's path and SHA-256, and (40,650,23).
* Official training runs only through `train-official`. That launches the frozen `train_adaptive.py` with `--campaign-state` set to the amended state, into a new directory outside the original, audit and withdrawn roots.
* `verify-learners` accepts only runs whose `authorising_artefact_sha256` equals the amended freeze's SHA-256. The pre-amendment QMIX seed 101 is therefore excluded. Seed 101 is re-run, and its 14 checkpoint SHA-256s are compared with the pre-amendment run and reported either way.

## 8. Constraint reporting

For the current best plan and for each finalised top-5, top-10 and selected plan, report the realized (C, g_H, g_V, Δ) and which limits are active: C = 16, g_V = 5, g_H = 5.

The current best on existing evidence is C = 20, g_H = 9, g_V = 5, Δ = 10 (coarse label (20,650,10)). Its active constraint is **g_V = 5**.

## 9. Unchanged

J_primary, the families and seeds, the 5 s min green (classical only), half-up rounding, the 5 s cycle step, the split and offset neighbourhoods, top 5 / top 10, the order of the frozen tie-break fields (with labels named as in §3a), the offset plan, the adaptive configuration, and every learner hyper-parameter. Nothing about QMIX changes in response to any fixed-timing result.

## Appendix: stage order

`precheck` → `prepare-floor --amendment-document <this file>` → `run-floor` → `finalise-coarse` → `run-fine` → `finalise-fine` → `run-validation` → `finalise-validation` → `freeze` → `train-official` / `verify-learners`.
