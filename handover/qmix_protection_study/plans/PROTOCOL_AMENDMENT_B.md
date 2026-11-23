# Amendement B au plan de confirmation (2026-11-19, complété le 2026-11-23)

**Statut : écrit avant tout trafic de confirmation. B n'est pas gelé.** Aucune graine 8c51–8c60 n'a été générée et aucun manifeste de confirmation n'existe. Aucune exécution B n'a eu lieu.

Ce texte remplace les versions précédentes de l'amendement là où elles se contredisent. Il modifie `plans/PLAN_CONFIRMATION.md` et `tools/confirmation/confirmation_plan.json`. Il ne devient définitif qu'au gel (`ETAPES.cmd b-freeze`), qui n'est possible que dans les conditions de la section 9.

Convention : **vérifié** = contrôlé dans un fichier ou par un test, ici ; **rapporté** = donné par la passation ou par l'utilisateur, non contrôlé ici.

## 1. Méthodes, bras et trafics

| Méthode | Bras | Profils | Rôle |
|---|---|---|---|
| QMIX, VDN (10 + 10 checkpoints) | garantie seule ; sans protection | R0 à R4 | garantie : décisions ; sans protection : descriptif |
| IDQN (10 checkpoints) | garantie seule | R0 seulement | décisions (contrastes avec QMIX et VDN, section 4) |
| IDQN (les mêmes 10) | sans protection | R0 seulement | **descriptif uniquement**, dans aucune décision |
| Comparateurs classiques | — | selon le profil (section 2) | comparateur principal : décisions ; autres : descriptif |

- **Politiques.** Ce sont les 30 politiques du plan de robustesse : 10 QMIX, 10 VDN et 10 IDQN, graines d'entraînement 101 à 110, avec leurs checkpoints déjà sélectionnés. Aucune nouvelle sélection, aucun entraînement. `b-plan` lit les étiquettes et les SHA-256 dans `<racine robustesse>\plan.json`. Il refuse si les étiquettes QMIX/VDN diffèrent de `confirmation_plan.json`, ou s'il n'y a pas exactement 10 IDQN de graines 101 à 110. `b-prepare` refuse si une copie a un autre SHA-256 (testé).
- **Trafics.** Les 50 trafics de confirmation 8051–8060, 8151–8160, 8251–8260, 8351–8360 et 8451–8460 ne sont générés que par `b-prepare`, **après** un gel valide (testé). Les graines 3001–3010, 3101–3120 et 2201–2205 ne sont pas utilisées.

## 2. Comparateurs classiques (B1, B2)

**Comparateur principal.**
- R1–R3 : la sélection scellée de A ou d'A-ext de plus faible J de validation.
  - Le choix est automatique, fait par `choose_primary`, avec le départage préspécifié : oft_g5, oft_min7, actuated_min7, actuated_g5, tod_g5, tod_min7.
  - Il est scellé dans le plan B avant tout trafic de confirmation.
  - Le plan refuse de se construire si une sélection attendue manque.
- R0 et R4 : C19, verts 8/5, décalage 9.

**Valeurs attendues sans A-ext**, vérifiées sur les fichiers de sélection reçus :

| Profil | Comparateur principal | J de validation (s) |
|---|---|---|
| R1 | plan fixe optimisé g5, C25 14/5 D1 | 1,9399 |
| R2 | actionné min7, gap 2, H 60, V 15 | 1,3669 |
| R3 | plans par période g5 | 2,7219 |

**Extension A-ext (B2).** Elle est conservée, séparée de A, avec ses propres racine, plan et empreinte (`plans/PLAN_COMPARATEURS.md` §10) :
- un feu actionné à vert minimal de 5 s sur les deux axes, jaune 3 s, zone 40 m ;
- gap 1, 2 ou 3 s ; vert maximal principal 30, 45 ou 60 s ; vert maximal secondaire 10, 15 ou 25 s, soit 27 réglages sur R1–R3 ;
- conception sur 8c11–8c15 (405 simulations), puis 5 finalistes par profil validés sur 8c21–8c25 (75 simulations), soit 480 au total.

