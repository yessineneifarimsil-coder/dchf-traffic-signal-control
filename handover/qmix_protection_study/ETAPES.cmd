@echo off
rem Ordered steps of the protection study (Windows, conda env traffic_rl). Run from this folder:
rem     cd /d C:\research\qmix_protection_study
rem     ETAPES.cmd <step>
rem Steps: tests | diagnose | ablation-plan | ablation-prepare <fingerprint> | ablation-run | ablation-progress |
rem        ablation-analyse | figures | latex-check | robustness-plan | robustness-prepare <fingerprint> |
rem        robustness-run | robustness-progress | robustness-analyse | robustness-smoke |
rem        robustness-check-smoke | latex | dois | archive
rem Comparators (plans/PLAN_COMPARATEURS.md; root CMP): comparators-plan | comparators-measure |
rem        comparators-prepare <fingerprint> | comparators-run <stage> | comparators-progress |
rem        comparators-finalise <stage> | comparators-verify-manifests
rem Read-only analyses: mp-check-static | mp-check-robustness | j-cycle | cp-ablation | cp-robustness |
rem        guarantee-diagnostic | check-r0-demand | check-statistics <statistics.py of A004>
rem Robustness root: set ROB before calling (default below). The analysis script is fixed with the plan:
rem its SHA-256 is part of the plan fingerprint, so it must not change between robustness-plan and the end.
rem Exit codes: a sequential step returns the code of its script (robustness-progress: 0 every cell finished,
rem 3 some not finished, 5 at least one corrupted result; robustness-analyse: 0 complete and verified,
rem 3 technical criteria failed, 4 incomplete, 1 stopped). latex returns 1 as soon as pdflatex or bibtex fails.
rem ablation-run and robustness-run only LAUNCH 4 workers in separate windows: their exit code covers the
rem launch, never the workers' success. Check completion with the matching *-progress step and logs\*.log.
setlocal
if "%QMIX_RESULTS%"=="" set QMIX_RESULTS=D:\QMIX_Results
set ABL=%QMIX_RESULTS%\protection_ablation_2026-10-29
set MIN7=%QMIX_RESULTS%\fixed_timing_min7_2026-10-28
if "%ROB%"=="" set ROB=%QMIX_RESULTS%\robustness_validation
if "%CMP%"=="" set CMP=%QMIX_RESULTS%\comparators_robustness_profiles
if "%PDFLATEX%"=="" set PDFLATEX=pdflatex
if "%BIBTEX%"=="" set BIBTEX=bibtex
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
  echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
  echo Check completion with: ETAPES.cmd ablation-progress, and logs\ablation_shard0.log to logs\ablation_shard3.log
  goto :eof)
if "%1"=="ablation-progress" python tools\ablation_runner.py progress --root %ABL% & goto :eof
if "%1"=="ablation-analyse" python tools\ablation_analysis.py --root %ABL% --out analysis\ablation & goto :eof
if "%1"=="figures" python figures\make_figures.py --ablation analysis\ablation --min7 %MIN7%\summary\comparison_runs.csv & goto :eof
if "%1"=="latex-check" python manuscript\check_latex.py manuscript\main.tex manuscript\references.bib & goto :eof
if "%1"=="latex" (
  pushd manuscript
  %PDFLATEX% -interaction=nonstopmode -halt-on-error main
  if errorlevel 1 (popd & echo LaTeX build failed at pdflatex pass 1: see manuscript\main.log and manuscript\main.blg & exit /b 1)
  %BIBTEX% main
  if errorlevel 1 (popd & echo LaTeX build failed at bibtex: see manuscript\main.log and manuscript\main.blg & exit /b 1)
  %PDFLATEX% -interaction=nonstopmode -halt-on-error main
  if errorlevel 1 (popd & echo LaTeX build failed at pdflatex pass 2: see manuscript\main.log and manuscript\main.blg & exit /b 1)
  %PDFLATEX% -interaction=nonstopmode -halt-on-error main
  if errorlevel 1 (popd & echo LaTeX build failed at pdflatex pass 3: see manuscript\main.log and manuscript\main.blg & exit /b 1)
  popd
  goto :eof)
