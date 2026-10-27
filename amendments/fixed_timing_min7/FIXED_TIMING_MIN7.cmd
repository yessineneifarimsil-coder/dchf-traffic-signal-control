@echo off
REM ==========================================================================
REM Etude min7 : plan fixe optimise (optimized_fixed_timing) recherche de
REM nouveau sous un vert minimal de 7 s, puis comparaison de developpement
REM sur les trafics 9301-9305.
REM
REM Usage : FIXED_TIMING_MIN7.cmd ETAPE [EMPREINTE]
REM
REM Ordre des etapes (chacune verifie la precedente et s'arrete sinon) :
REM   verifier                 empreintes, depot fige, tests simules (aucune ecriture sur D:)
REM   plan                     lecture seule : reconstitution, domaines, comptes, empreinte
REM   sumo                     verifications SUMO reelles -> RACINE\checks ; la mesure
REM                            (measure.json) n'est ecrite que si tout est complet et reussi
REM   plan                     de nouveau : estimations fondees sur la mesure locale
REM   preparer EMPREINTE_PLAN  espace disque, plan.json scelle
REM   grossier                 classement grossier (executions reutilisees verifiees),
REM                            5 gagnants, ordre fin scelle, nombre EXACT d'executions fines
REM   repro                    re-simulation des 5 gagnants (25 executions, controle 1e-12)
REM   fin EMPREINTE_GROSSIER   executions fines nouvelles (apres lecture du nombre exact) ;
REM                            refusee avant toute simulation si la reproduction est
REM                            absente, incomplete ou differente
REM   finaliser-fin            controle de reproduction, top 10
REM   validation               10 x 5 executions sur 2101-2105
REM   selection                regle figee ; plan min7 scelle avec parametres et empreintes
REM   preparer-comparaison     manifestes 9301-9305 (identiques aux pilotes), 60 cellules
REM   comparaison              A 5 + B 5 + QMIX historiques 50 = 60 evaluations
REM   avancement               evaluations enregistrees / 60 et cellules en attente
REM   adopter                  apres une interruption seulement : scelle un resultat ecrit
REM                            sans marqueur si sa provenance est verifiee ; refuse sinon ;
REM                            ne simule jamais, ne modifie aucun fichier existant ;
REM                            relancer ensuite l'etape interrompue (aucune simulation)
REM   synthese                 tableaux par trafic, moyennes, ecarts apparies, pilotes lus
REM
REM Variables (facultatives, a definir avant l'appel) :
REM   AQ_FROZEN_REPOSITORY  checkout propre du commit 8c14f32 (lu, jamais modifie)
REM   MIN7_ROOT             racine des nouveaux resultats
REM   MIN7_WORKERS          processus SUMO paralleles (defaut 4)
REM   PYTHON                interpreteur de l'environnement des campagnes (defaut python)
REM ==========================================================================
setlocal
set "TOOL=%~dp0"
if not defined AQ_FROZEN_REPOSITORY set "AQ_FROZEN_REPOSITORY=C:\Users\LENOVO\QMIX_Traffic_Coordination"
if not defined MIN7_ROOT set "MIN7_ROOT=D:\QMIX_Results\fixed_timing_min7_2026-10-27"
if not defined MIN7_WORKERS set "MIN7_WORKERS=4"
if not defined PYTHON set "PYTHON=python"
set "DRIVER=%TOOL%fixed_timing_min7.py"
set "COMMON=--repository-root "%AQ_FROZEN_REPOSITORY%" --root "%MIN7_ROOT%""

if /i "%~1"=="verifier" goto verifier
if /i "%~1"=="plan" goto plan
if /i "%~1"=="sumo" goto sumo
if /i "%~1"=="preparer" goto preparer
if /i "%~1"=="grossier" goto grossier
if /i "%~1"=="repro" goto repro
if /i "%~1"=="fin" goto fin
if /i "%~1"=="finaliser-fin" goto finaliser_fin
if /i "%~1"=="validation" goto validation
if /i "%~1"=="selection" goto selection
if /i "%~1"=="preparer-comparaison" goto preparer_comparaison
if /i "%~1"=="comparaison" goto comparaison
if /i "%~1"=="avancement" goto avancement
if /i "%~1"=="adopter" goto adopter
if /i "%~1"=="synthese" goto synthese
echo Etape inconnue ou absente : "%~1". Voir l'en-tete de ce fichier.
exit /b 2

:verifier
echo == Empreintes SHA-256 (a comparer a SHA256SUMS.txt) ==
for %%F in (fixed_timing_min7.py amendment002.py sumo_checks_min7.py test_fixed_timing_min7.py) do certutil -hashfile "%TOOL%%%F" SHA256
echo == Depot fige (attendu : 8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d, aucune ligne de statut) ==
git -C "%AQ_FROZEN_REPOSITORY%" rev-parse HEAD
git -C "%AQ_FROZEN_REPOSITORY%" status --porcelain
echo == Tests simules (aucune simulation SUMO, aucune ecriture sur D:) ==
pushd "%TOOL%"
"%PYTHON%" -B -m unittest test_fixed_timing_min7 -v
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:plan
"%PYTHON%" -B "%DRIVER%" plan %COMMON%
exit /b %ERRORLEVEL%

:sumo
"%PYTHON%" -B "%TOOL%sumo_checks_min7.py" %COMMON%
exit /b %ERRORLEVEL%

:preparer
if "%~2"=="" (
  echo Indiquez l'empreinte du plan affichee par l'etape plan.
  exit /b 2
)
"%PYTHON%" -B "%DRIVER%" prepare %COMMON% --approved-plan %~2
exit /b %ERRORLEVEL%

:grossier
"%PYTHON%" -B "%DRIVER%" finalise-coarse %COMMON%
exit /b %ERRORLEVEL%

:repro
"%PYTHON%" -B "%DRIVER%" run-repro %COMMON% --workers %MIN7_WORKERS%
exit /b %ERRORLEVEL%

:fin
if "%~2"=="" (
  echo Indiquez l'empreinte de l'ordre grossier affichee par l'etape grossier.
  exit /b 2
)
"%PYTHON%" -B "%DRIVER%" run-fine %COMMON% --workers %MIN7_WORKERS% --approved-coarse %~2
exit /b %ERRORLEVEL%

:finaliser_fin
"%PYTHON%" -B "%DRIVER%" finalise-fine %COMMON%
exit /b %ERRORLEVEL%

:validation
"%PYTHON%" -B "%DRIVER%" run-validation %COMMON% --workers %MIN7_WORKERS%
exit /b %ERRORLEVEL%

:selection
"%PYTHON%" -B "%DRIVER%" finalise-validation %COMMON%
exit /b %ERRORLEVEL%

:preparer_comparaison
"%PYTHON%" -B "%DRIVER%" prepare-comparison %COMMON%
exit /b %ERRORLEVEL%

:comparaison
"%PYTHON%" -B "%DRIVER%" run-comparison %COMMON% --workers %MIN7_WORKERS%
exit /b %ERRORLEVEL%

:avancement
"%PYTHON%" -B "%DRIVER%" progress %COMMON%
exit /b %ERRORLEVEL%

:adopter
"%PYTHON%" -B "%DRIVER%" adopt-results %COMMON%
exit /b %ERRORLEVEL%

:synthese
"%PYTHON%" -B "%DRIVER%" summarise %COMMON%
exit /b %ERRORLEVEL%
