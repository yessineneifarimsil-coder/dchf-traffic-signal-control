@echo off
setlocal

call conda activate traffic_rl
if errorlevel 1 (
  echo [ERROR] Could not activate traffic_rl.
  exit /b 1
)

cd /d %~dp0

python src\analysis\plot_final_integrated_dchf_distance_demand.py
if errorlevel 1 exit /b 1

python -c "import pandas as pd; c=pd.read_csv(r'results/tables/final_distance_demand_integrated_dchf_counts.csv').set_index('final_integrated_dchf_code').reindex([1,2,3,4,5],fill_value=0)['number_of_cases'].astype(int).to_dict(); e={1:3,2:3,3:0,4:4,5:20}; assert c==e,(c,e); d=pd.read_csv(r'results/tables/final_distance_demand_integrated_dchf_classes.csv'); assert int(d['seed_evidence'].eq('5-seed paired').sum())==15; print('Verified counts:',c); print('Verified five-seed cells: 15/30')"
if errorlevel 1 exit /b 1

echo.
echo Final DCHF outputs verified successfully.
endlocal
