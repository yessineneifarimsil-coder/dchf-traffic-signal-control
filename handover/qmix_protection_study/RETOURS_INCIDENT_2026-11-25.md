# RETOURS — incident TraCI de la part 2/4 (2026-11-25)

**B reste gelé** : plan `af3fd986…`, 2 470 tâches. Aucun fichier scellé par `freeze.json` n'a changé : `b_runner.py`, les évaluateurs, `ETAPES.cmd`, le plan, les marges, les graines, le contrôleur, la règle anti-attente, les critères et la statistique sont ceux de 2467ddd. Un test le vérifie, empreinte par empreinte. Rien n'a été supprimé, et aucune cellule terminée n'a été touchée.

## 1. Causes : où la connexion TraCI est ouverte et fermée

La connexion n'est pas ouverte dans le code de B. Elle l'est dans l'environnement figé, qui appelle la bibliothèque TraCI :

| Où | Fichier, lignes | Rôle |
|---|---|---|
| B | `tools/confirmation/b_runner.py` 695–701 (`default_evaluator`), 729–777 (`run`) | appelle l'évaluateur ; **toute** exception est notée `INTERRUPTED` (l. 763–764) et la part passe à la tâche suivante, dans le même processus |
| B | `tools/robustness/evaluate_any.py` 103, 115, 126, 139, 150 ; `comparators/evaluate_comparator.py` 77, 85, 105 | `import traci`, puis le module est passé à l'environnement |
| figé | `adaptive_qmix/environment.py` 92–104 (`reset`) | `self.traci.start(command)` (l. 103), **puis** `self.connection_open = True` (l. 104) |
| figé | `adaptive_qmix/environment.py` 419–422 (`close`) ; `evaluation.py` 144–145 et `baselines/runner.py` 458–459 (`finally: environment.close()`) | ne ferme **que si** `connection_open` est vrai |
| TraCI 1.25 | `traci/main.py` 109–159 (`init`, `start`) ; `traci/connection.py` 72–100 ; `sumolib/miscutils.py` 241–252 | voir (a) et (b) |
| protégé | `adaptive_qmix_protected` (`evaluate_protected`, `ProtectedEnvironment`) | **non lu ici** : ce paquet n'est pas dans la copie de revue. `REPRISE_B.cmd check` vérifie sous Windows que sa voie de démarrage est celle que le garde couvre |

Le code de TraCI lu ici est celui de la 1.25 (roues `traci-1.25.0` et `sumolib-1.25.0`). Pour ces fonctions, il est identique à la 1.28.

**(a) Confirmée.**
- `traci.start` sans port appelle `getFreeSocketPort()` : celle-ci lie un socket au port 0, lit le port choisi par le système (sous Windows, dans la plage dynamique 49152–65535), **ferme le socket**, puis lance SUMO avec `--remote-port`.
- Entre cette fermeture et la liaison par SUMO, le port est libre pour n'importe qui.
- De plus, un port de la plage dynamique peut être attribué au socket client de TraCI lui-même. Le client se connecte alors **à lui-même** et relit sa propre requête `getVersion` : c'est exactement `error('unpack requires a buffer of 3 bytes')`. Je l'ai reproduit ici avec le vrai code de TraCI (`logs/incident_2026-11-25/self_connect_repro.log`).

**(b) Confirmée.**
- `traci.init` enregistre la connexion sous le libellé `'default'` **avant** `getVersion`.
- `traci.start` n'intercepte que `TraCIException`. `struct.error` traverse donc, et le libellé reste enregistré, socket ouvert.
- `connection_open` étant resté faux, l'environnement ne ferme rien.
- Toute tâche suivante du même processus échoue avec `Connection 'default' is already active.` : ce sont les 562 tâches.

**Écart probable de 3 dans votre décompte** (566 interrompues pour 563 dans la part 2). `classify` compte comme « interrupted » une cellule dont le dossier `.tmp` existe. Les 3 cellules en cours dans les parts 0, 1 et 3 apparaissent donc ainsi pendant leur exécution. À confirmer par `ETAPES.cmd b-progress` une fois ces parts terminées : on attend 563 interrompues.

## 2. Changements, fichier par fichier (tous nouveaux)

