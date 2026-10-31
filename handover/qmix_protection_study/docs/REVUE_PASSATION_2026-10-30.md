# Revue de passation de l'étude des protections (2026-10-30)

**Objet :** vérification de la livraison `qmix_protection_study_f962478.zip`, produite par une autre session, puis fin des préparations. Aucune simulation n'a été lancée pour cette revue.

**Ce que la revue a eu sous les yeux :** uniquement l'archive. Les résultats bruts de `D:\QMIX_Results\protection_ablation_2026-10-29`, les pilotes et les dossiers min-7 ne sont pas accessibles depuis l'environnement de revue. Les contrôles portent donc sur les **données dérivées** de l'archive : `analysis/ablation/*.csv`, `figures/data/*.csv`. Ils ont été recalculés par des scripts indépendants (`review/`), dont les sorties sont dans `logs/revue_2026-10-30/`.

## 1. Archive et empreintes

| Contrôle | Résultat |
|---|---|
| SHA-256 de l'archive reçue | `956f211a4c2abad3dc86c08b73a2dcdd73acd23b6e4422849f5319bbd02b9a05`, identique à l'empreinte annoncée |
| Manifeste interne (`MANIFEST_SHA256.txt`, commit `f962478`) | 64 fichiers sur 64 présents, avec la taille et l'empreinte annoncées ; aucun fichier hors manifeste, à part le manifeste lui-même |

## 2. Résultats confirmés par recalcul indépendant

**Plan d'expérience :**
- 600 cellules uniques forment la grille complète : 30 modèles (10 par méthode) × 5 trafics (9301–9305) × 4 bras ;
- 50 cellules réutilisées, toutes QMIX sans protection ;
- 450 paires (bras − sans protection), toutes sur le **même modèle et le même trafic**, cohérentes avec `cells.csv` (0 écart sur ΔD et ΔJ) ;
- ΔJ n'est calculé que lorsque les deux évaluations sont évacuées.

**Échecs :**
- 6 échecs d'évacuation, tous conservés, avec J vide ; aucun J imputé ;
- répartition :
  - QMIX graine 101 sur 9305 ;
  - IDQN graine 101 sur 9302, 9303 et 9305 ;
  - IDQN graine 106 sur 9303 ;
  - IDQN graine 101 sur 9304, sous le vert minimal seul.

**Tableau méthode × bras du rapport d'ablation :** retrouvé exactement :
- évacuées, J moyen et effectif, D̄ ;
- interventions de la garantie (2, 0, 11 ; 1, 0, 5 ; toutes après 3 600 s) ;
- interventions du vert minimal ;
- compteur maximal et attente maximale.

**Paires comparables pour J :**

| | garantie | vert minimal | les deux |
|---|---|---|---|
| QMIX | 49 | 49 | 49 |
| VDN | 50 | 50 | 50 |
| IDQN | 46 | 45 | 46 |

**Vert minimal, chiffres retrouvés :**
- QMIX : ΔJ de +1,290 à +2,283 s (49/49 positives) ;
- VDN : ΔJ de +1,203 à +2,296 s (50/50 positives) ;
- IDQN : ΔD 25 positives et 25 négatives, médiane +56,5 véh·s ; médiane de ΔJ −0,061 s sur 45 paires ; perte de temps en baisse dans 41/50 paires.

**Interaction sur J :** nulle dans 47/49 blocs QMIX, 50/50 VDN et 35/45 IDQN. Pour IDQN, on obtient 36/45 à 1e-12 près : un effet d'arrondi flottant sans conséquence.

**Plans fixes (moyennes, `figures/data/fig1`) :** 2,772 s pour l'ancien plan et 3,156 s pour le plan contraint ; les deux concordent avec votre tableau.

**Garantie :**
- 0 intervention pendant la demande sur les 300 évaluations des bras « garantie » et « les deux » ;
- ΔD = 0 dans les 150 paires « garantie » ;
- compteur ≤ 127 s ;
- mais attente maximale d'un véhicule de 169 s, avec 8 évaluations au-dessus de 127 s.

