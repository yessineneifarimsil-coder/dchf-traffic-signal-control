# Dynamic Coordination Horizons for Cooperative Traffic Signal Control 
 
This repository contains the code, SUMO scenarios, and analysis scripts for the paper: 
 
"Dynamic Coordination Horizons in Cooperative Traffic Signal Control" 
 
## Main contribution 
 
The project proposes the Dynamic Coordination Horizon Framework (DCHF), which diagnoses when traffic signal coordination is effective, marginal, capacity-constrained, or outside its useful horizon. 
 
## Installation 
 
```bash 
conda env create -f environment.yml 
conda activate traffic_rl 
``` 
 
## Reproduce main results 
 
```bat 
reproduce_all.bat 
``` 
 
## Main scripts 
 
- src/baselines/two_intersections/evaluate_multiseed_offset_qmix_per_second.py 
- src/baselines/two_intersections/max_pressure_corridor.py 
- src/analysis/scenario_a_statistical_tests.py 
 
## Main outputs 
 
- results/tables/ 
- results/raw/ 
- results/figures/ 
 
## Final Scenario A values 
 
- Optimized fixed offset: 169.782 +/- 1.275 
- QMIX V2: 177.291 +/- 1.040 
- Max Pressure: 149.911 +/- 2.640 
- QMIX approximation gap: 4.42%% 
 
## Reproducibility note 
 
Scenario A uses 10 paired seeds and includes Wilcoxon signed-rank tests with bootstrap confidence intervals. Other horizon experiments may use fewer seeds and are reported according to the protocol described in the paper. 
