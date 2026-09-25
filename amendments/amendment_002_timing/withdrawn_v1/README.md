# WITHDRAWN: first Amendment 002 (timing track)

**Status: WITHDRAWN.** Never executed. Not evidence. This path, and the branch that holds it, is never the execution commit for any run. Runs execute only from a clean checkout of `8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d`.

## What was withdrawn

| File (original location, unmodified) | Role |
|---|---|
| `D:\QMIX_Results\qualification_300m_medium_timing_amendment_20260920\amended_timing_campaign.py` | first Amendment-002 driver |
| `D:\QMIX_Results\qualification_300m_medium_timing_amendment_20260920\protocol_amendment_002.md` | first Amendment-002 protocol text |
| the precheck output of that driver, if one was saved | console output |
| `PROTOCOL_AMENDMENT_002_ADDENDUM.md` as of commit `507a1c2` | draft addendum, never sealed |

`amendment002.py --action archive-withdrawn` copies the files byte for byte into `D:\QMIX_Results\WITHDRAWN_timing_amendment_002_v1_20260920`. It writes `SHA256SUMS` and `README_WITHDRAWN.md` there and verifies that the sources did not change. It refuses to write inside the withdrawn root.

The revised driver also refuses to use any directory that holds these files as its execution root.

## Why

The fine search deduplicated by `candidate_key` = (C, split_thousandths, Δ). That is a label, not the realized plan (C, g_H, g_V, Δ mod C). At C ≤ 35, half-up rounding maps several split labels onto one plan:

* 208 boundary labels are 195 plans;
* 834 fine labels are 486 plans;
* two of the five coarse "winners", (20,550,10) and (20,600,10), are the same plan (C = 20, g_H = 8, g_V = 6, Δ = 10).

The counts 834 / 99 / 735 / 3,675 were derived from the wrong centres and are withdrawn. The draft counts 486 / 90 / 396 / 1,980 in `507a1c2` are withdrawn too.

## Superseded by

`../amendment002.py` and `../PROTOCOL_AMENDMENT_002_ADDENDUM.md` (revised). Their SHA-256s are sealed into the floor work order and recorded in the amended freeze.
