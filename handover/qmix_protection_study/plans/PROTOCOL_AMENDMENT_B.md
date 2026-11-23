# Amendement B au plan de confirmation (2026-11-19, rectifié le 2026-11-23)

**Statut : écrit avant tout trafic de confirmation. B n'est pas gelé.** Aucune graine 8c51–8c60 n'a été générée. Aucune exécution B n'a eu lieu.

Cet amendement modifie `plans/PLAN_CONFIRMATION.md` et `tools/confirmation/confirmation_plan.json`. Il ne deviendra définitif qu'au gel (`ETAPES.cmd b-freeze`). Le gel n'est possible qu'une fois le code terminé et testé, dans les conditions de la section 6.

Le texte déclare :
- trois écarts (B1, B2, B3) ;
- une correction de la référence statistique ;
- le rectificatif du 2026-11-23 (sections 1 B3, 4, 5, 6 et 7) ;
- un recomptage.

Tout le reste est inchangé (section 8).

## 1. Écarts déclarés

### B1. Comparateur principal : la meilleure sélection scellée

**Ancienne règle.** Le comparateur principal de R1–R3 était le plan fixe optimisé g5 (OFT g5).

**Nouvelle règle.** Pour R1, R2 et R3, le comparateur principal est celui qui a **le plus faible J de validation** parmi toutes les sélections scellées des campagnes A et A-ext. Pour R0 et R4, il reste C19 8/5 D9, inchangé.

**Calcul automatique.** Le choix est fait par `b_runner.choose_primary`, une fonction testée qui lit les fichiers `selections/*.json` de A et de A-ext. Chaque fichier est contrôlé contre son propre sceau. En cas d'égalité, l'ordre fixé est : oft_g5, oft_min7, actuated_min7, actuated_g5, tod_g5, tod_min7.

**Quand.** Le choix est fait avant le gel (`b-plan`, puis `b-freeze`). Il est écrit dans le plan B et dans `margins.json`, et son empreinte entre dans `freeze.json`.

**Contrôle d'intégralité.** Le plan refuse de se construire si une sélection attendue manque :
- R1 et R2 : oft_g5, oft_min7, actuated_min7, actuated_g5 ;
- R3 : les mêmes, plus tod_g5 et tod_min7.

**Valeurs attendues sans A-ext**, vérifiées sur les fichiers de sélection reçus (test `test_B1_primary_from_the_A_selections`) :

| Profil | Comparateur principal | J de validation (s) | δ (s) |
|---|---|---|---|
| R0 | C19 8/5 D9 | 2,7651 | 0,138 |
| R1 | plan fixe optimisé g5, C25 14/5 D1 | 1,9399 | 0,100 |
| R2 | actionné min7, gap 2 s, H 60 s, V 15 s | 1,3669 | 0,100 |
| R3 | plans par période g5 | 2,7219 | 0,136 |
| R4 | C19 8/5 D9 | 2,7651 | 0,138 |

Si l'actionné g5 de A-ext fait mieux en validation que la valeur ci-dessus pour un profil, il devient le principal de ce profil, et δ est recalculé à partir de son J de validation.

**Marge.** La règle ne change pas : δ = max(0,05 × J_val ; 0,10 s).

**Pourquoi.** La règle initiale fixait OFT g5 avant que les sélections de A existent. Or A montre que, sur R2 et R3, un autre comparateur classique fait nettement mieux en validation (1,367 contre 1,572 ; 2,722 contre 3,581). La nouvelle règle compare les méthodes apprises au meilleur comparateur classique disponible en validation. Elle est appliquée mécaniquement, sur des données de validation, sans regarder le moindre trafic de confirmation.

### B2. L'actionné à vert minimal de 5 s est inclus, comme extension des références

La campagne A-ext (`plans/PLAN_COMPARATEURS.md` section 10, racine `D:\QMIX_Results\comparators_actuated_g5`) sélectionne un feu actionné à vert minimal de 5 s pour R1, R2 et R3.

**Pourquoi A-ext.**
- L'actionné de A impose un vert minimal de 7 s, que QMIX et VDN n'ont pas.
- Ses réglages retenus sont au bord de la grille (gap 2 s, vert maximal secondaire 15 s).

