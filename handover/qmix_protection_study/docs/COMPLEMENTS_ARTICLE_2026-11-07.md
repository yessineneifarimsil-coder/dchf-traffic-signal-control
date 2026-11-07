# Compléments pour l'article (2026-11-07) : comparateurs, confirmation, analyses sans simulation

**Ce qui n'a pas été fait.** Aucun entraînement. Aucune étape longue n'a été lancée. Le plan de robustesse, les 600 évaluations, les dépôts figés et les trafics finaux réservés n'ont pas été touchés.

Plans détaillés :
- `plans/PLAN_COMPARATEURS.md` pour A ;
- `plans/PLAN_CONFIRMATION.md` pour B.

## 0. Statut de chaque information

| Statut | Signification | Exemples |
|---|---|---|
| **Lu** | lu ici dans les fichiers disponibles | code et configurations figés ; tables de l'ablation (600 évaluations) ; données de la figure 1 ; définitions des grilles A002/min7 |
| **Mesuré ici** | rodage cloud, sur graines de conception uniquement, avec SUMO 1.28 (ta pile : SUMO 1.25) ; ce ne sont pas des résultats | statistiques de commutation du Max Pressure ; décomposition de la pression ; durées par exécution |
| **Rapporté** | donné dans ta demande, absent des fichiers disponibles ici, non vérifié | J du Max Pressure de 7,7 à 11,5 s sur la robustesse ; diagnostic IDQN 107/8203 ; 35 paires IDQN dégradées ; 17 évaluations QMIX où la garantie agit ; comptes de famine de la robustesse ; document A004 |
| **Proposé** | à décider ; rien n'est lancé | toutes les étapes de A1–A3 ; le plan B (marge de 10 %, Bonferroni à 99,5 %, ordre des règles) ; la variante réduite de la grille grossière |

## 1. A4 — Max Pressure canonique (vérification en lecture seule)

### 1.1 Lu dans le code et les configurations figés

Sortie : `logs/revue_2026-11-07/mp_check_static.json`.

| Point | Constat |
|---|---|
| Vert minimal | **10 s**. L'évaluateur de robustesse charge `qualification_300m_medium.json`, sans section `baselines`, donc avec les valeurs par défaut de l'exécuteur. C'est **identique** à la configuration officielle `baselines_300m_medium.json` (10 s). |
| Jaune | 3 s, identique. |
| Décision | Après le vert minimal, à chaque seconde : changement si la pression de l'autre phase est **strictement** supérieure ; une égalité conserve la phase. Pas de vert maximal. J1 et J2 sont indépendants. |
| Pression | P_i(p) = Σ sur les 4 couples de voies en ligne droite de la phase de [véhicules sur **toute** la voie entrante − véhicules sur **toute** la voie sortante]. L'accesseur est `lane_vehicle_number` : véhicules arrêtés et en mouvement comptent pareil. Les voies mesurent 279 à 290 m sur H et 190 m sur V. Les couples de mouvements sont identiques à la configuration officielle. |

**Conclusion :** aucune divergence entre le Max Pressure de la robustesse et le Max Pressure officiel.

### 1.2 Mesuré ici sur 5 graines de conception

Une graine par profil : 8011, 8111, 8211, 8311 et 8411. Ce ne sont pas les graines d'évaluation.

Sorties :
- `logs/revue_2026-11-07/mp_check_logs_design_seeds_cloud.json` ;
- `mp_pressure_decomposition_R0_8011_cloud.json`.

| Profil | J (s) | Changements par heure et par carrefour | Vert médian H / V | Verts terminés au minimum de 10 s | Part de jaune |
|---|---|---|---|---|---|
| R0 | 7,37 | 270–273 | 10 / 10 s | 92–94 % | 23 % |
| R1 | 11,92 | 263–267 | 10 / 10 s | 84 % | 22 % |
| R2 | 10,83 | 260–261 | 10 / 10 s | 81–84 % | 22 % |
| R3 | 9,95 | 261–262 | 10 / 10 s | 75 % | 22 % |
| R4 | 8,93 | 254–260 | 10 / 10 s | 86–88 % | 21–22 % |

Ces J vont de 7,4 à 11,9 s sur les graines de conception. C'est cohérent avec les 7,7 à 11,5 s rapportés sur les graines d'évaluation, mais calculé avec une autre version de SUMO.

**Mécanisme, observé et non supposé.** La décomposition porte sur R0, graine 8011.

