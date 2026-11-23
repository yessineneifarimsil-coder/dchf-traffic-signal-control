# RETOURS — vérifié, non vérifié, blocages (version du 2026-11-23, finalisation de f61e030)

**B n'est pas gelé.** Aucune graine de confirmation n'a été lancée et aucun manifeste de confirmation n'a été généré. Aucune donnée n'a été supprimée, aucun dépôt figé ni résultat existant n'a été modifié, aucun entraînement n'a eu lieu.

Le détail des commandes lancées ici se trouve dans `logs/revue_2026-11-23/JOURNAL_CONTROLES.md`.

## 1. Sources

| Source | État |
|---|---|
| `HANDOFF_QMIX_2026-11-15.md` | lu en entier |
| `plans/PROTOCOL_AMENDMENT_B.md`, `plans/PLAN_CONFIRMATION.md`, `confirmation_plan.json`, `RUNBOOK_B.md`, ce fichier | lus, puis réécrits de façon cohérente |
| Fichiers de sélection de A (`comparateurs_resultats.zip`) | lus, chacun contrôlé contre son sceau ; l'archive est égale à `24a4f5f6…` |
| `guarantee_diagnostic/` (analyses du 2026-11-07) | lu (section 2) |
| `A_comparators_results.md` | **jamais reçu.** Les valeurs de A viennent des fichiers de sélection scellés |
| Plan de robustesse (`<ROB>\plan.json`, checkpoints) | **non disponible ici.** Les 30 étiquettes et leurs SHA-256 sont lus sur Windows par `b-plan` et `b-prepare`, qui refusent toute incohérence |
| A003 (`amendment003.py`, dossier `C:\Users\LENOVO\QMIX_A003_P3\a003`) | **non disponible ici** (section 4) |
| Paquet A004 | **non vu** |

## 2. Vérifié ici

- **Les deux défauts du runner** de a9640b1 sont reproduits puis corrigés, preuves avant et après à l'appui :
  - (a) `classify` acceptait une cellule avec garantie à compteur de 200 s et écart SUMO de 3 ;
  - (b) la relecture ignorait ces deux champs.
- Désormais, tout le résumé est recalculé depuis les traces gzip par le vrai lecteur, comparé en entier, et les contrats sont réévalués. Une violation bloque toute décision.
- **Paramètres figés**, lus dans le code :
  - décisions toutes les 5 s, jaune de 3 s, nouveau vert de 2 s (`switch_new_green_s`) : c'est le contrat de vert minimal des apprenants ;
  - Max Pressure : vert minimal de 10 s, valeur par défaut de l'exécuteur.
- **Procédure statistique de B**, lue dans `statistics.py` (statistics-1.1, `ed133bb2…`) : rééchantillonnage croisé indépendant des graines et des trafics, appariement ou diffusion, PCG64 et `SeedSequence`, percentiles, refus des valeurs non finies. Résultats de référence reproduits : 74 nombres.
- **R0 :** les 35 paires IDQN dégradées (D2) sont en R1 (17) et R2 (18), aucune en R0. Les seules interventions de la garantie listées en R0 sont 2 interventions QMIX après la demande.
- **Décompte :** 2470, par le code, sur les sélections réelles de A (avec des doublures pour A-ext et la racine robustesse).
- **Tests :** 167, dont 165 passent. Les 2 erreurs viennent de l'absence du paquet protégé, et sont identiques sur les versions précédentes.
- **Statique :** vermin indique Python 3.5 minimum ; `ETAPES.cmd` est en CRLF, avec 56 étapes (finalisation) et aucune commande de suppression.

## 3. Rapporté, non vérifié ici

- Historique : `8b6413a9…437a` = `amendment003.protocol_hashes()['statistics_1_2']` (passation). Ce label n'est **pas** revendiqué pour B.
- En R0, aucune intervention pendant la demande pour VDN et pour les autres exécutions IDQN, avec un ΔD̄ nul et aucune hausse appariée de J. Le fichier lu ne couvre que les exécutions sélectionnées ; B le mesurera.
- Un `import amendment003` lancé sans `-B` dans le dossier A003, et donc la présence possible d'un `__pycache__`. **Ni son existence, ni sa date, ni son effet ne sont établis ici.** `ETAPES.cmd b-stats-inspect` les constate en lecture seule, sans rien supprimer.
- Que les 30 checkpoints du plan de robustesse soient ceux du paquet A004.

## 4. Non fait, et pourquoi

| Point | Raison | Ce qui le remplace |
|---|---|---|
| Rodage réel sous Python 3.7 / SUMO 1.25 | Python 3.7 n'est pas installable ici (refusé par le proxy) ; SUMO est en 1.28 ; le paquet protégé manque | `b-measure` sous Windows : 16 cellules réelles, tous les chemins. Le gel l'exige |
| Codes de retour sous un vrai `cmd.exe` | Wine plante ici (`free(): invalid pointer`, code 134) | `verify_etapes_cmd.cmd` sous Windows, qui teste par `CALL` et par `cmd /c` les réussites et les échecs. **355 contrôles attendus : total calculé, pas observé.** Le gel exige « 0 failed » |
| A-ext (480 simulations) | Ni D:, ni la pile Windows | Commandes prêtes ; tests sur des doublures ; contrôle de disque ajouté au lancement |
| Équivalence avec statistics-1.2 (historique) | A003 n'est pas disponible ici | Non revendiquée. B utilise `b-crossed-bootstrap-1` (implémentation statistics-1.1). `b-stats-inspect` et `b-stats-extract` restent des diagnostics en lecture seule |
| Audit disque actualisé | Pas d'accès à D: | `ETAPES.cmd disk-audit`. Les 6,8 Go libres du 2026-11-15 sont périmés |

