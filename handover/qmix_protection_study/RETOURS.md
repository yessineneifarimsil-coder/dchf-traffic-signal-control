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

## 8. Retour Windows du 2026-11-24 sur b058301

**Rapporté par Yessine (sous Windows) :**
- `statistics.py` : SHA-256 brut `0e43bf5b…`, 635 fins de ligne CRLF ; `ed133bb2…` après normalisation CRLF→LF.
- `b-stats-results` : `DIFFERENT … 74 numbers checked, 1 differences (numpy 1.21.6, python 3.7.16)`.
- `disk-audit`, avec `BCONF=C:\research\confirmation_B_2026-11-24` : `B can start on current free space: True` (17,71 Go libres sur C:). C'est une estimation avant rodage : le besoin définitif reste le volume mesuré par le rodage plus 4 Go.
- `tests_B.txt` (lu ici) : 172 tests, 28 échecs et 3 erreurs. Les deux tests du paquet protégé passent.

**Diagnostic, vérifié ici.**
- **L'unique différence est le contrôle d'empreinte du module, pas un nombre.** Dans b058301, la liste des différences contenait le message d'empreinte (sha brut CRLF ≠ `ed133bb2…`), suivi des écarts numériques. Le décompte de 1 et `tests_B.txt` montrent qu'aucun nombre ne différait : les 74 nombres sont reproduits sous numpy 1.21.6 et Python 3.7.16 (rapporté, déduit du décompte).
- Une copie CRLF du fichier de référence donne exactement `0e43bf5b…` et 635 CRLF.
- **Les 28 échecs et 2 des 3 erreurs ont la même cause.** La préparation commune des tests (`setUp`) exigeait une résolution statistique sans différence. Un `setUp` en échec saute le `tearDown`, et le résumé factice restait donc installé pour les tests suivants. C'est pourquoi `RealReaders` voyait J absent et un compteur non détecté.
- **La 3e erreur** (`IndexError` dans les travailleurs du rodage) vient de `spawn` : sous Windows, les travailleurs n'héritent pas du résumé factice du test.
- Ces deux motifs sont reproduits ici avec un code figé converti en CRLF (`logs/revue_2026-11-24/`).

**Corrections, sans changement scientifique.**
- `stats_reference.py` :
  - le module est accepté s'il est identique octet pour octet, ou identique **après la seule normalisation CRLF→LF** ;
  - le rapport sépare l'identité du module (`module_identity`, `module_differences`, avec le sha brut, le sha LF et le nombre de CRLF) des nombres (`numbers_checked`, `number_differences`) ;
  - chaque différence est affichée en entier, préfixée `module identity:` ou `number:`.
- `b_runner.py` : le rodage passe au travailleur le résumeur à utiliser. Une option `start_method` permet de tester `spawn`. Le comportement normal est inchangé.
- Tests :
  - `addCleanup` restaure l'état même si `setUp` échoue ;
  - 3 tests ajoutés : copie CRLF reproduite, contenu modifié au-delà des fins de ligne détecté, rodage sous `spawn`.
- Ce qui n'a pas changé : l'algorithme, la référence (74 nombres), le plan (empreinte `693bab0a…`), la famille de 12, les marges, les règles et le décompte de 2470.

**À refaire sous Windows avec cette livraison, dans un nouveau dossier :**
1. `ETAPES.cmd tests`. Le gel lit `logs\tests_B.txt`, qui doit finir par `OK` (attendu : 175 tests).
2. `verify_etapes_cmd.cmd`.
3. `b-stats-results`. Attendu : `module identity: identical … after CRLF->LF normalisation …`, puis `REPRODUCED: module identity OK | numbers: 74 checked, 0 differing`.
4. `disk-audit`.

Le `tests_B.txt` actuel, en `FAILED`, ne peut pas servir au gel.

## 9. Retour Windows du 2026-11-25 sur 1aa6731 : encodage du texte

**Rapporté (Windows, Python 3.7.16, numpy 1.21.6, SUMO 1.25) :**
- 175 tests : 170 réussis, 5 erreurs ;
- les 2 tests qui demandent `adaptive_qmix_protected` passent ;
- `b-stats-results` : `REPRODUCED`, 74 nombres, 0 différence ;
- `verify_etapes_cmd` : 355 contrôles, 0 failed.

**Les 5 erreurs** (`test_b_runner.Analyse`, lues dans `tests_B.txt`) ont une cause unique. `write_report` ouvrait `RESULTATS_B.md` sans encodage, Windows a donc pris cp1252 par défaut, et le caractère combinant `\u0304` de « D̄ » a levé `UnicodeEncodeError`. **Reproduit ici** sur le code de 1aa6731 par le nouveau test, qui force cp1252 : même exception, même caractère (`logs/revue_2026-11-25/cp1252_avant_1aa6731.log`).

**Corrections, sans aucun changement de calcul.**
1. **Fichiers.** `encoding="utf-8"` est passé à 175 ouvertures de fichiers texte, en lecture comme en écriture, y compris `gzip.open` en mode texte et `read_text`. Elles se répartissent dans 35 fichiers : `tools/` (b_runner, confirmation_analysis, stats_reference, check_statistics, disk, monitor, aext_search, article_analyses, mp_check, check_r0_demand, ablation_analysis, smoke, etapes_check, make_archive, verify_manifest), `tests/`, `diagnosis/` et `figures/`.
   - Le nouveau test statique `tests/test_text_encoding.py` refuse toute ouverture en mode texte sans encodage, ainsi qu'un mode non littéral.
   - **Exception déclarée : 12 fichiers scellés**, inchangés octet pour octet. Leur SHA-256 figure dans les plans de campagnes déjà exécutées : `CODE_FILES` de la campagne A, `plan.json` de la robustesse et de l'ablation. `robustness_analysis.py` refuse de tourner si sa propre empreinte diffère de celle du plan de robustesse.
   - Ces 12 fichiers ne lisent et n'écrivent que de l'ASCII (`json.dump` avec `ensure_ascii`, CSV numériques, sorties SUMO). Ils ont déjà tourné sous Windows. La suite passe ici sous une locale ASCII stricte (voir plus bas).
