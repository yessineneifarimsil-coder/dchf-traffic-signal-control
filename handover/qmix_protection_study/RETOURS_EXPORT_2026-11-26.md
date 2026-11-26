# RETOURS — export public de B (2026-11-26)

**Ce qui est livré ici, ce sont des outils, pas les fichiers de données.** BCONF et D: ne sont pas accessibles depuis ce conteneur. `B_episodes.csv`, les comparaisons, `search_counts.csv` et le ZIP d'export sont produits sous Windows par `EXPORT_B.cmd` (RUNBOOK_B, étape 11). Ce qui suit vient de la lecture du code ; les fichiers figés lus sont ceux de 8c14f32 et de 2467ddd.

Rien de scellé n'a changé : `b_runner.py`, les évaluateurs, `ETAPES.cmd`, le plan, les marges et le module statistique. Un test compare les empreintes à celles de 2467ddd.

## 1.1 Où l'analyse lit ses valeurs

- **Identité de la cellule :** `<BCONF>/plan.json`, champ `jobs`, construit par `b_runner.build_jobs` (l. 275–296).
  - Cellule apprise : profil, graine, modèle, méthode, bras, `checkpoint_sha256`, dossier.
  - Comparateur : `spec`, `spec_sha256`, `labels`. Un dossier peut porter plusieurs étiquettes, si les spécifications sont identiques.
- **État :** `b_runner.classify` (l. 587–615).
- **Valeurs :** `<BCONF>/<cellule>/cell_summary.json`.
  - Il est écrit par `finalize_cell` (l. 629–649) à partir de `robustness_analysis.cell_metrics`.
  - L'analyse le lit dans `b_runner.cell_rows` (l. 970–1000), après la relecture des traces gzip (`recheck_cell`).
  - `cell_rows` transmet à `confirmation_analysis.analyse` les champs `J_primary_s` (en `repr`), `status`, `open_wait_at_end_s` (vide si `None`), etc.
- **Marges :** `<BCONF>/margins.json`, avec pour chaque profil la J de validation, δ et le comparateur principal. Il est scellé par `freeze.json`.
- **Toutes les colonnes demandées existent dans `cell_summary.json`.** `interventions_*` et `sumo_mismatch_s` ne concernent que les bras appris ; ils sont vides pour les comparateurs.

## 1.3 Graine du bootstrap

- `confirmation_analysis.py` (l. 157, 160, 336, 338) appelle `paired_crossed_bootstrap` **sans** `rng_seed`.
- La graine est donc la valeur par défaut, `BOOTSTRAP_RNG_NAMESPACE = 0x53544154` (1398030676), définie dans `statistics.py`, ligne 78.
- Le générateur est `PCG64(SeedSequence([rng_seed, lignes, colonnes]))`, dans `statistics.py`, lignes 445–447.
- **Cette graine n'est pas écrite dans `results.json` :** elle est fixée par le module scellé.
- Les intervalles de décision et à 95 % sont deux appels distincts, avec la même graine.

## 1.6 Ce que partagent deux méthodes portant le même numéro de graine

Code d'entraînement figé `QMIX_Traffic_Coordination` :
- `rng.py`, lignes 13–45 : les espaces de noms dépendent de la graine, **jamais de la méthode** ;
- `models.py`, lignes 94–110 ;
- `training.py`, lignes 125–126 et 141–145 ;
- `replay.py`, ligne 69.

**Partagé :**
- les **mêmes réseaux locaux initiaux** J1 et J2 ;
- les **mêmes tirages d'exploration** : seuil et action candidate, deux par agent et par décision, tirés même quand l'action gloutonne est jouée ;
- le **même flux de tirage du replay**, dont les indices ne dépendent que de la taille du tampon ;
- au k-ième épisode, le **même trafic et la même graine SUMO** ;
- la même graine Python/PyTorch.

**Non partagé :**
- le mélangeur de QMIX, qui a sa propre graine ;
- les actions, les trajectoires et le contenu du replay ;
- l'indice d'épisode à transition égale, car les épisodes finissent à l'évacuation.

