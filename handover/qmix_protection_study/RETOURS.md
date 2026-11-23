# RETOURS — ce qui manque, ce qui n'a pas été vérifié, ce qui reste à décider (2026-11-19, rectifié le 2026-11-23)

Ce fichier liste tout ce que le travail n'a pas pu établir, conformément à la consigne : « Si quelque chose manque, écris-le dans RETOURS.md. » Rien de ce qui suit n'a été supposé dans le code : chaque point non établi y est soit refusé, soit enregistré tel quel.

**B n'est pas gelé.** Aucune graine de confirmation n'a été générée ni lancée. Le gel définitif reste à faire sous Windows, dans les conditions de `PROTOCOL_AMENDMENT_B.md` section 6.

## 0. Rectificatif du 2026-11-23 : ce qui a été fait

| Point | Fait | Où |
|---|---|---|
| 1. IDQN | 10 checkpoints IDQN historiques (lus dans le plan de robustesse, graines 101–110), garantie seule, R0, 10 trafics : 100 évaluations. Contrastes QMIX − IDQN et VDN − IDQN : effet, procédure, famille F2 à 97,5 % distincte de F1 à 99,5 %, sensibilité à 1 − 0,05/12. Total recompté : **2370** | `PROTOCOL_AMENDMENT_B.md` §1 B3, §3, §4 ; `confirmation_plan.json` `learned_contrasts` ; `confirmation_analysis.learned_contrast` ; tests |
| 2. Conservation | Suppression des données de A désactivée dans le code (refus, test) ; étape `archive-a-delete` retirée ; audit et archives vérifiées conservés ; livraison dans une nouvelle copie versionnée, vérifiable par `tools/verify_manifest.py` | `archive_campaign_A.py`, `ETAPES.cmd`, `RUNBOOK_B.md` étape 0 |
| 3. Service | Tous les effectifs ; plus aucun intervalle sur les évaluations regroupées ; intervalles par modèle et par trafic, avec leurs hypothèses ; borne unilatérale si 0 ; aucun bootstrap de taux | `PROTOCOL_AMENDMENT_B.md` §5 ; `confirmation_analysis.unit_counts` ; `service_counts.csv` |
| 4. Validation et gel | Lecteurs réels testés sur des cellules complètes finalisées en gzip, altérations détectées ; relecture gzip de chaque cellule à l'analyse et au rodage ; rodage réel en parallèle ; gel refusé sans rodage sous Python 3.7 / SUMO 1.25, sans code identique au code rodé, sans rapport Windows « 0 failed », sans tests « OK » | `b_runner.py` (`recheck_cell`, `measure`, `check_freeze_prerequisites`) ; tests `RealReaders`, `Freeze` |
| 5. Coût et formulation | Débit mesuré avec 4 processus (efficacité parallèle) ; estimation attendue et pessimiste ; « une nuit n'est pas garantie » ; actionné g5 présenté comme extension des références, sans prétendre reproduire l'autorité des apprenants (verts possibles de 2 s) | `b_runner.estimate` ; plans ; `RUNBOOK_B.md` |

## 1. Documents et consignes non reçus

1. **`A_comparators_results.md` n'a jamais été reçu.** Seuls `HANDOFF_QMIX_2026-11-15.md` et `comparateurs_resultats.zip` sont arrivés.
   - Les valeurs de A utilisées (J de validation, réglages retenus) ont été lues **dans les fichiers de sélection scellés du zip**, contrôlés contre leur sceau.
   - Le zip est contrôlé égal à l'archive A `24a4f5f6…`. L'empreinte du plan de A est `03af6200…`.
   - Les valeurs attendues (R1 1,940 ; R2 1,367 ; R3 2,722) y sont retrouvées exactement.
2. **La consigne du 2026-11-19 s'arrête à « Inclure en tête : ».** Le contenu demandé pour l'en-tête de `RUNBOOK_B.md` n'est pas connu. J'y ai mis les prérequis et les règles d'arrêt, en le signalant en tête du fichier.
3. **Le paquet A004 n'a pas été vu.** Les 30 politiques (QMIX, VDN, IDQN) sont lues dans le plan de robustesse (`<ROB>\plan.json`, copies dans `<ROB>\checkpoints\`).
   - `b-plan` refuse si les étiquettes QMIX/VDN diffèrent de `confirmation_plan.json`, ou s'il n'y a pas exactement 10 IDQN avec les graines 101–110.
   - `b-prepare` refuse si un SHA-256 diffère.
   - Que ce soient exactement les checkpoints du paquet A004 n'a pas été vérifié ici.
4. **Les étiquettes IDQN ne sont écrites nulle part à la main.** Elles ne sont pas connues ici. Elles sont lues dans le plan de robustesse et figées par l'empreinte du plan B. Le mot « historiques » de la consigne est compris comme « ceux du plan de robustesse ». **À confirmer** : si d'autres checkpoints IDQN sont visés, le dire avant `b-freeze`.

## 2. Référence statistique (à trancher avant `b-freeze`)

5. **statistics-1.2.** D'après la passation, `8b6413a9…437a` est `amendment003.protocol_hashes()['statistics_1_2']`, pas le hash d'un fichier.
   - C'est corrigé (`PROTOCOL_AMENDMENT_B.md` §2).
   - `tools/confirmation/check_statistics.py` reposait sur l'ancienne lecture. Il n'est plus une étape du gel.
6. **amendment003 n'a pas été vu.** On ne sait pas si statistics-1.2 spécifie exactement `paired_crossed_bootstrap` du module figé, utilisé par F1 (comparateur déterministe) et F2 (comparateur appris).
   - **Décision à prendre avant le gel :** confirmer ce module, ou en désigner un autre (`--statistics`).
   - `b-freeze <dossier A003>` enregistre la valeur statistics-1.2, en lecture seule.
