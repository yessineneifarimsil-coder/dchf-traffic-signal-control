# Results Summary — Dynamic Coordination Horizon Framework

This file summarizes the main empirical findings of the DCHF traffic signal control project. It is intended to help reviewers, collaborators, ChatGPT, Claude, or future users understand the results without reading all raw simulation files.

## 1. Main scientific message

The project proposes the Dynamic Coordination Horizon Framework (DCHF). The goal is not to prove that QMIX is always the best traffic signal controller. The goal is to diagnose when traffic signal coordination is useful, marginal, capacity-constrained, or outside its useful horizon.

The key diagnostic metric is the MARL approximation gap:

[
G_{\mathrm{QMIX}}(x)=
\left(
\frac{J_{\mathrm{QMIX}}(x)-J_{\mathrm{off}}^\star(x)}
{J_{\mathrm{off}}^\star(x)}
\right)100
]

where (J_{\mathrm{QMIX}}(x)) is the waiting time of QMIX and (J_{\mathrm{off}}^\star(x)) is the waiting time of the best optimized fixed-offset benchmark.

The regime classification is:

* Effective: (G_{\mathrm{QMIX}}\leq 5%)
* Marginal: (5% < G_{\mathrm{QMIX}}\leq 10%)
* Outside horizon: (G_{\mathrm{QMIX}}>10%)

The buffered ratio is used to distinguish algorithmic limitations from physical capacity limitations:

[
BR(x)=\frac{N_{\mathrm{buffered}}(x)}{N_{\mathrm{expected}}(x)}
]

Capacity regimes:

* (BR<0.01): unconstrained
* (0.01\leq BR<0.10): mild insertion pressure
* (0.10\leq BR<0.25): capacity-limited
* (BR\geq0.25): oversaturated

## 2. Scenario A — Reference two-intersection corridor

Scenario A is the main 10-seed comparison between optimized fixed offset, QMIX V2, and Max Pressure.

Final 10-seed values:

* Optimized fixed offset: waiting time (169.782 \pm 1.275), speed (7.969 \pm 0.007), queue (14.416 \pm 0.067)
* QMIX V2: waiting time (177.291 \pm 1.040), speed (7.914 \pm 0.014), queue (14.739 \pm 0.048)
* Max Pressure: waiting time (149.911 \pm 2.640), speed (9.283 \pm 0.027), queue (9.535 \pm 0.072)

Main interpretation:

* QMIX V2 is close to the optimized fixed-offset benchmark.
* The QMIX approximation gap is (4.42%), so Scenario A is inside the DCHF effective zone.
* Max Pressure is the strongest controller in Scenario A.
* This does not weaken the DCHF contribution; it supports the idea that DCHF identifies which controller family is suitable in each regime.

Statistical tests:

* Optimized offset minus QMIX V2: mean difference (-7.509), 95% CI ([-8.448,-6.553]), Wilcoxon (p=0.001953)
* Optimized offset minus Max Pressure: mean difference (19.870), 95% CI ([18.020,21.807]), Wilcoxon (p=0.001953)
* QMIX V2 minus Max Pressure: mean difference (27.380), 95% CI ([25.777,28.929]), Wilcoxon (p=0.001953)

All three comparisons remain significant after Bonferroni correction.

## 3. Scenario B — Turning-movement transfer

Scenario B adds turning movements.

Main result:

* QMIX transferred from Scenario A remains effective with a multi-seed approximation gap of approximately (3.18%).
* Directly trained Scenario B QMIX performs much worse, with an approximation gap of approximately (50.26%).

Interpretation:

* The transferred policy reveals an implicit curriculum effect.
* Training first on a simpler through-movement corridor can produce a better transferable cooperative policy than direct training on the more complex turning scenario.

## 4. Two-intersection spatial horizon

The spatial horizon was evaluated by varying the distance between two intersections.

Main finding:

* (d=200) m and (d=300) m are effective.
* (d=100) m is marginal.
* (d\geq500) m is outside the useful coordination horizon under the tested medium-demand condition.

Interpretation:

* Useful two-intersection coordination is concentrated around 200--300 m in the tested corridor.
* The spatial horizon is empirical and conditional, not a universal law.

## 5. Two-intersection demand horizon

Demand was varied at the representative effective distance (d=300) m.

Main finding:

* Low demand (0.5\times): coordination is weak or outside because traffic interaction is low.
* Medium demand (1.0\times): effective.
* High demand (1.5\times): effective boundary.
* Saturation (2.0\times): effective but capacity-sensitive.
* Oversaturation (2.5\times): marginal and capacity-constrained.

Interpretation:

* Coordination is most useful when demand is strong enough to create interaction but not so high that capacity dominates.
* Low demand may not need coordination.
* Oversaturated corridors require capacity or demand management before advanced control.

## 6. Three-intersection extension

The three-intersection experiments show that pairwise effective spacing does not automatically generalize when a downstream signal is added.

Important finding:

* With (d_{12}=300) m fixed, downstream spacing (d_{23}=300) m and (d_{23}=500) m can remain effective.
* (d_{23}=750) m appears marginal in the tested condition.
* Some shorter or longer configurations become outside horizon.

Interpretation:

* The horizon is non-monotonic and regime-dependent.
* Distance interacts with offset structure, demand, downstream queues, and corridor configuration.

## 7. Five-intersection reference scalability

A homogeneous five-intersection corridor was tested with:

[
d_{12}=d_{23}=d_{34}=d_{45}=300\text{ m}
]

under medium demand.

Main result:

* QMIX gap: (-1.536 \pm 0.815%)
* Coordination Gain: (52.965 \pm 0.161%)
* Effective-regime stability: 100%
* Teleports: 0
* Buffered ratio: approximately 0.003

Interpretation:

* Under favourable homogeneous conditions, cooperative coordination remains effective up to (N=5).
* This supports an empirical lower bound (H_N\geq5) only under the tested conditions.
* It is not a universal scalability claim.

## 8. Five-intersection distance--demand stress test

The (N=5) stress test evaluated 16 distance--demand conditions.

Result:

* Effective: 3 of 16
* Marginal: 1 of 16
* Outside: 12 of 16

Capacity diagnosis:

* Buffered ratio remains close to zero.
* Teleports are zero.

Interpretation:

* Failures are mainly coordination-transfer limitations, not physical capacity failures.
* The (N=5) scalability result is conditional.
* Cooperative MARL should not be deployed blindly across all distances and demands.

## 9. Max Pressure interpretation

Max Pressure performs best in Scenario A.

This is not a contradiction. It strengthens the DCHF message:

* Optimized fixed offset is the progression-based classical benchmark.
* Max Pressure is a strong pressure-based adaptive non-learning controller.
* QMIX is a learned cooperative MARL controller.
* DCHF identifies which controller family is suitable under each regime.

The current project includes Max Pressure in Scenario A. Broader Max Pressure sweeps across demand, spacing, and scalability are recommended for future work.

## 10. Main conclusion

The main conclusion is:

The DCHF shifts traffic signal control evaluation from “Does MARL beat fixed-time?” to “Under which operating regimes is coordination useful, marginal, capacity-constrained, or outside its useful horizon?”

The work should not be interpreted as a universal proof of QMIX superiority. It is a diagnostic framework for coordination usefulness and controller-family selection.
