# Plan de confirmation pré-enregistré (B)

**Date :** 2026-11-07.

**Statut : brouillon de pré-enregistrement. Non gelé, non lancé.** Aucune graine de confirmation n'a été générée.

**Paramètres :**
- `tools/confirmation/confirmation_plan.json` : paramètres lisibles par machine ;
- `tools/confirmation/confirmation_analysis.py` : analyse, écrite et testée avant toute exécution.

## 1. Question

Les politiques QMIX et VDN figées, avec la seule garantie, servent-elles tous les véhicules sur des trafics jamais utilisés ? Et que vaut leur J face aux comparateurs réoptimisés pour chaque profil (A) ?

Le bras sans protection est secondaire.

## 2. Gel : l'ordre des opérations est imposé

1. **A terminé.** Les sélections sont scellées (`selections/*.json`).
2. **Gel du plan B.** Son empreinte couvre :
   - les graines ;
   - les SHA-256 des 20 checkpoints ;
   - les spécifications et SHA-256 des sélections de A ;
   - les marges calculées (`margins.json`) ;
   - le code de l'analyse ;
   - le nombre de réplicats, l'espace aléatoire et l'ordre des règles.
3. **Génération** des trafics de confirmation, **puis** les exécutions.
4. **Analyse appliquée une fois.**

Rien de ce plan ne change après le gel. Un écart serait déclaré comme amendement, daté, avant tout regard sur les sorties.

## 3. Trafics

Il y a 10 graines neuves par profil : 8c51–8c60, soit 50 trafics. Elles ont été réservées le 2026-11-07 dans `tools/comparators/seeds.py` et sont refusées par tout le code de recherche (testé).

Les trafics sont générés avec la spécification inchangée des profils R0–R4.

Ne sont jamais utilisés :
- 3001–3010 et 3101–3120 ;
- 8c01–8c05, l'évaluation de robustesse ;
- 8c11–8c25, la conception et la validation des comparateurs.

## 4. Politiques et bras

| Élément | Contenu |
|---|---|
| Politiques | QMIX et VDN : les 10 checkpoints sélectionnés par méthode (graines 101–110), vérifiés par SHA-256. Pas de réentraînement, pas de nouvelle sélection. IDQN n'en fait pas partie. |
| Bras principal | `guarantee` (la garantie seule) |
| Bras secondaire | `none` |

## 5. Comparateurs, par profil