| Moment | Voies entrantes de la phase | Voies sortantes de la phase | Autre phase (entrantes / arrêtés) | Pression |
|---|---|---|---|---|
| Fin d'un vert H, J1 | 11,2 véhicules, aucun arrêté | 15,3 véhicules | V : 4,6 / 1,4 | H négative, V +3,7 |
| Fin d'un vert V | 2,4 véhicules, aucun arrêté | 4,0 véhicules | H : 17,5 / 6,2 | V négative, H +5,7 |

À la fin d'un vert H, le peloton que H vient de libérer occupe la voie sortante (le lien de 280 m entre J1 et J2) et compte contre H. La pression H devient donc négative juste après le vert minimal, alors que 11 véhicules approchent encore.

**Conséquences :**
- le contrôleur alterne quasi mécaniquement 10 s de vert et 3 s de jaune ;
- il accorde le même vert médian à H qu'à V, alors que l'axe principal porte environ 3 fois plus de demande ;
- il perd 22 % du temps en jaune.

**Ce que cela implique pour l'article.** Le Max Pressure canonique est conforme à sa définition figée, mais c'est un comparateur faible sur cette géométrie : il ne peut pas tenir lieu de référence « adaptative forte ». Les comparateurs réglés par profil de A (OFT, actionné) remplissent ce rôle.

**Proposition, non lancée.** Une variante qui compte seulement les véhicules arrêtés, ou une zone limitée, serait un autre contrôleur selon le code figé lui-même. Elle ne pourrait figurer qu'en sensibilité déclarée.

### 1.3 À exécuter sous Windows

```bat
ETAPES.cmd mp-check-static
ETAPES.cmd mp-check-robustness
```

- `mp-check-static` doit redonner les mêmes constats.
- `mp-check-robustness` traite les 25 cellules `canonical_mp` de la robustesse : J, commutations et verts.

## 2. C — Analyses sans simulation

### 2.1 Intervalles de Clopper-Pearson pour les comptes de famine

Script : `tools/article_analyses/clopper_pearson.py`. Il est exact et n'utilise que la bibliothèque standard.

**Exécuté ici sur les 600 évaluations de l'ablation (lu).** Sortie : `logs/revue_2026-11-07/cp_ablation/`.

| Groupe | Échecs d'évacuation | IC 95 % | Attente ≥ 300 s | IC 95 % |
|---|---|---|---|---|
| Avec garantie ou both (3 méthodes × 2 bras) | 0/300 | [0 ; 1,22 %] (unilatéral : 1,0 %) | 0/300 | [0 ; 1,22 %] |
| Sans protection (3 méthodes) | 5/150 | [1,09 ; 7,61 %] | 6/150 | [1,48 ; 8,50 %] |
| IDQN sans protection | 4/50 | [2,22 ; 19,23 %] | 4/50 | idem |
| QMIX sans protection | 1/50 | [0,05 ; 10,65 %] | 2/50 | [0,49 ; 13,71 %] |
| IDQN, vert minimal seul | 1/50 | [0,05 ; 10,65 %] | 1/50 | idem |

Tous les échecs ont une attente de compteur ouverte à la fin.

**Réserve.** Les évaluations d'un même modèle sur plusieurs trafics ne sont pas indépendantes. L'intervalle est donc une borne descriptive, pas une inférence sur les modèles.

**Sous Windows, sur la robustesse :** `ETAPES.cmd cp-robustness`. Il lit `analysis\robustness\cells.csv` et produit, par scénario, contrôleur ou méthode, et bras, les mêmes trois événements.

### 2.2 Courbe J(cycle) issue des recherches OFT existantes

Script : `tools/article_analyses/j_cycle_curve.py`. **Il n'a pas été exécuté** : les racines de recherche sont sur `D:`.

**Ce que fait le script :**
- Il relit chaque `evaluation_metrics.json` `optimized_fixed_timing` / `benchmark_design` des racines d'origine, de l'audit des cycles courts, d'A002 et de min7.
- Il identifie chaque plan réalisé.
- Il contrôle que les doublons entre racines concordent à 1e-9 ; sinon il les liste et sort avec le code 1.
- Il construit les courbes « meilleur plan par cycle » (g ≥ 5 et g ≥ 7) et le meilleur plan sur 40–140 s.