## 5. Blocages et décisions qui restent avant le gel

1. **Procédure statistique retenue : `b-crossed-bootstrap-1`.** Il reste à reproduire ses résultats de référence sous Windows (`b-stats-results` doit afficher `REPRODUCED`), puis à résoudre (`b-stats-resolve`). Si le résultat est `DIFFERENT` (la version de numpy diffère), ne pas résoudre et signaler. La voie de résolution « statistics-1.2 » est retirée.
2. **Contrat de vert minimal des apprenants à 2 s.** Il découle de la configuration figée. S'il était démenti par le rodage (`shortest green … below`), arrêter et signaler : ne pas changer le seuil après coup.
3. **Le format de `sumo --version` sous SUMO 1.25 n'est pas vérifié ici.** Le gel exige que la version contienne « 1.25 ». Si `environment.sumo` vaut « unknown », vérifier le PATH ou `SUMO_HOME`.
4. **matplotlib** n'est peut-être pas installé dans `traffic_rl`. Sans lui, il n'y a pas de graphique en forêt ; aucune installation n'est faite sans demande.
5. **Espace disque.** Le besoin définitif est le volume mesuré par le rodage pour les exécutions restantes, plus 4 Go. Les environ 8,4 Go cités sont une estimation avant mesure. Si la place manque, choisir une racine sur un autre volume : rien n'est supprimé.
6. **En-tête du runbook.** La consigne du 2026-11-19 était tronquée après « Inclure en tête : ». Le runbook complet de cette version la remplace ; à compléter si quelque chose manquait.

## 6. Changements de cette version, par rapport à a9640b1

**Protocole.**
- IDQN sans protection en R0 : 100 évaluations, descriptives seulement. Total : 2470.
- Une seule famille de 12 contrastes, à 1 − 0,05/12, au lieu des familles séparées à 99,5 % et 97,5 %.
- Pour IDQN, la décision reste fondée sur J, avec un descriptif conditionnel aux paires évacuées.
- D̄ est calculé sur toutes les paires valides, échecs compris.
- Effets appariés de la garantie et interventions.
- La règle de desserte est limitée aux bras du contraste.

**Code.**
- Contrats techniques et relecture complète.
- Mode diagnostic sans décision.
- Blocage des décisions en cas d'échec technique.

**Statistique.** Outil `stats_reference.py` ; le gel exige une résolution ; l'import A003 au gel est supprimé.

**Rodage et gel.**
- Rodage étendu à 16 cellules, avec débit par type de contrôleur et coûts de gzip et de relecture.
- Gel conditionné au disque et à la résolution statistique.

**Exploitation.**
- `b-processes`, `b-backup-logs`, `b-watch`.
- Contrôle de disque d'A-ext ; audit pour B (2470) et A-ext, avec la racine cible.
- Runbook complet.

**Formulation.** La garantie n'est plus dite pénalisante pour IDQN en R0 ; l'actionné g5 est présenté comme une extension des références.

## 7. Finalisation de f61e030 (deux corrections ciblées)

**1. Couverture attendue pour IDQN.**
- `service()` calculait la couverture comme « modèles × trafics de tous les profils », soit 500 cellules pour IDQN, au lieu de 100 en R0.
- La couverture vient maintenant du périmètre prévu par le plan : QMIX et VDN sur les 5 profils (500 cellules par bras, règle inchangée) ; IDQN sur `arms.idqn_profiles` = R0 (100 cellules par bras).
- Elle compare les **identités** (graine d'entraînement, profil, trafic) : un doublon ne compense pas une cellule manquante, et une cellule hors périmètre est refusée.
- L'énoncé descriptif de desserte d'IDQN est limité à R0 (`service_claim_scope`) ; le rapport cite ce périmètre et la couverture.
- Aucun intervalle n'est réintroduit sur les cellules regroupées.
- Tests ajoutés : 100 cellules complètes, énoncé autorisé sur R0 ; une cellule manquante, interdit ; un doublon, refusé ; une cellule IDQN hors R0, inattendue ; QMIX et VDN, 500 cellules, règle inchangée.

**2. Référence statistique harmonisée.**
- Dans `confirmation_plan.json`, `statistics.procedure` et `statistics.reference.name` désignent `b-crossed-bootstrap-1 (implementation statistics-1.1)`. L'empreinte statistics-1.2 est rangée sous `historical_statistics_1_2`, avec le statut « HISTORICAL, NOT VERIFIED, NOT CLAIMED ».
- `stats_reference.py resolve` et le gel n'acceptent plus que `b-crossed-bootstrap-1`. Le refus d'une résolution « statistics-1.2 », même écrite à la main, est testé.
- L'étape `b-stats-resolve-12` est retirée : `ETAPES.cmd` compte 56 étapes, et le harness Windows attend 355 contrôles.
- Les documents, les docstrings et `check_statistics.py` (marqué historique) sont harmonisés.
- Sont inchangés : l'algorithme, les 10 000 réplicats, la famille de 12, le niveau 1 − 0,05/12, les intervalles à 95 %, les marges, les règles et les garde-fous du gel.

**Contrôles de cette finalisation :** voir `logs/revue_2026-11-23/finalisation/`.
