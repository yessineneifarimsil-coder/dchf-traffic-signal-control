# Plan de confirmation pré-enregistré (B)

**Statut : brouillon de pré-enregistrement. Non gelé, non lancé.** Aucune graine de confirmation n'a été générée.

**Mise à jour du 2026-11-07.** Ont été intégrés :
- la marge d'équivalence ;
- la référence statistique A004 ;
- le périmètre des comparateurs ;
- la justification de l'exclusion d'IDQN.

**Fichiers :**
- `tools/confirmation/confirmation_plan.json` : paramètres, avec une **empreinte** (`fingerprint`) qui couvre tous les champs ; l'analyse refuse un plan modifié (testé) ;
- `tools/confirmation/confirmation_analysis.py` : analyse.

Empreinte du brouillon : `66fcb6786349161e8367a6952d9ff0f2145c17081da9902cc57b5cb0411f72d8`. Elle sera recalculée au gel, quand les sélections de A et `margins.json` y seront ajoutés.

## 1. Question

Les politiques QMIX et VDN figées, avec la seule garantie, servent-elles tous les véhicules sur des trafics jamais utilisés ? Et que vaut leur J face au meilleur comparateur classique disponible pour chaque profil ?

## 2. Gel : ordre imposé

1. A terminé : sélections scellées.
2. `check-statistics` exécuté : fichier A004 vérifié.
3. Gel du plan B. L'empreinte couvre :
   - les graines ;
   - les SHA-256 des checkpoints ;
   - les sélections de A ;
   - `margins.json` ;
   - le code de l'analyse et la référence A004.
4. Génération des trafics de confirmation, puis exécutions.
5. Analyse appliquée une fois.

## 3. Trafics, politiques et bras

**Trafics.** 10 graines neuves par profil (8c51–8c60), soit 50 trafics. Elles sont réservées dans `tools/comparators/seeds.py` et refusées par tout le code de recherche.

Ne sont jamais utilisés :
- 3001–3010 et 3101–3120 ;
- 8c01–8c05 ;
- 8c11–8c25.

**Politiques.** Les 10 checkpoints sélectionnés de QMIX et les 10 de VDN, vérifiés par SHA-256. Pas de réentraînement, pas de nouvelle sélection.

**Bras.** Principal : `guarantee`. Secondaire : `none`.

## 4. Pourquoi IDQN est exclu

L'exclusion est décidée avant que le moindre trafic de confirmation existe. Trois raisons :

1. **La question.** La confirmation porte sur les méthodes coopératives à factorisation de valeur (QMIX, VDN) avec la seule garantie. IDQN, fait d'apprenants indépendants sans coordination, sert de référence non coopérative dans le développement, l'ablation et la robustesse. Ses résultats y sont rapportés en entier.
2. **Une instabilité connue avant la confirmation.**
   - **Ablation, lu.** IDQN est la seule méthode dont l'effet du vert minimal est irrégulier : il améliore certains modèles, en dégrade d'autres, corrige 4 échecs et en crée 1. IDQN compte 4 échecs sur 50 sans protection (Clopper-Pearson à 95 % : [2,2 % ; 19,2 %]).
   - **Robustesse, rapporté.** La garantie seule augmente D̄ dans 35 paires IDQN, selon la définition D2. Le diagnostic 107/8203 montre de longs verts opposés après les interventions.
   - **Conséquence.** IDQN avec garantie n'est pas un candidat stable qu'une confirmation pourrait corroborer.
3. **La multiplicité.** Ajouter IDQN porterait la famille principale de 10 à 15 comparaisons (Bonferroni à 99,67 %). Tous les intervalles de décision s'élargiraient, pour une configuration qui n'est pas candidate.

**Conséquences déclarées :**
- La confirmation ne permet aucune conclusion sur IDQN.
- Ses résultats de développement, d'ablation et de robustesse sont conservés et rapportés en entier.
- **Limite.** Les méthodes confirmées ont été retenues après les résultats de développement et de robustesse. La confirmation les teste sur des trafics neufs ; elle ne compare pas toutes les méthodes.

## 5. Comparateurs par profil

| Profil | Principal (décisions) | Secondaires (descriptifs) |
|---|---|---|
| R0 | C19 8/5 D9 : OFT g ≥ 5 de la qualification, réutilisé (demande R0 de même loi, vérifiée) | C25 12/7 D0 (OFT g ≥ 7 de la qualification) ; Max Pressure canonique |
| R1, R2 | OFT g5 réoptimisé (A1, grille grossière réduite, écart D1) | OFT min7 ; actionné min7 ; Max Pressure ; C19 ; C25 |
| R3 | OFT g5 réoptimisé (A1, D1) | les mêmes, plus les plans par période g5 et min7 |
| R4 | C19 8/5 D9, **gelé, non réoptimisé pour R4 (déclaré)** | C25 (gelé) ; Max Pressure |

