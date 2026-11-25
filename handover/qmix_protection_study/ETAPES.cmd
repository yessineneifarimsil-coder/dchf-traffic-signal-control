@echo off
rem Ordered steps of the protection study (Windows, conda env traffic_rl). Run from this folder:
rem     cd /d C:\research\qmix_protection_study
rem     ETAPES.cmd <step>
rem Steps: tests | diagnose | ablation-plan | ablation-prepare <fingerprint> | ablation-run | ablation-progress |
rem        ablation-analyse | figures | latex-check | latex | robustness-plan | robustness-prepare <fingerprint> |
rem        robustness-run | robustness-progress | robustness-analyse | robustness-smoke |
rem        robustness-check-smoke | dois | archive
rem Comparators (plans/PLAN_COMPARATEURS.md; root CMP): comparators-plan | comparators-measure |
rem        comparators-prepare <fingerprint> | comparators-run <stage> | comparators-progress |
rem        comparators-finalise <stage> | comparators-verify-manifests
rem Read-only analyses: mp-check-static | mp-check-robustness | j-cycle | cp-ablation | cp-robustness |
rem        guarantee-diagnostic | check-r0-demand | check-statistics <file> (withdrawn from the B freeze, see
rem        plans\PROTOCOL_AMENDMENT_B.md section 2)
rem Disk (read-only audit, verified archive of campaign A design runs): disk-audit | archive-a [zip path] |
rem        archive-a-dryrun. Deleting campaign A data is DISABLED in this delivery (rectificatif 2026-11-23).
rem Campaign A-ext (actuated, 5 s minimum green; root AEXT): aext-plan | aext-prepare <fingerprint> |
rem        aext-run <stage> | aext-progress | aext-finalise <stage>     (stages: aext-design, aext-validation)
rem Campaign B (confirmation; root BCONF; RUNBOOK_B.md): b-plan | b-measure (parallel run-in, design seeds) |
rem        b-stats-results | b-stats-resolve (procedure b-crossed-bootstrap-1, statistics-1.1 implementation) |
rem        b-stats-inspect / b-stats-extract <A003 folder> (read-only diagnostics of the historical statistics-1.2
rem        reference, not claimed) | b-freeze (needs logs\verify_etapes_B.txt, logs\tests_B.txt and the
rem        statistical resolution, see RUNBOOK_B.md) | b-prepare <fingerprint> | b-run | b-progress | b-analyse
rem Operations: b-processes (0 none running, 3 workers running) | b-backup-logs | b-watch (second terminal)
rem Exit codes: every step ends with an explicit "exit /b <code>" so that CALL and "cmd /c ETAPES.cmd <step>"
rem both return the code of its script (2026-11-07 correction: "command & goto :eof" returned 0 under cmd /c on
rem Windows when the command failed). robustness-progress / comparators-progress: 0 every run finished, 3 some
rem not finished, 5 at least one corrupted result (same for aext-progress and b-progress); robustness-analyse: 0 complete and verified, 3 technical
rem criteria failed, 4 incomplete, 1 stopped. latex returns 1 as soon as pdflatex or bibtex fails.
rem ablation-run, robustness-run, comparators-run, aext-run and b-run only LAUNCH 4 workers in separate windows: their exit code
rem covers the launch, never the workers' success. Check completion with the matching *-progress step.
rem ROB (robustness root) defaults to the real root of 2026-11-04; the steps that read it stop with code 2
rem when the folder does not exist. Override with: set ROB=<folder> before calling.
setlocal
rem Console output of every Python step is UTF-8 (2026-11-25): a cp850/cp1252 console never makes a print fail.
set PYTHONIOENCODING=utf-8
if "%QMIX_RESULTS%"=="" set QMIX_RESULTS=D:\QMIX_Results
set ABL=%QMIX_RESULTS%\protection_ablation_2026-10-29
set MIN7=%QMIX_RESULTS%\fixed_timing_min7_2026-10-28
if "%ROB%"=="" set ROB=%QMIX_RESULTS%\robustness_validation_2026-11-04
if "%CMP%"=="" set CMP=%QMIX_RESULTS%\comparators_robustness_profiles
if "%AEXT%"=="" set AEXT=%QMIX_RESULTS%\comparators_actuated_g5
if "%BCONF%"=="" set BCONF=%QMIX_RESULTS%\confirmation_B
if "%PDFLATEX%"=="" set PDFLATEX=pdflatex
if "%BIBTEX%"=="" set BIBTEX=bibtex
call conda activate traffic_rl || (echo conda env traffic_rl not found & exit /b 2)

