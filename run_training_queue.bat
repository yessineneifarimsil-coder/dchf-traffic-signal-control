@echo off
REM Sequential seeded training queue. One run at a time -- these all use SUMO
REM and must not overlap. ~2h13m each, 9 runs, ~20 hours total.
cd /d C:\Users\LENOVO\QMIX_Traffic_Coordination
call conda activate traffic_rl

if not exist results\logs mkdir results\logs

for %%S in (102 103 104 105) do (
    echo [%DATE% %TIME%] START qmix seed %%S
    python -u src\qmix\train_qmix_corridor_v2_seed%%S.py > results\logs\train_qmix_seed%%S.log 2>&1
    echo [%DATE% %TIME%] DONE  qmix seed %%S
)

for %%S in (101 102 103 104 105) do (
    echo [%DATE% %TIME%] START vdn seed %%S
    python -u src\qmix\train_vdn_corridor_v2_seed%%S.py > results\logs\train_vdn_seed%%S.log 2>&1
    echo [%DATE% %TIME%] DONE  vdn seed %%S
)

echo [%DATE% %TIME%] QUEUE COMPLETE
pause