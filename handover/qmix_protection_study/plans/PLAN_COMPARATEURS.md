# Comparateurs équitables pour les profils de robustesse R0–R4

**Statut.** Préparé, testé et chiffré le 2026-11-07, puis mis à jour avec les décisions du même jour. **Non lancé.**

**Pas d'entraînement.** Le plan de robustesse et ses outils restent inchangés.

## 0. Décisions du 2026-11-07, fixées avant tout résultat de comparateur

Ces décisions sont déclarées dans `comparator_search.py` (`DECLARATIONS`) et entrent dans l'empreinte du plan.

| Code | Décision |
|---|---|
| D1 — **écart déclaré** | La grille grossière utilise des décalages tous les **10 s** (0, 10, …, < C) au lieu de 5 s, sur toutes ses parties : grille d'origine, cycles courts et plancher. La règle fine est **inchangée** : décalages ± 10 s **au pas de 1 s** autour de chaque alias grossier de chaque gagnant. |
| D2 | La recherche par profil (A1 OFT g5/min7, A2 actionné, A3 plans par période) ne porte que sur **R1, R2 et R3**. |
| D3 | **R0 : pas de recherche.** On réutilise les plans des recherches OFT de qualification : C19 8/5 D9 (g ≥ 5) et C25 12/7 D0 (g ≥ 7). La condition est vérifiée (§ 1). |
| D4 | **R4 : pas de recherche.** Comparateurs gelés seulement (C19, C25, Max Pressure canonique). Ils sont déclarés comme **non réoptimisés pour R4**. |

**Portée de D2.** La décision de n'appliquer la recherche qu'à R1–R3 vaut aussi pour l'actionné (A2), puisque R4 ne doit recevoir aucune recherche. Ajouter un actionné réglé pour R0 ou pour R4 coûterait 160 exécutions par profil ; ce n'est pas prévu.

## 1. Condition de D3 : la demande R0 est-elle celle de la qualification ?

Outil : `tools/comparators/check_r0_demand.py` (`ETAPES.cmd check-r0-demand`). Il compare sans simulation.

**Résultat exécuté ici : IDENTICAL_LAW**, aucun écart (`logs/revue_2026-11-07b/check_r0_demand_cloud.json`).

**Éléments identiques :**
- effectifs par flux (900, 700, puis 4 × 300) ;
- itinéraires et rangs des flux ;
- fenêtre de 3600 s, coupure à 7200 s, N = 2800 ;
- R0 n'a aucun profil temporel ;
- loi de génération : départs i.i.d. uniformes sur les secondes entières [0, 3600), avec des effectifs exacts par flux ;
- éléments `vType` et `route` ;
- attributs des véhicules ;
- ordre de tri.

**Contrôle empirique, informatif.** On compare 5 manifestes R0 (graines 8011–8015, inutilisées) à 5 manifestes de conception de qualification (2001–2005, régénérés par le générateur figé). La distance de Kolmogorov-Smirnov par flux vaut 0,019 à 0,034, avec p de 0,24 à 0,80.

**Différences qui ne sont pas des différences de demande :**
- identifiants des véhicules ;
- graines de trafic et de SUMO (nouvelle famille, par construction) ;
- tirages réalisés.

**Conclusion :** rien à signaler. La réutilisation de C19 et de C25 sur R0 est fondée. Ces deux plans ont été choisis sur des trafics tirés de la même loi.

## 2. Graines (`tools/comparators/seeds.py`)

| Rôle | Graines (profil de code c) | Usage |
|---|---|---|
| Évaluation de robustesse | 8c01–8c05 | déjà utilisées ; jamais pour régler |
| Conception | 8c11–8c15 | classer (R1–R3) |
| Validation | 8c21–8c25 | choisir (R1–R3) |
| Confirmation (réservée) | 8c51–8c60 | plan B seulement ; refusées par tout le code de recherche |

## 3. A1 — Plan fixe réoptimisé (R1, R2, R3)

On applique la procédure d'origine (`grids.py`), avec l'écart D1 :

1. **Grossier :**
   - grille d'origine : C de 40 à 140 s par pas de 10 ; parts de 0,30 à 0,75 par pas de 0,05 ;
   - cycles courts {20, 25, 30, 35} ;
   - plancher 16–19 s en g5 (vide en min7) ;
   - décalages au pas de 10 s ;
   - unité : le plan réalisé. On retient les 5 meilleurs.
2. **Fin :** règle figée au pas de 1 s autour de chaque alias. On retient les 10 meilleurs.
3. **Validation**, puis **sélection** selon l'ordre figé : J, puis perte de temps, puis cycle le plus court, puis clé.

La validité suit la règle figée : 5 exécutions CLEARED, J fini, aucune imputation. Un échec n'est jamais relancé.

