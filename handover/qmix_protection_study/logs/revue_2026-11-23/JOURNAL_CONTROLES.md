# Journal des contrôles exécutés (2026-11-23)

**Environnement de revue.** Conteneur Linux, Python 3.11.17, numpy 2.4.6, SUMO 1.28.0. Le code figé est `QMIX_Traffic_Coordination` à 8c14f32, `statistics.py` = `ed133bb2…`. Le paquet protégé `adaptive_qmix_protected` est absent ; il n'y a ni Windows, ni D:.

**Ce journal ne contient que ce qui a réellement été lancé ici.** Les contrôles Windows sont dans `RUNBOOK_B.md` ; ils n'ont pas été lancés.

| # | Contrôle | Commande | Résultat observé | Fichier |
|---|---|---|---|---|
| 1 | Reproduction des défauts sur a9640b1 | `python -B logs/revue_2026-11-23/repro_defauts_classify_recheck.py <copie a9640b1>` | (a) `('complete', [])` pour une cellule avec garantie à compteur 200 s et écart SUMO 3 ; (b) relecture `[]` après modification de ces deux champs | `repro_avant_a9640b1.log` |
| 2 | Même script, code corrigé | même commande, sur la copie de travail | (a) `corrupted` avec 3 violations nommées ; (b) `max_counter_s: stored 200, re-read 16`, `sumo_mismatch_s: stored 3, re-read 0` | `repro_apres_correctif.log` |
| 3 | Suite complète des tests | `python -B -m unittest discover -s tests` | 167 tests, 165 passent. Les 2 erreurs (`test_ablation_metrics.CounterReconstruction`, `test_robustness.Adapter`) viennent de l'absence d'`adaptive_qmix_protected` ; elles sont identiques sur 42b58f2 et a9640b1 | `unittest_all_cloud_py311.log` |
| 4 | Incident de test (consigné) | même commande, lancée pendant que je modifiais `confirmation_plan.json` | 7 échecs : l'empreinte du code a changé entre le rodage et le gel d'un même test. Le lancement suivant, sans modification concurrente, donne le résultat n° 3. Seul, `test_b_runner` passe ses 45 tests | — |
| 5 | Résultats de référence statistiques | `python -B tools/confirmation/stats_reference.py results` | `REPRODUCED: 74 numbers checked, 0 differences (numpy 2.4.6, python 3.11.17)` | `stats_reference_results_cloud.log` |
| 6 | Décompte de B | `b_runner.py plan`, avec les sélections réelles de A et des doublures pour A-ext et la racine robustesse | `"runs": 2470`, `"learned": 2200`, `"comparators": 270` ; principaux R1 oft_g5 1,9399, R2 actuated_min7 1,3669, R3 tod_g5 2,7219, R0/R4 C19 2,7651 | `b_plan_stand_in_rob.log` |
| 7 | pyflakes | `python -m pyflakes <19 fichiers>` | 4 avertissements « imported but unused » : imports de détection de disponibilité (numpy, matplotlib, module figé), marqués `noqa` | `pyflakes.log` |
| 8 | Compatibilité Python 3.7 (statique) | `vermin -t=3.7- --no-tips --violations <19 fichiers>` | `Minimum required versions: 3.5` | `vermin.log` |
| 9 | Harness `cmd.exe` | `wine cmd /c "echo hi"` | `free(): invalid pointer`, code 134 : Wine est inutilisable ici. **Aucun code de retour cmd.exe observé** | `wine_unavailable.log` |
| 10 | Vérification R0 de la garantie | lecture de `guarantee_diagnostic/interventions.csv` (analyses du 2026-11-07) | Paires IDQN D2 : R1 17, R2 18, R0 0. Interventions listées en R0 : 2, QMIX, toutes après la demande. Le fichier ne couvre que les exécutions sélectionnées | — |
| 11 | Paramètres figés | lecture de `config/adaptive_qmix/qualification_300m_medium.json` et de `executors.py` | `control_interval_s` 5, `yellow_duration_s` 3, `switch_new_green_s` 2. Max Pressure : `minimum_green_s` par défaut 10, car la configuration n'a pas de section `baselines` | — |
| 12 | Statique d'ETAPES.cmd | `tests/test_etapes_cmd.py` (dans la suite n° 3) | 57 étapes à cette date (56 après la finalisation : `b-stats-resolve-12` retiré), CRLF, `exit /b` en fin de bloc, aucune commande de suppression, étapes statistiques en `python -B`, `b-freeze` sans import A003 | — |
| 13 | Archive de livraison | `python tools/make_archive.py --out <dossier>`, puis extraction dans un dossier neuf et `python tools/verify_manifest.py` | Le SHA-256 du ZIP ne peut pas figurer dans un fichier du ZIP : il est dans `<zip>.sha256`, livré à côté, et dans le rapport de livraison | — |
| 14 | Retour Windows (2026-11-24) : simulation CRLF, avant et après correctif | voir `logs/revue_2026-11-24/README.md` | Avant (b058301) : 51 tests, 28 échecs et 2 erreurs. Après : 175 tests, seules les 2 erreurs du paquet protégé absent ; `REPRODUCED` sur le fichier CRLF | `logs/revue_2026-11-24/` |
