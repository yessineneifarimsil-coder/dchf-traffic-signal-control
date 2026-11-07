# Journaux du 2026-11-07, deuxième partie : application des décisions

Environnement de revue : Linux, Python 3.11, SUMO 1.28. Le code figé 8c14f32 est présent ; `QMIX_PROTECTED` ne l'est pas.

| Fichier | Contenu |
|---|---|
| `check_r0_demand_cloud.json` | Demande R0 face à la demande de qualification : verdict IDENTICAL_LAW, aucun écart |
| `check_statistics_frozen_file_refused_cloud.json` | L'outil de vérification d'A004 refuse le fichier statistics-1.1 du code figé (hash `ed133bb2…` ≠ `8b6413a9…`). statistics-1.2 n'est pas disponible ici. |
| `unittest_all_without_frozen.log`, `unittest_all_with_frozen_code.log` | Suite complète : 74 tests, OK. Avec le code figé, 3 tests sont ignorés (ils exigent `QMIX_PROTECTED`) ; sans lui, 27. |
| `vermin.log`, `pyflakes.log` | Compatibilité Python 3.7 et analyse statique |
| `etapes_harness_wine.log` | Vérification d'`ETAPES.cmd` sous Wine : 138 contrôles réussis, sans les contrôles CALL et conda |

**Non reçu :** les résultats des analyses sans risque et de `comparators-measure` annoncés comme joints.
