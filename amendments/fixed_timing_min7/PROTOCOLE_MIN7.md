# Étude min7 : plan fixe optimisé sous un vert minimal de 7 s

**Statut.** Plan d'exécution borné. Aucune recherche, sélection ou comparaison n'a encore été exécutée sur les données réelles. Les nombres marqués « exact après `grossier` » dépendent des résultats de conception existants. Ils sont donc établis par l'outil et scellés avant toute nouvelle simulation de l'étape fine.

**Portée.** Uniquement la piste `optimized_fixed_timing`. Le plan à décalage optimisé `optimized_fixed_offset` (90, 500, 41), soit 42/42 s, n'est pas concerné et n'est pas réutilisé comme référence.

**Ce qui est exclu.** Pas de nouvel entraînement, pas de nouveau test final, pas de contrôleur à coupure de vert, pas d'autre valeur de vert minimal.

## 1. Ce qui n'est jamais modifié

L'outil lit les éléments suivants, mais n'y écrit jamais :

* le checkout d'exécution `C:\Users\LENOVO\QMIX_Traffic_Coordination` au commit `8c14f32` ;
* `C:\Users\LENOVO\QMIX_PROTECTED` ;
* les racines de l'original, de l'audit des cycles courts, de l'Amendement 002 (learners compris) et de l'Amendement 003 ;
* les sélections ;
* les pilotes protégés.

Le contrôle est fait de deux façons :

* `Layout` refuse toute nouvelle racine qui chevauche une racine protégée ;
* toute écriture passe par `assert_writable`, limité à `D:\QMIX_Results\fixed_timing_min7_2026-10-27`.

Le test de bout en bout photographie les racines protégées (taille et date de chaque fichier) avant et après toutes les étapes.

Pour éviter tout bytecode dans le checkout :

* toutes les commandes utilisent `python -B` ;
* le pilote refuse de s'exécuter depuis l'intérieur du checkout ;
* chaque étape vérifie que `git rev-parse HEAD` vaut `8c14f32988e92ddc6b1421d70258f5fbd2f2cc4d` et que `git status --porcelain` est vide.

## 2. Procédure d'origine reconstituée à partir du code et des artefacts

