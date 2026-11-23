# Contrôles de la finalisation de f61e030 (2026-11-23)

**Environnement.** Conteneur Linux : Python 3.11.17, numpy 2.4.6, SUMO 1.28.0 ; code figé 8c14f32 (`statistics.py` = `ed133bb2…`). **Le paquet protégé `adaptive_qmix_protected` est absent.** Il n'y a ni Windows, ni D:.

| Contrôle | Journal | Résultat observé |
|---|---|---|
| Suite complète `python -B -m unittest discover -s tests -v` | `unittest_all.log` | 172 tests : **170 réussis, 0 échec, 0 sauté, 2 erreurs**. Les 2 erreurs (`test_ablation_metrics.CounterReconstruction.test_equals_protected_service_counters` et `test_robustness.Adapter.test_equivalence_at_2800_and_denominator_otherwise`) sont des **contrôles non réalisés** : il leur manque `adaptive_qmix_protected`. Ils ne sont pas réussis ; ils sont à repasser sous Windows (`ETAPES.cmd tests`) |
| Décompte de B (`b_runner.py plan`) | `b_plan_count.log` | `"runs": 2470`, `"learned": 2200`, `"comparators": 270`. Sélections utilisées par les tests : les sélections réelles scellées de A, plus des doublures pour A-ext et la racine robustesse |
| Résultats de référence de `b-crossed-bootstrap-1` | `stats_reference_results.log` | `REPRODUCED: 74 numbers checked, 0 differences` sous Python 3.11 ici. **La reproduction sous Python 3.7 sur Windows reste à faire** |
| pyflakes | `pyflakes.log` | 4 avertissements « imported but unused », tous des imports de détection de disponibilité (`noqa`) ; aucun autre |
| vermin, cible 3.7 | `vermin.log` | minimum requis : 3.5 |
| `cmd.exe` (harness Windows) | `wine_unavailable.log` | **non réalisé** : Wine plante (code 134). Le total de 355 contrôles est attendu, pas observé |
| CRLF | — | `ETAPES.cmd` et `verify_etapes_cmd.cmd` : fins de ligne CRLF |
| Archive | (rapport de livraison) | ZIP, SHA-256 et manifeste vérifiés après extraction ; voir le fichier `.sha256` livré à côté du ZIP |

**Non lancé** : expériences historiques, A-ext, B. Aucun manifeste de confirmation n'a été généré. B n'est pas gelé.
