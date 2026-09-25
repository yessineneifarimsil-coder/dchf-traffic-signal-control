# Protocol Amendment 002: addendum to adopt before any fine-search run

Status: **must be hashed and placed in the amendment root before `run-fine`.**
Scope: the optimized-fixed-timing track only. Frozen code: `8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d`, not modified.

## 1. What was checked

Everything below was recomputed from the frozen `plans.py`/`search.py`/`campaign.py`:

| Claim in the Amendment-002 plan | Verified |
|---|---|
| Amended fine grid around the reported five winners, clip [20,140] | **834 keys** (60 more rejected by the 5 s min green: 40 × (C20, 10/4), 20 × (C20, 11/3)) |
| Keys already evaluated by the audit | **99** keys → 495 runs |
| New keys | **735** keys → 3675 runs |
| Duplicate keys inside the fine grid | 0 |
| Original fine grid (clip [40,140]) | 621 keys = 3105 runs; the parameterised generator reproduces the frozen one exactly |
| Cycles reached | {20, 25, 30, 35}. None ≥ 40, so no overlap with any original run |
| Lower clip | Does nothing. The unclipped grid is identical because C = 15 and C = 10 can't fit two 5 s greens. The min-green rule does the work. |

The arithmetic in the plan is right. What it counts is not.

## 2. Findings

### F1 (blocking): at C ≤ 35, split labels no longer identify distinct plans

`candidate_key = (C, split_thousandths, Δ)`. The executor only receives `(C, g_H, g_V, yellow, Δ)`: `runner.py` and `executors.py` never read `split_thousandths` or `f_H`. Greens are rounded half-up to whole seconds. At C = 20 the usable green is 14 s, so a 0.05 split step is 0.7 s and a 0.025 step is 0.35 s. Several keys therefore run the same signal plan:

* Coarse audit: 208 keys are only **195** executed plans.
* **The 4th and 5th coarse winners, (20,550,10) and (20,600,10), are the same plan** (g_H 8, g_V 6, Δ 10). They are adjacent in the audit ranking because they tied exactly and the key tie-break separated them. So the fine grid is seeded by four plans, and the fifth neighbourhood adds **0** keys.
* Amended fine grid: 834 keys are only **486** executed plans (alias classes: 199 × 1, 226 × 2, 61 × 3).
* Of the 735 "new" keys, 67 run a plan the audit already ran. Only **396** new plans exist, which is 1980 runs, not 3675.
* The frozen fine top 10 keeps the 10 best **keys**. With classes of 2 or 3 identical plans, the shortlist can collapse to about 4 distinct plans. Validation would then pick from far fewer plans than the original C = 40 stage did.

This effect did not exist before the amendment. The original 1980 coarse keys are 1980 plans, and the original 621 fine keys are 621 plans. The amendment's domain extension created it.

### F2 (blocking): a run that fails to clear leaves the stage impossible to finalise

`execute_campaign` writes a completion marker only for cleared runs. `finalise_stage` treats a missing marker as an incomplete stage and refuses to finalise. It also re-runs the failure on every resume. The frozen search rule says a non-clearing candidate is INVALID and excluded, but the campaign cannot express that. At g_V = 5 s and C = 20, a clearance failure is plausible. If one happens with no rule in place, the choice of what to do is made after seeing results.

### F3 (blocking): the old freeze still authorises official training

`authorize_run` accepts any `--campaign-state` whose `freeze_baseline_plans` artefact verifies. The original state (with (40,650,23)) still verifies. Nothing stops a QMIX/VDN/IDQN run from being authorised against the superseded baseline. The pre-final freeze does not check which baseline freeze a checkpoint was trained under. In addition, `write_stage_artefact` overwrites silently, so writing a new freeze into the original state directory would destroy the old evidence.

### F4 (blocking): the external `amended_timing_campaign.py` was not available for review