**Position de QMIX.** QMIX n'a aucune exécution sur les graines de conception 2001–2005. Sa position est donc une **bande de référence** sur une autre famille de trafics. Valeurs lues ici dans l'ablation et la figure 1, sur les trafics de développement 9301–9305 :

| Contrôleur | J |
|---|---|
| QMIX sans protection | moyenne 3,11 s (49/50 évacuées) ; moyennes par modèle de 2,98 à 3,21 s |
| Ancien plan C19 8/5 | 2,77 s |
| Plan min7 C25 12/7 | 3,16 s |

Les deux plans fixes servent de pont entre les familles : leur J de conception (lu par le script) comparé à leur J de développement mesure l'écart entre familles.

**Sous Windows :** `ETAPES.cmd j-cycle`, qui écrit `analysis\j_cycle\j_cycle.json`, `.csv` et `.pdf`.

### 2.3 Généralisation du diagnostic IDQN 107/8203

Script : `tools/article_analyses/guarantee_diagnostic.py`. **Il n'a pas été exécuté** : les sorties de la robustesse ne sont pas disponibles ici.

**Définitions, fixées dans le script :**
- **Après chaque intervention de la garantie :** le vert servi, puis le **vert suivant de la phase opposée**. Sa durée est signalée au-delà de 60 s, avec le délai avant que la phase servie revoie le vert.
- **Carrefour de l'intervention :** colonne `intersection` si elle existe ; sinon le carrefour dont le jaune démarre à cette seconde ; sinon les deux, en le signalant.
- **Par flux** (colonne `stream` du manifeste) : véhicules, attente moyenne et maximale, nombre ≥ 60 s et ≥ 300 s. S'y ajoute l'écart avec l'exécution `none` appariée.

**Sélections :**
- **Paires IDQN dégradées** (« guarantee − none ») :
  - D1 : ΔJ > 0, ou le bras échoue alors que `none` évacue (définition principale) ;
  - D2 : ΔD̄ > 0 ;
  - D3 : D1 ou D2.
- **Évaluations QMIX où la garantie agit :** au moins une intervention, pendant ou après la demande.

Les effectifs de chaque définition sont imprimés face aux 35 et 17 rapportés. Si aucune définition ne retrouve 35, la tienne diffère : il faudra me la donner pour l'ajouter.

**Sous Windows :** `ETAPES.cmd guarantee-diagnostic`, qui écrit `analysis\guarantee_diagnostic\`.

## 3. Récapitulatif du chiffrage

| Élément | Exécutions | Durée (4 processus) | Disque | Code | Tests |
|---|---|---|---|---|---|
| A1 OFT g5 + min7, 5 profils | 55 875 connues (grossier 55 375 + validation 500) ; fin exact après le grossier, borne 123 750 | 23–58 h connues | 4,6 Go (borne 15 Go) | `comparator_search.py`, `grids.py` | 3 + 5 |
| A2 actionné min7 | 800 | 0,3–0,8 h | 0,07 Go | `controllers.py` | 5 |
| A3 R3 par période | 320 | 0,1–0,3 h | 0,03 Go | `controllers.py` | 2 |
| Comparateurs retenus sur les trafics de robustesse | 85 | < 0,1 h | 0,2 Go | `evaluate_comparator.py` | (chaîne) |
| A4 Max Pressure | 0 (lecture seule) | quelques secondes | — | `mp_check.py` | exécuté ici |
| B confirmation | 2320 | ≈ 2,3–2,6 h | ≈ 10 Go | `confirmation_analysis.py` ; exécuteur à écrire | 5 |
| C analyses | 0 | quelques minutes | < 0,1 Go | `article_analyses/*.py` | 6 |

**Variante réduite de A1, non implémentée :** pas de décalage de 10 s dans la grille grossière, soit 27 925 exécutions au lieu de 55 375. C'est un écart à la procédure d'origine, à décider explicitement.

## 4. Ordre proposé

1. **Analyses sans risque, à faire maintenant :** `mp-check-static`, `mp-check-robustness`, `cp-robustness`, `guarantee-diagnostic`, `j-cycle`.
2. **Avant de choisir la variante de A1 :** `comparators-measure`, qui fixe les durées réelles.
3. **Ton accord** sur la variante (fidèle ou réduite), puis `comparators-plan`, `comparators-prepare`, et les étapes de A dans l'ordre de `PLAN_COMPARATEURS.md`.
4. **Après A :** écriture et test de l'exécuteur de B, validation de la marge et vérification contre A004, gel de B, puis seulement l'exécution.
