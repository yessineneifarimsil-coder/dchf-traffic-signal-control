# RUNBOOK B — de l'installation à l'analyse de la confirmation (rectifié le 2026-11-23)

> **Note.** La consigne du 2026-11-19 s'arrête à « Inclure en tête : ». Ce qui devait figurer ici n'a pas été reçu (voir `RETOURS.md`). L'en-tête ci-dessous contient les prérequis et les règles d'arrêt. Complète-le si ta consigne prévoyait autre chose.

## En-tête : prérequis et règles

**Nouvelle copie de travail versionnée.**
- Ne pas écraser `C:\research\qmix_protection_study`.
- Installer cette livraison dans un **nouveau dossier**, par exemple `C:\research\qmix_protection_study_B_2026-11-23`, à partir du commit indiqué dans le rapport de livraison (branche `claude/elegant-pascal-bid0st`, dossier `handover/qmix_protection_study`).
- Toute modification ultérieure se fait dans une nouvelle copie, jamais dans celle-ci après le gel.

**Ouvrir une Anaconda Prompt**, puis :

```
cd /d C:\research\qmix_protection_study_B_2026-11-23
```

`ETAPES.cmd` active `traffic_rl` lui-même. S'il ne le trouve pas, il renvoie le code 2. La pile attendue est **Python 3.7.16, PyTorch 1.13.1 CPU, SUMO 1.25** : le gel refuse toute autre version de Python ou de SUMO.

**Ne jamais toucher à :**
- `C:\research\libsignal_repro` ;
- `D:\IEV_Results`, ni aux processus de la campagne IEV (ne jamais les tuer) ;
- la racine de la campagne A (`D:\QMIX_Results\comparators_robustness_profiles`) : elle n'est que lue ;
- les artefacts A002, A003, A004 et ceux du test final.

**Aucune donnée de A n'est supprimée par cette livraison.** La suppression est désactivée dans le code ; l'étape correspondante n'existe plus.

**Avant le calcul long :**
- appliquer les réglages d'alimentation de la passation du 2026-11-15, section 7 (les commandes `powercfg` y sont ; elles ne sont pas recopiées ici) ;
- vérifier que Windows Update est en pause.

**Graines :**
- 3001–3010 sont consommées ; 3101–3120 sont réservées ; 2201–2205 ne sont jamais utilisées ;
- les graines de confirmation 8c51–8c60 ne sont générées que par `b-prepare`, après `b-freeze`.

**Codes de sortie :**

| Code | Sens |
|---|---|
| 0 | Réussi, ou toutes les exécutions sont terminées |
| 1 | `STOP:` avec un message ; rien n'a été modifié au-delà de ce que dit le message |
| 2 | Environnement conda ou dossier ROB introuvable |
| 3 | Exécutions pas toutes terminées : relancer l'étape `*-run` |
| 5 | Au moins un résultat corrompu. **Ne rien relancer.** Le noter et le signaler |

Les étapes `*-run` ne font que lancer 4 fenêtres. Leur code ne porte que sur le lancement.

**Ne jamais**, quel que soit le résultat :
- modifier un contrôleur ou relancer une sélection parce qu'un résultat déplaît ;
- relancer une exécution corrompue ;
- supprimer un dossier de résultats.

**Durées.** Ce sont des estimations, pas des engagements. **Une nuit n'est pas garantie** pour B : la durée réelle se lit en 3.3, d'après le rodage en parallèle.

---

## Étape 0. Installation et contrôles (avant tout)

| # | Commande | Sortie attendue | Code | Durée | En cas d'écart |
|---|---|---|---|---|---|
| 0.1 | `python tools\verify_manifest.py` | `MANIFEST OK` | 0 | secondes | `different:` ou `missing:` : la copie n'est pas la livraison. Ne pas continuer, la réinstaller |
| 0.2 | `ETAPES.cmd tests > logs\tests_B.txt 2>&1`, puis `findstr /b "Ran OK FAILED" logs\tests_B.txt` | `Ran … tests`, puis `OK`, ou `OK (skipped=n)` si un module figé manque | 0 | quelques minutes | `FAILED` : ne rien lancer. Le fichier sert au gel, qui le refusera |
| 0.3 | `tools\etapes_check\verify_etapes_cmd.cmd > logs\verify_etapes_B.txt 2>&1`, puis `findstr "Result:" logs\verify_etapes_B.txt` | `Result: 319 checks passed, 0 failed.` | 0 | 5 à 15 min | Le moindre `FAIL` (`findstr FAIL logs\verify_etapes_B.txt`) : ne pas utiliser `ETAPES.cmd`, copier le rapport. Le gel le refusera |
| 0.4 | `ETAPES.cmd disk-audit` | JSON avec l'espace libre de C: et D:, les dossiers de `D:\QMIX_Results`, les runs de A par étape, le total de `D:\IEV_Results`, les besoins estimés, et `B_can_start_on_free_space`. Écrit `logs\storage_audit.json`. Lecture seule | 0 | 1 à 10 min | `B_can_start_on_free_space` vaut `false` : voir l'étape 1 |

