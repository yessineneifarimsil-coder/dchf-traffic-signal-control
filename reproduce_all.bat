@echo off 
echo Activating environment... 
call conda activate traffic_rl 
 
echo Running Scenario A multi-seed offset/QMIX evaluation... 
python src\baselines\two_intersections\evaluate_multiseed_offset_qmix_per_second.py 
 
echo Running Max Pressure Scenario A... 
python src\baselines\two_intersections\max_pressure_corridor.py 
 
echo Running Scenario A statistical tests... 
python src\analysis\scenario_a_statistical_tests.py 
 
echo Done. Check results\tables and results\figures. 
pause 
