# Plan de confirmation pré-enregistré (B)

**Statut : pré-enregistrement amendé (amendement B du 2026-11-19, rectifié le 2026-11-23 ; `plans/PROTOCOL_AMENDMENT_B.md`). Non gelé, non lancé.** Aucune graine de confirmation n'a été générée. Le gel n'est possible qu'avec le code terminé et testé (section 2).

**Historique :**
- **2026-11-07.** Ont été intégrés la marge d'équivalence, la référence statistique, le périmètre des comparateurs et la justification de l'exclusion d'IDQN.
- **2026-11-19 (amendement B).** Quatre changements :
  - B1 : le comparateur principal est la sélection scellée de plus faible J de validation ;
  - B2 : l'actionné à vert minimal de 5 s (A-ext) est inclus ;
  - B3 : IDQN reste hors de la famille principale ;
  - la référence statistics-1.2 est corrigée : c'est une empreinte de protocole, pas le hash d'un fichier.
- **2026-11-23 (rectificatif).** Six changements :
  - IDQN (10 checkpoints historiques, garantie seule) est ajouté au scénario de référence, soit 100 évaluations, pour les contrastes QMIX − IDQN et VDN − IDQN (famille F2, section 7) ;
  - les statistiques de service sont rapportées par unité (modèle, trafic), sans intervalle sur les évaluations regroupées ;
  - les lecteurs sont testés sur les sorties gzip, et chaque cellule est relue à l'analyse ;
  - le gel exige un rodage réel en parallèle sous Python 3.7 / SUMO 1.25, le contrôle Windows des commandes et les tests ;
  - aucune donnée de A n'est supprimée ;
  - l'actionné g5 est présenté comme une extension des références.

**Fichiers :**
- `tools/confirmation/confirmation_plan.json` : paramètres, avec une **empreinte** (`fingerprint`) qui couvre tous les champs ;
- `tools/confirmation/b_runner.py` : exécuteur de B (plan, mesure, gel, préparation, exécution, avancement, analyse) ;
- `tools/confirmation/confirmation_analysis.py` : règles de décision, appelées par `b_runner.py analyse`.

Empreinte de `confirmation_plan.json` rectifié : `8070f6f62a2bc274283cac1387cd594e630a5fafa31bc5d0c2f93eab213a99fa`. L'empreinte du plan B (tâches, sélections, marges, code) est calculée par `b-plan` et fixée par `b-freeze` dans `freeze.json`.

## 1. Question

Les politiques QMIX et VDN figées, avec la seule garantie, servent-elles tous les véhicules sur des trafics jamais utilisés ? Que vaut leur J face au meilleur comparateur classique disponible pour chaque profil (famille F1) ? Et, au scénario de référence, l'apprentissage conjoint fait-il mieux que les apprenants indépendants IDQN (famille F2) ?

## 2. Gel : ordre imposé

