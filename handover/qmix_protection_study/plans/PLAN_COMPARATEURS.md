# Comparateurs équitables pour les profils de robustesse R0–R4

**Date :** 2026-11-07.

**Statut :** préparé, testé, chiffré. **Non lancé.** Aucune simulation longue avant ton accord.

**Pas d'entraînement.** Rien n'est ajouté au plan de robustesse ; ce dernier reste inchangé.

## 1. Ce que chaque comparateur doit permettre de dire

Les politiques apprises ont été choisies avant la robustesse. Elles sont évaluées sur des profils qu'aucun comparateur classique n'a vus. Comparer ces politiques au seul plan C19, réglé pour la demande de qualification, avantage les politiques apprises. Chaque comparateur ci-dessous est donc **réglé pour le profil lui-même**, sur des graines qui lui sont propres.

## 2. Graines

Le registre est dans `tools/comparators/seeds.py`. Les graines sont fixées avant toute exécution. Toutes appartiennent à la famille `robustness` (code 80) et sont produites par le générateur inchangé.

| Rôle | Graines (profil de code c = 0…4) | Usage |
|---|---|---|
| évaluation de robustesse | 8c01–8c05 | déjà utilisées ; jamais pour régler un comparateur |
| conception | 8c11–8c15 | classer les candidats (A1, A2, A3) |
| validation | 8c21–8c25 | choisir un candidat (A1, A2, A3) |
| confirmation (réservée) | 8c51–8c60 | plan B uniquement ; refusées par tout le code de recherche (testé) |

Les graines 3001–3010 et 3101–3120 restent refusées par le générateur.

## 3. A1 — Plan fixe réoptimisé par profil, procédure OFT d'origine

Le code est `tools/comparators/grids.py` et `comparator_search.py`. La procédure reprend les générateurs figés (`baselines/plans.py`) ainsi que les règles d'A002 et de l'étude min7. Seuls changent le seuil d'admissibilité et les graines.

**Étapes :**

1. **Grossier.**
   - Grille d'origine : C de 40 à 140 s par pas de 10 ; parts de 0,30 à 0,75 par pas de 0,05 ; décalages Δ = 0, 5, …, C−5.
   - Cycles courts : {20, 25, 30, 35}.
   - **Extension au plancher physique :** C ∈ [2·g_min + 6, 20), soit 16 à 19 s en g5 ; cette bande est vide en min7.
   - L'unité est le plan réalisé (C, g_H, g_V, Δ mod C).
   - On retient les 5 meilleurs.
2. **Fin.**
   - Règle figée autour de **chaque** alias grossier des 5 gagnants : C ± 10 s par pas de 5, borné au plancher et à 140 ; part ± 0,050 par pas de 0,025 ; Δ ± 10 s par pas de 1.
   - On prend l'union, réduite aux plans réalisés.
   - On retient les 10 meilleurs en conception.
3. **Validation** de ces 10 sur les 5 graines de validation du profil.
4. **Sélection** selon l'ordre figé : J moyen, puis perte de temps moyenne, puis cycle le plus court, puis clé réalisée.

**Validité :** règle figée. Un candidat n'est valide que si ses 5 exécutions sont CLEARED, avec J et perte de temps finis. On n'impute jamais de valeur. Un échec d'évacuation est un résultat définitif : il n'est jamais relancé.

**Deux versions :**

| Version | Admissibilité | Plancher | Plans grossiers (réalisés) |
|---|---|---|---|
| g5, « sans vert minimal » | g_H ≥ 5 et g_V ≥ 5 : la règle d'origine du benchmark, il n'existe pas de version sans aucun seuil | 16 s | 1980 + 195 + 40 = **2215** |
| min7 | g_H ≥ 7 et g_V ≥ 7 | 20 s | 1980 + 158 = **2138**, sous-ensemble des 2215 |

Ces comptes reproduisent ceux publiés par A002 et min7 (testé) :
- 1980 + 208 + 68 étiquettes ;
- 2143 étiquettes en min7 ;
- borne fine de 2475 plans en min7.

**Partage des exécutions.** Chaque plan réalisé est simulé une seule fois par graine. L'étape grossière min7 ne coûte donc aucune exécution de plus.

**Ordres scellés.** Chaque ordre est écrit une seule fois par `finalise`, qui affiche le nombre exact d'exécutions avant tout lancement. Les plans déjà simulés sont réutilisés.

