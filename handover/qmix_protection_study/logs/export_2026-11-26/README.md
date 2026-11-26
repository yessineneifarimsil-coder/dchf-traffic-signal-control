# Contrôles des outils d'export (2026-11-26)

Conteneur Linux, Python 3.11, numpy 2.4.6. **Ni BCONF ni D: ne sont accessibles ici** : les outils sont testés sur la fixture figée de `test_b_runner`, qui comprend 2 470 cellules synthétiques, 30 échecs dans les bras sans protection et l'analyse figée réelle avec 1 000 réplicats.

| Fichier | Résultat |
|---|---|
| `unittest_all_crlf.log` | `Ran 216 tests`, 3 erreurs : les 2 tests du paquet protégé absent, plus `test_network_facts_from_the_frozen_network`. Ce dernier échouait parce que la copie CRLF simulée n'a pas de fichier réseau ; il est désormais **sauté** dans ce cas (`OK (skipped=1)`), et passe sur la copie figée complète (`OK`) |

Ce qui est vérifié sur la fixture :
- `B_episodes.csv` : 2 470 lignes, 30 échecs scientifiques, 1 100 évaluations protégées sans échec ;
- J vide exactement pour les cellules non évacuées ;
- BCONF inchangé, octet pour octet ;
- les 12 décisions de `decisions.csv` figé retrouvées par `reestimate_B.py`, avec des nombres égaux ;
- un J modifié est signalé (`DIFFERENCES FOUND`), sans être corrigé ;
- les sensibilités sont marquées non décisionnelles ;
- `search_counts` : réutilisations, répétitions, conflits et orphelins ;
- `network_facts` et `training_facts` sur le dépôt figé ;
- remplacement des chemins personnels ;
- `check_export`, `finalize_export`, `EXPORT_B.cmd` (CRLF, `exit /b`).
