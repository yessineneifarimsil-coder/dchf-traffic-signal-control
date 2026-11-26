@echo off
rem Public export of campaign B (2026-11-26). READ-ONLY on BCONF, campaign A, A-ext, the frozen code and the
rem checkpoints; every output goes into the NEW folder BEXPORT. Nothing is simulated, nothing is deleted.
rem Run from the installation folder, in an Anaconda Prompt, after:
rem     set BCONF=C:\research\confirmation_B_2026-11-24
rem Optional overrides (defaults below): BEXPORT, BANALYSIS, CMP, AEXT, ROB, QMIX_PROTECTED_ROOT, AQ_FROZEN_REPOSITORY.
rem Steps: episodes | reestimate | search-counts | facts | check | finalize | all
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
if "%BCONF%"=="" (echo BCONF is not set: set BCONF=C:\research\confirmation_B_2026-11-24 first & exit /b 2)
if not exist "%BCONF%\freeze.json" (echo %BCONF%\freeze.json not found & exit /b 2)
if "%BEXPORT%"=="" set BEXPORT=C:\research\B_export_2026-11-26
if "%CMP%"=="" set CMP=D:\QMIX_Results\comparators_robustness_profiles
if "%AEXT%"=="" set AEXT=D:\QMIX_Results\comparators_actuated_g5
if "%ROB%"=="" set ROB=D:\QMIX_Results\robustness_validation_2026-11-04
if "%QMIX_PROTECTED_ROOT%"=="" set QMIX_PROTECTED_ROOT=C:\Users\LENOVO\QMIX_PROTECTED
if "%AQ_FROZEN_REPOSITORY%"=="" set AQ_FROZEN_REPOSITORY=C:\Users\LENOVO\QMIX_Traffic_Coordination
if "%BANALYSIS%"=="" set BANALYSIS=C:\research\qmix_protection_study_B_reprise_2026-11-25\analysis\confirmation
if not exist "%BANALYSIS%\decisions.csv" (echo %BANALYSIS%\decisions.csv not found: set BANALYSIS=^<folder of the frozen analysis^> & exit /b 2)
call conda activate traffic_rl || (echo conda env traffic_rl not found & exit /b 2)

if "%~1"=="episodes" goto x_episodes
if "%~1"=="reestimate" goto x_reestimate
if "%~1"=="search-counts" goto x_search
if "%~1"=="facts" goto x_facts
if "%~1"=="check" goto x_check
if "%~1"=="finalize" goto x_finalize
if "%~1"=="all" goto x_all
echo Unknown step "%~1". Steps: episodes ^| reestimate ^| search-counts ^| facts ^| check ^| finalize ^| all
exit /b 1

:x_episodes
python tools\export_b\export_episodes.py --root %BCONF% --out %BEXPORT%
exit /b %errorlevel%

:x_reestimate
python tools\export_b\copy_once.py tools\export_b\reestimate_B.py %BEXPORT%\reestimate_B.py
if errorlevel 1 exit /b 1
python -I %BEXPORT%\reestimate_B.py --episodes %BEXPORT%\B_episodes.csv --margins %BEXPORT%\B_margins.json --statistics %QMIX_PROTECTED_ROOT%\src\adaptive_qmix\protocol\statistics.py --out %BEXPORT% --frozen-decisions %BANALYSIS%\decisions.csv --sensitivity
exit /b %errorlevel%

:x_search
python tools\export_b\search_counts.py --cmp %CMP% --aext %AEXT% --out %BEXPORT%
exit /b %errorlevel%

:x_facts
python tools\export_b\network_facts.py --root %BCONF% --out %BEXPORT%
if errorlevel 1 exit /b 1
python tools\export_b\training_facts.py --frozen %AQ_FROZEN_REPOSITORY% --protected %QMIX_PROTECTED_ROOT% --rob %ROB% --out %BEXPORT%
exit /b %errorlevel%

:x_check
python tools\export_b\check_export.py --export %BEXPORT% --bconf %BCONF%
exit /b %errorlevel%

:x_finalize
python tools\export_b\finalize_export.py --export %BEXPORT% --name B_export_2026-11-26
exit /b %errorlevel%

:x_all
call "%~f0" episodes
if errorlevel 1 (echo STOP at episodes & exit /b 1)
call "%~f0" reestimate
if errorlevel 1 (echo STOP at reestimate & exit /b 1)
call "%~f0" search-counts
if errorlevel 1 (echo STOP at search-counts: see search_counts_details.json & exit /b 1)
call "%~f0" facts
if errorlevel 1 (echo STOP at facts & exit /b 1)
call "%~f0" check
if errorlevel 1 (echo STOP at check: see check_export.txt & exit /b 1)
call "%~f0" finalize
exit /b %errorlevel%