if "%1"=="robustness-plan" python tools\robustness\robustness_runner.py plan --root %ROB% & goto :eof
if "%1"=="robustness-prepare" python tools\robustness\robustness_runner.py prepare --root %ROB% --approved-plan %2 & goto :eof
if "%1"=="robustness-run" (
  start "rob0" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 0/4 ^> logs\robustness_shard0.log 2^>^&1
  start "rob1" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 1/4 ^> logs\robustness_shard1.log 2^>^&1
  start "rob2" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 2/4 ^> logs\robustness_shard2.log 2^>^&1
  start "rob3" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 3/4 ^> logs\robustness_shard3.log 2^>^&1
  echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
  echo Check completion with: ETAPES.cmd robustness-progress, and logs\robustness_shard0.log to logs\robustness_shard3.log
  goto :eof)
if "%1"=="robustness-progress" python tools\robustness\robustness_runner.py progress --root %ROB% & goto :eof
if "%1"=="robustness-analyse" python tools\robustness\robustness_analysis.py --root %ROB% --out analysis\robustness & goto :eof
if "%1"=="robustness-smoke" python tools\robustness\smoke.py --root %QMIX_RESULTS%\robustness_smoke_NEW --checkpoint %QMIX_RESULTS%\qualification_300m_medium_timing_amendment002r\learners\qmix\seed101\qmix_seed101_t350000.pth & goto :eof
if "%1"=="robustness-check-smoke" python tools\robustness\cell_state.py check-smoke --root %QMIX_RESULTS%\robustness_smoke_2026-10-29 & goto :eof
if "%1"=="comparators-plan" python tools\comparators\comparator_search.py plan --root %CMP% & goto :eof
if "%1"=="comparators-measure" python tools\comparators\comparator_search.py measure --root %CMP% & goto :eof
if "%1"=="comparators-prepare" python tools\comparators\comparator_search.py prepare --root %CMP% --approved-plan %2 & goto :eof
if "%1"=="comparators-verify-manifests" python tools\comparators\comparator_search.py verify-manifests --root %CMP% --robustness-root %ROB% & goto :eof
if "%1"=="comparators-run" (
  start "cmp0" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 0/4 ^> logs\comparators_%2_shard0.log 2^>^&1
  start "cmp1" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 1/4 ^> logs\comparators_%2_shard1.log 2^>^&1
  start "cmp2" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 2/4 ^> logs\comparators_%2_shard2.log 2^>^&1
  start "cmp3" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 3/4 ^> logs\comparators_%2_shard3.log 2^>^&1
  echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
  echo Check completion with: ETAPES.cmd comparators-progress, and logs\comparators_%2_shard0.log to shard3.log
  goto :eof)
if "%1"=="comparators-progress" python tools\comparators\comparator_search.py progress --root %CMP% & goto :eof
if "%1"=="comparators-finalise" python tools\comparators\comparator_search.py finalise --root %CMP% --stage %2 & goto :eof
if "%1"=="mp-check-static" python tools\comparators\mp_check.py static --out logs\mp_check_static.json & goto :eof
if "%1"=="mp-check-robustness" python tools\comparators\mp_check.py robustness --root %ROB% --out analysis\mp_check_robustness.json & goto :eof
if "%1"=="j-cycle" python tools\article_analyses\j_cycle_curve.py --roots %QMIX_RESULTS%\qualification_300m_medium_official %QMIX_RESULTS%\qualification_300m_medium_boundary_audit_20260920 %QMIX_RESULTS%\qualification_300m_medium_timing_amendment002r %MIN7% --ablation-cells analysis\ablation\cells.csv --fixed-plan-runs figures\data\fig1_same_traffic_performance.csv --out analysis\j_cycle & goto :eof
if "%1"=="cp-ablation" python tools\article_analyses\clopper_pearson.py --ablation analysis\ablation\cells.csv --out analysis\cp_ablation & goto :eof
if "%1"=="cp-robustness" python tools\article_analyses\clopper_pearson.py --robustness analysis\robustness\cells.csv --out analysis\cp_robustness & goto :eof
if "%1"=="guarantee-diagnostic" python tools\article_analyses\guarantee_diagnostic.py --root %ROB% --analysis analysis\robustness --out analysis\guarantee_diagnostic & goto :eof
if "%1"=="check-r0-demand" python tools\comparators\check_r0_demand.py --out logs\check_r0_demand.json & goto :eof
if "%1"=="check-statistics" python tools\confirmation\check_statistics.py --a004 %2 --out logs\check_statistics.json & goto :eof
if "%1"=="dois" python docs\literature\verify_dois.py & goto :eof
if "%1"=="archive" python tools\make_archive.py & goto :eof
echo Unknown step "%1". See the header of this file and README.md.
exit /b 2