if "%~1"=="tests" goto s_tests
if "%~1"=="diagnose" goto s_diagnose
if "%~1"=="ablation-plan" goto s_ablation_plan
if "%~1"=="ablation-prepare" goto s_ablation_prepare
if "%~1"=="ablation-run" goto s_ablation_run
if "%~1"=="ablation-progress" goto s_ablation_progress
if "%~1"=="ablation-analyse" goto s_ablation_analyse
if "%~1"=="figures" goto s_figures
if "%~1"=="latex-check" goto s_latex_check
if "%~1"=="latex" goto s_latex
if "%~1"=="robustness-plan" goto s_robustness_plan
if "%~1"=="robustness-prepare" goto s_robustness_prepare
if "%~1"=="robustness-run" goto s_robustness_run
if "%~1"=="robustness-progress" goto s_robustness_progress
if "%~1"=="robustness-analyse" goto s_robustness_analyse
if "%~1"=="robustness-smoke" goto s_robustness_smoke
if "%~1"=="robustness-check-smoke" goto s_robustness_check_smoke
if "%~1"=="comparators-plan" goto s_comparators_plan
if "%~1"=="comparators-measure" goto s_comparators_measure
if "%~1"=="comparators-prepare" goto s_comparators_prepare
if "%~1"=="comparators-verify-manifests" goto s_comparators_verify_manifests
if "%~1"=="comparators-run" goto s_comparators_run
if "%~1"=="comparators-progress" goto s_comparators_progress
if "%~1"=="comparators-finalise" goto s_comparators_finalise
if "%~1"=="mp-check-static" goto s_mp_check_static
if "%~1"=="mp-check-robustness" goto s_mp_check_robustness
if "%~1"=="j-cycle" goto s_j_cycle
if "%~1"=="cp-ablation" goto s_cp_ablation
if "%~1"=="cp-robustness" goto s_cp_robustness
if "%~1"=="guarantee-diagnostic" goto s_guarantee_diagnostic
if "%~1"=="check-r0-demand" goto s_check_r0_demand
if "%~1"=="check-statistics" goto s_check_statistics
if "%~1"=="disk-audit" goto s_disk_audit
if "%~1"=="archive-a" goto s_archive_a
if "%~1"=="archive-a-dryrun" goto s_archive_a_dryrun
if "%~1"=="aext-plan" goto s_aext_plan
if "%~1"=="aext-prepare" goto s_aext_prepare
if "%~1"=="aext-run" goto s_aext_run
if "%~1"=="aext-progress" goto s_aext_progress
if "%~1"=="aext-finalise" goto s_aext_finalise
if "%~1"=="b-plan" goto s_b_plan
if "%~1"=="b-measure" goto s_b_measure
if "%~1"=="b-stats-results" goto s_b_stats_results
if "%~1"=="b-stats-inspect" goto s_b_stats_inspect
if "%~1"=="b-stats-extract" goto s_b_stats_extract
if "%~1"=="b-stats-resolve" goto s_b_stats_resolve
if "%~1"=="b-freeze" goto s_b_freeze
if "%~1"=="b-prepare" goto s_b_prepare
if "%~1"=="b-run" goto s_b_run
if "%~1"=="b-progress" goto s_b_progress
if "%~1"=="b-analyse" goto s_b_analyse
if "%~1"=="b-processes" goto s_b_processes
if "%~1"=="b-backup-logs" goto s_b_backup_logs
if "%~1"=="b-watch" goto s_b_watch
if "%~1"=="dois" goto s_dois
if "%~1"=="archive" goto s_archive
echo Unknown step "%~1". See the header of this file and README.md.
exit /b 2

:s_tests
python -m unittest discover -s tests -v
exit /b %errorlevel%

:s_diagnose
python diagnosis\diagnose_clearance_failure.py --runs-root %MIN7%\comparison\runs --model qmix_seed101_t350000 --failed 9305 --ok 9301 9302 9303 9304 --out diagnosis\out_qmix101_t350000_9305
exit /b %errorlevel%

