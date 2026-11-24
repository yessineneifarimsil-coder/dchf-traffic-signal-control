# Contrôles du 2026-11-24 : retour Windows sur b058301

**Environnement de revue :** conteneur Linux, Python 3.11.17, numpy 2.4.6. **Windows simulé :** copie du code figé où seul `statistics.py` est converti en CRLF (`<scratchpad>/frozen_crlf`). Son SHA-256 brut est `0e43bf5b…`, avec 635 fins de ligne CRLF, exactement comme le checkout Windows rapporté.

| Fichier | Commande | Résultat observé |
|---|---|---|
| `sim_windows_avant_b058301.log` | b058301, `test_b_runner` + `test_stats_reference`, code figé CRLF | `Ran 51 tests`, `FAILED (failures=28, errors=2)` : le motif Windows est reproduit (28 échecs ; 2 des 3 erreurs, voir plus bas) |
| `unittest_all_crlf.log` | copie corrigée, `unittest discover -s tests`, code figé CRLF | `Ran 175 tests`, `FAILED (errors=2)` : les 2 erreurs sont `No module named 'adaptive_qmix_protected'`, un paquet absent ici et dont les tests passent sous Windows |
| `unittest_all_lf.log` | même suite, code figé LF | même résultat : 175 tests, mêmes 2 erreurs |
| `stats_results_crlf.log` | `stats_reference.py results --statistics <figé CRLF>` | `identical to the reference file after CRLF->LF normalisation (635 CRLF line endings; raw SHA-256 0e43bf5b…)` ; `REPRODUCED: module identity OK \| numbers: 74 checked, 0 differing`, code 0 |
| `stats_results_lf.log` | même commande, fichier LF | `byte-identical` ; `REPRODUCED`, code 0 |
| `stats_results_contenu_modifie.log` | fichier CRLF plus une ligne de commentaire | `DIFFERENT: module identity: …` affiché en entier ; `numbers: 74 checked, 0 differing`, code 1 |
| `pyflakes.log`, `vermin.log` | sur les 4 fichiers modifiés | 3 imports de détection de disponibilité (numpy, matplotlib) ; Python 3.5 minimum |

**La troisième erreur Windows** (`test_measure_with_the_planned_parallelism`, `IndexError` dans chaque travailleur) ne se reproduit pas sous Linux, où les processus sont créés par `fork` et héritent du correctif de test. Le test ajouté `test_measure_under_spawn_as_on_windows` force `spawn`, le mode de Windows, et passe ici.

**Ce qui n'a pas été observé :** la nouvelle livraison n'a été lancée ni sous Windows, ni sous Python 3.7 / numpy 1.21.6.