## 6. Critères

| Rôle | Critère |
|---|---|
| Principal | J par (modèle, trafic), avec N = total du manifeste |
| Service | Échec d'évacuation ; échec avec un compteur ouvert ; au moins un véhicule en attente ≥ 300 s |
| Secondaires | D̄ sur la fenêtre de demande ; perte de temps ; attente maximale |

## 7. Statistique

**Référence : A004 = statistics-1.2**, SHA-256 `8b6413a9ccffa2bbbcf0d3cfdde6c7460b4785193aa419f7d4725885dc38437a`.

**Procédure :** bootstrap croisé apparié (`paired_crossed_bootstrap`, `official=False`), 10 000 réplicats, intervalle par percentiles. Le plan croise 10 modèles et 10 trafics, et le comparateur est diffusé par trafic : D_ij = J_appris(i,j) − J_comparateur(j).

**Mise en œuvre.** L'analyse charge **le fichier A004 lui-même** (`--statistics <chemin>`) et refuse tout autre SHA-256 (testé).

**Vérification de la version, état au 2026-11-07 :**
- **statistics-1.2 est absent de tous les dépôts et branches disponibles ici.** Le code figé 8c14f32 est **statistics-1.1** : fichier `ed133bb2…`, empreinte de protocole `72769a92…`. C'est bien la version que citent les résumés de comparaison. L'historique ne contient que les versions 1.0 et 1.1.
- **La correspondance n'a donc pas pu être vérifiée ici.** Elle se fait sous Windows avec `ETAPES.cmd check-statistics <chemin du statistics.py d'A004>` (`tools/confirmation/check_statistics.py`).
- Cet outil vérifie le SHA-256, puis compare à statistics-1.1 :
  - les constantes (réplicats, espace aléatoire, niveau, plan) ;
  - le code source de `paired_crossed_bootstrap` et des 8 fonctions qu'il appelle ;
  - la signature ;
  - les résultats numériques sur des panneaux croisés identiques (déterministe et appris, 95 % et 99,5 %, 10 000 réplicats), au bit près.
- **Verdict :** `IDENTICAL_BOOTSTRAP` ou `DIFFERENT_BOOTSTRAP`, avec les écarts. Dans les deux cas, l'analyse utilise A004. Si les bootstraps diffèrent, les résumés de comparaison existants, calculés en 1.1, ne peuvent pas être mis en regard des résultats de confirmation sans le signaler.

**Niveaux :**
- **Décisions : intervalle à 99,5 %** (Bonferroni sur les 10 comparaisons principales, 5 profils × 2 méthodes) ;
- **Description : 95 %**.

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
- **Énoncé de service** pour une méthode : seulement avec 0 échec avec attente ouverte sur ses 500 évaluations avec garantie. Il s'accompagne de la borne de Clopper-Pearson unilatérale à 95 % (0,6 %).
- Sont **descriptifs (95 %)** : « guarantee − none », le bras `none` et les comparateurs secondaires.

## 9. Chiffrage

| Élément | Exécutions |
|---|---|
| Évaluations apprises : 2 méthodes × 10 modèles × 2 bras × 5 profils × 10 trafics | 2000 |
| Comparateurs : (3 + 6 + 6 + 8 + 3) × 10 | 260 |
| **Total** | **2260** |

- **Durée :** environ 2,3 h sur 4 processus à 14,5 s par évaluation ; environ 2,5 h si 10 % des exécutions vont jusqu'à la coupure.
- **Disque :** environ 10 Go.

## 10. Code, tests et ce qui manque

| Élément | État |
|---|---|
| Analyse | `confirmation_analysis.py` |
| Vérification d'A004 | `check_statistics.py` |
| Tests (`tests/test_confirmation_analysis.py`, 9) | ordre et bornes des règles ; marge de 2026-11-07 avec son plancher ; empreinte du plan ; décisions sur panneaux synthétiques ; échec avec attente ouverte ; cellule manquante ; refus d'un module statistique autre que la référence ; outil A004 qui distingue un bootstrap identique d'un bootstrap modifié |
| Exécuteur des évaluations | **Pas encore écrit.** Il sera dérivé du runner de robustesse, avec les comparateurs passés par `evaluate_comparator.py` (compteurs activés). Il est à écrire et à tester après A, avant le gel. |
| Analyse, après les exécutions seulement | `python tools\confirmation\confirmation_analysis.py --cells <cells.csv> --margins <margins.json> --statistics <statistics.py d'A004> --out analysis\confirmation` |
