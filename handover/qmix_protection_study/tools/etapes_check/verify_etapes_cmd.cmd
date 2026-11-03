@echo off
rem ==========================================================================================
rem Checks the step dispatch of ETAPES.cmd and how its exit codes come back. Nothing real runs:
rem a temporary copy of the study holds stand-in scripts (stub.py) that only record their call and
rem exit with the code in FAKE_RC; conda is replaced by a no-op; pdflatex and bibtex are replaced by
rem tex_stub.py (through PDFLATEX and BIBTEX), which exits with FAKE_PDFLATEX_RC / FAKE_BIBTEX_RC. Run from the study folder, in the
rem traffic_rl prompt:
rem     tools\etapes_check\verify_etapes_cmd.cmd
rem Exit status 0 when every expectation holds; the report lists each check.
rem ETAPES_CHECK_UNDER_WINE=1 exists only for a supporting run under Wine on Linux, whose cmd (9.0) neither
rem returns the exit /b code of a CALLed batch nor evaluates "call X || ..." as Windows does: it keeps the
rem cmd /c checks and skips the CALL and conda checks. On Windows, run without it: every check applies.
rem ==========================================================================================
setlocal EnableDelayedExpansion
set "SRC=%~dp0..\.."
set "T=%TEMP%\etapes_check_%RANDOM%_%RANDOM%"
set "S=%T%\study"
set "ETAPES_CALLS=%T%\calls.txt"
set /a PASS=0, FAIL=0
for %%D in (logs tests diagnosis figures manuscript docs\literature tools\robustness bin) do mkdir "%S%\%%D" 2>nul
mkdir "%T%\bin" 2>nul
copy /y "%SRC%\ETAPES.cmd" "%S%\ETAPES.cmd" >nul
copy /y "%~dp0test_stub.py" "%S%\tests\test_stub.py" >nul
copy /y "%~dp0tex_stub.py" "%T%\tex_stub.py" >nul
set "PDFLATEX=python "%T%\tex_stub.py" pdflatex"
set "BIBTEX=python "%T%\tex_stub.py" bibtex"
for %%F in (tools\robustness\cell_state.py diagnosis\diagnose_clearance_failure.py tools\ablation_runner.py tools\ablation_analysis.py figures\make_figures.py manuscript\check_latex.py tools\robustness\robustness_runner.py tools\robustness\robustness_analysis.py tools\robustness\smoke.py docs\literature\verify_dois.py tools\make_archive.py) do copy /y "%~dp0stub.py" "%S%\%%F" >nul
>"%T%\bin\conda.cmd" echo @exit /b %%FAKE_CONDA_RC%%
set "FAKE_CONDA_RC=0"
set "PATH=%T%\bin;%PATH%"
echo Copy under test: %S%
echo.
echo == Sequential steps: exit code seen by CALL and by a separate cmd /c process ==
for %%R in (0 5) do (
  call :check tests %%R unittest-stub
  call :check diagnose %%R diagnose_clearance_failure.py
  call :check ablation-plan %%R "ablation_runner.py plan"
  call :check ablation-prepare %%R "ablation_runner.py prepare" FPRINT
  call :check ablation-progress %%R "ablation_runner.py progress"
  call :check ablation-analyse %%R ablation_analysis.py
  call :check figures %%R make_figures.py
  call :check latex-check %%R check_latex.py
  call :check robustness-plan %%R "robustness_runner.py plan"
  call :check robustness-prepare %%R "robustness_runner.py prepare" FPRINT
  call :check robustness-progress %%R "robustness_runner.py progress"
  call :check robustness-analyse %%R robustness_analysis.py
  call :check robustness-smoke %%R smoke.py
  call :check robustness-check-smoke %%R "cell_state.py check-smoke"
  call :check dois %%R verify_dois.py
  call :check archive %%R make_archive.py
)
echo.
echo == LaTeX build: a failure of pdflatex or bibtex stops the chain and returns 1 ==
call :latex 0 0 0 4 "pdflatex, bibtex, pdflatex, pdflatex"
call :latex 0 2 1 2 "bibtex fails: no further pdflatex"
call :latex 3 0 1 1 "first pdflatex fails: bibtex not run"
echo.
echo == Refusals ==
call :expect_code unknown-step 2 "unknown step"
if "%ETAPES_CHECK_UNDER_WINE%"=="1" (echo   SKIP  conda environment missing: not evaluable under Wine) else (
  set "FAKE_CONDA_RC=1"
  call :expect_code tests 2 "conda environment missing"
  set "FAKE_CONDA_RC=0"
)
echo.
echo == Parallel launch (4 workers each): the launcher cannot see the workers' exit codes ==
call :parallel robustness-run "robustness_runner.py run" robustness_shard
call :parallel ablation-run "ablation_runner.py run" ablation_shard
echo.
echo Result: %PASS% checks passed, %FAIL% failed.
if %FAIL% gtr 0 (exit /b 1)
rmdir /s /q "%T%" 2>nul
exit /b 0