**Ce que c'est, et ce que ce n'est pas.** C'est une **extension des références classiques** : un candidat de plus, sélectionné par la même règle figée. Il **ne reproduit pas** l'autorité de commande des méthodes apprises, dont les verts peuvent finir après 2 s. Il ne prétend donc pas mettre les comparateurs à égalité de moyens avec elles.

**Dans B**, il est évalué sur les 50 trafics :
- principal s'il a le plus faible J de validation (règle B1) ;
- secondaire sinon.

### B3. IDQN : hors de la famille principale, ajouté au scénario de référence (révisé le 2026-11-23)

**Ce qui ne change pas.** IDQN n'est pas comparé aux contrôleurs classiques. La justification de la section 4 de `PLAN_CONFIRMATION.md` vaut pour cette famille.

**Ce qui est ajouté.** Le manuscrit étudie aussi le bénéfice de l'apprentissage conjoint face à des apprenants indépendants. Pour cette question, B évalue :
- **les 10 checkpoints IDQN historiques** du plan de robustesse (méthode `idqn`, graines d'entraînement 101–110, une chacune) ;
- **avec la garantie seule** ;
- **au scénario de référence R0**, sur ses 10 nouveaux trafics 8051–8060, les mêmes que QMIX et VDN.

Cela fait **100 évaluations**.

Les étiquettes et les SHA-256 des checkpoints IDQN sont lus dans le plan de robustesse et figés par l'empreinte du plan B. Aucune n'est écrite à la main. Le plan refuse de se construire s'il n'y a pas exactement 10 checkpoints IDQN, avec les graines 101 à 110 (testé).

Les contrastes sont définis à la section 4.

## 2. Correction : la référence statistics-1.2

**L'erreur.** Le brouillon du 2026-11-07 traitait `8b6413a9ccffa2bbbcf0d3cfdde6c7460b4785193aa419f7d4725885dc38437a` comme le SHA-256 d'un fichier `statistics.py`.

**Ce qu'est cette valeur (passation du 2026-11-15).** C'est `amendment003.protocol_hashes()['statistics_1_2']`, l'empreinte d'un JSON canonique, reproduite depuis le dossier A003. Ce n'est le hash d'aucun fichier.

**Conséquences :**
- La règle « refuser tout fichier dont le SHA-256 diffère de 8b6413a9… » est retirée, ainsi que l'étape `check-statistics` du gel.
- B utilise `paired_crossed_bootstrap` du module statistique figé, avec `official=False`. Un autre fichier peut être désigné au gel par `--statistics <chemin>`. Le chemin et le SHA-256 du fichier sont écrits dans `freeze.json` et imposés ensuite (testé).
- **Facultatif.** `b-freeze <dossier A003>` enregistre en lecture seule la valeur statistics-1.2, sans écrire de bytecode dans ce dossier (testé).
- **Limite.** Le contenu d'amendment003 n'a pas été vu ici. Que statistics-1.2 spécifie exactement ce bootstrap reste à confirmer avant le gel (`RETOURS.md`).

## 3. Recomptage exact (rectifié)

Le compte est produit par le code (`b_runner.py plan`) et testé (`test_exact_count_and_no_duplicate_folder`). Une spécification identique n'est évaluée qu'une fois et sert à toutes ses étiquettes.

| Profil | QMIX et VDN (2 × 10 modèles × 2 bras × 10 trafics) | IDQN (10 modèles × garantie × 10 trafics) | Spécifications de comparateurs distinctes | Exécutions de comparateurs |
|---|---|---|---|---|
| R0 | 400 | **100** | 3 : C19, C25 12/7 D0, Max Pressure | 30 |
| R1 | 400 | 0 | 7 : OFT g5, OFT min7, actionné min7, actionné g5, C19, C25, Max Pressure | 70 |
| R2 | 400 | 0 | 7 : les mêmes | 70 |
| R3 | 400 | 0 | 7 : OFT g5 = OFT min7 = C25 12/7 D0 (une seule spécification), actionné min7, actionné g5, par période g5, par période min7, C19, Max Pressure | 70 |
| R4 | 400 | 0 | 3 : C19, C25, Max Pressure | 30 |
| **Total** | **2000** | **100** | | **270** |

**Total : 2370 évaluations** (2100 apprises et 270 de comparateurs).

Sans IDQN, le total serait de 2270. L'ancien chiffre de 2260 omettait l'actionné g5 (+30) et comptait deux fois la spécification commune de R3 (−20).

**Coût.** Il est mesuré, pas promis :
- **Disque.** 2370 × la taille par exécution mesurée par le rodage, plus 4 Go de marge au démarrage. Avant mesure, l'ordre de grandeur est de 8 Go, soit un seuil d'environ 12 Go libres.
- **Durée.** Elle est estimée à partir du **rodage en parallèle** (section 6) :
  - estimation attendue = (2100 × durée moyenne d'une exécution apprise + 270 × durée moyenne d'un comparateur) / (4 × efficacité parallèle mesurée) ;
  - estimation pessimiste : la même formule avec les durées maximales observées.
- Avant mesure, l'ordre de grandeur est de 2,4 h sur 4 processus.
- **Une nuit n'est pas garantie.** Des exécutions qui vont jusqu'à la coupure à 7 200 s, la campagne IEV sur la même machine ou une mise en veille allongent la durée.

## 4. Contrastes entre apprenants : famille F2 (rectificatif)

**Question.** L'apprentissage conjoint (QMIX, VDN) fait-il attendre les véhicules moins qu'IDQN, au scénario de référence et avec la garantie ?

**Effet mesuré.** Pour chaque méthode conjointe M (QMIX, puis VDN) :
- différence D_kj = J_M(k, j) − J_IDQN(k, j), où k est la graine d'entraînement (101–110) et j l'un des 10 trafics de R0 ;
- effet = moyenne des 100 valeurs D_kj ;
- une valeur négative veut dire que M fait attendre moins qu'IDQN.

**Procédure.** `paired_crossed_bootstrap` du module figé, avec un comparateur appris (`comparator_kind="learned"`), `official=False`, 10 000 réplicats, intervalle par percentiles.
- Chaque réplicat tire les graines d'entraînement et les trafics, et les applique aux deux méthodes.
- L'appariement par **numéro** de graine d'entraînement est la convention du protocole statistique (statistics-1.1). Il ne crée aucun lien causal entre un modèle QMIX et un modèle IDQN de même numéro.

**Multiplicité.**
- **F1** (famille principale) : les 10 comparaisons des méthodes apprises au comparateur classique principal, décidées à **99,5 %** (Bonferroni sur 10).
- **F2** : les 2 contrastes QMIX − IDQN et VDN − IDQN, décidés à **97,5 %** (Bonferroni sur 2).
- Le risque d'erreur par famille est contrôlé à 0,05 dans chaque famille. **Ce n'est pas une seule famille de 15 comparaisons, ni de 12.** Les deux familles répondent à deux questions différentes :
  - F1 : face au meilleur contrôleur classique ;
  - F2 : apprentissage conjoint face à apprentissage indépendant.
- Aucun énoncé ne les combine.
- **Sensibilité préspécifiée, descriptive seulement :** les intervalles de F2 sont aussi donnés à 1 − 0,05/12 ≈ 99,58 %, ce qui correspond à Bonferroni sur les 12 comparaisons de décision.

**Marge et règles.**
- δ est celui de R0 : 0,138 s.
- Les règles et leur ordre sont ceux de F1 :
  - échec de desserte si l'une des deux méthodes a un échec avec attente ouverte sous garantie ;
  - non estimable si l'une a un échec quelconque.
- Une décision de F2 ne vaut que pour le scénario de référence, avec ces 10 modèles par méthode.

**Distinction.** F1 compare des apprenants à des contrôleurs déterministes : une valeur par trafic, diffusée sur les modèles. F2 compare deux populations de modèles appris. Les deux sont présentées dans des tableaux et des graphiques séparés (`decisions.csv`, colonne `family` ; `forest.png` et `forest_joint.png`).

## 5. Statistiques de service (rectificatif)

**Tous les effectifs sont rapportés**, pour chaque groupe (profil, méthode ou comparateur, bras) et pour chaque événement : échec d'évacuation, échec avec attente ouverte, attente ≥ 300 s.

**Aucun intervalle n'est calculé sur les évaluations regroupées.** Les mêmes 10 modèles sont évalués sur les mêmes trafics : les évaluations ne sont pas des essais indépendants. Un intervalle de Clopper-Pearson sur, par exemple, 0 échec sur 500 ne garantit pas une fiabilité. Il n'est plus présenté.

**Unités statistiques et hypothèses des intervalles proposés :**

| Unité | Effectif | Hypothèse | Ce que l'intervalle ne dit pas |
|---|---|---|---|
| Modèle | modèles touchés au moins une fois, sur 10 | les 10 graines d'entraînement sont des tirages indépendants de la procédure d'entraînement | il est conditionnel à ces trafics ; ce n'est pas un taux par évaluation |
| Trafic | trafics touchés au moins une fois, sur 10 par profil | les trafics sont des tirages indépendants du générateur du profil | il est conditionnel à ces modèles |

**Calcul des intervalles.**
- Les deux sont des intervalles exacts de Clopper-Pearson à 95 %.
- Avec 0 événement, la borne supérieure unilatérale à 95 % est donnée : 0 sur 10 donne 25,9 %.
- **Aucun bootstrap de taux** n'est utilisé : après zéro événement, il donnerait [0 ; 0], ce qui n'établit pas un risque nul.

**Énoncé de desserte.** Il n'est autorisé que sur le plan complet (10 modèles × 50 trafics) et sous la seule forme « aucun échec avec attente ouverte observé sur ces évaluations ». Il est toujours accompagné des effectifs par modèle et par trafic. Il n'est jamais formulé comme un risque nul.

## 6. Validation technique et gel (rectificatif)

**Rodage réel (`b-measure`) :**
- 12 exécutions réelles sur graines de **conception** uniquement (R0 8011–8012, R1 8111–8112, R3 8311), lancées sur **4 processus en parallèle**, comme B ;
- QMIX et VDN dans les deux bras, IDQN avec garantie, et 4 comparateurs ;
- chaque exécution est finalisée comme dans B (journaux en gzip), puis **relue depuis ses fichiers gzip** par le même lecteur (`robustness_analysis.cell_metrics`), qui doit retrouver exactement le même résumé ;
- le rodage enregistre le débit, l'efficacité parallèle, les versions de Python et de SUMO et les SHA-256 du code.

**Le gel définitif est refusé** (testé) si l'une de ces conditions manque :
1. le rodage n'a pas réussi ;
2. il n'a pas tourné sous **Python 3.7** et **SUMO 1.25** ;
3. le code a changé depuis le rodage : le code gelé doit être le code testé (`ETAPES.cmd` compris) ;
4. le contrôle Windows des commandes (`tools\etapes_check\verify_etapes_cmd.cmd`) n'affiche pas « 0 failed » ;
5. les tests unitaires (`ETAPES.cmd tests`) n'affichent pas « OK ».

Les rapports, leurs SHA-256 et l'environnement du rodage sont écrits dans `freeze.json`.

**Relecture à l'analyse.** `b-analyse` relit chaque cellule depuis ses journaux gzip. Une cellule dont le résumé recalculé diffère est exclue, jamais imputée, et listée.

**Garde-fous des graines.** Seuls `b-prepare`, puis `b-run`, touchent aux graines de confirmation 8c51–8c60, et seulement après un gel valide (testé).

## 7. Conservation des données (rectificatif)

- **Aucune donnée de la campagne A n'est supprimée par cette livraison.** La suppression est désactivée dans le code (`archive_campaign_A.py`, testé) et l'étape `archive-a-delete` est retirée d'`ETAPES.cmd`.
- L'audit (`disk-audit`) et la création d'archives vérifiées (`archive-a`, `archive-a-dryrun`) restent autorisés.
- Les outils et plans modifiés vivent dans une **nouvelle copie de travail versionnée**. La passation est publiée par commit, et sous Windows elle s'installe dans un nouveau dossier (`RUNBOOK_B.md`, étape 0).
- Les dépôts gelés et la campagne A restent intacts. Les 8 fichiers de code de A gardent leur SHA-256 (testé).

## 8. Inchangé

- QMIX et VDN figés : les 20 politiques et checkpoints de la campagne de robustesse, contrôlés par SHA-256. Bras `guarantee` (principal) et `none` (secondaire).
- 50 trafics neufs, 8c51–8c60. Tous les comparateurs scellés sont évalués sur les mêmes 50.
- Bootstrap apparié croisé (`official=False`), 10 000 réplicats. Intervalle à 99,5 % pour les décisions de F1 et à 95 % pour la description.
- Les règles de décision et leur ordre (section 8 du plan).
- Critères de service et critères secondaires (D̄, temps perdu, attente maximale).
- Aucune cellule manquante n'est imputée.