1. A terminé et A-ext finalisé : toutes les sélections scellées. Le plan refuse de se construire s'il en manque une.
2. `b-plan`, puis `b-measure`, le rodage réel : 12 exécutions sur graines de conception, jamais de confirmation, sur 4 processus en parallèle. Chacune est finalisée en gzip et relue depuis le gzip. Le rodage enregistre le débit et les versions de Python et de SUMO.
3. `ETAPES.cmd tests` et `tools\etapes_check\verify_etapes_cmd.cmd` sous Windows, leurs sorties étant enregistrées dans `logs\`.
4. `b-freeze`, une seule fois. **Il refuse si :**
   - le rodage n'a pas réussi ;
   - il n'a pas tourné sous Python 3.7 et SUMO 1.25 ;
   - le code a changé depuis le rodage ;
   - le contrôle Windows n'affiche pas « 0 failed » ;
   - les tests n'affichent pas « OK ».

   Il écrit `margins.json` et `freeze.json`, qui contient :
   - l'empreinte du plan B ;
   - le SHA-256 de `margins.json` ;
   - les SHA-256 du code, `ETAPES.cmd` compris ;
   - le module statistique (chemin et SHA-256) ;
   - les SHA-256 des sélections et des 30 checkpoints (dans l'empreinte) ;
   - les rapports et l'environnement du rodage ;
   - en option, le contrôle de statistics-1.2 par le dossier A003.
5. `b-prepare <empreinte>` génère les 50 trafics de confirmation et copie les checkpoints vérifiés. `b-run` lance les exécutions. Toutes les étapes refusent si le code, le plan, les marges ou le module statistique diffèrent du gel.
6. `b-analyse` relit chaque cellule depuis le gzip et applique l'analyse une fois.

## 3. Trafics, politiques et bras

**Trafics.** 10 graines neuves par profil (8c51–8c60), soit 50 trafics. Elles sont réservées dans `tools/comparators/seeds.py` et refusées par tout le code de recherche.

Ne sont jamais utilisés :
- 3001–3010 et 3101–3120 ;
- 8c01–8c05 ;
- 8c11–8c25.

**Politiques.** Les 10 checkpoints sélectionnés de QMIX et les 10 de VDN : ceux du plan de robustesse (`<racine robustesse>\plan.json`, copies dans `checkpoints\`), comparés aux étiquettes de `confirmation_plan.json` et vérifiés par SHA-256. Pas de réentraînement, pas de nouvelle sélection.

**IDQN (rectificatif).** Les 10 checkpoints IDQN historiques du plan de robustesse (graines d'entraînement 101–110), évalués avec la garantie seule, au scénario de référence R0, sur ses 10 trafics 8051–8060 : 100 évaluations. Leurs étiquettes et SHA-256 sont lus dans le plan de robustesse et figés au gel.

**Bras.** Principal : `guarantee`. Secondaire : `none`, pour QMIX et VDN seulement.

## 4. Pourquoi IDQN est hors de la famille principale

IDQN n'est pas comparé aux contrôleurs classiques (famille F1). Ce choix a été fait avant que le moindre trafic de confirmation existe, pour trois raisons. Depuis le rectificatif, IDQN est en revanche évalué au scénario de référence, comme référence des contrastes de la famille F2 (section 7).

1. **La question.** La confirmation porte sur les méthodes coopératives à factorisation de valeur (QMIX, VDN) avec la seule garantie. IDQN, fait d'apprenants indépendants sans coordination, sert de référence non coopérative dans le développement, l'ablation et la robustesse. Ses résultats y sont rapportés en entier.
2. **Une instabilité connue avant la confirmation.**
   - **Ablation, lu.** IDQN est la seule méthode dont l'effet du vert minimal est irrégulier : il améliore certains modèles, en dégrade d'autres, corrige 4 échecs et en crée 1. IDQN compte 4 échecs sur 50 sans protection (Clopper-Pearson à 95 % : [2,2 % ; 19,2 %]).
   - **Robustesse, rapporté.** La garantie seule augmente D̄ dans 35 paires IDQN, selon la définition D2. Le diagnostic 107/8203 montre de longs verts opposés après les interventions.
   - **Conséquence.** IDQN avec garantie n'est pas un candidat stable qu'une confirmation pourrait corroborer.
3. **La multiplicité.** Ajouter IDQN à la famille principale la porterait de 10 à 15 comparaisons face aux classiques. Tous les intervalles de décision s'élargiraient, pour une configuration qui n'est pas candidate. Les contrastes F2 forment une famille distincte, avec son propre contrôle d'erreur (section 7). Ils n'ajoutent pas 5 comparaisons à F1.

**Conséquences déclarées :**
- La confirmation ne permet aucune conclusion sur IDQN face aux contrôleurs classiques. Elle ne permet que les contrastes F2, au scénario de référence.
- Ses résultats de développement, d'ablation et de robustesse sont conservés et rapportés en entier.
- **Limite.** Les méthodes confirmées ont été retenues après les résultats de développement et de robustesse. La confirmation les teste sur des trafics neufs ; elle ne compare pas toutes les méthodes.

## 5. Comparateurs par profil (amendement B1, B2)

**Principal (décisions).**
- R1–R3 : la sélection scellée de A ou A-ext dont le J de validation est le plus faible, choisie par `b_runner.choose_primary` avant le gel.
- R0 et R4 : C19 8/5 D9. Pour R4, C19 est gelé et n'a pas été réoptimisé (déclaré).

**Secondaires (descriptifs).** Tous les autres comparateurs évalués du profil.

| Profil | Principal attendu sans A-ext (J_val, δ) | Évalués |
|---|---|---|
| R0 | C19 8/5 D9 (2,765 ; 0,138 s) | C19 ; C25 12/7 D0 ; Max Pressure |
| R1 | plan fixe optimisé g5, C25 14/5 D1 (1,940 ; 0,100 s) | OFT g5 ; OFT min7 ; actionné min7 ; actionné g5 ; C19 ; C25 ; Max Pressure |
| R2 | actionné min7, gap 2, H 60, V 15 (1,367 ; 0,100 s) | les mêmes |
| R3 | plans par période g5 (2,722 ; 0,136 s) | les mêmes, plus les plans par période g5 et min7 (OFT g5 = OFT min7 = C25 12/7 D0, évalué une fois) |
| R4 | C19 8/5 D9 (2,765 ; 0,138 s) | C19 ; C25 ; Max Pressure |

L'actionné g5 devient le principal d'un profil s'il fait mieux en validation que la valeur indiquée.

## 6. Critères

| Rôle | Critère |
|---|---|
| Principal | J par (modèle, trafic), avec N = total du manifeste |
| Service | Échec d'évacuation ; échec avec un compteur ouvert ; au moins un véhicule en attente ≥ 300 s |
| Secondaires | D̄ sur la fenêtre de demande ; perte de temps ; attente maximale |

## 7. Statistique

**Procédure :** bootstrap croisé apparié (`paired_crossed_bootstrap`, `official=False`) du module statistique figé, 10 000 réplicats, intervalle par percentiles. Le plan croise 10 modèles et 10 trafics, et le comparateur est diffusé par trafic : D_ij = J_appris(i,j) − J_comparateur(j).

**Référence statistics-1.2 (corrigée par l'amendement B).** `8b6413a9ccffa2bbbcf0d3cfdde6c7460b4785193aa419f7d4725885dc38437a` est `amendment003.protocol_hashes()['statistics_1_2']`, l'empreinte d'un JSON canonique. **Ce n'est pas le hash d'un fichier.**

Conséquences :
- La règle du 2026-11-07 qui refusait tout fichier d'un autre SHA-256 est retirée, ainsi que l'étape `check-statistics`.
- Le fichier statistique utilisé (par défaut `adaptive_qmix/protocol/statistics.py` figé, sinon `--statistics` au gel) est enregistré, chemin et SHA-256, dans `freeze.json`. Il est imposé ensuite.
- `--a003-root` au gel enregistre la valeur statistics-1.2 lue dans A003, en lecture seule. Que statistics-1.2 spécifie exactement ce bootstrap reste à confirmer avant le gel (`RETOURS.md`).

**Niveaux :**
- **F1, décisions : intervalle à 99,5 %** (Bonferroni sur les 10 comparaisons principales, 5 profils × 2 méthodes) ;
- **Description : 95 %**.

**Famille F2 : apprentissage conjoint face à IDQN (rectificatif).**
- **Contrastes :** QMIX − IDQN et VDN − IDQN, au scénario de référence, sous garantie.
- **Effet :** la moyenne des D_kj = J_M(k, j) − J_IDQN(k, j) sur les 10 graines d'entraînement k et les 10 trafics j.
- **Procédure :** `paired_crossed_bootstrap` avec comparateur appris. Les modèles sont appariés par numéro de graine, selon la convention du protocole ; ce numéro ne crée aucun lien causal.
- **Décisions à 97,5 %** (Bonferroni sur 2). Le risque d'erreur est contrôlé à 0,05 dans chaque famille ; aucune conclusion ne combine F1 et F2.
- **Sensibilité descriptive :** les intervalles sont aussi donnés à 1 − 0,05/12.
- **Marge :** δ de R0, soit 0,138 s. Les règles de décision sont les mêmes.

**Statistiques de service (rectificatif).**
- Tous les effectifs sont rapportés, à trois niveaux : évaluations, modèles touchés sur 10, trafics touchés.
- Aucun intervalle n'est calculé sur les évaluations regroupées, qui ne sont pas indépendantes : mêmes modèles, mêmes trafics.
- Les intervalles de Clopper-Pearson à 95 % sont donnés au niveau modèle (graines d'entraînement supposées indépendantes, conditionnellement aux trafics) et au niveau trafic (trafics supposés indépendants, conditionnellement aux modèles).
- Avec 0 événement, la borne unilatérale est donnée (0 sur 10 : 25,9 %).
- Aucun bootstrap de taux : un [0 ; 0] après zéro échec n'établit pas un risque nul.

**Marge d'équivalence**, par profil : **δ = max(0,05 × J_val ; 0,10 s)**.

- **J_val** est le J moyen de validation du comparateur principal :
  - R1–R3 : lu dans sa sélection scellée ;
  - C19 (R0, R4) : 2,765071 s, son J de validation sur 2101–2105 lu dans le gel amendé. D'où δ = 0,138 s pour R0 et R4.
- Le cas R4 est déclaré : le J de validation de C19 vient de la demande de qualification, pas de R4.
- La règle et ses deux constantes sont dans le plan et dans l'empreinte. `margins.json` est écrit au gel.

## 8. Règles de décision

Les règles s'appliquent par profil et par méthode, avec [L, U] l'intervalle à 99,5 % de D. La première règle vérifiée l'emporte.

1. **ÉCHEC DE SERVICE** : au moins un échec avec compteur ouvert sous garantie.
2. **NON ESTIMABLE** : tout autre échec appris, ou un échec du comparateur. J n'est jamais imputé. Une sensibilité descriptive est rapportée.
3. **SUPÉRIEUR AU-DELÀ DE LA MARGE** : U < −δ.
4. **SUPÉRIEUR** : U < 0.
5. **ÉQUIVALENT** : −δ < L et U < δ.
6. **INFÉRIEUR AU-DELÀ DE LA MARGE** : L > δ.
7. **INFÉRIEUR** : L > 0.
8. **NON CONCLUANT** dans tous les autres cas.

**Conclusions autorisées :**
- Elles portent sur un profil et une méthode à la fois, sans décision agrégée.
- **Énoncé de service** pour une méthode : seulement avec 0 échec avec attente ouverte sur ses 500 évaluations avec garantie, et sous la forme « aucun échec avec attente ouverte observé ». Il est toujours accompagné des effectifs par modèle et par trafic, et jamais présenté comme un risque nul ni comme une garantie de fiabilité. La borne de 0,6 % sur 500 évaluations regroupées est retirée (rectificatif).
- Les décisions F2 ne valent que pour le scénario de référence, avec ces 10 modèles par méthode.
- Sont **descriptifs (95 %)** : « guarantee − none », le bras `none` et les comparateurs secondaires.

## 9. Chiffrage (recompté par le code, rectificatif)

| Élément | Exécutions |
|---|---|
| QMIX et VDN : 2 méthodes × 10 modèles × 2 bras × 5 profils × 10 trafics | 2000 |
| IDQN : 10 modèles × garantie × R0 × 10 trafics | 100 |
| Comparateurs : (3 + 7 + 7 + 7 + 3) spécifications distinctes × 10 trafics | 270 |
| **Total** | **2370** |

Le compte est affiché par `b-plan` et testé.

**Coût, mesuré et non promis :**
- **Durée.** Elle est estimée par le rodage en parallèle : durées moyennes et maximales par type d'exécution, et efficacité mesurée sur 4 processus. Avant mesure, l'ordre de grandeur est de 2,4 h. **Une nuit n'est pas garantie**, à cause des coupures à 7 200 s, de la campagne IEV sur la même machine ou d'une mise en veille.
- **Disque.** 2370 × la taille mesurée par exécution (journaux en gzip). B ne démarre pas sous ce besoin plus 4 Go. Avant mesure, l'ordre de grandeur est d'environ 8 Go, soit un seuil d'environ 12 Go.

## 10. Code, tests et commandes

| Élément | État |
|---|---|
| Exécuteur | `tools/confirmation/b_runner.py`, dérivé du runner de robustesse. Mêmes états : complet, échec scientifique, interrompu, corrompu, non commencé. Une seule relance d'une exécution interrompue ; une exécution corrompue n'est jamais relancée. `evaluation_metrics.json` est écrit en dernier. Les dossiers en double sont retirés avant `--shard i/n`. Le seuil de disque est contrôlé au lancement. Les comparateurs passent par `evaluate_comparator.py` (via `evaluate_ext.py`), avec compteurs. |
| Analyse | `b_runner.py analyse` relit chaque cellule depuis le gzip et produit `analysis/confirmation/` : `decisions.csv` (colonne `family` : F1 ou F2), `forest.png`, `forest_joint.png`, `service_counts.csv` (effectifs et intervalles par unité), `results.json`, `RESULTATS_B.md`. Les règles de décision sont celles de `confirmation_analysis.py`. |
| Tests | `tests/test_b_runner.py` et `tests/test_confirmation_analysis.py` (synthétiques), plus les lecteurs réels sur des cellules complètes finalisées en gzip (`RealReaders`). Le rodage réel se fait sous Windows (`b-measure`). |
| Commandes Windows | `ETAPES.cmd b-plan`, `b-measure`, `b-freeze`, `b-prepare <empreinte>`, `b-run`, `b-progress`, `b-analyse`. Séquence complète dans `RUNBOOK_B.md`. |