Le décompte de 319 contrôles en 0.3 se décompose ainsi :
- 213 contrôles du 2026-11-07 ;
- 90 pour les 15 nouveaux appels × 2 codes × 3 contrôles ;
- 8 pour les 4 refus quand ROB manque ;
- 2 pour le refus de `b-run` ;
- 6 pour les lancements parallèles `aext-run` et `b-run`.

Ce nombre est calculé, pas observé : s'il diffère alors qu'il y a « 0 failed », le noter.

## Étape 1. Si la place manque (aucune suppression)

Cette livraison ne libère pas de place en supprimant des données de A. Deux options :

- **Mettre la racine de B sur un disque qui a la place.** Avant 3.1, faire `set BCONF=E:\QMIX_Results\confirmation_B` (exemple), et garder la même valeur pour **toutes** les étapes `b-*` de la même Anaconda Prompt. Revérifier avec `ETAPES.cmd disk-audit`.
- **Archiver en option**, pour une décision ultérieure : `ETAPES.cmd archive-a E:\QMIX_archives\campaignA_design_runs.zip` écrit un zip vérifié (`"ok": true`), sans rien supprimer. `ETAPES.cmd archive-a-dryrun` affiche ce qu'une suppression future, autorisée explicitement, libérerait. Rien n'est changé.

## Étape 2. Campagne A-ext : actionné à vert minimal de 5 s (environ 1 h, non garanti)

L'actionné g5 est une **extension des références classiques**. Il ne reproduit pas l'autorité des méthodes apprises, dont les verts peuvent finir après 2 s.

| # | Commande | Sortie attendue | Code | Durée | En cas d'écart |
|---|---|---|---|---|---|
| 2.1 | `ETAPES.cmd aext-plan` | `runs_by_stage` = 405 et 75, `runs_upper_bound` = 480, la raison d'être, puis `plan fingerprint: <64 caractères>` | 0 | secondes | Code 1 : copier le message |
| 2.2 | `ETAPES.cmd aext-prepare <empreinte de 2.1>` | Manifestes de conception et de validation écrits, contrôlés identiques à ceux de A ; ordre `aext-design` écrit | 0 | 1 à 2 min | Manifestes différents de A : arrêter et signaler |
| 2.3 | `ETAPES.cmd aext-run aext-design` | 4 fenêtres | 0 | environ 50 min | Une fenêtre se ferme tout de suite : lire `logs\aext_aext-design_shard<i>.log` |
| 2.4 | `ETAPES.cmd aext-progress` | `aext-design` : 405/405 ; `aext-validation` : ordre pas encore écrit | 3 | secondes | Des dossiers interrompus : refaire 2.3. Code 5 : ne rien relancer |
| 2.5 | `ETAPES.cmd aext-finalise aext-design` | Les 5 meilleurs réglages par profil ; ordre `aext-validation` (75) écrit | 0 | secondes | Code 1 : copier le message |
| 2.6 | `ETAPES.cmd aext-run aext-validation` | 4 fenêtres | 0 | environ 10 min | comme 2.3 |
| 2.7 | `ETAPES.cmd aext-progress` | Les deux étapes terminées | 0 | secondes | 3 : refaire 2.6. 5 : ne rien relancer |
| 2.8 | `ETAPES.cmd aext-finalise aext-validation` | `selections\R1_…__actuated_g5.json`, `R2_…`, `R3_…` | 0 | secondes | Un second appel refuse : c'est normal |

## Étape 3. Campagne B : plan, rodage réel, gel