| Fichier | Contenu |
|---|---|
| `tools/confirmation/traci_guard.py` | démarrage protégé, installé à la place de `traci.start` dans le processus de reprise seulement. Avant chaque démarrage : libère un libellé resté enregistré et termine les SUMO lancés encore vivants. Chaque tentative utilise un port de la plage de la part (21000–21999, 22000–22999, 23000–23999, 24000–24999 : hors plage dynamique), vérifié libre. Même commande SUMO, `--remote-port` ajouté comme le fait TraCI. Le SUMO lancé doit être encore en vie après la poignée de main. Un échec du **démarrage ou de la poignée de main** donne lieu à **au plus 3 nouvelles tentatives**, chacune journalisée dans `BCONF\resume\traci_guard_rNN_wK.jsonl`. Ensuite l'erreur remonte et la cellule est `INTERRUPTED`. Après chaque cellule, quelle qu'en soit l'issue, la connexion restante est retirée et les SUMO restants sont terminés. Une erreur **pendant la simulation** n'est jamais relancée |
| `tools/confirmation/resume_b_runner.py` | lanceur autour de `b_runner.run` figé. `assign` écrit une seule fois `BCONF\resume\assignment_NN.json` : les tâches non terminées, réparties en tourniquet sur 4 processus. `run --worker k` exécute sa liste par `b_runner.run` (mêmes contrôles de gel, même règle de reprise, même journal). `check` et `preflight` refusent tant qu'un processus B ou A-ext tourne (code 3), si le plan, le lanceur ou le garde diffèrent, ou si la voie de démarrage n'est pas couverte |
| `tools/confirmation/verify_finished_b.py` | vérification **en lecture seule** du point 4 (section 3) |
| `REPRISE_B.cmd` | étapes `check`, `verify-finished`, `assign`, `run` (CRLF, `exit /b` en fin de bloc). `ETAPES.cmd` est scellé, d'où ce fichier séparé |
| `tests/test_resume_b.py`, `tests/fake_traci_server.py` | 25 tests (section 5) |

**Point 3.**
- **Ce n'était pas déjà le cas.** `run --shard i/4` répartit **toutes** les tâches selon leur position. Relancer `2/4` remettrait les 563 tâches sur un seul processus, de même que `0/1`. Un test le montre.
- **Le dossier partiel.** Il est remplacé proprement par la règle figée : l'ancien `.tmp` est renommé `<cellule>.incomplete1` (conservé), puis la tâche repart dans un `.tmp` neuf.
- Une seconde interruption est conservée et jamais relancée. Les tentatives de démarrage du garde se font à l'intérieur d'une même exécution : elles ne consomment pas cette reprise unique.

## 3. Point 4 : les cellules terminées ont-elles bien piloté leur propre SUMO ?

**C'est vérifiable avec les données enregistrées.** SUMO écrit en tête de `tripinfo.xml` les options de sa propre ligne de commande ; je l'ai vu sur SUMO 1.28 ici, et pas sous 1.25. `verify_finished_b.py` contrôle, pour chaque cellule terminée :
- que `route-files` est le manifeste de la cellule ;
- que `tripinfo-output` est son propre dossier de travail ;
- que `seed` est la graine SUMO du manifeste ;
- que les identifiants des véhicules sont exactement ceux du manifeste, une fois chacun, au nombre de `scheduled_total` ;
- que `cell_summary.json` donne N et `tripinfo_rows` égaux à ce nombre, sans problème ;
- pour les bras appris, `sumo_mismatch_s` = 0 (concordance des feux) ;
- qu'aucun port n'a servi à deux cellules à des heures qui se chevauchent.

Commande, en lecture seule : `REPRISE_B.cmd verify-finished` (rapport `logs\verify_finished_B.json`). **Si l'en-tête manque sous SUMO 1.25**, la sortie le dit (code 4). Il ne reste alors que la concordance des identifiants, du nombre et des feux, sans preuve par le port.

## 4. Ce qui n'a pas été vérifié ici

- Le paquet protégé (`ProtectedEnvironment`, `evaluate_protected`) : `REPRISE_B.cmd check` le lit sous Windows.
- Le format de l'en-tête de `tripinfo` sous SUMO 1.25.
- La plage dynamique et les plages réservées de cette machine : `check` les lit par `netsh`, en lecture seule.
- Aucun lancement réel de SUMO 1.25 sous Windows.

## 5. Tests

`tests/test_resume_b.py` (25 tests), avec une doublure de TraCI qui reproduit la sémantique de la 1.25, et avec le **vrai** TraCI et un faux serveur quand TraCI est importable :
- l'incident reproduit sans le garde ;
- un `struct.error` au démarrage est nettoyé, puis réessayé sur un autre port, et **la tâche suivante démarre normalement** ;
- 4 échecs donnent l'erreur, sans libellé ni processus restant ; une cellule dont tous les démarrages échouent est `INTERRUPTED` et la suivante se termine ;
- une erreur pendant la simulation : une seule tentative, la cellule `INTERRUPTED` ;
- la répartition sur 4 processus de la seule part 2 ; le refus si un processus B tourne ;
- les cellules terminées, le plan, le gel et les marges inchangés ; les dossiers partiels conservés ;
- les 5 cas du vérificateur ;
- `REPRISE_B.cmd` ;
- les empreintes scellées égales à celles de 2467ddd.

Les ports des tests sont 25000–25999.