La variante à 7 s de A reste inchangée : ses 8 fichiers de code gardent leur SHA-256 (testé). Le g5 est une **extension des références**, pas une autorité de commande identique à celle des apprenants, dont les verts peuvent finir après 2 s. **A-ext n'a pas été exécutée** : ses commandes sont prêtes et testées sur des doublures.

## 3. Décompte

Le décompte est calculé par le code (`b-plan`), profil par profil. Les spécifications de comparateurs réellement identiques et les dossiers en double sont dédupliqués avant le partage entre processus. Le total n'est pas forcé : il change si les sélections finales changent.

| Profil | QMIX et VDN | IDQN | Comparateurs (spécifications distinctes × 10 trafics) |
|---|---|---|---|
| R0 | 400 | 200 | 3 × 10 = 30 |
| R1 | 400 | 0 | 7 × 10 = 70 |
| R2 | 400 | 0 | 7 × 10 = 70 |
| R3 | 400 | 0 | 7 × 10 = 70 (OFT g5 = OFT min7 = C25 12/7 D0, évalué une fois) |
| R4 | 400 | 0 | 3 × 10 = 30 |
| **Total** | **2000** | **200** | **270** |

**Total : 2470.** Il est vérifié par `b-plan` sur les sélections réelles de A, avec des doublures pour A-ext et la racine robustesse (`logs/revue_2026-11-23/b_plan_stand_in_rob.log`), et testé.

## 4. Critère principal et famille de décisions

**Critère.**
- J, le temps d'attente moyen par véhicule, reste le critère principal. Il n'est jamais imputé quand une exécution ne s'évacue pas.
- Un échec d'évacuation correctement enregistré est une observation terminée, jamais un motif de relance.

**Une seule famille confirmatoire de 12 contrastes.**
- 10 contrastes : QMIX avec garantie et VDN avec garantie, chacun moins le comparateur principal, sur les 5 profils.
- 2 contrastes en R0 : QMIX avec garantie − IDQN avec garantie, et VDN avec garantie − IDQN avec garantie.

**Correction.** Bonferroni pour un risque familial de 5 %. Les 12 intervalles bilatéraux sont au niveau exact 1 − 0,05/12 = 99,5833… % ; c'est vérifié par `check_family`, qui refuse tout autre niveau (testé). L'estimation utilise 10 000 réplicats du bootstrap croisé apparié (section 8). Les intervalles à 95 % servent à la description. Les deux questions sont présentées dans des tableaux séparés, qui affichent la même correction. Cette famille remplace les niveaux de 99,5 % et 97,5 % des versions précédentes.

**Limites du bootstrap.** C'est un intervalle par percentiles qui rééchantillonne indépendamment les graines d'entraînement et les trafics. C'est une approximation, **pas une garantie exacte en petit échantillon** (10 × 10). Les deux facteurs y sont traités comme échangeables, et les cellules manquantes ne peuvent pas être prises en compte.

**Règles de décision**, dans l'ordre préspécifié : échec de desserte ; non estimable ; supérieur au-delà de la marge ; supérieur ; équivalent ; inférieur au-delà de la marge ; inférieur ; non concluant.

**Portée des règles.** Elles s'appliquent aux bras du contraste considéré :
- dans un bras avec garantie du contraste, un échec avec attente ouverte donne « échec de desserte » ;
- tout autre échec qui empêche le contraste complet donne « non estimable » ;
- un échec dans un bras sans protection, descriptif, n'invalide pas un contraste sous garantie (testé).

**IDQN.**
- La décision reste fondée sur J. J n'est pas remplacé par D̄.
- Un descriptif conditionnel est toujours rapporté : la différence de J sur les seules paires où les deux exécutions se sont évacuées, avec son dénominateur. Exclure les échecs peut changer la comparaison.

**Marges.** δ = max(0,05 × J de validation du comparateur principal ; 0,10 s).
- R0 et R4 : δ = 0,138 s, d'après l'ancrage nominal de C19 (J de validation 2,765071 s sur la demande de qualification). **C19 n'a pas été réoptimisé sur R4.**
- Les deux contrastes avec IDQN reprennent la marge nominale de R0, 0,138 s. Elle sert de seuil d'intérêt pratique commun et n'est pas recalculée à partir des résultats de confirmation.