2. **Console.**
   - `ETAPES.cmd` fixe `PYTHONIOENCODING=utf-8` juste après `setlocal`, avant toute étape (testé).
   - Les chaînes littérales des `print` des outils sont en ASCII (testé). Les sorties console de `b-analyse` sont en ASCII ; « D̄ » reste dans les fichiers UTF-8.
3. **Test d'exécution.** `test_the_report_is_written_when_the_default_encoding_is_cp1252` :
   - toute ouverture sans encodage des modules de l'analyse est forcée en cp1252, comme sous Windows ;
   - la console est un flux ASCII strict ;
   - `b_runner.main(["analyse", …])` doit réussir, avec 12 lignes de décision et un `RESULTATS_B.md` lisible en UTF-8 strict qui contient « D̄ ».

**Contrôles ici** (`logs/revue_2026-11-25/`) : 181 tests ; seules les 2 erreurs du paquet protégé absent, dans trois configurations :
- code figé CRLF ;
- code figé LF ;
- **locale C**, où l'encodage par défaut est l'ASCII, avec `PYTHONIOENCODING=ascii:strict`.

**Inchangés :** l'algorithme, la référence statistique, le plan (`693bab0a…`), les marges, les règles, la famille de 12 et le total de 2470.

**Conséquence pour A-ext.** `aext_search.py` fait partie des fichiers corrigés, et donc des empreintes de code d'A-ext. Si un `aext-plan` a déjà été produit, `aext-prepare` et `aext-run` refuseront avec « code differs ». Il faut refaire `aext-plan` dans une racine neuve. Rien n'a été lancé.

**À refaire sous Windows, dans un nouveau dossier :** `ETAPES.cmd tests` (attendu : 181 tests, `OK`), `verify_etapes_cmd.cmd` (355 attendus, 0 failed), `b-stats-results`.

## 10. Retour Windows du 2026-11-25 sur b574cbd : le test statique dépendait de la version de Python

**Rapporté :**
- 181 tests : 179 réussis, 2 échecs, tous deux dans `test_text_encoding` ;
- les 5 tests `test_b_runner.Analyse` passent, dont le test cp1252 ;
- `verify_etapes_cmd` : 355 contrôles, 0 failed ;
- `b-stats-results` : `REPRODUCED`.

**Cause, vérifiée ici : la version de Python, pas les chemins ni les fins de ligne.** Le test lisait les chaînes littérales par `ast.Constant`. Python 3.8 et suivants les produisent sous cette forme, mais **Python 3.7 les produit en `ast.Str`**. Sous 3.7 :
- chaque mode littéral (`"rb"`, `"w"`…) passait donc pour un mode non littéral. D'où les 34 signalements, dont le premier est `make_archive.py:60`, qui est en réalité `open(dest, "rb")` ;
- et la ligne 3 de l'échantillon, `open(p, "rb")`, était retenue à tort.
- Le contrôle des `print` ne voyait, pour la même raison, aucun littéral sous 3.7 : il passait sans rien vérifier.

**Reproduction ici.** J'ai fourni à l'ancienne règle (b574cbd) des arbres reconstruits sous la forme de Python 3.7. Elle donne `[1, 2, 3, 5, 8, 9]` sur l'échantillon. Sur le code, elle donne 34 signalements, le premier étant `tools/make_archive.py:60` : exactement le résultat Windows (`logs/revue_2026-11-25/regle_py37_avant.log`).

**Correction : le test seul.**
- `literal_str` accepte les deux formes (`Str.s` et `Constant.value`).
- L'échantillon est vérifié en LF et en CRLF, sous les deux formes d'arbre.
- Deux tests sont ajoutés :
  - tout le code, sous la forme 3.7, donne 0 ouverture fautive et 0 littéral non ASCII dans les `print` ;
  - les chemins sont comparés avec `/`, et les 12 fichiers exemptés sont bien trouvés.
- L'analyse ignore les avertissements du parseur. Le `DeprecationWarning: invalid escape sequence \c` vient de la docstring de `tools/disk/archive_campaign_A.py` (`logs\campaignA_archive.json`) : c'est un avertissement sans effet sur l'encodage, et le fichier n'a pas été modifié.

**Aucune vraie ouverture sans encodage n'a été trouvée** : aucun fichier d'outil n'a été modifié, et les 12 fichiers figés sont inchangés.

**Contrôles ici :** 183 tests ; seules les 2 erreurs du paquet protégé absent, avec le code figé en CRLF et sous une locale ASCII stricte.

**À refaire sous Windows**, dans un nouveau dossier : `ETAPES.cmd tests` (attendu : 183 tests, `OK`).

## 11. Incident TraCI de la part 2/4 pendant B (2026-11-25)

Voir `RETOURS_INCIDENT_2026-11-25.md` (causes confirmées, changements, ce qui n'a pas changé) et `RUNBOOK_B.md`, étape 9 bis.
