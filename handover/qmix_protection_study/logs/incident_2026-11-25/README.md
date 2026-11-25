# Contrôles de l'incident TraCI (2026-11-25)

Conteneur Linux, Python 3.11.17, traci/sumolib 1.28.0 installés ; roues traci/sumolib 1.25.0 lues en lecture seule (`roues_traci125_sha256.txt`). Pour `connect`, `init`, `start`, `Connection.__init__` et `getFreeSocketPort`, le code de la 1.28 est identique à celui de la 1.25 (vérifié par `diff`).

| Fichier | Contenu | Résultat |
|---|---|---|
| `code_lu_traci125_et_environnement_fige.txt` | extraits de traci 1.25 et de `adaptive_qmix/environment.py` (figé) | causes (a) et (b) |
| `self_connect_repro.py`, `.log` | client TraCI réel connecté à lui-même | `1st start: error('unpack requires a buffer of 3 bytes')`, label encore enregistré, puis `Connection 'default' is already active.` : les deux messages de l'incident |
| `tripinfo_header_sumo128_exemple.xml` | en-tête écrit par SUMO 1.28 avec `--remote-port` | `route-files`, `tripinfo-output`, `remote-port`, `seed`, heure de lancement. Format sous 1.25 **non vérifié** |
| `unittest_all_crlf.log` | suite complète, code figé CRLF | `Ran 208 tests`, `FAILED (errors=2)` : les 2 tests du paquet protégé absent ; les 25 tests de `test_resume_b` passent, dont 3 avec le vrai traci |
| `unittest_all_locale_ascii.log` | même suite, locale C, console ASCII stricte | même résultat |

Note : une première exécution de deux suites **en parallèle** a donné 2 échecs de `RealTraci`. Les deux processus de test utilisaient alors les mêmes plages de ports, en même temps. Le garde a réagi comme prévu : 4 tentatives, l'erreur, aucun libellé ni processus restant. Les tests utilisent désormais une plage à eux (25000–25999).