## 3. Les six points demandés

| Point | Constat | Action |
|---|---|---|
| Mêmes modèles et trafics dans les comparaisons | Confirmé : grille complète et paires appariées sur (modèle, trafic). | — |
| Échecs et effectifs conservés | Confirmé dans les données, le rapport, le bilan, la table et les figures (croix et effectifs affichés). | — |
| « Aucune des 300 évaluations sous contrainte ne bat le plan fixe » | **Formulation incorrecte.** 299 des 300 sont évacuées et aucune de ces 299 n'a un J (ni une perte de temps) inférieur au plan contraint. La 300e est un échec, sans J, non comparable. De même, sur les 600 évaluations : 0 sur 594 évacuées sous l'ancien plan, et 6 échecs. Le fichier `fixed_plan_comparison.txt` faisait déjà la distinction (« valid 49/50 »), mais les textes de synthèse non. | Corrigé dans le manuscrit (résumé, § 5.1, § 5.3, discussion), le bilan, le rapport d'ablation et le plan de campagne. |
| Ablation ≠ effet du réentraînement | Respecté dans le rapport, le bilan et le manuscrit (§ 6, limites). | Le résumé précise désormais « to policies trained without them ». Les pilotes sont présentés comme non appariés aux politiques historiques. |
| Borne du compteur ≠ attente totale | Respecté : le manuscrit (§ 3, § 5.3, limites) et le rapport le disent, avec la preuve (169 s). | — |
| Coût de la garantie pendant la demande | Correctement déclaré non évalué (0 intervention pendant la demande). | Le script d'analyse de robustesse affiche « NOT EVALUATED » lorsque c'est encore le cas. |

## 4. Autres corrections

1. **Groupes de trafics du plan contraint.**
   - `RAPPORT_ABLATION.md` affirmait que « le plan d'origine visait 2011–2015 / 2111–2115 », avec un renvoi à `PROTOCOLE_MIN7.md`. C'est faux : le code gelé fixe `benchmark_design` 2001–2005 et `benchmark_validation` 2101–2105 (`baselines/integrity.py`, lignes 51–52), et `PROTOCOLE_MIN7.md` dit la même chose.
   - La phrase a été remplacée et la correction signalée dans le texte.
2. **31 tests min-7.**
   - Le bilan disait ne trouver ce chiffre que dans `controles_cloud/tests_simules.log`.
   - Corrigé : la preuve est votre sortie terminal (« Ran 31 tests in 1548.888s », « OK », code 0), sans fichier journal local conservé. `controles_cloud/tests_simules.log` est le journal des tests exécutés dans l'environnement cloud, pas sur votre machine.
   - La même distinction est faite dans l'annexe du manuscrit.
3. **Réutilisation des 50 évaluations QMIX.**
   - Le manuscrit affirmait que l'évaluateur reproduit « byte for byte » les fichiers gelés. Cette preuve vient d'un contrôle antérieur (S1, `protected_checks_2026-10-24`) dont le journal n'est pas dans l'archive.
   - Le texte le dit désormais, avec une mention « à compléter » : joindre ce journal au paquet de réplication.
4. **Échecs.** « The last vehicle » est devenu « the last one or two vehicles ». IDQN graine 101 sur 9305 laisse deux véhicules, `S1N1_v0298` et `N1S1_v0299`.
5. **Légende de la table 1.** La perte de temps est une moyenne par évaluation sur les véhicules arrivés, moyennée sur les évaluations évacuées. Exemple : IDQN 19,54 s sur 46 évaluations, et 20,38 s si l'on inclut les 4 échecs.
6. **Compilation.** Le PDF a été compilé avec TeX Live sous Linux : 12 pages, aucune référence ni citation indéfinie, 0 avertissement BibTeX, 2 débordements de ligne mineurs. Le README et le bilan ont été mis à jour.