## 4. A2 — Contrôle actionné à coupure de vert, vert minimal 7 s

Le code est `tools/comparators/controllers.py`, classe `ActuatedGapOutExecutor`.

**Fonctionnement, par carrefour :**
- Vert minimal de 7 s sur les deux phases.
- Détecteur virtuel de présence sur les 40 derniers mètres de chaque voie entrante de la phase verte.
- Appel conflictuel : au moins un véhicule sur une voie de la phase rouge (mémoire d'appel).
- Le vert se termine si un appel existe et que :
  - le temps sans détection atteint le paramètre gap (coupure), ou
  - le vert atteint son maximum (max-out).
- Sans appel, le vert reste en place (pas de rappel).
- Jaune de 3 s. Pas de coordination entre les deux carrefours.

**Petite grille (27 réglages) :** gap ∈ {2, 3, 4} s × vert max H ∈ {30, 45, 60} s × vert max V ∈ {15, 25, 35} s, avec une zone de 40 m. On garde les 5 meilleurs en conception, on les valide, puis on en sélectionne un : J, puis perte de temps, puis ordre de la grille.

## 5. A3 — R3 : un plan fixe par période

Le code est la classe `TimeOfDayScheduleExecutor`. Les périodes sont celles de la spécification de R3 : [0, 900), [900, 2700) et [2700, 3600) s.

**Transition, fixée avant toute exécution :**
- Un cycle n'est jamais interrompu.
- J1 démarre le nouveau plan à la fin de son cycle en cours.
- J2 prolonge son vert H (attente) jusqu'à ce que le nouveau décalage soit rétabli, puis suit le nouveau plan.
- Ce comportement est vérifié sous SUMO et dans les tests : jaunes de 3 s, aucun passage direct d'un vert à l'autre, décalages 23 s puis 10 s rétablis.

**Procédure, pour chaque version g5 et min7 :**
1. Pour chaque période, on classe tous les plans valides de R3 issus des étapes grossière et fine de cette version. Le critère est le J de la période : moyenne de waitingTime + departDelay sur les véhicules **programmés** dans la période, avec le plan appliqué tout l'épisode. Cette étape ne demande aucune nouvelle exécution.
2. On retient les 3 meilleurs plans par période, d'où 27 combinaisons.
3. Ces combinaisons sont exécutées avec les vraies transitions en conception. On en garde 5, qui passent en validation, puis on sélectionne.

**Limite assumée.** Le classement par période est une heuristique de conception : un plan isolé ne voit pas l'état laissé par la période précédente. Seules les 27 combinaisons, exécutées en vrai, décident.

## 6. Évaluation des comparateurs retenus sur les trafics de robustesse

L'étape `robustness-eval` évalue chaque comparateur sélectionné sur 8c01–8c05, avec compteurs de service par seconde et journaux complets :
- 3 comparateurs par profil (OFT g5, OFT min7, actionné) ;
- plus 2 plans par période pour R3.

Cela donne **85 évaluations**. Elles se placent à côté des cellules existantes de la robustesse.

`verify-manifests` vérifie d'abord que les manifestes régénérés sont identiques octet pour octet à ceux de la campagne de robustesse.

## 7. Chiffrage

**Mesures disponibles.** La durée par exécution mesurée ici est de 14,4 à 17,6 s, avec 1 processus, SUMO 1.28 et l'étape `measure`. La taille est de 82 Ko en mode compact et de 2,2 Mo en journaux complets, plus environ 25 % de compteurs.

**Hypothèse retenue pour Windows :** 6 à 15 s par exécution et par processus, sur 4 processus.

**La mesure locale fait foi.** `comparators-measure` doit être exécuté sur la machine Windows avant `comparators-plan` ; le plan intègre alors la mesure.

| Élément | Exécutions | Durée (4 processus) | Disque |
|---|---|---|---|
| A1 grossier : 2215 plans × 5 graines × 5 profils, partagé g5/min7 | 55 375 | 23 à 58 h | 4,5 Go |
| A1 fin, g5 et min7 | exact après `finalise coarse` ; borne 2 × 5 × 12 375 = 123 750 | borne 52 à 129 h ; en pratique bien moins (voisinages qui se recouvrent, plans déjà faits) | ≤ 10 Go |
| A1 validation : 10 × 5 × 2 versions × 5 profils | 500 | 0,2 à 0,5 h | 0,04 Go |
| A2 actionné : (27 + 5) × 5 graines × 5 profils | 800 | 0,3 à 0,8 h | 0,07 Go |
| A3 R3 par période : (27 + 5) × 5 × 2 versions | 320 | 0,1 à 0,3 h | 0,03 Go |
| Évaluation sur les trafics de robustesse | 85 | < 0,1 h | 0,23 Go |
| **Total connu avant l'étape fine** | **56 995 + 85** | **24 à 60 h** | **≈ 5 Go** |
| Borne haute absolue | 180 830 | 75 à 188 h | ≈ 15 Go |

**Variante réduite, à décider : non implémentée.** Un pas de décalage de 10 s dans la grille grossière seulement ramène celle-ci à 1117 plans par profil, soit 27 925 exécutions au lieu de 55 375 (gain d'environ 11 à 29 h). La recherche fine reste au pas de 1 s. C'est un écart à la procédure d'origine : il faudrait le déclarer comme tel.

## 8. Commandes Windows (`traffic_rl`)

Toutes passent par `ETAPES.cmd`. La racine est `%CMP%` (par défaut `D:\QMIX_Results\comparators_robustness_profiles`).

```bat
ETAPES.cmd comparators-measure
ETAPES.cmd comparators-plan
ETAPES.cmd comparators-prepare <empreinte>
ETAPES.cmd comparators-verify-manifests

ETAPES.cmd comparators-run coarse
ETAPES.cmd comparators-progress
ETAPES.cmd comparators-finalise coarse

ETAPES.cmd comparators-run actuated-design
ETAPES.cmd comparators-finalise actuated-design
ETAPES.cmd comparators-run fine-g5
ETAPES.cmd comparators-finalise fine-g5
ETAPES.cmd comparators-run fine-min7
ETAPES.cmd comparators-finalise fine-min7
ETAPES.cmd comparators-run validation-g5
ETAPES.cmd comparators-finalise validation-g5
ETAPES.cmd comparators-run validation-min7
ETAPES.cmd comparators-finalise validation-min7
ETAPES.cmd comparators-run actuated-validation
ETAPES.cmd comparators-finalise actuated-validation
ETAPES.cmd comparators-run tod-design-g5
ETAPES.cmd comparators-finalise tod-design-g5
ETAPES.cmd comparators-run tod-design-min7
ETAPES.cmd comparators-finalise tod-design-min7
ETAPES.cmd comparators-run tod-validation-g5
ETAPES.cmd comparators-finalise tod-validation-g5
ETAPES.cmd comparators-run tod-validation-min7
ETAPES.cmd comparators-finalise tod-validation-min7

ETAPES.cmd comparators-run robustness-eval
ETAPES.cmd comparators-progress
```

**Points d'usage :**
- `comparators-measure` est à lancer avant `comparators-plan` (6 exécutions courtes, environ 2 min).
- L'empreinte passée à `comparators-prepare` est celle qu'affiche `comparators-plan`.
- `comparators-progress` renvoie 0 quand tout est terminé, 3 tant qu'il manque des exécutions, 5 en cas de résultat corrompu.
- `comparators-finalise coarse` affiche le nombre exact d'exécutions fines.
- `comparators-run` lance 4 processus : son code de sortie ne couvre que le lancement. On contrôle ensuite avec `comparators-progress` et `logs\comparators_<étape>_shard*.log`.
- L'ordre `robustness-eval` est créé automatiquement après la dernière sélection.

## 9. Ce qui a été exécuté ici, et ce qui ne l'a pas été

**Exécuté ici (cloud, SUMO 1.28 ; ce ne sont pas des résultats) :**
- `measure` ;
- `prepare` sur une racine jetable ;
- 4 vraies exécutions grossières, avec états, reprise et codes de sortie ;
- 9 exécutions de rodage des contrôleurs sur des graines de conception, dont la vérification des transitions.

Journaux : `logs/revue_2026-11-07/`.

**Tests :**

| Fichier | Contenu | Nombre |
|---|---|---|
| `tests/test_comparators.py` | grilles, graines, actionné, plans par période | 11 |
| `tests/test_comparator_search.py` | chaîne complète avec faux évaluateur : sélections recalculées indépendamment, échec scientifique jamais relancé, résultat corrompu bloquant, ordres scellés, code modifié refusé | 5 |

**Non exécuté :** aucune étape de recherche réelle. Les durées Windows restent à mesurer.
