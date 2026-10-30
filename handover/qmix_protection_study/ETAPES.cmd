@echo off
rem Ordered steps of the protection study (Windows, conda env traffic_rl). Run from this folder:
rem     cd /d C:\research\qmix_protection_study
rem     ETAPES.cmd <step>
rem Steps: tests | diagnose | ablation-plan | ablation-prepare <fingerprint> | ablation-run | ablation-progress |
rem        ablation-analyse | figures | latex-check | robustness-plan | robustness-prepare <fingerprint> |
rem        robustness-run | robustness-progress | robustness-analyse | robustness-smoke | dois | archive
rem Robustness root: set ROB before calling (default below). The analysis script is fixed with the plan:
rem its SHA-256 is part of the plan fingerprint, so it must not change between robustness-plan and the end.
setlocal
if "%QMIX_RESULTS%"=="" set QMIX_RESULTS=D:\QMIX_Results
set ABL=%QMIX_RESULTS%\protection_ablation_2026-10-29
set MIN7=%QMIX_RESULTS%\fixed_timing_min7_2026-10-28
if "%ROB%"=="" set ROB=%QMIX_RESULTS%\robustness_validation
call conda activate traffic_rl || (echo conda env traffic_rl not found & exit /b 2)

if "%1"=="tests" python -m unittest discover -s tests -v & goto :eof
if "%1"=="diagnose" python diagnosis\diagnose_clearance_failure.py --runs-root %MIN7%\comparison\runs --model qmix_seed101_t350000 --failed 9305 --ok 9301 9302 9303 9304 --out diagnosis\out_qmix101_t350000_9305 & goto :eof
if "%1"=="ablation-plan" python tools\ablation_runner.py plan --root %ABL% & goto :eof
if "%1"=="ablation-prepare" python tools\ablation_runner.py prepare --root %ABL% --approved-plan %2 & goto :eof
if "%1"=="ablation-run" (
  start "abl0" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 0/4 ^> logs\ablation_shard0.log 2^>^&1
  start "abl1" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 1/4 ^> logs\ablation_shard1.log 2^>^&1
  start "abl2" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 2/4 ^> logs\ablation_shard2.log 2^>^&1
  start "abl3" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 3/4 ^> logs\ablation_shard3.log 2^>^&1
  goto :eof)
if "%1"=="ablation-progress" python tools\ablation_runner.py progress --root %ABL% & goto :eof
if "%1"=="ablation-analyse" python tools\ablation_analysis.py --root %ABL% --out analysis\ablation & goto :eof
if "%1"=="figures" python figures\make_figures.py --ablation analysis\ablation --min7 %MIN7%\summary\comparison_runs.csv & goto :eof
if "%1"=="latex-check" python manuscript\check_latex.py manuscript\main.tex manuscript\references.bib & goto :eof
if "%1"=="latex" (cd manuscript & pdflatex main & bibtex main & pdflatex main & pdflatex main & cd .. & goto :eof)
if "%1"=="robustness-plan" python tools\robustness\robustness_runner.py plan --root %ROB% & goto :eof
if "%1"=="robustness-prepare" python tools\robustness\robustness_runner.py prepare --root %ROB% --approved-plan %2 & goto :eof
if "%1"=="robustness-run" (
  start "rob0" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 0/4 ^> logs\robustness_shard0.log 2^>^&1
  start "rob1" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 1/4 ^> logs\robustness_shard1.log 2^>^&1
  start "rob2" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 2/4 ^> logs\robustness_shard2.log 2^>^&1
  start "rob3" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 3/4 ^> logs\robustness_shard3.log 2^>^&1
  goto :eof)
if "%1"=="robustness-progress" python tools\robustness\robustness_runner.py progress --root %ROB% & goto :eof
if "%1"=="robustness-analyse" python tools\robustness\robustness_analysis.py --root %ROB% --out analysis\robustness & goto :eof
if "%1"=="robustness-smoke" python tools\robustness\smoke.py --root %QMIX_RESULTS%\robustness_smoke_NEW --checkpoint %QMIX_RESULTS%\qualification_300m_medium_timing_amendment002r\learners\qmix\seed101\qmix_seed101_t350000.pth & goto :eof
if "%1"=="dois" python docs\literature\verify_dois.py & goto :eof
if "%1"=="archive" python tools\make_archive.py & goto :eof
echo Unknown step "%1". See the header of this file and README.md.
exit /b 2
