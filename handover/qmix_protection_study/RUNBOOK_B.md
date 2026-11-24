# RUNBOOK B — de l'installation à l'analyse de la confirmation (version du 2026-11-24)

Ce document est la séquence complète, dans une **Anaconda Prompt** sous Windows. Chaque étape donne la commande exacte, la sortie et le code attendus, les fichiers produits et la conduite à tenir en cas d'écart. Les chemins marqués **[À RENSEIGNER]** ne sont pas connus ici : remplace-les avant de lancer la commande.

## Règles (à relire avant chaque session)

- **Ne jamais toucher** à `C:\research\libsignal_repro`, à `D:\IEV_Results` ni à leurs processus (campagne IEV). Ne jamais les arrêter.
- **Lecture seule** : la racine de A (`D:\QMIX_Results\comparators_robustness_profiles`), les dépôts figés, les checkpoints, et les résultats de A002, A003, A004, de l'ablation, de la robustesse et des comparateurs A. Cette livraison ne supprime aucune donnée.
- **Aucune mise à jour de `traffic_rl`**, sauf décision explicite.
- **Graines :**
  - 3001–3010 sont consommées ; 3101–3120 sont réservées ; 2201–2205 ne sont jamais utilisées ;
  - 8051–8060, 8151–8160, 8251–8260, 8351–8360 et 8451–8460 ne sont générées que par `b-prepare`, **après** `b-freeze`.
- **Ne jamais :**
  - relancer une cellule corrompue ou un échec scientifique ;
  - modifier un contrôleur ou une sélection parce qu'un résultat déplaît ;
  - modifier le code après le rodage. Il faudrait alors tout recommencer dans une nouvelle racine B.
- **Codes de sortie :**

| Code | Sens |
|---|---|
| 0 | Réussi, ou tout est terminé |
| 1 | `STOP:` avec un message ; rien n'a été modifié au-delà de ce que dit le message |
| 2 | Environnement conda ou dossier ROB introuvable |
| 3 | Pas encore terminé (pour `b-processes` : des travailleurs tournent) |
| 5 | Au moins une cellule corrompue ou en échec technique. Ne rien relancer, signaler |

- Les étapes `*-run` ne font que **lancer** 4 fenêtres : leur code ne porte que sur le lancement.
- **Durées** : ce sont des estimations. **Une nuit n'est pas garantie** pour B.

---

## Étape 0. Installation dans un nouveau dossier

| # | Commande | Attendu | Code | En cas d'écart |
|---|---|---|---|---|
| 0.1 | `certutil -hashfile "[À RENSEIGNER : chemin du ZIP reçu]" SHA256` | Le SHA-256 donné dans le rapport de livraison | 0 | Différent : ne pas extraire, redemander le ZIP |
| 0.2 | `mkdir C:\research\qmix_protection_study_B_2026-11-24` | Dossier créé. Il ne doit pas exister ; ne pas réutiliser l'ancien dossier | 0 | « existe déjà » : choisir un autre nom, ne rien écraser |
| 0.3 | `%SystemRoot%\System32\tar.exe -xf "[À RENSEIGNER : chemin du ZIP]" -C C:\research\qmix_protection_study_B_2026-11-24` | Aucune sortie (le tar de conda échoue avec « Cannot connect to C: » : utiliser celui-ci) | 0 | Erreur : copier le message |
| 0.4 | `cd /d C:\research\qmix_protection_study_B_2026-11-24` | — | 0 | — |
| 0.5 | `conda activate traffic_rl`, puis `python --version` et `sumo --version` | `Python 3.7.16` ; `Eclipse SUMO sumo Version 1.25…` (format exact non vérifié ici) | 0 | Autre version : le gel refusera ; signaler. `sumo` introuvable : vérifier `echo %SUMO_HOME%` ; le rodage lit `%SUMO_HOME%\bin\sumo` |
| 0.6 | `python tools\verify_manifest.py` | `… files listed, 0 problems …` puis `MANIFEST OK` | 0 | `different:` ou `missing:` : la copie n'est pas la livraison. Réextraire dans un nouveau dossier |