| # | Commande | Sortie attendue | Code | Durée | En cas d'écart |
|---|---|---|---|---|---|
| 3.1 | `ETAPES.cmd b-plan` | Une ligne par profil, au format `QMIX/VDN 400 \| IDQN … \| comparator runs …` : IDQN 100 en R0 et 0 ailleurs ; comparateurs 30, 70, 70, 70, 30. Une ligne `primary` par profil. Puis `"runs": 2370`, `"learned": 2100`, `"comparators": 270`, et l'empreinte | 0 | secondes | `sealed selections … required` : A-ext n'est pas finalisé. `IDQN checkpoints have training seeds …` : le plan de robustesse n'a pas les 10 IDQN 101–110, signaler. Principal R1, R2 ou R3 différent de oft_g5 (1,9399), actuated_min7 (1,3669) ou tod_g5 (2,7219) : c'est l'actionné g5 qui fait mieux en validation (B2) ; le noter |
| 3.2 | `ETAPES.cmd b-measure` | **Rodage réel** : 12 exécutions sur graines de **conception** (R0 8011–8012, R1 8111–8112, R3 8311), sur 4 processus en parallèle. Chacune est finalisée en gzip et relue depuis le gzip. Dernière ligne : `RUN-IN OK: 12 runs on design seeds, 4 workers, … runs/h`. Le JSON donne aussi `parallel_efficiency`, les durées moyennes et maximales, `recheck_s_per_run` et `environment` (doit montrer Python 3.7.16 et SUMO 1.25) | 0 | 2 à 10 min | `STOP: run-in failed …` : **ne pas geler**. Copier le message ; le détail est dans `measure_failed_<date>.json` de la racine B. C'est le premier passage réel de la chaîne complète (garantie, compteurs, gzip, relecture) |
| 3.3 | `ETAPES.cmd b-plan` | Même empreinte qu'en 3.1. `"source": "measure.json (parallel run-in, 4 workers)"`, `wall_h_4_workers` (attendu), `wall_h_4_workers_pessimistic`, `start_threshold_gb` | 0 | secondes | Empreinte différente : arrêter et signaler. Si la durée pessimiste dépasse la fenêtre disponible, lancer B quand même un soir, et non la veille d'une échéance ; une exécution interrompue reprend (étape 4) |
| 3.4 | `ETAPES.cmd b-freeze` ou `ETAPES.cmd b-freeze C:\Users\LENOVO\QMIX_A003_P3\a003` | `plan_fingerprint`, `margins_sha256`, `"jobs": 2370`, `statistics_1_2`, puis `FROZEN. Next: b-prepare <empreinte>` | 0 | secondes | **Refus attendus et voulus :** `no run-in` ; `run-in environment … is not Python 3.7 / SUMO 1.25` ; `code changed since the run-in` (refaire 3.2 dans une **nouvelle** racine B) ; `etapes_check report … does not show a clean pass` (refaire 0.3) ; `unit_tests report …` (refaire 0.2) ; `already frozen`. `equal: false` dans `statistics_1_2` : arrêter avant 4.1 et signaler |

**Après 3.4, ne plus rien modifier** dans cette copie de travail ni dans la racine B : code, `confirmation_plan.json`, sélections, module statistique.

## Étape 4. Campagne B : exécution

| # | Commande | Sortie attendue | Code | Durée | En cas d'écart |
|---|---|---|---|---|---|
| 4.1 | `ETAPES.cmd b-prepare <empreinte de 3.4>` | `prepared … (2370 runs)` : 50 trafics de confirmation générés, 30 checkpoints copiés et vérifiés (10 QMIX, 10 VDN, 10 IDQN) | 0 | 1 à 3 min | `differs from the freeze` : quelque chose a changé depuis le gel, signaler. `already prepared` : passer à 4.2 |
| 4.2 | `ETAPES.cmd b-run` | `preflight OK: 2370 runs to do, … GB required …`, puis 4 fenêtres | 0 | valeur de 3.3, **sans garantie** | `STOP: not enough disk space` : aucune fenêtre lancée, voir l'étape 1. Autre `STOP` : copier le message |
| 4.3 | `ETAPES.cmd b-progress`, à vérifier au matin | `finished 2370/2370` | 0 | 1 à 2 min | **3** et des fenêtres encore ouvertes : B tourne encore, attendre. **3** et toutes les fenêtres fermées : refaire 4.2 (une exécution interrompue est relancée une fois). **5** : ne rien relancer ; noter les dossiers `CORRUPTED` |

## Étape 5. Analyse

| # | Commande | Sortie attendue | Code | Durée | En cas d'écart |
|---|---|---|---|---|---|
| 5.1 | `ETAPES.cmd b-analyse` | Des lignes `F1 …` (10) et `F2 …` (2) avec les décisions, `missing cells: 0`, puis `written: analysis\confirmation` | 0 | relecture gzip : 2370 × `recheck_s_per_run` de 3.2, plus quelques minutes de bootstrap | `missing cells` > 0 : cellules absentes, corrompues ou dont la relecture diffère (`recheck_mismatch`). Elles sont listées dans `results.json`, jamais imputées ; les comparaisons concernées sont marquées INCOMPLET |

**Fichiers produits** dans `analysis\confirmation\` :
- `decisions.csv` : colonne `family`, F1 (face au classique principal, 99,5 %) ou F2 (QMIX − IDQN et VDN − IDQN, 97,5 %) ;
- `forest.png` et `forest_joint.png` : seulement si matplotlib est installé, non vérifié ;
- `service_counts.csv` : tous les effectifs, et les intervalles par modèle et par trafic ;
- `results.json` ;
- `RESULTATS_B.md`.

**Lire les taux de service correctement.**
- Aucun intervalle n'est calculé sur les évaluations regroupées.
- « 0 événement » n'est jamais un risque nul : la borne unilatérale par modèle, pour 0 sur 10, est de 25,9 %.

**Si `forest.png` manque :** installer matplotlib change l'environnement `traffic_rl`. Le demander avant.