It lives only on `D:\`. This addendum therefore specifies the rules, and `amendment002.py` implements them against the frozen code. Use it, or commit your script so it can be diffed against it.

### Non-blocking findings

* **Reuse is valid in principle.** The frozen campaign already reuses coarse runs inside the fine stage: run directories are keyed by candidate, not stage, so the 54 coarse keys inside the original fine grid are satisfied by their coarse runs whenever both stages share a runs root. Reusing audit runs is the same operation across two roots. It is safe when each run passes the frozen `completion_problems` against the **original** manifests, with the full environment identity (config, network, source commit, campaign version, schema).
* **Offset track:** its candidates, seeds and selection are independent of the timing track. Reuse the two original artefacts byte for byte.
* **Validation seeds 2101–2105:** reusing them for a second selection round is legitimate. They are selection data. Condition: no original timing-validation result (C = 40 finalists, (40,650,23)) may enter the amended selection, and the audit root must contain no validation run. The driver checks the latter.
* **The new optimum sits on the lattice floor again.** Three of the five coarse winners are at C = 20. This is not the Amendment-001 truncation: 20 s is the smallest cycle on the preregistered 5 s cycle lattice that can hold two 5 s greens. Cycles 16–19 are a resolution gap, like 21–24, not a bound. Do not extend below 20.

## 3. Amended rules (adopt verbatim)

**A2-1 Fine geometry.** Frozen `fine_timing_candidates` with the cycle clip [20,140]. Nothing else changes.

**A2-2 Executed-plan identity.** Two keys are the same candidate if and only if they share `(C, g_H, g_V, yellow, Δ)`. Every retention step counts executed plans:
* coarse: the top 5 distinct plans of the combined 1980 + 208 evidence, under the frozen `(mean design J, key)` order;
* fine: the top 10 distinct plans;
* each plan is scored once, under a representative key. The representative is the lowest key already evaluated by a preregistered grid (original coarse, original fine, audit coarse), or otherwise the lowest key. The choice is structural and never uses a score.

This rule is a verified no-op on the original campaign.

**A2-3 Alias verification.** Wherever two keys of one plan both have runs, their per-seed clearance status, J_primary and time loss must be exactly equal. Otherwise the stage stops and the collapse is withdrawn. The audit alone provides 13 alias pairs × 5 seeds.

**A2-4 Clearance failure.** A run that finishes with `CLEARANCE_FAILURE` gets a hash-sealed failure marker and is never re-simulated. Its candidate is INVALID and excluded (frozen `summarise_candidate` / `rank_by_design`). Exceptions and crashes are still re-run. If fewer than 10 valid fine plans exist, the stage fails closed (frozen rule).

**A2-5 Evidence roots.** Each key has exactly one evidence root, fixed by which grid defined it: original keys use the original root, audit keys use the audit root, and every other key uses the amendment root. All runs are verified against the original campaign's manifests, read-only. No manifest is generated.

**A2-6 Validation.** The amended fine top 10 × 2101–2105 = 50 runs. Selection uses frozen `select_timing_plan` (J, time loss, shorter cycle, key). Original validation results are not consulted.

**A2-7 Freeze.** Written to a **new** state directory `<amendment root>\campaign_state`. The frozen `complete_global_stage` and `build_baseline_freeze_payload` are used on artefacts from the amendment root. The two offset artefacts there are byte-identical copies, re-verified at freeze time. The payload records the superseded freeze (path, SHA-256, (40,650,23)), Amendment 001's hash and this addendum's hash. Writing a second freeze is refused.

**A2-8 Learner eligibility.** Only official learner runs whose `run_manifest.json` records `authorising_artefact_sha256` equal to the SHA-256 of the amended freeze may enter learner validation (`verify-learners`). Everything else is excluded. That covers pre-amendment QMIX seed 101, and any run launched against the old state by mistake.

## 4. Run budget

| Item | Runs | Source |
|---|---|---|
| Combined coarse evidence re-verified | 10 940 (9 900 original + 1 040 audit) | reused, 0 new |
| Fine plans with audit evidence | 90 plans / 99 keys → 450 runs reused | reused |
| New fine plans, if the executed-plan 5th winner adds no keys | 396 plans → **1 980** | new |
| New fine plans, given the true 5th distinct coarse plan | 396–792 plans → **1 980–3 960**; e.g. (20,650,5) or (20,650,15) → 1 980, (25,600,5) → 2 165, (30,650,0) → 2 505 | new; the `precheck` prints the exact figure |
| Validation | 50 | new |

The 5th executed-plan winner is the best-ranked key after the audit's reported top five that is not an alias of the first four. That is already on disk, and `precheck` computes it before anything is written.

## 5. Execution order

```bat
conda activate traffic_rl
cd /d C:\Users\LENOVO\QMIX_Traffic_Coordination
set A2=<path>\amendment002.py

python %A2% --action precheck            &:: read-only; must print PRECHECK PASS
certutil -hashfile <amendment root>\PROTOCOL_AMENDMENT_002_ADDENDUM.md SHA256
python %A2% --action finalise-coarse
python %A2% --action run-fine --shard-index 0 --shard-count 4   &:: ... one per worker
python %A2% --action finalise-fine
python %A2% --action run-validation
python %A2% --action finalise-validation
python %A2% --action freeze --amendment-document <amendment root>\PROTOCOL_AMENDMENT_002_ADDENDUM.md
```

Official training from here on uses `--campaign-state <amendment root>\campaign_state` and a **new** learner output root. The pre-amendment `seed101` directory is never overwritten.

If `precheck` fails, stop and report the message. Likely causes are an audit layout that differs from `<root>\runs` (pass `--audit-runs`), audit markers written under a different campaign version, or manifests that differ from the original. Do not loosen a check to make it pass.

## 6. Unchanged

J_primary, the design/validation/final families and seeds, the 5 s min green (classical only), round-half-up, the 5 s cycle step, the ±0.05/0.025 split neighbourhood, the ±10/1 s offset neighbourhood, top 5/top 10, the frozen tie-breaks, the offset plan (90,500,41), the adaptive config, and every learner hyper-parameter.

## 7. Commitments to fix before results

1. **QMIX seed 101 is re-run** under the amended freeze (Amendment 001 made this rerun conditional on reopening, and the track was reopened). Training is configured deterministic, so compare the 14 checkpoint SHA-256s with the pre-amendment run and report the result. The re-run counts either way.
2. **Lattice floor.** If the selected plan has C = 20, report it as the optimum on the 5 s cycle lattice at its structural floor. Report that cycles 16–19, like all non-multiples of 5, were not searched.
3. **Interpretation.** Webster's cycle, (1.5L + 5)/(1 − Y), with L = 6 s and critical lane flows of 450 and 150 veh/h/lane, gives about 20–23 s for any saturation flow from 1500 to 2000 veh/h/lane. The Webster split would starve V below 5 s at C = 20, so the min green binds, and (20,650,10) is exactly g_H 9 / g_V 5. This is illustrative only, because saturation flow is not a frozen parameter. It supports reading the selected plan as a rapid-service plan at low v/c, not as progression.
4. **Metric.** Short cycles reduce full stops, which is what `waitingTime` counts, more than they reduce time loss. Mean completed time loss and yellow fraction must sit next to J_primary for the fixed-timing plan, exactly as for QMIX.
5. **Selection bias.** The design J (3.04 s) is the minimum over 2 188 keys and is biased low. Only the validation J and, later, the final-test J are reportable as that plan's performance.
6. **No reaction.** Nothing about QMIX (min green, reward, observation, budget) changes in response to the fixed-timing result.
