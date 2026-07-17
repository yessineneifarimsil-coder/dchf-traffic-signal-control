# A Dynamic Coordination Horizon Framework for Traffic Signal Control

Code, SUMO scenarios, processed data, and analysis outputs for:

> **A Dynamic Coordination Horizon Framework for Traffic Signal Control: Diagnosing Controller Effectiveness Across Operating Regimes**

## Scope

The repository implements the Dynamic Coordination Horizon Framework (DCHF) and the evaluated controller families: simultaneous fixed-time control, optimized fixed offset, queue-based adaptive control, Max Pressure, Independent DQN, QMIX, and the VDN mixer ablation.

The reported evidence has three levels:

1. **Ten-seed formal comparisons:** Scenario A reference and Scenario B transfer.
2. **Five-seed paired validation:** spatial and demand sweeps, boundary-adjacent cells, and selected scalability tests.
3. **Single-seed exploratory mapping:** the remaining joint distance-demand cells.

Multi-seed evaluation varies SUMO traffic realizations for fixed trained policies. It does not constitute independent training-seed replication.

## Installation

```bat
conda env create -f environment.yml
conda activate traffic_rl
```

SUMO must be available in the activated environment. Confirm with:

```bat
sumo --version
python -c "import traci, sumolib; print('TraCI and sumolib available')"
```

## Exact trained policies

The exact policy checkpoints used in the article will be deposited in an immutable archive after supervisor and coauthor approval. The archive will include the model manifest and SHA-256 hashes. Its DOI will be added after publication. Evaluation scripts expect the checkpoints under `results/raw/` using the filenames listed in `MODEL_MANIFEST.csv`.

## Regenerate the final integrated DCHF map

```bat
verify_final_dchf_outputs.bat
```

Expected class counts:

- useful-effective: 3
- capacity-constrained: 3
- close/no-gain: 0
- marginal: 4
- outside horizon: 20

Exactly 15 of the 30 joint-grid cells use five-seed paired gap evidence; the remaining 15 are single-seed exploratory.

## Scenario A formal comparison

```bat
reproduce_scenario_a.bat
```

Expected headline values:

- optimized fixed offset: 169.782 +/- 1.275 s
- QMIX V2: 177.291 +/- 1.040 s
- Max Pressure: 149.911 +/- 2.640 s
- QMIX approximation gap: 4.42%

## Important interpretation

The numerical horizons are conditional on the tested controller, trained policy, action space, cycle, synthetic corridor family, and evidence campaign. The DCHF protocol is reusable, but the reported numerical boundaries are not universal traffic-control constants.

## Repository structure

- `src/`: controller, environment, experiment, and analysis code
- `results/tables/`: processed and seed-level result tables
- `results/figures/`: generated figures
- `results/archive/`: superseded outputs retained only for provenance
- `environment.yml`: software environment
- `MODEL_MANIFEST.csv`: mapping from checkpoints to reported experiments

## Citation

Citation metadata will be added after publication.