| Rôle | Comparateurs |
|---|---|
| Principal | `oft_g5` : plan fixe réoptimisé pour le profil (A1, règle d'origine g ≥ 5) |
| Secondaires (descriptifs) | OFT min7 ; actionné min7 ; Max Pressure canonique ; ancien plan C19 8/5 D9 ; plan min7 C25 12/7 D0 ; pour R3, plans par période g5 et min7 |

Le choix du comparateur principal est fixé ici. Il ne dépend d'aucun résultat de confirmation.

## 6. Critères

| Rôle | Critère |
|---|---|
| Principal | J par (modèle, trafic) : moyenne de waitingTime + departDelay sur les N véhicules programmés du manifeste |
| Service | Échec d'évacuation ; échec avec un compteur ouvert à la fin ; au moins un véhicule en attente ≥ 300 s |
| Secondaires | D̄ sur la fenêtre de demande ; perte de temps ; attente maximale |

## 7. Statistique, identique à la procédure figée

**Procédure.** On utilise `adaptive_qmix.protocol.statistics.paired_crossed_bootstrap`. Il est importé du code figé, jamais recopié, et appelé avec `official=False`.

**Plan croisé.** Le plan croise 10 modèles (graines d'entraînement) et 10 trafics. Le comparateur déterministe est diffusé par trafic : D_ij = J_appris(i,j) − J_comparateur(j).

**Paramètres :**
- 10 000 réplicats ;
- espace aléatoire figé ;
- intervalle par percentiles.

**Ce plan n'a pas pu être relu ici.** Le document « A004 » cité dans la demande ne se trouve dans aucun des fichiers disponibles. Le plan reprend donc la procédure croisée du protocole figé (`statistics-1.1`). **À vérifier contre A004 avant le gel.**

**Multiplicité.** Il y a 5 profils × 2 méthodes face au comparateur principal, soit 10 comparaisons. On applique Bonferroni : décisions sur l'intervalle **à 99,5 %**. L'intervalle à 95 % est rapporté pour description.

**Marge d'équivalence.** Pour chaque profil, δ = 0,10 × le J moyen de validation du comparateur principal sélectionné. Cette valeur est lue dans sa sélection scellée et figée au gel.

C'est une **proposition**. Le facteur 0,10 est à valider (ou à remplacer) avant le gel.

## 8. Règles de décision

Les règles s'appliquent par profil et par méthode, avec [L, U] l'intervalle à 99,5 % de D. Un D négatif signifie que la politique apprise fait mieux. La première règle vérifiée l'emporte.

1. **ÉCHEC DE SERVICE.** Au moins une évaluation avec garantie échoue avec un compteur ouvert. La comparaison de J n'est alors pas lue comme un succès.
2. **NON ESTIMABLE.** Tout autre échec appris, ou un échec du comparateur sur un trafic. J n'est jamais imputé. Une analyse de sensibilité sans le modèle ou le trafic en cause est rapportée, à titre descriptif seulement.
3. **SUPÉRIEUR AU-DELÀ DE LA MARGE :** U < −δ.
4. **SUPÉRIEUR :** U < 0.
5. **ÉQUIVALENT :** −δ < L et U < δ.
6. **INFÉRIEUR AU-DELÀ DE LA MARGE :** L > δ.
7. **INFÉRIEUR :** L > 0.
8. **NON CONCLUANT** dans tous les autres cas.

**Conclusions autorisées :**
- Elles portent sur un profil et une méthode à la fois. Aucune décision n'est prise en agrégeant les profils.
- **Énoncé de service** pour une méthode : « aucun déni de service indéfini sur ces 50 trafics ». Il n'est autorisé que si les 500 évaluations avec garantie de cette méthode ne comptent aucun échec avec attente ouverte. La borne de Clopper-Pearson doit accompagner l'énoncé : unilatérale à 95 %, elle vaut 0,6 % pour 0/500.
- Sont **descriptifs (95 %)** : le contraste « guarantee − none » (effet de la garantie seule, apparié par modèle et trafic), le bras `none` et les comparateurs secondaires.

## 9. Chiffrage

| Élément | Exécutions |
|---|---|
| Évaluations apprises : 2 méthodes × 10 modèles × 2 bras × 5 profils × 10 trafics | 2000 |
| Comparateurs : 6 × 5 profils × 10 trafics + 2 plans par période × 10 trafics (R3) | 320 |
| **Total** | **2320** |

- **Durée :** environ 2,3 h sur 4 processus, à 14–15 s par évaluation (13–14 s mesurés pour l'ablation sous Windows). Jusqu'à environ 2,6 h si 10 % des exécutions vont jusqu'à la coupure de 7200 s.
- **Disque :** environ 10 Go (journaux complets et compteurs par seconde).

## 10. Code, tests et ce qui manque

| Élément | État |
|---|---|
| Analyse | `confirmation_analysis.py` ; 5 tests (`tests/test_confirmation_analysis.py`) : ordre et bornes des règles, graines neuves et disjointes, décisions sur des panneaux synthétiques à effet connu, échec avec attente ouverte, cellule manquante sans décision |
| Exécuteur des évaluations | **Pas encore écrit.** Il sera dérivé du runner de robustesse (mêmes états de cellule et codes de sortie), avec les comparateurs de A passés par `evaluate_comparator.py` (compteurs activés). Il dépend des sélections de A et doit être écrit et testé **avant** le gel. |
| Commande d'analyse, après les exécutions seulement | `python tools\confirmation\confirmation_analysis.py --cells <cells.csv> --margins <margins.json> --out analysis\confirmation` |