**Interprétation.** QMIX/VDN contre IDQN compare des méthodes complètes sous la protection déclarée : procédure d'entraînement, architecture et garantie ensemble. Ce contraste ne prouve pas, à lui seul, un effet causal de la coordination ou du mélangeur.

## 5. D̄ et effets de la garantie (descriptifs)

**D̄** reste secondaire. Ses moyennes et ses différences sont calculées sur **toutes les paires techniquement valides où il est défini, échecs d'évacuation compris**, et pas seulement sur les exécutions évacuées. Cela vaut aussi pour les 12 contrastes : intervalle à 95 % quand le panneau est complet.

**Effets de la garantie**, rapportés dans B pour chaque profil et chaque méthode (IDQN en R0 seulement), sur les mêmes modèles et les mêmes trafics :
- les interventions pendant la demande et après, par bras ;
- J avec garantie − J sans protection, sur les paires toutes deux évacuées, avec leur nombre ;
- D̄ avec garantie − D̄ sans protection, sur toutes les paires valides ;
- les effectifs présents et attendus, échecs compris.

Une hausse entre deux moyennes calculées sur des ensembles différents d'exécutions évacuées ne constitue pas une pénalité appariée.

**Ce qu'on sait de R0 avant B :**
- **Vérifié** dans `guarantee_diagnostic/interventions.csv` (analyses du 2026-11-07) : les 35 paires IDQN où la garantie seule a augmenté D̄ (définition D2) sont toutes en R1 (17) et en R2 (18), aucune en R0. Les seules interventions de la garantie listées en R0 sont 2 interventions QMIX, toutes deux **après** la demande.
- Ce fichier ne couvre que les exécutions sélectionnées (paires IDQN dégradées, exécutions QMIX où la garantie agit). Que VDN et les autres exécutions IDQN n'aient aucune intervention pendant la demande en R0, avec un ΔD̄ nul et aucune hausse appariée de J, est donc **rapporté**, et non vérifié ici. B le mesurera.
- Le plan ne dit plus que la garantie pénalise IDQN au scénario de référence.

## 6. Statistiques de service

**Effectifs.** Tous les effectifs bruts sont donnés par profil, méthode et bras, avec l'effectif attendu du plan. IDQN n'est attendu qu'en R0, donc son absence ailleurs n'est pas une incomplétude (testé).

**Aucun intervalle binomial n'est calculé sur les cellules regroupées.** Les mêmes modèles sont évalués sur les mêmes trafics.

**Intervalles proposés**, stratifiés par profil :

| Unité | Dénominateur | Hypothèse d'indépendance | Ce que l'intervalle ne dit pas |
|---|---|---|---|
| Modèle | modèles touchés au moins une fois, sur 10 | les graines d'entraînement sont des tirages indépendants de la procédure d'entraînement ; conditionnel aux trafics | ni une probabilité par véhicule, ni une probabilité par exécution |
| Trafic | trafics touchés au moins une fois, sur 10 | les trafics sont des tirages indépendants du générateur du profil ; conditionnel aux modèles | idem |

- Les intervalles sont des Clopper-Pearson exacts. On donne, **séparément**, l'intervalle bilatéral à 95 % et la borne supérieure unilatérale à 95 % : pour 0 sur 10, celle-ci vaut 25,9 %.
- Aucun bootstrap de taux n'est utilisé : un [0 ; 0] après zéro échec n'établit pas un risque nul.
- Tous profils réunis, seuls les effectifs sont donnés, sans intervalle.

## 7. Contrats techniques (défauts corrigés)

**Défauts reproduits dans le code a9640b1, puis corrigés** (`logs/revue_2026-11-23/repro_avant_a9640b1.log` et `repro_apres_correctif.log`) :
- **(a)** `classify` classait « complete » une cellule avec garantie évacuée, de résumé `max_counter_s = 200` et `sumo_mismatch_s = 3` ;
- **(b)** la relecture ne comparait qu'une liste partielle de champs (`RECHECKED`), qui ignorait ces deux champs.