:s_ablation_plan
python tools\ablation_runner.py plan --root %ABL%
exit /b %errorlevel%

:s_ablation_prepare
python tools\ablation_runner.py prepare --root %ABL% --approved-plan %2
exit /b %errorlevel%

:s_ablation_run
set "LAUNCH_RC=0"
start "abl0" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 0/4 ^> logs\ablation_shard0.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "abl1" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 1/4 ^> logs\ablation_shard1.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "abl2" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 2/4 ^> logs\ablation_shard2.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "abl3" cmd /c python -u tools\ablation_runner.py run --root %ABL% --shard 3/4 ^> logs\ablation_shard3.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
echo Check completion with: ETAPES.cmd ablation-progress, and logs\ablation_shard0.log to logs\ablation_shard3.log
exit /b %LAUNCH_RC%

:s_ablation_progress
python tools\ablation_runner.py progress --root %ABL%
exit /b %errorlevel%

:s_ablation_analyse
python tools\ablation_analysis.py --root %ABL% --out analysis\ablation
exit /b %errorlevel%

:s_figures
python figures\make_figures.py --ablation analysis\ablation --min7 %MIN7%\summary\comparison_runs.csv
exit /b %errorlevel%

:s_latex_check
python manuscript\check_latex.py manuscript\main.tex manuscript\references.bib
exit /b %errorlevel%

:s_latex
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
exit /b 0

:s_robustness_plan
python tools\robustness\robustness_runner.py plan --root %ROB%
exit /b %errorlevel%

:s_robustness_prepare
python tools\robustness\robustness_runner.py prepare --root %ROB% --approved-plan %2
exit /b %errorlevel%

:s_robustness_run
if not exist "%ROB%\" goto rob_missing
set "LAUNCH_RC=0"
start "rob0" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 0/4 ^> logs\robustness_shard0.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "rob1" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 1/4 ^> logs\robustness_shard1.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "rob2" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 2/4 ^> logs\robustness_shard2.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "rob3" cmd /c python -u tools\robustness\robustness_runner.py run --root %ROB% --shard 3/4 ^> logs\robustness_shard3.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
echo Check completion with: ETAPES.cmd robustness-progress, and logs\robustness_shard0.log to logs\robustness_shard3.log
exit /b %LAUNCH_RC%

:s_robustness_progress
if not exist "%ROB%\" goto rob_missing
python tools\robustness\robustness_runner.py progress --root %ROB%
exit /b %errorlevel%

:s_robustness_analyse
if not exist "%ROB%\" goto rob_missing
python tools\robustness\robustness_analysis.py --root %ROB% --out analysis\robustness
exit /b %errorlevel%

:s_robustness_smoke
python tools\robustness\smoke.py --root %QMIX_RESULTS%\robustness_smoke_NEW --checkpoint %QMIX_RESULTS%\qualification_300m_medium_timing_amendment002r\learners\qmix\seed101\qmix_seed101_t350000.pth
exit /b %errorlevel%

:s_robustness_check_smoke
python tools\robustness\cell_state.py check-smoke --root %QMIX_RESULTS%\robustness_smoke_2026-10-29
exit /b %errorlevel%

:s_comparators_plan
python tools\comparators\comparator_search.py plan --root %CMP%
exit /b %errorlevel%

:s_comparators_measure
python tools\comparators\comparator_search.py measure --root %CMP%
exit /b %errorlevel%

:s_comparators_prepare
python tools\comparators\comparator_search.py prepare --root %CMP% --approved-plan %2
exit /b %errorlevel%

:s_comparators_verify_manifests
if not exist "%ROB%\" goto rob_missing
python tools\comparators\comparator_search.py verify-manifests --root %CMP% --robustness-root %ROB%
exit /b %errorlevel%

:s_comparators_run
set "LAUNCH_RC=0"
start "cmp0" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 0/4 ^> logs\comparators_%2_shard0.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "cmp1" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 1/4 ^> logs\comparators_%2_shard1.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "cmp2" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 2/4 ^> logs\comparators_%2_shard2.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "cmp3" cmd /c python -u tools\comparators\comparator_search.py run --root %CMP% --stage %2 --shard 3/4 ^> logs\comparators_%2_shard3.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
echo Check completion with: ETAPES.cmd comparators-progress, and logs\comparators_%2_shard0.log to logs\comparators_%2_shard3.log
exit /b %LAUNCH_RC%

