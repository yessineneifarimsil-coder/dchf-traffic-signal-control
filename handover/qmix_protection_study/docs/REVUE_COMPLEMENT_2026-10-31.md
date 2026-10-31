# Complément de revue (2026-10-31)

## 1. `ETAPES.cmd` : dispatch et codes de sortie (vérification, sans modification)

**`ETAPES.cmd` n'a pas été modifié.** Aucun défaut de dispatch n'est retenu.

**Outil.** `tools/etapes_check/verify_etapes_cmd.cmd` travaille sur une copie temporaire de l'étude. Chaque script appelé par une étape y est remplacé par `stub.py`, qui enregistre son appel et sort avec le code `FAKE_RC`. Les tests sont remplacés par `test_stub.py`, conda par une commande sans effet. Aucune simulation, aucune lecture de D:.

**Exécution dans l'environnement de revue (Wine 9.0 sous Linux) : 65 contrôles réussis, 0 échec** (`logs/revue_2026-10-31/verify_etapes_cmd_wine.log`).

Deux comportements de `cmd` sous Wine diffèrent de Windows :
- `call` d'un fichier batch ne renvoie pas le code de `exit /b` ;
- `call X || ...` déclenche la branche `||` même quand X renvoie 0.

Ce run a donc été fait :
- avec `ETAPES_CHECK_UNDER_WINE=1`, qui ne garde que les contrôles par processus `cmd /c` ;
- sur une copie d'`ETAPES.cmd` dont la seule ligne d'activation conda était neutralisée ;
- avec un `python.exe` de substitution compilé pour Wine, qui imite `stub.py`.

Ce sont des éléments de preuve, pas la preuve sous Windows.

**Constats :**

| Point | Résultat |
|---|---|
| Dispatch | Chacune des 15 étapes séquentielles appelle le bon script avec les bons arguments (y compris `--approved-plan` pour les `prepare`). |
| Codes de sortie séquentiels | Le code du script remonte tel quel par `cmd /c ETAPES.cmd <étape>` (0 et 5) ; `tests` renvoie 1 si un test échoue. |
| Étape inconnue | Code 2. |
| Exécutions parallèles (`ablation-run`, `robustness-run`) | Les 4 workers démarrent (shards 0/4 à 3/4), chacun avec son journal `logs\*_shardN.log`. **Le lanceur renvoie 0 même si les workers sortent en erreur (5)** : `start` n'attend pas les workers. Leurs codes ne remontent donc pas. Le contrôle de complétude passe par `*-progress` (code 3 tant qu'une cellule manque, code transmis par `ETAPES.cmd`), et les causes se lisent dans les journaux. |
| Non couvert par l'outil | L'étape `latex`, qui enchaîne plusieurs commandes. Son code de sortie est celui du dernier `cd ..` : un échec de compilation n'y est pas visible. C'est un constat de lecture, sans modification. |
| À confirmer sous Windows | Les contrôles par `call` et l'échec d'activation conda (code 2 attendu) : lancer `tools\etapes_check\verify_etapes_cmd.cmd` dans l'invite `traffic_rl`, sans variable `ETAPES_CHECK_UNDER_WINE`. |

## 2. Conclusions reformulées

Manuscrit, bilan, rapport d'ablation, plan de campagne et revue du 2026-10-30.

**Comparaison sous contrainte.** Elle est présentée comme **asymétrique** :
- un plan fixe **réoptimisé** pour le vert minimal de 7 s ;
- face aux politiques **historiques**, entraînées sans contrainte et **contraintes seulement à l'évaluation, sans réentraînement** ;
- 0 de leurs 299 évaluations évacuées ne bat ce plan, et 1 échoue.

**Pilotes entraînés avec les deux protections.** Une graine par méthode ; J moyen de 4,32 à 5,48 s, au-dessus des deux plans fixes. Ils sont présentés comme un **signal exploratoire défavorable**, sans prédiction sur la réussite ou l'échec d'une campagne complète.

**Décision sur de nouveaux entraînements :** après la validation de robustesse et la lecture intégrale des travaux proches. Aucune option n'est privilégiée.

## 3. En attente

Les « points 2 à 4 » à corriger avec tests de régression ne figuraient pas dans les éléments reçus pour cette revue. Leur correction sera faite dès réception de la liste. Le package corrigé sera livré ensuite, avant le lancement de la robustesse.