| Version | Plans grossiers réalisés, pas de 10 s | Pour mémoire, pas de 5 s |
|---|---|---|
| g5 (règle d'origine g ≥ 5) | 990 + 107 + 20 = **1117** | 2215 |
| min7 (g ≥ 7) | 990 + 87 = **1077**, inclus dans les 1117 | 2138 |

Chaque plan réalisé est simulé une seule fois par graine : l'étape grossière min7 ne coûte rien de plus. La borne de la recherche fine passe à 2535 nouveaux plans par version et par profil. Le nombre exact est affiché par `comparators-finalise coarse` avant tout lancement.

## 4. A2 — Actionné à coupure de vert, vert minimal 7 s (R1, R2, R3)

`controllers.py`, `ActuatedGapOutExecutor` : inchangé.

- Grille de 27 réglages : gap {2, 3, 4} s × vert max H {30, 45, 60} s × vert max V {15, 25, 35} s, avec une zone de 40 m.
- On garde les 5 meilleurs, qu'on valide, puis on sélectionne.

## 5. A3 — R3, plans par période

Inchangé. Périodes [0, 900), [900, 2700), [2700, 3600). Transition sans interruption de cycle, avec rétablissement du décalage. Pour chaque période : top 3 sur le J de la période ; 27 combinaisons exécutées en conception ; 5 en validation ; une sélection.

## 6. Évaluation sur les trafics de robustesse

- **R1–R3 :** OFT g5, OFT min7 et actionné, plus les 2 plans par période de R3. Cela fait **55 évaluations**, avec compteurs et journaux complets.
- **R0 et R4 :** C19, C25 et le Max Pressure font déjà partie des contrôleurs de la campagne de robustesse. Aucune évaluation nouvelle.

`comparators-verify-manifests` vérifie d'abord l'identité des manifestes de R1–R3 avec ceux de la campagne.

## 7. Chiffrage exact

**Mesure Windows non reçue.** Les résultats de `comparators-measure` annoncés comme joints ne me sont pas parvenus. Les durées ci-dessous sont donc données pour 6, 10 et 15 s par exécution, plus la mesure cloud (17,6 s).

**Calcul exact sur ta machine.** La racine `%CMP%` contient déjà `measure.json`. `ETAPES.cmd comparators-plan` affiche donc la durée exacte de chaque étape (`estimate_by_stage`) avec ta mesure. Formule : heures = exécutions × s / 4 / 3600.

| Étape | Exécutions (exactes) | 6 s | 10 s | 15 s | cloud 17,6 s | Disque (compact, 82 Ko) |
|---|---|---|---|---|---|---|
| coarse (1117 × 5 × 3) | 16 755 | 7,0 h | 11,6 h | 17,5 h | 20,5 h | 1,4 Go |
| validation-g5 et validation-min7 | 150 + 150 | 0,1 h | 0,2 h | 0,3 h | 0,4 h | 0,02 Go |
| actuated-design et actuated-validation | 405 + 75 | 0,2 h | 0,3 h | 0,5 h | 0,6 h | 0,04 Go |
| tod-design et tod-validation (g5, min7) | 270 + 50 | 0,1 h | 0,2 h | 0,3 h | 0,4 h | 0,03 Go |
| **Total connu avant la recherche fine** | **17 855** | **7,4 h** | **12,4 h** | **18,6 h** | **21,8 h** | **1,5 Go** |
| fine-g5 et fine-min7 | exact après `finalise coarse` ; borne 38 025 + 38 025 | borne 31,7 h | borne 52,8 h | borne 79,2 h | borne 93,1 h | borne 6,2 Go |
| robustness-eval (journaux complets, 2,7 Mo) | 55 | < 0,1 h | < 0,1 h | < 0,1 h | < 0,1 h | 0,15 Go |

**À propos de la borne fine.** C'est une borne théorique : elle somme les 5 plus grands voisinages, sans recouvrement. Des gagnants voisins se recouvrent largement, et les plans déjà simulés ne sont pas relancés.

## 8. Commandes Windows (`traffic_rl`)

**Avant le plan :**

```bat
ETAPES.cmd check-r0-demand
ETAPES.cmd comparators-plan
ETAPES.cmd comparators-prepare <empreinte>
ETAPES.cmd comparators-verify-manifests
```

- `check-r0-demand` refait la vérification du § 1 sur ta pile ; il doit afficher IDENTICAL_LAW, code 0.
- `comparators-plan` affiche le chiffrage exact par étape avec ton `measure.json`.
- `comparators-prepare` prend l'empreinte affichée par `comparators-plan`.

**Recherches**, pour chaque étape, dans l'ordre :

1. `coarse`
2. `actuated-design`
3. `fine-g5`
4. `fine-min7`
5. `validation-g5`
6. `validation-min7`
7. `actuated-validation`
8. `tod-design-g5`
9. `tod-design-min7`
10. `tod-validation-g5`
11. `tod-validation-min7`

Pour chacune :

```bat
ETAPES.cmd comparators-run <étape>
ETAPES.cmd comparators-progress
ETAPES.cmd comparators-finalise <étape>
```

- `comparators-progress` renvoie 0 quand l'étape est terminée, 3 s'il reste des exécutions, 5 en cas de résultat corrompu.
- `comparators-finalise coarse` affiche le nombre exact d'exécutions fines.

**Fin :**

```bat
ETAPES.cmd comparators-run robustness-eval
```

`comparators-run` lance 4 processus : son code de sortie ne couvre que le lancement. On contrôle avec `comparators-progress` et `logs\comparators_<étape>_shard*.log`.

## 9. Exécuté ici, et tests

**Exécuté ici :**
- vérification de la demande R0 ;
- chaîne réelle `measure` → `plan` → `prepare` → 4 exécutions grossières ;
- 9 exécutions de rodage des contrôleurs. Tout est sur graines de conception, avec SUMO 1.28 ; ce ne sont pas des résultats.

Journaux : `logs/revue_2026-11-07/` et `logs/revue_2026-11-07b/`.

**Tests :**

| Fichier | Contenu | Nombre |
|---|---|---|
| `tests/test_comparators.py` | grilles aux pas de 5 et de 10 s ; règle fine inchangée ; graines ; actionné ; plans par période ; demande R0 identique et écart signalé | 13 |
| `tests/test_comparator_search.py` | chaîne complète avec faux évaluateur sur R1 et R3 ; périmètre, déclarations et comptes exacts | 6 |