:check
rem %1 step, %2 FAKE_RC, %3 token the stand-in must record, %4 optional extra argument
set "FAKE_RC=%~2"
set "WANT=%~2"
if "%~1"=="tests" if not "%~2"=="0" set "WANT=1"
del "%ETAPES_CALLS%" 2>nul
if "%ETAPES_CHECK_UNDER_WINE%"=="1" goto check_process
pushd "%S%"
call ETAPES.cmd %~1 %~4 >nul 2>&1
set "GOT=!ERRORLEVEL!"
popd
if "!GOT!"=="!WANT!" (call :ok "%~1, FAKE_RC=%~2: CALL returns !GOT!") else (call :ko "%~1, FAKE_RC=%~2: CALL returns !GOT! [want !WANT!]")
:check_process
del "%ETAPES_CALLS%" 2>nul
pushd "%S%"
cmd /c ETAPES.cmd %~1 %~4 >nul 2>&1
set "GOT=!ERRORLEVEL!"
popd
if "!GOT!"=="!WANT!" (call :ok "%~1, FAKE_RC=%~2: cmd /c process exits !GOT!") else (call :ko "%~1, FAKE_RC=%~2: cmd /c process exits !GOT! [want !WANT!]")
findstr /c:"%~3" "%ETAPES_CALLS%" >nul 2>&1
if errorlevel 1 (call :ko "%~1: the step did not call %~3") else (call :ok "%~1: the step called %~3")
exit /b 0

:expect_code
pushd "%S%"
cmd /c ETAPES.cmd %~1 >nul 2>&1
set "GOT=!ERRORLEVEL!"
popd
if "!GOT!"=="%~2" (call :ok "%~3: returns !GOT!") else (call :ko "%~3: returns !GOT! [want %~2]")
exit /b 0

:parallel
rem %1 step, %2 token, %3 log prefix
set "FAKE_RC=5"
del "%ETAPES_CALLS%" 2>nul
pushd "%S%"
cmd /c ETAPES.cmd %~1 >"%T%\launch.txt" 2>&1
set "GOT=!ERRORLEVEL!"
popd
set /a WAITED=0
:parallel_wait
set "N=0"
if exist "%ETAPES_CALLS%" for /f "delims=" %%l in ('findstr /c:"%~2" "%ETAPES_CALLS%"') do set /a N+=1
if !N! lss 4 if !WAITED! lss 60 (
  ping -n 2 127.0.0.1 >nul
  set /a WAITED+=1
  goto parallel_wait
)
if "!N!"=="4" (call :ok "%~1: 4 workers started, shards 0/4..3/4") else (call :ko "%~1: !N! workers seen [want 4]")
for %%i in (0 1 2 3) do (
  findstr /c:"shard %%i/4" "%ETAPES_CALLS%" >nul 2>&1
  if errorlevel 1 call :ko "%~1: shard %%i/4 not launched"
  if not exist "%S%\logs\%~3%%i.log" call :ko "%~1: logs\%~3%%i.log not written"
)
if "!GOT!"=="0" (call :ok "%~1: launcher returns 0 although every worker exited 5 (expected: START does not wait; check completion with the progress step)") else (call :ko "%~1: launcher returns !GOT!")
findstr /c:"covers the launch only" "%T%\launch.txt" >nul 2>&1
if errorlevel 1 (call :ko "%~1: the launcher does not say that its code covers the launch only") else (call :ok "%~1: the launcher says that its code covers the launch only")
exit /b 0

:latex
rem %1 FAKE_PDFLATEX_RC, %2 FAKE_BIBTEX_RC, %3 expected exit code, %4 expected number of tool calls, %5 label
set "FAKE_PDFLATEX_RC=%~1"
set "FAKE_BIBTEX_RC=%~2"
if "%ETAPES_CHECK_UNDER_WINE%"=="1" goto latex_process
del "%ETAPES_CALLS%" 2>nul
pushd "%S%"
call ETAPES.cmd latex >nul 2>&1
set "GOT=!ERRORLEVEL!"
popd
if "!GOT!"=="%~3" (call :ok "latex, %~5: CALL returns !GOT!") else (call :ko "latex, %~5: CALL returns !GOT! [want %~3]")
:latex_process
del "%ETAPES_CALLS%" 2>nul
pushd "%S%"
cmd /c ETAPES.cmd latex >"%T%\latex.txt" 2>&1
set "GOT=!ERRORLEVEL!"
popd
if "!GOT!"=="%~3" (call :ok "latex, %~5: cmd /c process exits !GOT!") else (call :ko "latex, %~5: cmd /c process exits !GOT! [want %~3]")
set "N=0"
if exist "%ETAPES_CALLS%" for /f "delims=" %%l in ('type "%ETAPES_CALLS%"') do set /a N+=1
if "!N!"=="%~4" (call :ok "latex, %~5: !N! tool calls") else (call :ko "latex, %~5: !N! tool calls [want %~4]")
if not "%~3"=="0" (
  findstr /c:"LaTeX build failed" "%T%\latex.txt" >nul 2>&1
  if errorlevel 1 (call :ko "latex, %~5: no failure message") else (call :ok "latex, %~5: failure message printed")
)
set "FAKE_PDFLATEX_RC="
set "FAKE_BIBTEX_RC="
exit /b 0

:ok
set /a PASS+=1
echo   OK    %~1
exit /b 0

:ko
set /a FAIL+=1
echo   FAIL  %~1
exit /b 0