**Correction.**
- La relecture décompresse les traces gzip.
- Elle **recalcule tout le résumé** avec le vrai lecteur (`robustness_analysis.cell_metrics`), le compare **en entier** au résumé enregistré, puis réévalue les contrats sur le résumé recalculé.
- `classify` vérifie les mêmes contrats sur chaque cellule.

| Contrat | Bras concernés |
|---|---|
| Compteur de service ≤ 127 s. C'est une borne du compteur, pas de l'attente cumulée d'un véhicule | bras avec garantie seulement : pas imposé au bras sans protection |
| Aucun écart de feux SUMO (`protection_record.json`) | tous les bras appris |
| Vert réalisé le plus court pendant la demande ≥ le minimum propre au contrôleur | apprenants : 2 s (`executor.switch_new_green_s` de la configuration figée, vérifié) ; actionné min7 : 7 s ; actionné g5 : 5 s ; Max Pressure : 10 s (valeur par défaut de l'exécuteur figé, la configuration n'ayant pas de section `baselines`, vérifié). Plans fixes et par période : verts rapportés, sans contrat, car un premier vert coupé par le décalage ou par un changement de période n'est pas une violation |
| Compteurs enregistrés égaux à leur recalcul ; état de l'exécuteur égal à la phase enregistrée ; N lignes de tripinfo ; J égal à tripinfo | toutes les cellules |
| Champs critiques présents | toutes les cellules |

Les 7 s ne sont pas imposées aux politiques sous garantie seule.

**En cas de violation.**
- La cellule est en échec technique : état `corrupted`, conservée, jamais relancée, signalée « TECHNICAL » par `b-progress`, qui renvoie le code 5. Elle n'est jamais présentée comme un échec scientifique d'évacuation.
- **Toute décision confirmatoire est bloquée.**
- Une analyse sans relecture (`--no-recheck`) n'est qu'un diagnostic, sans décision (testé).

**Tests de régression** (`tests/test_b_runner.py`) :
- compteur au-dessus de la borne dans une cellule évacuée ;
- écart de feux dans chaque bras ;
- champ critique absent ;
- résumé modifié ;
- compteur modifié dans la trace gzip ;
- gzip tronqué ;
- bras sans protection au-dessus de 127 s (valide) ;
- vert minimal selon le contrôleur ;
- échec scientifique conservé sans relance ;
- même échec dans un bras avec garantie, classé violation technique.

## 8. Procédure statistique : ce qui est vérifié, et sa résolution avant le gel

**Rapporté.** `8b6413a9…437a` est `amendment003.protocol_hashes()['statistics_1_2']`, une empreinte de protocole et non le SHA-256 d'un fichier. A003 n'a pas été vu ici.

**Vérifié dans le code que B appelle** (`adaptive_qmix/protocol/statistics.py`, `PROTOCOL_VERSION = "statistics-1.1"`, fichier `ed133bb2…` de la copie figée) :
- chaque réplicat tire **indépendamment, avec remise**, les indices des graines d'entraînement et ceux des trafics, et réévalue toute la matrice échantillonnée ;
- comparateur appris : appariement un à un par graine et par trafic. Comparateur déterministe : une valeur par trafic, diffusée sur les graines ;
- générateur numpy PCG64 initialisé par `SeedSequence([espace de noms, lignes, colonnes])`. Deux contrastes de même forme partagent donc les mêmes tirages ;
- intervalle par percentiles (`numpy.percentile`, interpolation linéaire par défaut) ;
- une valeur non finie est refusée : aucune donnée manquante n'est rééchantillonnée ni imputée.

**Résultats de référence** (`tools/confirmation/stats_reference_results.json`) : des panneaux synthétiques, à comparateur déterministe et appris, aux niveaux 95 % et 1 − 0,05/12, avec 10 000 et 2 000 réplicats.
- Ils ont été calculés ici avec ce fichier (Python 3.11, numpy 2.4.6) et sont reproduits à l'identique : 74 nombres, tolérance 10⁻¹².
- Ils doivent être **reproduits sous Windows** (`b-stats-results`), où la version de numpy diffère.
- Une modification du tirage est détectée (testé).