La source fait foi : le code figé (`baselines/plans.py`, `search.py`, `campaign.py`, `runner.py`, `metrics.py`), le pilote A002 exécuté (`amendment002.py`, SHA-256 `f624ec32…3164f`, copie octet pour octet vérifiée à l'import) et ses ordres scellés. L'étape `plan` relit et vérifie :

* le gel amendé (`verify_stage_artefact`) ;
* l'empreinte du pilote ;
* l'empreinte de l'addendum ;
* les empreintes des ordres plancher et fin enregistrées dans le gel ;
* l'artefact de validation ;
* la clé remplacée (40, 650, 23).

Elle s'arrête si l'un de ces éléments diffère.

### 2.1 Plan actuellement sélectionné et provenance

* **Plan :** `optimized_fixed_timing`, étiquette (19, 577, 9) = C 19 s, vert H 8 s, vert V 5 s, jaunes 3 s, décalage J2 9 s (J1 décalage 0).
* **Validation :** J moyen 2,765071428571429 s et perte de temps 11,74861 s sur `benchmark_validation` 2101–2105. Ces valeurs sont lues dans le gel par l'étape `plan` et affichées.
* **Provenance :** classement sur `benchmark_design` 2001–2005, puis sélection sur la validation avec le départage figé ; étape `timing_fine_design` de l'Amendement 002.
* **Plan remplacé :** il remplace le plan d'origine (40, 650, 23).
* **Le vert V de 5 s viole la contrainte de 7 s.** Ce plan reste la référence existante (bras A).

### 2.2 Domaines, pas et étapes réellement exécutés

| Étape | Domaine | Pas | Admissibilité | Comptes |
|---|---|---|---|---|
| Grossier d'origine | C = 40…140 | 10 s ; parts 0,30…0,75 pas 0,05 ; Δ = 0, 5, …, C−5 | g_H ≥ 5 et g_V ≥ 5 (`candidate_is_valid`) | 1980 étiquettes = 1980 plans |
| Audit des cycles courts | C ∈ {20, 25, 30, 35}, mêmes parts et décalages | — | g ≥ 5 | 220 étiquettes, 208 admissibles, 195 plans réalisés |
| Audit plancher (A002 R2) | C ∈ {16, 17, 18, 19} ; Δ ∈ {0, 5, 10, 15} | — | g ≥ 5 | 68 étiquettes, 40 plans, 200 exécutions |
| Classement grossier combiné | 1980 + 208 + 68 étiquettes, réduites aux plans réalisés | — | — | top 5 plans réalisés |
| Fin (A002 R3) | autour de **chaque** étiquette grossière (alias) de chacun des 5 gagnants : C ± 10 pas 5 (coupé à [16, 140]), part ± 0,050 pas 0,025 dans [0,25 ; 0,80], Δ ± 10 pas 1 (mod C) ; union dédupliquée par plan réalisé | — | g ≥ 5 | top 10 sur la conception |
| Validation | les 10 finalistes sur 2101–2105, uniquement à partir des exécutions de l'Amendement 002 | — | — | sélection |

### 2.3 Règles de sélection, de validité et de départage

* **Identité d'un candidat (A002 R1) :** le plan réalisé (C, g_H, g_V, Δ mod C). Les verts sont arrondis à la demie supérieure : g_H = round_half_up(part × (C − 6)), g_V = C − 6 − g_H. Les étiquettes d'un même plan doivent concorder graine par graine à 1e-12 près, faute de quoi l'étape s'arrête.
* **Départage sans étiquette :** chaque plan porte un nom canonique, la plus petite part qui donne son g_H. L'ordre des noms canoniques est exactement celui des clés réalisées. Les départages figés lisent donc le plan, quel que soit l'alias simulé, et le pilote le vérifie à chaque classement.
* **Classement :** `rank_by_design`, par J moyen sur 5 graines puis par la clé.
* **Sélection :** `select_timing_plan`, par J moyen, puis perte de temps moyenne, puis cycle le plus court, puis clé réalisée.
* **Validité :** un candidat n'est valide que si chacune de ses 5 exécutions est `CLEARED`, avec `J_primary_valid` et J et perte de temps finis. Sinon il est exclu ; aucun J n'est imputé.
* **Échecs d'évacuation (A002 R4) :** chaque échec reçoit un marqueur de résultat scellé et n'est jamais re-simulé.
* **Calcul exact de J :** `metrics.scheduled_demand_metrics` donne J_primary = Σ (waitingTime + departDelay) / 2800, sur les 2800 véhicules programmés, lus dans `tripinfo.xml`. J n'est valide que si l'exécution est `CLEARED`, sans tripinfo manquant, sans issue exceptionnelle et avec tous les véhicules terminés. Ce n'est ni J_legacy, ni l'attente moyenne affichée par SUMO.

### 2.4 Écarts par rapport à la procédure telle qu'elle avait été résumée

Le résumé était : grille grossière 40–140 ; extension aux cycles courts ; audit plancher 16–19 ; recherche fine sur une union d'alias ; validation. Il est exact dans ses grandes lignes, avec quatre précisions :

1. **L'« extension aux cycles courts » n'était pas adaptative.** C'était un audit séparé, sur un ensemble fixe de cycles {20, 25, 30, 35}, dans sa propre racine (`…_boundary_audit_20260920`), avec les parts et décalages du générateur figé.
2. **L'unité de classement est le plan réalisé, pas l'étiquette.** 13 groupes d'alias existent dans 1980 + 208, et 41 dans la grille combinée. Les départages passent par le nom canonique.
3. **Les exécutions grossières et fines antérieures ont été réutilisées après vérification.** Elles n'ont pas été re-simulées. Une exécution est réutilisée si elle passe la complétude figée et le manifeste d'exécution, avec une pile logicielle unique égale à la pile courante.
4. **La validation n'a utilisé que les exécutions propres à l'Amendement 002.** Aucun résultat de validation à C = 40 de l'original n'y est entré.

## 3. Nouvelle recherche : tout vert ≥ 7 s

**Seul changement.** Le prédicat d'admissibilité devient g_H ≥ 7 et g_V ≥ 7. Le réseau, la demande, les jaunes de 3 s, l'exécuteur, les conditions initiales, les métriques et toutes les règles du §2 sont inchangés. Les générateurs sont ceux du code figé et d'A002, avec le seuil en paramètre. Avec un seuil de 5, l'outil redonne exactement les grilles et les voisinages d'A002 et du code figé (testé).

**Cycle minimal structurel :** 7 + 3 + 7 + 3 = 20 s.

| Étape | Domaine min7 | Comptes |
|---|---|---|
| Grossier, C 40–140 | grille d'origine filtrée par g ≥ 7 | 1980 étiquettes = 1980 plans (aucune n'est rejetée) |
| Grossier, cycles courts | C ∈ {20, 25, 30, 35}, parts 0,30…0,75, Δ = 0, 5, …, C−5 | 220 → 163 étiquettes admissibles, 158 plans |
| — dont C = 20 (borne) | seuls les verts (7, 7) ; Δ ∈ {0, 5, 10, 15} | 4 plans |
| — C = 25 / 30 / 35 | | 35 / 54 / 70 étiquettes ; 30 / 54 / 70 plans |
| Bande plancher | [20, 20) | **vide** : le minimum structurel est le premier cycle de la grille |
| Grossier combiné | 2143 étiquettes | **2138 plans × 5 = 10 690 exécutions, toutes déjà faites** (min7 ⊂ grilles à 5 s) ; réutilisées après vérification ; **0 nouvelle** |
| Contrôle de déterminisme | les 5 gagnants re-simulés sur 2001–2005 dans la nouvelle racine ; toutes les sorties simulées identiques à 1e-12, sinon arrêt | 25 exécutions |
| Fin | règle figée autour de chaque alias des 5 gagnants min7, cycles coupés à [20, 140], filtre g ≥ 7 ; plans déjà évalués (grossier, fin d'origine, fin A002) réutilisés | **exact après `grossier`** ; borne a priori ≤ 2475 nouveaux plans (12 375 exécutions) ; par cycle des gagnants : C 20 → ≤ 1920, C 25 → ≤ 5325, C 30 → ≤ 6500, C 35 → ≤ 9125, C ≥ 40 → ≤ 12 375 exécutions |
| Validation | top 10 sur 2101–2105, exécutions neuves de la nouvelle racine | 50 exécutions |
| Sélection | `select_timing_plan` (J, perte de temps, cycle, clé réalisée) | 1 plan, scellé avec ses paramètres, ses contraintes actives et ses empreintes |

**Ordre de lecture des résultats.** Le pilote calcule et affiche le nombre exact de nouvelles exécutions fines avant d'en lancer une seule. L'étape `fin` n'accepte que l'empreinte de l'ordre grossier affichée ; elle revérifie alors l'espace disque sur ce nombre exact. Ces bornes sont des maxima théoriques : des gagnants de même cycle et de décalages voisins se recouvrent largement. Dans le monde de test simulé, 5 gagnants (C 20, 25 et 40) donnaient 164 nouveaux plans, soit 820 exécutions.

## 4. Données : réutilisation explicite

* **Conception 2001–2005 et validation 2101–2105 :** ce sont les groupes de la recherche d'origine. Ils sont réutilisés pour que seule la contrainte change. Ce sont des données de développement connues : la sélection min7 **n'est pas une validation indépendante**.
* **Aucune autre graine n'est nécessaire.** Il existe une seule raison technique qui empêcherait la réutilisation : une pile logicielle (python, numpy, pytorch, SUMO) différente de celle des exécutions réutilisées. Dans ce cas `plan` l'affiche et `preparer` refuse. Re-simuler les 10 690 exécutions grossières serait alors une décision à prendre explicitement ; elle ne fait pas partie de ce plan et n'est jamais substituée en silence.
* **9301–9305 n'interviennent ni dans l'optimisation ni dans la sélection :**
  * la famille `development` est refusée par `search.assert_family_allowed` à chaque exécution de recherche (testé) ;
  * leurs manifestes ne sont générés qu'à `preparer-comparaison` ;
  * `preparer-comparaison` exige le plan min7 déjà scellé, dont l'empreinte entre dans l'ordre de comparaison.

## 5. Comparaison de développement (9301–9305)

**Cellules.** 60 évaluations, chacune enregistrée une seule fois.

| Bras | Contenu | Évaluations |
|---|---|---|
| A | ancien plan (19, 577, 9), relu dans le gel amendé, inchangé, exécuté par `run_baseline` figé | 5 |
| B | nouveau plan min7 scellé, exécuté de la même façon | 5 |
| C | les 10 politiques QMIX historiques de `selection_records.json` (graines 101–110, checkpoints sélectionnés), dont le SHA-256 est vérifié puis la copie revérifiée ; évaluateur figé `evaluate_checkpoint.py` (`development_evaluation`, journaux complets, `subscription`) ; sans protection | 50 |

**Pilotes protégés.** Ils sont **lus**, jamais réévalués, dans `D:\QMIX_Results\protected_pilot_2026-10-24`. Les points t250000 et t360000 des trois pilotes (qmix, vdn et idqn, graine 201) sont présentés tous les deux ; aucun n'est choisi après coup.

**Mêmes demandes partout.** Les manifestes 9301–9305 des pilotes doivent être identiques octet pour octet aux nouveaux (csv et rou.xml), sinon `preparer-comparaison` s'arrête.

**Contrôle de J.** Pour chaque cellule et chaque résultat de pilote, la synthèse recalcule J à partir de `tripinfo.xml`. Elle refuse de s'écrire en cas d'incohérence au-delà de 1e-9 ou de cellule manquante.

**Échecs.** Un échec d'évacuation est un résultat. Il apparaît comme tel, son J est vide et il n'est jamais imputé. Une cellule déjà enregistrée n'est jamais relancée. Seul un plantage avant tout résultat (aucune métrique) est relançable.

**Contenu de la synthèse :**

* tableau par trafic ;
* moyennes par bras et par modèle, en précisant le nombre de J valides ;
* écarts appariés B − A par trafic et leur moyenne ;
* QMIX historique par modèle et regroupé ;
* pilotes par méthode et par checkpoint.

## 6. Interprétation et limites

* **Le seuil de 7 s.** Le vert minimal de 7 s est un paramètre d'étude fixé pour cette expérience. Aucune justification normative ou piétonne n'est revendiquée.
* **Ce que mesure chaque plan fixe.** L'ancien plan répond à la comparaison avec la référence existante. Le nouveau répond à la comparaison sous une contrainte commune.
* **Pas d'appariement par graine.** Les 10 politiques QMIX historiques et le pilote unique ne sont pas appariés par graine d'entraînement. La comparaison est descriptive : elle ne permet d'attribuer un écart ni au seul réentraînement, ni au seul vert minimal.
* **Les 50 évaluations historiques** sont 10 modèles × 5 trafics, pas 50 modèles indépendants.
* **Aucun paramètre n'est modifié selon les performances observées.** Les grilles, les seuils, les graines, les règles et les marges sont fixés dans `plan.json` avant toute exécution ; l'empreinte du plan est revérifiée à chaque étape.

## 7. Durées et stockage

Les estimations de `plan` utilisent `RACINE\checks\measure.json`, mesuré par `sumo_checks_min7.py` **sur la machine qui exécutera**. Les valeurs mesurées dans le conteneur cloud de développement ne sont que des ordres de grandeur. Pour mémoire, l'entraînement QMIX projeté à environ 2,5 h dans le cloud a réellement duré environ 7 h en local. Le CMD fait donc mesurer localement avant `preparer`, qui refuse sans mesure locale.
