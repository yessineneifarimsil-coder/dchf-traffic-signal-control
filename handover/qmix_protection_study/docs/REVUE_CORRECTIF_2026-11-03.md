# Correctif des outils de robustesse (2026-11-03) : points 2 à 4 et `ETAPES.cmd`

**Portée.** Ce correctif touche uniquement l'outillage de la validation de robustesse, qui n'est pas lancée, et `ETAPES.cmd`.

Il ne remet pas en cause les 600 évaluations de l'ablation ni leurs résultats dérivés : aucun fichier sous `D:\QMIX_Results` n'est lu ni modifié.

Rien n'a été lancé ici :
- aucune évaluation de robustesse ;
- aucun entraînement ;
- aucun trafic final réservé.

Les anciens trafics finaux 3001–3010 ne sont pas utilisés.

**Empreinte du plan.** Le script d'analyse, `cell_state.py` et `evaluate_any.py` ont changé. **Toute empreinte de plan de robustesse imprimée avant le 2026-11-03 est caduque.** Relancer `ETAPES.cmd robustness-plan`.

## 1. Reproduction avant correction

Script : `review/repro_robustness_defects.py`. Il travaille sur des données synthétiques, sans SUMO. Les journaux sont dans `logs/revue_2026-11-03/`.

| Point | Version précédente (commit 66889c2) | Version corrigée |
|---|---|---|
| 2 | Une cellule `both` est déclarée manquante. On obtient `all_ok=True`, `S1_statement_allowed(R0)=True`, et un rapport non marqué incomplet. **REPRODUIT** | `all_ok=False`, `S1_statement_allowed(R0)=False`, rapport INCOMPLET. **NON REPRODUIT** |
| 3 | Deux `evaluation_metrics.json` sont tronqués. `progress` affiche « finished 2/2 » avec le code 0 ; `run` renvoie 0. **REPRODUIT** | `progress` affiche « finished 0/2 … corrupted 2 » avec le code 5 ; `run` renvoie 5. Aucune réévaluation, fichiers conservés. **NON REPRODUIT** |
| 4 | Le bras `both`, quand la garantie agit pendant la demande, affiche `guarantee_cost_during_demand = EVALUATED`. **REPRODUIT** | « NOT IDENTIFIED (… both − none also contains the minimum green; … both − min_green … not in this plan) ». **NON REPRODUIT** |
| `latex` | Un échec de `bibtex` (code 2) est masqué : sortie 0. Journal `latex_probe_avant.log` | Sortie 1 avec le message « LaTeX build failed at bibtex ». Journal `latex_probe_apres.log` |

## 2. Corrections

### Point 2 — analyse incomplète (`robustness_analysis.py`)

**Classement des cellules.** Chaque cellule du plan est classée par `cell_state.py` :
- une cellule **corrompue** arrête l'analyse (code 1), même si elle est déclarée manquante ;
- une cellule **sans résultat** arrête l'analyse, sauf si elle est déclarée manquante.

**Cellule déclarée manquante.** Elle **reste manquante** :
- T1 est faux ;
- `complete` vaut `false` et `all_ok` vaut `false` ;
- le rapport porte le bandeau « INCOMPLETE (INCOMPLET) » ;
- chaque effectif est affiché sous la forme présent/attendu ;
- le code de sortie est 4 ;
- `integrity_ok` (T2 à T5) est rapporté séparément.

**S1.** Pour chaque scénario, S1 vérifie les identités attendues d'après le plan : (scénario, trafic, contrôleur, modèle) pour **tous** les modèles et trafics des bras `learned:guarantee` et `learned:both`.

L'énoncé « pas de déni de service indéfini » n'est autorisé que si les trois conditions suivantes sont réunies :
- tous les runs attendus sont présents ;
- T2 à T5 sont vérifiés ;
- aucun échec n'a d'attente de compteur ouverte.

Sinon, le rapport donne la raison :
- INCOMPLETE, avec le nombre de runs manquants ;
- critères techniques en échec ;
- échecs avec attente ouverte.

Les bras P5 sont rapportés à titre d'information.

**S2, S3, S4 et le tableau des contrôleurs classiques** indiquent aussi les effectifs attendus, présents et manquants, avec un indicateur `complete`.

**Un échec scientifique correctement enregistré** (CLEARANCE_FAILURE complet) est une observation terminée. Il ne rend pas l'analyse incomplète.