## 5. Éléments encore non vérifiés

| Élément | Raison | Moyen de le vérifier |
|---|---|---|
| Correspondance entre les 600 dossiers bruts et `cells.csv` | Données brutes sur D: inaccessibles. Les contrôles de l'autre session (0 écart de feux SUMO, compteurs reconstruits = compteurs journalisés sur 100/100) sont rapportés mais non refaits. | `ETAPES.cmd ablation-analyse` vers un nouveau dossier de sortie, puis comparaison des `cells.csv` (lecture seule de D:) |
| Empreintes des 30 checkpoints et des manifestes | Fichiers absents de l'archive | Journaux `ablation-plan` sur votre machine |
| Pilotes : QMIX à 360 000 transitions, 4,434 (votre synthèse min-7) ou 4,435 (manuscrit) | Résultats bruts des pilotes absents ; écart d'arrondi probable autour de 4,4345 | Relire les 5 `evaluation_metrics.json` correspondants |
| Contrôle « byte for byte » de l'évaluateur protégé | Journal absent de l'archive | Joindre `protected_checks_2026-10-24` |
| Diagnostic QMIX 101 / 9305 | Les traces sur D: n'ont pas été relues ici. Les éléments présents dans `cells.csv` concordent : véhicule `S2N2_v0299` non arrivé, attente 3 600 s, perte de temps moyenne 11,93 s. | — |
| 2 tests sur 21 | Ils exigent `adaptive_qmix_protected` (commit `3611383`), absent ici. Ils passent sur votre machine (`logs/unittest_final.log`). | `ETAPES.cmd tests` |
| 10 nouveaux tests d'analyse de robustesse | Exécutés seulement sous Python 3.11 ; syntaxe compatible 3.4+ (vermin) | `ETAPES.cmd tests` sous `traffic_rl` |
| Littérature | Aucun texte intégral lu, ni par l'autre session ni ici. Crossref est bloqué depuis cet environnement : les 23 DOI de la bibliographie ont seulement été comparés aux fiches Crossref enregistrées dans l'archive (titres et années concordants). Les 9 références sans DOI ne sont pas vérifiées. | Lecture des textes intégraux (§ 6, P3) |
| Figures | Non régénérées : leurs données sont inchangées et concordent avec `cells.csv`. | `ETAPES.cmd figures` |

## 6. Préparations terminées pendant cette revue

**Script d'analyse de robustesse (`tools/robustness/robustness_analysis.py`) :**
- écrit avant toute simulation de robustesse ;
- il reprend sans modification les définitions de `tools/ablation_metrics.py` ;
- N est lu dans chaque manifeste, jamais fixé à 2 800 ;
- il implémente les critères techniques T1–T5 et les questions S1–S4 du plan ;
- si un critère technique échoue, aucun énoncé scientifique n'est produit ;
- il est appliqué une seule fois, et refuse de tourner s'il diffère de la version enregistrée dans le plan.

**Tests (`tests/test_robustness_analysis.py`) :** 10 tests sur des sorties synthétiques, avec N = 28 et 18 véhicules. Ils couvrent :
- un dénominateur constant détecté ;
- les échecs conservés sans J ;
- le coût « NOT EVALUATED » ;
- l'énoncé de desserte interdit en cas d'échec sous garantie ;
- les violations de contrat et de feux ;
- un compteur incohérent ;
- les cellules manquantes ;
- l'application unique ;
- un manifeste modifié.

**Runner (`robustness_runner.py`) :**
- le plan enregistre l'empreinte du script d'analyse ;
- `prepare` enregistre l'empreinte des manifestes ;
- **toute empreinte de plan affichée avant le 2026-10-30 est caduque.**

**`ETAPES.cmd` :** ajout des étapes `robustness-prepare`, `robustness-run`, `robustness-progress` et `robustness-analyse`.