**Racines utilisées.** Ce sont les valeurs par défaut d'`ETAPES.cmd`. Les vérifier, ou les définir avant toute étape B, dans **la même** Anaconda Prompt :

```
set QMIX_RESULTS=D:\QMIX_Results
set ROB=D:\QMIX_Results\robustness_validation_2026-11-04
set CMP=D:\QMIX_Results\comparators_robustness_profiles
set AEXT=D:\QMIX_Results\comparators_actuated_g5
set BCONF=D:\QMIX_Results\confirmation_B
```

`BCONF` et `AEXT` peuvent viser un autre volume existant, par exemple `E:\QMIX_Results\confirmation_B` **[À RENSEIGNER si besoin]**. Garder la même valeur pour toutes les étapes de la campagne.

## Étape 1. Machine : alimentation, secteur, mises à jour

**1.1 Alimentation** (une commande par ligne ; les réglages s'appliquent au mode actif) :

```
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS PBUTTONACTION 0
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setactive SCHEME_CURRENT
```

Contrôle : `powercfg /qh SCHEME_CURRENT SUB_BUTTONS LIDACTION` doit afficher `0x00000000` sur secteur.

**1.2 Secteur :**

```
powershell -NoProfile -Command "(Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus -ErrorAction Stop).PowerOnline"
```

- Attendu : `True`.
- `False` : brancher le chargeur avant de continuer.
- Une erreur, ou aucune réponse, **n'est pas une validation**. Dans ce cas, contrôle alternatif :

  ```
  powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus"
  ```

  Attendu : `Online`. Si les deux échouent, vérifier visuellement le voyant du chargeur et le noter dans le journal.

**1.3 Pause des mises à jour :**

```
reg query "HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings" /v PauseUpdatesExpiryTime
```

- Une date **future** indique une pause **déclarée**. Ce n'est pas une garantie qu'aucun redémarrage ne soit déjà programmé : regarder aussi Paramètres > Windows Update.
- Une date passée, ou une valeur absente : réactiver la pause dans Paramètres. Ne pas modifier le registre à la main.

## Étape 2. Contrôles du code sous Windows

| # | Commande | Attendu | Code | Fichiers | En cas d'écart |
|---|---|---|---|---|---|
| 2.1 | `ETAPES.cmd tests > logs\tests_B.txt 2>&1`, puis `findstr /b "Ran OK FAILED" logs\tests_B.txt` | `Ran … tests` puis `OK` ou `OK (skipped=n)` | 0 | `logs\tests_B.txt` (lu par le gel) | `FAILED` : ne rien lancer. Envoyer le fichier |
| 2.2 | `tools\etapes_check\verify_etapes_cmd.cmd > logs\verify_etapes_B.txt 2>&1`, puis `findstr "Result:" logs\verify_etapes_B.txt` | `Result: … checks passed, 0 failed.` (total **attendu : 355**, non observé) | 0 | `logs\verify_etapes_B.txt` (lu par le gel) | Le moindre `FAIL` (`findstr FAIL logs\verify_etapes_B.txt`) : ne pas utiliser `ETAPES.cmd`, envoyer le rapport |

Le harness vérifie chaque étape deux fois, par `CALL` et par `cmd /c`, en réussite comme en échec. **Le total de 355 est attendu, pas observé** : 51 appels × 2 codes × 3 contrôles, plus 11 (LaTeX), plus 23 refus, plus 15 lancements parallèles. Ce qui compte, c'est **0 failed**. Les contrôles essentiels (2.1 et 2.2) doivent passer sans échec avant tout le reste. Un autre total avec « 0 failed » est à noter et à signaler, sans le corriger.

## Étape 3. Disque (lecture seule)

| # | Commande | Attendu | Code | Fichiers | En cas d'écart |
|---|---|---|---|---|---|
| 3.1 | `ETAPES.cmd disk-audit` | JSON contenant : l'espace libre de C: et D: ; la taille des dossiers de `D:\QMIX_Results` ; le total de `D:\IEV_Results` ; les besoins de B (2470 exécutions) et d'A-ext ; `B_target`, `A_ext_target` ; `B_can_start_on_free_space`, `A_ext_can_start_on_free_space` | 0 | `logs\storage_audit.json` | `false` : mettre `BCONF` ou `AEXT` sur un autre volume existant (étape 0), puis refaire 3.1. Les anciens chiffres d'espace libre (6,8 Go le 2026-11-15) sont périmés |
| 3.2 | (facultatif) `ETAPES.cmd archive-a [À RENSEIGNER : E:\QMIX_archives\campaignA_design_runs.zip]` | JSON finissant par `"ok": true` ; manifeste et vérification fichier par fichier | 0 | le zip, `.manifest.json`, `.verification.json` | Une archive **copiée ne libère pas** l'espace des originaux : cette livraison ne supprime rien |

**Besoin disque définitif.** C'est le volume mesuré par le rodage (5.2 et 5.3 : `bytes_per_run` × exécutions restantes, affiché par `start_threshold_gb`), plus une marge de 4 Go. L'audit 3.1 n'en donne qu'une estimation avant mesure. `b-freeze` et `b-run` refusent si le volume cible n'a pas ce besoin.

## Étape 4. Campagne A-ext : actionné à vert minimal de 5 s

C'est une extension des références classiques, pas une autorité identique à celle des apprenants. 480 simulations ; durée estimée d'environ 1 h, non garantie.

| # | Commande | Attendu | Code | En cas d'écart |
|---|---|---|---|---|
| 4.1 | `ETAPES.cmd aext-plan` | `runs_by_stage` : 405 et 75 ; `runs_upper_bound` : 480 ; `plan fingerprint: …` | 0 | Copier le message |
| 4.2 | `ETAPES.cmd aext-prepare <empreinte de 4.1>` | Manifestes contrôlés identiques à ceux de A ; ordre `aext-design` écrit | 0 | Manifestes différents : arrêter et signaler |
| 4.3 | `ETAPES.cmd aext-run aext-design` | 4 fenêtres | 0 | `STOP: not enough disk space` dans une fenêtre (`logs\aext_aext-design_shard<i>.log`) : voir l'étape 3 |
| 4.4 | `ETAPES.cmd aext-progress` | `aext-design` 405/405 ; `aext-validation` sans ordre encore | 3 | Interrompues : faire l'étape 9, puis refaire 4.3. Code 5 : ne rien relancer |
| 4.5 | `ETAPES.cmd aext-finalise aext-design` | Les 5 meilleurs par profil ; ordre `aext-validation` (75) | 0 | Copier le message |
| 4.6 | `ETAPES.cmd aext-run aext-validation` | 4 fenêtres | 0 | Comme 4.3 |
| 4.7 | `ETAPES.cmd aext-progress` | Les deux étapes terminées | 0 | Comme 4.4 |
| 4.8 | `ETAPES.cmd aext-finalise aext-validation` | `selections\R1_…__actuated_g5.json`, `R2_…`, `R3_…` | 0 | Un second appel refuse : c'est normal |

## Étape 5. Plan B et rodage réel

| # | Commande | Attendu | Code | Fichiers | En cas d'écart |
|---|---|---|---|---|---|
| 5.1 | `ETAPES.cmd b-plan` | Par profil : `QMIX/VDN 400`, `IDQN 200` en R0 et 0 ailleurs, comparateurs 30/70/70/70/30 ; une ligne `primary` par profil ; `"runs": 2470` (si les sélections restent celles attendues) ; l'empreinte | 0 | — | `sealed selections … required` : A-ext n'est pas finalisée. `IDQN checkpoints have training seeds …` : signaler. Un autre principal que oft_g5 (R1), actuated_min7 (R2), tod_g5 (R3) : c'est l'actionné g5 qui fait mieux en validation ; le noter. Un autre total : le noter, sans le corriger |
| 5.2 | `ETAPES.cmd b-measure` | 16 exécutions réelles sur graines de **conception**, 4 processus. Dernière ligne : `RUN-IN OK: 16 runs on design seeds, 4 workers, … runs/h`. Le JSON donne `by_type` (durée moyenne et maximale, volume par type de contrôleur), `parallel_efficiency`, `finalize_gzip_s_per_run`, `recheck_s_per_run`, `environment` (Python 3.7.16, SUMO 1.25) | 0 | `<BCONF>\measure.json`, `<BCONF>\measure_runs\` | `STOP: run-in failed …` : **ne pas geler** ; envoyer `<BCONF>\measure_failed_<date>.json`. C'est le premier passage réel de la chaîne complète |
| 5.3 | `ETAPES.cmd b-plan` | Même empreinte qu'en 5.1 ; `"source": "measure.json (parallel run-in, 4 workers)"`, `wall_h_4_workers`, `wall_h_4_workers_pessimistic`, `start_threshold_gb` | 0 | — | Empreinte différente : signaler. Une durée pessimiste trop longue n'est pas une raison de changer le plan |

## Étape 6. Procédure statistique : b-crossed-bootstrap-1 (avant le gel)

**Fins de ligne.** Sous Windows, git extrait `statistics.py` en CRLF : son SHA-256 brut est `0e43bf5b65696f7184d61e307c3ccc1f8226d2d1eef5a0aa36e0cec84a592fab`. Après normalisation CRLF→LF, il vaut `ed133bb2…`, celui du fichier de référence. Seule cette normalisation est admise ; tout autre écart de contenu est une différence de module.

La procédure retenue pour B est **`b-crossed-bootstrap-1`** : le bootstrap croisé apparié de l'implémentation statistics-1.1, avec la reproduction obligatoire de ses résultats de référence sur cette machine. statistics-1.2 n'est pas revendiqué.

| # | Commande | Attendu | Code | Fichiers | En cas d'écart |
|---|---|---|---|---|---|
| 6.1 | `ETAPES.cmd b-stats-results` | Deux lignes : `module identity: identical to the reference file after CRLF->LF normalisation (635 CRLF line endings; raw SHA-256 0e43bf5b…)` (ou `byte-identical …` si le fichier est en LF), puis `REPRODUCED: module identity OK \| numbers: 74 checked, 0 differing (numpy 1.21.6, python 3.7.16)` | 0 | `logs\stats_reference_check.json` | `DIFFERENT` (code 1) : ne pas résoudre, envoyer le fichier. Chaque différence est affichée sur sa propre ligne `DIFFERENT: …`, préfixée `module identity:` (le contenu du module diffère au-delà des fins de ligne) ou `number:` (une valeur recalculée diffère). Ne jamais « corriger » la référence |
| 6.2 | `ETAPES.cmd b-stats-resolve` | `RESOLVED: b-crossed-bootstrap-1: … not labelled statistics-1.2` | 0 | `<BCONF>\stats_resolution.json` | `STOP` : lire le message. 6.1 doit avoir réussi |
| 6.3 | (diagnostic facultatif, pour signaler l'état d'A003) `ETAPES.cmd b-stats-inspect C:\Users\LENOVO\QMIX_A003_P3\a003` | `files: … \| __pycache__: PRESENT/absent […] \| top-level code …: [] \| manifests: …` | 0 | `logs\a003_inspection.json` | Aucun import, rien n'est écrit dans A003. Un `__pycache__` présent est **signalé**, pas supprimé ; sa date n'est pas sa date de création. Ce diagnostic ne change pas la procédure de B |

`b-stats-extract` reste disponible pour un diagnostic historique (`python -B`, instantané avant et après). Il n'intervient pas dans le gel.

## Étape 7. Gel

| # | Commande | Attendu | Code | Fichiers | En cas d'écart |
|---|---|---|---|---|---|
| 7.1 | `ETAPES.cmd b-freeze` | `plan_fingerprint`, `margins_sha256`, `"jobs": 2470`, `statistical procedure: …`, puis `FROZEN. Next: b-prepare <empreinte>` | 0 | `<BCONF>\margins.json`, `<BCONF>\freeze.json` | Refus voulus : `no run-in` ; `run-in environment … is not Python 3.7 / SUMO 1.25` ; `code changed since the run-in` (rodage à refaire dans une **nouvelle** racine B) ; `etapes_check report …` (refaire 2.2) ; `unit_tests report …` (refaire 2.1) ; `statistical reference not resolved` ou `procedure … refused` (étape 6) ; `not enough disk space` (étape 3) ; `already frozen` |

**Après 7.1, ne plus rien modifier** dans ce dossier ni dans la racine B.

## Étape 8. Préparation, lancement, suivi

| # | Commande | Attendu | Code | En cas d'écart |
|---|---|---|---|---|
| 8.1 | `ETAPES.cmd b-prepare <empreinte de 7.1>` | `prepared … (2470 runs)` : 50 manifestes de confirmation, 30 checkpoints copiés et vérifiés | 0 | `differs from the freeze` : signaler. `already prepared` : passer à 8.2 |
| 8.2 | `ETAPES.cmd b-processes` | `0 B / A-ext process(es) running: a relaunch is possible` | 0 | Code 3 : des travailleurs tournent déjà, **ne pas relancer** |
| 8.3 | `ETAPES.cmd b-run` | `preflight OK: … runs to do, … GB required …`, puis 4 fenêtres | 0 | `STOP: not enough disk space` : aucune fenêtre lancée, voir l'étape 3. Autre `STOP` : copier le message |
| 8.4 | Dans une **seconde** Anaconda Prompt (même dossier, `conda activate traffic_rl`, mêmes `set`) : `ETAPES.cmd b-watch` | Toutes les 10 min : avancement par étape et par profil ; exécutions terminées dans les 30 dernières minutes et débit ; estimation du restant (`estimation indisponible` sans historique suffisant) ; processus B et A-ext actifs (sans compter le suivi lui-même) ; espace libre des volumes cibles | — | Arrêt par Ctrl+C. Le décompte « finished » est rapide ; l'état qui fait foi est celui de `b-progress` |
| 8.5 | `ETAPES.cmd b-progress` | `finished 2470/2470` | 0 | 3 : voir l'étape 9. 5 : ne rien relancer ; noter les lignes `TECHNICAL` ou `CORRUPTED` |

## Étape 9. Reprise après une interruption (coupure, redémarrage)

1. `ETAPES.cmd b-processes` doit répondre code 0. Avec le code 3, des travailleurs tournent encore : attendre.
2. `ETAPES.cmd b-backup-logs` copie `logs\b_shard*.log`, `logs\aext_*_shard*.log` et les `run_log_*.jsonl` dans `logs\backup_<date>\`. Rien n'est supprimé. Une relance écrase les journaux de console.
3. `ETAPES.cmd b-run`, ou `aext-run <étape>`. Une exécution interrompue est relancée une seule fois ; une cellule corrompue ou un échec scientifique ne le sont jamais.
4. Pour diagnostiquer un arrêt : `Get-WinEvent` sur le journal System, événements 41, 42, 1074 et 6008.

## Étape 10. Analyse

| # | Commande | Attendu | Code | Fichiers | En cas d'écart |
|---|---|---|---|---|---|
| 10.1 | `ETAPES.cmd b-analyse` | 12 lignes `[family of 12] …` (10 face aux classiques, 2 face à IDQN) avec les décisions, `missing cells: 0`, `written: analysis\confirmation` | 0 | `analysis\confirmation\` : `decisions.csv`, `technical_checks.json`, `service_counts.csv`, `results.json`, `RESULTATS_B.md`, `forest*.png` (si matplotlib est présent) | Décisions `BLOCKED` : un contrôle technique a échoué (`technical_checks.json`), aucune décision n'est rendue, signaler. `INCOMPLETE` : cellules absentes, jamais imputées |

Chaque cellule est relue depuis ses traces gzip, ce qui coûte environ 2470 × `recheck_s_per_run` de 5.2. L'option `--no-recheck`, qui ne passe pas par `ETAPES.cmd`, ne produit qu'un diagnostic, sans décision.

Aucune conclusion de B n'est rédigée avant ces fichiers.