### Point 3 — résultats corrompus (`cell_state.py`, `robustness_runner.py`, `evaluate_any.py`)

**États d'une cellule :**

| État | Définition |
|---|---|
| complete | Métriques lisibles ; identité conforme à la cellule planifiée ; statut CLEARED ; tous les fichiers requis présents |
| scientific_failure | Idem, avec le statut CLEARANCE_FAILURE |
| corrupted | Métriques illisibles, statut inconnu, identité différente ou fichier requis absent |
| interrupted | Répertoire présent sans `evaluation_metrics.json` |
| not_started | Aucun répertoire |

**Seuls `complete` et `scientific_failure` comptent comme terminés.**

**Fichiers requis.** Pour tous les contrôleurs :
- `evaluation_metrics.json` et `run_manifest.json` ;
- `tripinfo.xml` ;
- `episode_summary.csv`, `reward_seconds.csv`, `signal_phases.csv` ;
- `service_counters.csv`.

Pour les contrôleurs protégés (learned et P5), s'y ajoutent `protection_decisions.csv` et `protection_record.json`.

**Identité.** `evaluate_any.py` inscrit désormais lui-même dans `evaluation_metrics.json` :
- `scenario`, `controller` et `traffic_seed` ;
- pour les modèles appris, `checkpoint_sha256`, calculé sur la copie évaluée.

Ce dernier est comparé à l'empreinte du modèle dans le plan. Le contrôle ne dépend donc pas des champs écrits par l'évaluateur protégé.

**Comportement de `run` :**
- une cellule terminée est sautée ;
- une cellule corrompue est signalée, conservée telle quelle et jamais relancée ;
- une interruption sans résultat est renommée `.incomplete1` et relancée une fois ;
- une deuxième interruption est laissée pour diagnostic ;
- une exception de l'évaluateur est traitée comme une interruption.

**Comportement de `progress` :** il compte séparément les cellules complètes, les échecs scientifiques, les corrompues, les interrompues et les non commencées, et liste les cellules corrompues.

**Codes de sortie de `run` et `progress` :**
- 0 : tout est terminé ;
- 3 : des cellules ne sont pas terminées ;
- 5 : au moins un résultat est corrompu.

### Point 4 — attribution du coût (`s3_costs`)

**Contrastes :**
- `guarantee − none` mesure l'effet de la garantie seule ;
- `both − none` mesure l'effet combiné du vert minimal et de la garantie.

**Champs ajoutés :** `contrast`, `effect_measured` et `guarantee_activated_during_demand`. Ce dernier sépare l'activation de la garantie de l'identification de son coût.

**Valeurs de `guarantee_cost_during_demand` :**
- `EVALUATED (guarantee - none)` : seulement dans le bras `guarantee`, avec au moins une intervention pendant la demande ;
- `NOT IDENTIFIED` : dans le bras `both` quand la garantie a agi. Isoler son coût exigerait `both − min_green`, absent du plan. Ni ce bras ni aucune simulation n'ont été ajoutés ;
- `NOT EVALUATED` : dans les deux bras, quand la garantie n'agit pas pendant la demande.

**Clés et colonnes :**
- `dJ_whole_episode_s` : épisode entier, paires où les deux runs dégagent ;
- `dD_bar_demand_window_s` : fenêtre de demande [0, 3 600) s, toutes les paires.

Le rapport, `plans/PLAN_ROBUSTESSE.md` et le manuscrit (section *Prepared but not executed*) emploient les mêmes libellés.

### `ETAPES.cmd`

- **Dispatch.** Inchangé. Le défaut supposé est retiré, conformément à la demande.
- **`latex`.** `pdflatex` est lancé en `-interaction=nonstopmode -halt-on-error`. Après chaque appel à `pdflatex` ou `bibtex`, un test `if errorlevel 1` arrête la chaîne, affiche l'étape en échec et renvoie 1.
  - On n'utilise pas `&&`, parce que sous Wine 9.0 `&&` n'arrête pas la chaîne, même au premier niveau (sonde exécutée ici). Sous Windows, les deux formes sont équivalentes.
  - `PDFLATEX` et `BIBTEX` valent par défaut `pdflatex` et `bibtex`. Elles ne servent qu'à substituer des simulacres dans l'outil de vérification.