:s_comparators_progress
python tools\comparators\comparator_search.py progress --root %CMP%
exit /b %errorlevel%

:s_comparators_finalise
python tools\comparators\comparator_search.py finalise --root %CMP% --stage %2
exit /b %errorlevel%

:s_mp_check_static
python tools\comparators\mp_check.py static --out logs\mp_check_static.json
exit /b %errorlevel%

:s_mp_check_robustness
if not exist "%ROB%\" goto rob_missing
python tools\comparators\mp_check.py robustness --root %ROB% --out analysis\mp_check_robustness.json
exit /b %errorlevel%

:s_j_cycle
python tools\article_analyses\j_cycle_curve.py --roots %QMIX_RESULTS%\qualification_300m_medium_official %QMIX_RESULTS%\qualification_300m_medium_boundary_audit_20260920 %QMIX_RESULTS%\qualification_300m_medium_timing_amendment002r %MIN7% --ablation-cells analysis\ablation\cells.csv --fixed-plan-runs figures\data\fig1_same_traffic_performance.csv --out analysis\j_cycle
exit /b %errorlevel%

:s_cp_ablation
python tools\article_analyses\clopper_pearson.py --ablation analysis\ablation\cells.csv --out analysis\cp_ablation
exit /b %errorlevel%

:s_cp_robustness
python tools\article_analyses\clopper_pearson.py --robustness analysis\robustness\cells.csv --out analysis\cp_robustness
exit /b %errorlevel%

:s_guarantee_diagnostic
if not exist "%ROB%\" goto rob_missing
python tools\article_analyses\guarantee_diagnostic.py --root %ROB% --analysis analysis\robustness --out analysis\guarantee_diagnostic
exit /b %errorlevel%

:s_check_r0_demand
python tools\comparators\check_r0_demand.py --out logs\check_r0_demand.json
exit /b %errorlevel%

:s_check_statistics
python tools\confirmation\check_statistics.py --a004 %2 --out logs\check_statistics.json
exit /b %errorlevel%

:s_disk_audit
python tools\disk\audit_storage.py --qmix-results %QMIX_RESULTS% --a-root %CMP% --aext-root %AEXT% --b-root %BCONF% --out logs\storage_audit.json
exit /b %errorlevel%

:s_archive_a
if not "%~2"=="" goto s_archive_a_to
python tools\disk\archive_campaign_A.py archive --a-root %CMP%
exit /b %errorlevel%

:s_archive_a_to
python tools\disk\archive_campaign_A.py archive --a-root %CMP% --zip "%~2"
exit /b %errorlevel%

:s_archive_a_dryrun
python tools\disk\archive_campaign_A.py --dry-run --a-root %CMP%
exit /b %errorlevel%

:s_aext_plan
python tools\comparators_ext\aext_search.py plan --root %AEXT% --a-root %CMP%
exit /b %errorlevel%

:s_aext_prepare
python tools\comparators_ext\aext_search.py prepare --root %AEXT% --a-root %CMP% --approved-plan %2
exit /b %errorlevel%

:s_aext_run
set "LAUNCH_RC=0"
start "aext0" cmd /c python -u tools\comparators_ext\aext_search.py run --root %AEXT% --stage %2 --shard 0/4 ^> logs\aext_%2_shard0.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "aext1" cmd /c python -u tools\comparators_ext\aext_search.py run --root %AEXT% --stage %2 --shard 1/4 ^> logs\aext_%2_shard1.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "aext2" cmd /c python -u tools\comparators_ext\aext_search.py run --root %AEXT% --stage %2 --shard 2/4 ^> logs\aext_%2_shard2.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "aext3" cmd /c python -u tools\comparators_ext\aext_search.py run --root %AEXT% --stage %2 --shard 3/4 ^> logs\aext_%2_shard3.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
echo Check completion with: ETAPES.cmd aext-progress, and logs\aext_%2_shard0.log to logs\aext_%2_shard3.log
exit /b %LAUNCH_RC%

