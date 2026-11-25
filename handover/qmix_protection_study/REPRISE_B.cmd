@echo off
rem Resumption of campaign B after the TraCI incident of 2026-11-25 (worker 2/4). See RUNBOOK_B.md, section R.
rem ETAPES.cmd is sealed by freeze.json (its SHA-256 is part of the frozen code): these steps live in this separate
rem file so that ETAPES.cmd and every executor file of B stay byte-for-byte those of the freeze.
rem Run from the installation folder, with BCONF set to the campaign root:
rem     set BCONF=C:\research\confirmation_B_2026-11-24
rem     REPRISE_B.cmd <step>
rem Steps:
rem   check            read-only: plan, states, start path of the frozen environment, port ranges, processes
rem                    (0 ready, 1 problem, 3 B / A-ext processes still running)
rem   verify-finished  read-only: every finished cell ran its own SUMO (logs\verify_finished_B.json)
rem                    (0 verified, 1 problem, 4 some cells without SUMO header)
rem   assign           writes BCONF\resume\assignment_NN.json: unfinished jobs dealt over 4 workers
rem                    (refused with code 3 while a B or A-ext process runs)
rem   run              resume preflight, then LAUNCHES 4 workers in separate windows (exit code = launch only)
rem Progress: ETAPES.cmd b-progress. Processes: ETAPES.cmd b-processes. Nothing here deletes anything.
setlocal
set PYTHONIOENCODING=utf-8
if "%BCONF%"=="" (echo BCONF is not set: set BCONF=^<campaign root^> first & exit /b 2)
if not exist "%BCONF%\freeze.json" (echo %BCONF%\freeze.json not found & exit /b 2)
call conda activate traffic_rl || (echo conda env traffic_rl not found & exit /b 2)

if "%~1"=="check" goto r_check
if "%~1"=="verify-finished" goto r_verify
if "%~1"=="assign" goto r_assign
if "%~1"=="run" goto r_run
echo Unknown step "%~1". Steps: check ^| verify-finished ^| assign ^| run
exit /b 1

:r_check
python tools\confirmation\resume_b_runner.py check --root %BCONF% --workers 4
exit /b %errorlevel%

:r_verify
python tools\confirmation\verify_finished_b.py --root %BCONF% --out logs\verify_finished_B.json
exit /b %errorlevel%

:r_assign
python tools\confirmation\resume_b_runner.py assign --root %BCONF% --workers 4
exit /b %errorlevel%

:r_run
python tools\confirmation\resume_b_runner.py preflight --root %BCONF%
if errorlevel 1 goto r_run_refused
set "LAUNCH_RC=0"
start "r0" cmd /c python -u tools\confirmation\resume_b_runner.py run --root %BCONF% --worker 0 ^> logs\b_shard_resume_w0.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "r1" cmd /c python -u tools\confirmation\resume_b_runner.py run --root %BCONF% --worker 1 ^> logs\b_shard_resume_w1.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "r2" cmd /c python -u tools\confirmation\resume_b_runner.py run --root %BCONF% --worker 2 ^> logs\b_shard_resume_w2.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "r3" cmd /c python -u tools\confirmation\resume_b_runner.py run --root %BCONF% --worker 3 ^> logs\b_shard_resume_w3.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
echo 4 resume workers launched in separate windows. This exit code covers the launch only, not the workers' results.
echo Check completion with: ETAPES.cmd b-progress, and logs\b_shard_resume_w0.log to logs\b_shard_resume_w3.log
exit /b %LAUNCH_RC%

:r_run_refused
echo Resumption refused by the preflight above: nothing was launched.
exit /b 1