**Que les 30 checkpoints de B viennent de ce code n'est pas vérifié ici :** `training_facts.json` rapporte les champs `source` du plan de robustesse.

## 3.1 Réseau (copie figée, `corridor_2x2.net.xml`, SHA-256 `3f4449c4…`)

**À reconfirmer sous Windows**, où `network_facts.json` lit le fichier réellement chargé par B.
- 14 arêtes, 2 voies chacune, 13,89 m/s partout.
- Longueur des voies :

  | Arêtes | Longueur |
  |---|---|
  | E0, E2, -E0, -E2 | 289,6 m |
  | E4–E7 et leurs inverses | 189,6 m |
  | E1, -E1 (entre J1 et J2) | 279,2 m |

- J1 et J2 sont à 300 m l'un de l'autre. Le stockage dérivé sur E1 et -E1 est de 37 véhicules par voie, à 5 m de longueur plus 2,5 m d'écart.
- Aucun détecteur n'est défini dans le réseau. L'actionné utilise une zone virtuelle sur les `zone_m` derniers mètres de chaque voie entrante de la phase verte (`controllers.py`, l. 10–12 et 87–93), avec les longueurs de la configuration. Les `zone_m` de B sont lus dans `plan.json`.

## 3.2 Entraînement (code figé ; chaque valeur citée avec fichier et ligne dans `training_facts.json`)

- **Optimiseur :** Adam (`learner.py`, l. 55), taux d'apprentissage 0,0005.
  - Ses autres paramètres ne sont pas fixés dans le code : ce sont les valeurs par défaut de PyTorch.
  - Perte : Huber (SmoothL1, β = 1) ; écrêtage des gradients à 10 (norme L2) ; γ = 0,99 par pas de 5 s ; Double DQN.
- **Calendrier :**
  - budget de 360 000 transitions ;
  - préchauffage de 5 000 ;
  - une mise à jour par transition au-delà, soit 355 000 au total ;
  - lot de 256, replay de 200 000 ;
  - copie de la cible toutes les 500 mises à jour ;
  - ε de 1 à 0,05 sur 250 000 transitions ;
  - 14 checkpoints, de 50 000 à 360 000.
- **Sélection d'un checkpoint (`statistics.select_checkpoint`) :**
  - les 14 checkpoints, exactement une fois chacun, sur la famille `learner_validation` et les graines 2201–2205 ;
  - choix par J moyen minimal, puis temps perdu minimal, puis checkpoint le plus précoce.
- **Portes d'éligibilité :** `training_seed_succeeded` et les 7 portes de validité d'une exécution (`validity.GATE_NAMES`).
- **Nombre d'épisodes par graine de validation : non disponible** dans le dépôt figé, qui ne contient pas l'appelant de `select_checkpoint`. `training_facts.py` le cherche sous Windows dans le dépôt protégé.
- **Journaux de validation par checkpoint :** recherchés sous Windows, à côté des sources des checkpoints. S'ils sont absents, c'est écrit « non disponible ».

## Partie 2 (campagne A)

Les chiffres (≈ 34 500 tâches, ≈ 29 785 dossiers, 4 685 réutilisations en fine-min7, 30 en validation) **ne peuvent être confirmés ici** : les ordres coarse et fine ne sont pas dans la copie reçue. `search_counts.py` les compte sous Windows à partir des identités de cellules (profil, trafic, SHA-256 de la spécification, mode) et des dossiers réellement présents.

## Écarts par rapport à la consigne

- `reestimate_B.py` lit ses valeurs dans le seul `B_episodes.csv`. Il a aussi besoin de `B_margins.json`, copie conforme de `margins.json`, et du module statistique figé, qu'il importe.
- Quatre colonnes sont ajoutées à `B_episodes.csv` : `cell_state`, `comparator_labels`, `comparator_variant` et `model_tag`.
- Le ZIP est écrit dans le dossier d'export ; il en contient tout le reste.