7. **Appariement de F2 par numéro de graine.** C'est la convention du module figé pour un comparateur appris : il refuse des graines différentes. Ce numéro ne crée aucun lien causal entre un modèle QMIX et un modèle IDQN. L'intervalle reflète le rééchantillonnage croisé des graines et des trafics. C'est déclaré dans le plan.

## 3. Non vérifié dans cet environnement (Linux, sans Windows)

8. **Aucun accès à Windows ni à D:.** Aucune commande n'a été lancée sur la machine de Yessine.
9. **Le rodage réel sous Python 3.7 / SUMO 1.25 n'a pas pu être fait ici.**
   - Ce conteneur a Python 3.11 et SUMO 1.28. Python 3.7 n'est pas installable ici : `uv` ne le fournit plus, et le téléchargement direct est refusé (404 via le proxy).
   - Le paquet protégé `adaptive_qmix_protected` (garantie, compteurs) n'existe pas ici. Aucune évaluation apprise ni aucun comparateur avec compteurs ne peut donc tourner.
   - **Le rodage se fait sous Windows (`b-measure`, RUNBOOK 3.2).** Le gel le rend obligatoire : il refuse sans rodage réussi sous Python 3.7 / SUMO 1.25, avec exactement le code gelé.
10. **Ce qui a été testé ici :**
    - la logique du runner, avec des évaluateurs factices ;
    - le **lecteur réel** `robustness_analysis.cell_metrics` sur des cellules complètes et cohérentes (fichiers du même format que les évaluateurs), finalisées en gzip puis relues depuis le gzip, avec altérations détectées (`RealReaders`) ;
    - le rodage en parallèle avec 4 processus (évaluateur factice) ;
    - le contrôleur g5 sous SUMO 1.28, sans compteurs (2026-11-19).
11. **Le harness `verify_etapes_cmd.cmd` n'a pas pu tourner ici.** Wine plante dans ce conteneur (`free(): invalid pointer`, même sur `cmd /c echo`).
    - Le contrôle statique `tests/test_etapes_cmd.py` passe.
    - À lancer sous Windows (RUNBOOK 0.3) ; attendu : `319 checks passed, 0 failed`. Ce nombre est calculé, pas observé.
12. **matplotlib dans `traffic_rl` : inconnu.** Sans lui, `b-analyse` produit tout sauf les graphiques en forêt.
13. **Python 3.7 : compatibilité statique seulement.** vermin indique un minimum de 3.5. Les tests doivent repasser sous 3.7.16 (`ETAPES.cmd tests`), ce que le gel exige.
14. **La version de SUMO est lue par `sumo --version`** (PATH, puis `%SUMO_HOME%\bin`). Si elle est introuvable, `environment.sumo` vaut « unknown » et le gel refuse. Il faudra alors mettre SUMO dans le PATH ou définir `SUMO_HOME`.

## 4. Disque et conservation

15. Le 2026-11-15, D: avait 6,8 Go libres. Avant mesure, **B demande environ 12 Go** (environ 8 Go plus 4 Go). Cette livraison ne supprime rien. Si la place manque, mettre la racine B sur un autre disque (`set BCONF=…`, RUNBOOK étape 1), ou attendre une décision explicite sur les données de A.
16. Un zip des runs de conception de A écrit sur D: n'y libère rien tant que rien n'est supprimé. La suppression reste désactivée.

## 5. Défauts de A corrigés dans le nouveau code seulement

Les 8 fichiers de code de A ne sont pas modifiés (SHA-256 du plan de A inchangés, testé).

17. Dossiers en double dans un ordre : A-ext et B les retirent avant le partage entre processus.
18. `report` non réinitialisé dans `finalise` : A-ext le reconstruit à chaque version.
19. `estimate_upper_bound` omettait `robustness-eval` : A-ext compte toutes ses étapes.

## 6. Remarques sur le plan

20. **Recomptage :** 2000 évaluations QMIX/VDN, 100 IDQN, 270 comparateurs, soit **2370**. Calculé par le code et testé.
21. **Sans A-ext, B ne se construit pas** : le contrôle d'intégralité des sélections refuse.
22. **Si l'actionné g5 fait mieux en validation pour un profil, il devient principal**, et δ change en conséquence (règle B1, appliquée avant le gel).
23. **Durée.** Avant mesure, environ 2,4 h sur 4 processus, sur une base d'environ 14,5 s par exécution apprise. C'est une valeur ancienne, mesurée hors parallélisme. La valeur à retenir est celle de `b-plan` après `b-measure`, attendue et pessimiste. **Une nuit n'est pas garantie.**

## 7. Tests exécutés ici

24. **Suite complète** (Python 3.11, SUMO 1.28, module statistique figé `8c14f32`) : 138 tests, dont 136 passent, plus les 2 tests de `tests/test_verify_manifest.py` (OK), écrits pendant ce lancement et passés séparément. Nouveaux ou modifiés : `test_b_runner` 33 (dont `RealReaders` 3), `test_confirmation_analysis` 12, `test_disk` 6, `test_etapes_cmd` 9, `test_aext` 12, `test_verify_manifest` 2.
    - Les 2 erreurs (`test_ablation_metrics.CounterReconstruction`, `test_robustness.Adapter`) demandent le paquet protégé `adaptive_qmix_protected`, absent de ce conteneur. Elles sont identiques sur la version livrée en `42b58f2` : ce sont des limites de l'environnement, pas des régressions.
    - À repasser sous Windows avec `ETAPES.cmd tests`. Le gel l'exige.
25. **`test_b_runner` a tourné sur les vrais fichiers de sélection de A** (`B_TEST_A_SELECTIONS`). Sans cette variable, il utilise une doublure scellée avec les mêmes J de validation.