- **Exécutions parallèles** (`ablation-run`, `robustness-run`). Le lanceur affiche que **son code couvre le lancement seulement, pas la réussite des workers**, et renvoie vers `*-progress` et les journaux de shards. Aucune attente n'a été ajoutée, donc aucun rapport final de worker n'est à tester.
- **Nouvelle étape `robustness-check-smoke`.** Elle applique les règles de `cell_state.py` (fichiers, scénario, contrôleur, statut) aux 4 runs de rodage du 2026-10-29.

## 3. Exécuté ici (environnement de revue Linux, Python 3.11)

| Vérification | Résultat | Journal |
|---|---|---|
| Suite de tests `python -m unittest discover -s tests -v` | **Ran 40 tests, OK (skipped=3), code 0.** Les 3 tests ignorés exigent `QMIX_PROTECTED`, absent ici | `unittest_all.log` |
| Tests de l'analyse (18) | OK | idem |
| Tests du runner et des états de cellule (9) : JSON tronqué, fichiers requis absents, identité incohérente (autre checkpoint, autre trafic, autre bras), échec scientifique complet jamais relancé, statut inconnu, interruption reprise une fois puis laissée, `check-smoke` | OK | idem |
| Parcours synthétique de bout en bout (2) : plan → 4 shards avec un faux évaluateur → interruption puis reprise → `progress` 0 → analyse code 0 ; puis corruption → `progress` 5, aucune relance, analyse code 1 | OK | idem |
| Reproduction avant / après | points 2 à 4 reproduits avant, non reproduits après | `repro_points_2_4_avant.log`, `repro_points_2_4_apres.log` |
| vermin (cible Python 3.7) sur les fichiers modifiés | minimum requis 3.4 | `vermin.log` |
| pyflakes sur les fichiers modifiés | aucun nouvel avertissement. Les 4 imports inutilisés de `evaluate_any.py` existaient déjà dans 66889c2 | `pyflakes.log` |
| Outil de vérification d'`ETAPES.cmd` sous Wine 9.0 (sans les contrôles CALL et conda) | 79 contrôles réussis, 0 échec, dont l'échec de `latex` par `pdflatex` ou `bibtex`, le message des lancements parallèles et `robustness-check-smoke` | `etapes_harness_wine.log` |
| Sonde `latex` sous Wine avec des `pdflatex.exe` / `bibtex.exe` de substitution | 0/0 → 0 ; bibtex 2 → 1 ; pdflatex 3 → 1 | `latex_probe_apres.log` |
| Compilation réelle du manuscrit (TeX Live) avec la séquence de `latex` | 4 étapes, code 0, 12 pages, aucune référence indéfinie ; contrôle statique OK | `latex_build_linux.log`, `latex_check.log` |

## 4. À exécuter sous Windows (non exécuté ici)

1. `ETAPES.cmd tests` : toute la suite sur la pile `traffic_rl` (Python 3.7.16), y compris les 3 tests qui exigent `QMIX_PROTECTED`.
2. `tools\etapes_check\verify_etapes_cmd.cmd` : tous les contrôles, y compris CALL et conda, que Wine ne permet pas d'évaluer.
3. `ETAPES.cmd robustness-check-smoke` : confirme sur les sorties réelles du 2026-10-29 la liste des fichiers requis pour un contrôleur fixe, la pression maximale canonique, P5 `both` et un modèle appris `both`.
4. **Recommandé avant le plan :** un nouveau rodage `ETAPES.cmd robustness-smoke` (4 runs courts, sorties non interprétées), suivi de `python tools\robustness\cell_state.py check-smoke --root <nouvelle racine> --stamped`. Il vérifie que l'évaluateur modifié inscrit bien l'identité, y compris `checkpoint_sha256`.
5. `ETAPES.cmd robustness-plan` pour obtenir la nouvelle empreinte, puis l'approbation de l'opérateur ou de l'opératrice avant `robustness-prepare`.

## 5. Ce que ce correctif ne change pas

- **Les conclusions de l'ablation** et leur formulation :
  - le plan fixe réoptimisé et les politiques historiques contraintes sans réentraînement restent distingués ;
  - les pilotes restent un signal exploratoire défavorable, sans prédiction sur une campagne complète.
- **La décision sur de nouveaux entraînements** vient après la robustesse et la lecture des travaux proches.
- **Le classement des revues** n'est pas vérifié.