:s_aext_progress
python tools\comparators_ext\aext_search.py progress --root %AEXT%
exit /b %errorlevel%

:s_aext_finalise
python tools\comparators_ext\aext_search.py finalise --root %AEXT% --stage %2
exit /b %errorlevel%

:s_b_plan
if not exist "%ROB%\" goto rob_missing
python tools\confirmation\b_runner.py plan --root %BCONF% --a-root %CMP% --aext-root %AEXT% --rob-root %ROB%
exit /b %errorlevel%

:s_b_measure
if not exist "%ROB%\" goto rob_missing
python tools\confirmation\b_runner.py measure --root %BCONF% --a-root %CMP% --aext-root %AEXT% --rob-root %ROB%
exit /b %errorlevel%

:s_b_stats_results
python -B tools\confirmation\stats_reference.py results --out logs\stats_reference_check.json
exit /b %errorlevel%

:s_b_stats_inspect
python -B tools\confirmation\stats_reference.py inspect-a003 --a003 "%~2" --out logs\a003_inspection.json
exit /b %errorlevel%

:s_b_stats_extract
python -B tools\confirmation\stats_reference.py extract-a003 --a003 "%~2" --inspection logs\a003_inspection.json --out logs\a003_extract.json
exit /b %errorlevel%

:s_b_stats_resolve
python -B tools\confirmation\stats_reference.py resolve --root %BCONF% --procedure b-crossed-bootstrap-1 --results logs\stats_reference_check.json
exit /b %errorlevel%

:s_b_freeze
if not exist "%ROB%\" goto rob_missing
python tools\confirmation\b_runner.py freeze --root %BCONF% --a-root %CMP% --aext-root %AEXT% --rob-root %ROB%
exit /b %errorlevel%

:s_b_prepare
if not exist "%ROB%\" goto rob_missing
python tools\confirmation\b_runner.py prepare --root %BCONF% --a-root %CMP% --aext-root %AEXT% --rob-root %ROB% --approved-plan %2
exit /b %errorlevel%

:s_b_run
python tools\confirmation\b_runner.py preflight --root %BCONF%
if errorlevel 1 goto b_run_refused
set "LAUNCH_RC=0"
start "b0" cmd /c python -u tools\confirmation\b_runner.py run --root %BCONF% --shard 0/4 ^> logs\b_shard0.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "b1" cmd /c python -u tools\confirmation\b_runner.py run --root %BCONF% --shard 1/4 ^> logs\b_shard1.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "b2" cmd /c python -u tools\confirmation\b_runner.py run --root %BCONF% --shard 2/4 ^> logs\b_shard2.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
start "b3" cmd /c python -u tools\confirmation\b_runner.py run --root %BCONF% --shard 3/4 ^> logs\b_shard3.log 2^>^&1
if errorlevel 1 set "LAUNCH_RC=1"
echo 4 workers launched in separate windows. This exit code covers the launch only, not the workers' results.
echo Check completion with: ETAPES.cmd b-progress, and logs\b_shard0.log to logs\b_shard3.log
exit /b %LAUNCH_RC%

:b_run_refused
echo STOP: b-run refused before launching any worker (see the message above). Nothing was started.
exit /b 1

:s_b_progress
python tools\confirmation\b_runner.py progress --root %BCONF%
exit /b %errorlevel%

:s_b_analyse
python tools\confirmation\b_runner.py analyse --root %BCONF% --out analysis\confirmation
exit /b %errorlevel%

:s_b_processes
python tools\monitor\b_watch.py processes --b-root %BCONF% --aext-root %AEXT%
exit /b %errorlevel%

:s_b_backup_logs
python tools\monitor\b_watch.py backup-logs --b-root %BCONF% --aext-root %AEXT%
exit /b %errorlevel%

:s_b_watch
python tools\monitor\b_watch.py watch --b-root %BCONF% --aext-root %AEXT% --interval 600
exit /b %errorlevel%

:s_dois
python docs\literature\verify_dois.py
exit /b %errorlevel%

:s_archive
python tools\make_archive.py
exit /b %errorlevel%

:rob_missing
echo STOP: robustness root ROB=%ROB% does not exist. Set ROB to the robustness root before calling, e.g.
echo       set ROB=D:\QMIX_Results\robustness_validation_2026-11-04
exit /b 2
