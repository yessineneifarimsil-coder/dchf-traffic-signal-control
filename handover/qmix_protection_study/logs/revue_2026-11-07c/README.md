# Journaux du 2026-11-07, troisième partie : codes de sortie d'`ETAPES.cmd`, `ROB`, résultats Windows

| Fichier | Contenu |
|---|---|
| `unittest_all_*.log` | Suite complète : 80 tests, OK. Avec le code figé, 3 tests sont ignorés (ils exigent `QMIX_PROTECTED`) ; sans lui, 27. |
| `test_etapes_cmd_on_45b1cdb_version.log` | Le test statique appliqué à l'`ETAPES.cmd` de 45b1cdb donne 4 échecs et 1 erreur : il détecte le défaut signalé sous Windows. |
| `etapes_harness_wine.log` | `verify_etapes_cmd.cmd` sous Wine : 149/149. **Ce n'est pas une preuve** : la forme fautive passait aussi sous Wine. À relancer sous Windows. |
| `vermin.log`, `pyflakes.log` | Compatibilité Python 3.7 et analyse statique |

Les résultats Windows reçus sont dans `analysis/` (cp_robustness, guarantee_diagnostic, j_cycle, mp_check_robustness.json) et dans `logs/windows_2026-11-07/`. La confrontation 35/17 se trouve dans `analysis/guarantee_diagnostic/confrontation.json`.