**Exécution des tests ici :** 21 tests ; 19 réussis, 2 non exécutables faute du module protégé (`logs/revue_2026-10-30/unittest_cloud_py311.log`).

## 7. Suite priorisée (rien n'a été lancé)

| Priorité | Étape | Objectif scientifique | Prérequis | Coût estimé |
|---|---|---|---|---|
| P1 | `ETAPES.cmd tests` sur votre pile | Valider les 21 tests sous Python 3.7, dont les 10 nouveaux | Copier ce dossier | Environ 2 min |
| P2 | Validation de robustesse, 2 375 évaluations | Tester la desserte et la garantie **pendant** la demande, et les défauts latents, sur des trafics jamais vus | P1 ; `robustness-plan`, nouvelle empreinte ; environ 10 Go libres sur D: ; 4 cœurs | Environ 2,2–2,5 h de temps réel sur 4 processus (débit mesuré en ablation : 550 évaluations en 30 min 41 s) et environ 13 h CPU ; davantage si des évaluations échouent (7 200 s simulées chacune) |
| P3 | Lecture intégrale de 6 à 8 travaux proches (PyTSC, RESCO, Ault 2020, Wu 2018, Levin 2020, Raeis 2021, Papoudakis 2021) | Consolider la matrice, l'introduction et la position de la contribution | Accès aux textes | Plusieurs heures de lecture, à faire par vous ou en séance dédiée |
| P4 | Décision de recherche, après P2 **et P3** (précisé le 2026-10-31) | (a) Réentraînement « les deux », 30 entraînements, pour la question H3 (les politiques entraînées sous contrainte atteignent-elles le plan fixe contraint ?). (b) Réorientation vers un article méthodologique à résultat négatif. | P2 analysé. Pour (a) : un `run_kind` de campagne dans `QMIX_PROTECTED` (commit séparé et revu), les trafics finaux 3101–3120 générés après le gel, et environ 45 Go de disque pour 33 Go libres annoncés. | (a) Environ 110–120 h de temps réel (7–7,5 h mesurées par entraînement, 2 en parallèle), plus environ 4–5 h de sélection et environ 2 h de test final. (b) Rédaction. |
| P5 | Test final sur trafics nouveaux | Seule base d'une affirmation confirmatoire | P4 (a) terminé et plan gelé | Environ 2 h |

**Recommandation :** P1 puis P2 avant toute autre décision.

P2 est la seule étape peu coûteuse qui peut changer la conclusion sur la garantie. Si la garantie n'agit toujours pas pendant la demande dans R1, R2 et R4, l'article devra dire que son coût n'a pas pu être mesuré. La décision sur de nouveaux entraînements (P4) ne sera prise qu'après P2 et P3 ; aucune des deux options n'est privilégiée ici.

## 8. Appréciation

**L'ablation est solide dans ses limites déclarées :**
- grille complète et comparaisons appariées ;
- échecs conservés et indicateurs cohérents ;
- les erreurs relevées touchent la formulation, pas les données.

**Contribution défendable aujourd'hui :** une évaluation honnête et un mécanisme de défaillance documenté sur un petit cas.

**À formuler avec précision (2026-10-31) :**
- sous la contrainte de 7 s, le plan fixe a été réoptimisé, tandis que les politiques historiques ont été contraintes seulement à l'évaluation, sans réentraînement : 0 de leurs 299 évaluations évacuées ne bat ce plan, et 1 échoue ;
- les pilotes entraînés avec les protections (une graine par méthode) sont un signal exploratoire défavorable ; ils ne prédisent ni la réussite ni l'échec d'une campagne complète.

**Preuves encore insuffisantes pour une revue de premier quartile** (classement non vérifié) :
- un seul corridor ;
- des trafics de développement déjà vus ;
- des protections ajoutées sans réentraînement ;
- une garantie jamais sollicitée pendant la demande ;
- une littérature lue en résumé seulement.

Aucune publication ne peut être promise.