**Résolution obligatoire avant le gel** (`b-stats-resolve`, ou `b-stats-resolve-12`) :
- **`b-crossed-bootstrap-1`** : la procédure versionnée de B, c'est-à-dire l'implémentation ci-dessus, avec ses résultats de référence reproduits sous Python 3.7 sur la machine du rodage. Elle n'est **pas** étiquetée statistics-1.2.
- **statistics-1.2** : seulement avec les éléments suivants :
  - une inspection d'A003 en lecture seule (`b-stats-inspect` : aucun import, liste des fichiers, présence éventuelle d'un `__pycache__`, code exécuté à l'import, comparaison des manifestes) ;
  - une extraction gardée (`b-stats-extract` : `python -B`, dossier de travail temporaire, instantané du dossier avant et après, qui ne doit pas changer), dont la valeur égale `8b6413a9…` et qui retrouve l'objet de spécification correspondant ;
  - une note de revue indépendante, puisque l'opérateur ne peut pas être relecteur.

  Un nom de fonction ou une empreinte identiques ne suffisent pas.

**Garde-fous.** Le gel refuse une référence non résolue, faite avec un autre module, ou dont le rapport a changé (testé). L'ancien contrôle « facultatif » d'A003 au gel, qui importait le module, est supprimé.

**Le `__pycache__` d'A003.** Il est rapporté qu'un `import amendment003` a été lancé sans `-B` dans `C:\Users\LENOVO\QMIX_A003_P3\a003`. L'existence d'un `__pycache__` et son effet sur les contrôles d'intégrité **ne sont pas établis ici**. `b-stats-inspect` les constate sans rien supprimer, et ne présente pas une date comme la date de création.

## 9. Rodage, gel et exécution

**Rodage (`b-measure`).** 16 exécutions réelles sur graines de **conception** (R0 8011–8012, R1 8111–8112, R3 8311), lancées sur **4 processus**, qui couvrent :
- QMIX, VDN et IDQN, avec et sans garantie ;
- le plan fixe optimisé et C19 ;
- l'actionné min7 et le nouvel actionné g5 ;
- le plan par période et le Max Pressure ;
- pour chacun : compteurs, contrôle des feux, gzip, puis relecture par le vrai lecteur.

Il mesure la durée murale, le débit et le volume par type de contrôleur, et le coût de compression et de relecture.

**Le gel est refusé** (testé) sans :
1. rodage réussi sous Python 3.7 et SUMO 1.25 ;
2. code identique au code rodé : un changement de code scientifique après le rodage invalide celui-ci ;
3. contrôle Windows d'`ETAPES.cmd` affichant « 0 failed » ;
4. tests unitaires affichant « OK » ;
5. référence statistique résolue ;
6. sélections attendues scellées ;
7. espace disque suffisant sur le volume cible.

**Ce que scelle `freeze.json`** : le plan, les marges, les sélections, les checkpoints, le code (`ETAPES.cmd` compris), le module statistique, la résolution statistique et les rapports. Toute étape ultérieure refuse une différence.

**Exécution.**
- `b-run` refuse de démarrer si le volume cible a moins que le besoin restant mesuré plus 4 Go.
- La reprise suit le protocole : une seule relance d'une exécution interrompue ; aucune relance d'une cellule corrompue ou d'un résultat scientifique.
- La durée est estimée depuis le rodage, en version attendue et pessimiste. **Une nuit n'est pas garantie.**

## 10. Conservation

- Aucune donnée de A n'est supprimée : la suppression est désactivée dans le code (testé), et l'audit et les archives vérifiées restent possibles.
- Les dépôts figés, les checkpoints et les résultats de A002, A003, A004, de l'ablation, de la robustesse et des comparateurs A ne sont pas modifiés.
- L'installation se fait dans un nouveau dossier, vérifié par son manifeste (`RUNBOOK_B.md`).
- Aucune mise à jour de `traffic_rl` n'est demandée.
