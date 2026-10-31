# Bilan court pour l'encadrant (2026-10-29)

**Étude :** QMIX, VDN et IDQN sur deux carrefours espacés de 300 m. Décisions toutes les 5 s : PROLONGER, ou CHANGER avec 3 s de jaune.

## Ce qui a été fait

**1. Vérification des chiffres transmis, sur les fichiers.**
- Tous les chiffres du tableau de l'énoncé sont exacts :
  - ancien plan fixe 2,772 s ;
  - plan contraint à des verts ≥ 7 s : 3,156 s ;
  - 10 QMIX historiques : 3,106 s sur 49 évaluations valides sur 50 ;
  - pilotes 4,698 / 4,434, 4,324 / 4,815 et 5,478 / 4,898 s ;
  - perte de temps des plans fixes : 11,739 → 10,134 s.
- Sources : `comparison_runs.csv`, puis, pour les pilotes, les 30 `evaluation_metrics.json` bruts.
- Les effectifs 25 / 970 / 50 sont confirmés par les registres.
- **31 tests réussis sur votre machine** (corrigé le 2026-10-30) : la preuve est la sortie terminal que vous avez transmise (« Ran 31 tests in 1548.888s », « OK », code de sortie 0). Aucun fichier journal local de cette exécution n'a été retrouvé. Le fichier `controles_cloud/tests_simules.log` est un autre journal : celui des tests exécutés dans l'environnement cloud de développement, pas sur votre machine.

**2. Diagnostic de l'échec QMIX** (graine 101, checkpoint 350 000, trafic 9305 ; lecture seule).
- Il reste un seul véhicule, le dernier du flux secondaire sud→nord de J2.
- Il est arrêté à la ligne d'arrêt de 3 605 à 7 200 s : réseau vide, aucune attente d'insertion, aucun blocage physique.
- Un vert secondaire de 2 s s'est terminé juste avant son arrivée.
- L'observation devient ensuite presque constante. L'écart Q(PROLONGER) − Q(CHANGER) **croît** de +0,24 à +0,62 à mesure que la composante « temps de vert écoulé » sature. C'est un état absorbant de la politique gloutonne.
- Le même modèle a frôlé l'échec sur 9303 : une attente de 338 s, résorbée par la dérive inverse de la même composante.
- Les phases journalisées sont celles commandées, pas relues dans SUMO.

**3. Ablation à 4 bras** : 30 modèles × 5 trafics × 4 bras = 600 évaluations.
- 550 nouvelles et 50 réutilisées, vérifiées par empreintes ;
- plan figé avant les exécutions ;
- 0 écart de feux SUMO ;
- 31 minutes sur 4 processus.

**4. Préparations :**
- robustesse sur 5 scénarios nouveaux, 2 375 évaluations, environ 2,5 h ; non lancée ;
- campagne de réentraînement, 30 entraînements, environ 5 jours ; non lancée ;
- revue ciblée avec 23 DOI vérifiés ;
- manuscrit LaTeX ;
- 5 figures reproductibles.

## Résultats principaux de l'ablation

| Question | Réponse sur ces 5 trafics de développement |
|---|---|
| La garantie corrige-t-elle les défauts ? | **Oui**, les 6 échecs observés. Une intervention par évaluation, toujours **après** la fin de la demande |
| Son coût pendant la demande est-il testé ? | **Non** : 0 intervention pendant la demande sur 300 évaluations, donc ΔD = 0 dans les 150 paires |
| Le vert minimal a-t-il un coût régulier ? | **QMIX, VDN : régulier et élevé**, avec J de +1,2 à +2,3 s dans 100 % des paires. **IDQN : variable** : il améliore certains modèles, en dégrade d'autres, corrige 4 échecs et en crée 1 |
| Les protections interagissent-elles ? | **Non observé** : interaction nulle sur D dans 150/150 blocs, faute d'intervention de la garantie pendant la demande |
| Les conclusions dépendent-elles de l'indicateur ? | Pas pour QMIX et VDN. Oui pour IDQN et pour la comparaison des deux plans fixes. La perte de temps des véhicules arrivés masque les échecs |

**Comparaison avec les plans fixes** (formulation corrigée le 2026-10-30) :
- sous la même contrainte de vert ≥ 7 s, 299 des 300 évaluations apprises sont évacuées, et **aucune de ces 299** ne bat le plan fixe réoptimisé sous cette contrainte, ni sur J ni sur la perte de temps. Cette comparaison est asymétrique : le plan fixe a été réoptimisé pour la contrainte, tandis que les politiques sont les politiques historiques, entraînées sans contrainte et contraintes seulement à l'évaluation, sans réentraînement. ;
- la 300e (IDQN graine 101, checkpoint 225 000, vert minimal seul, trafic 9304) est un **échec d'évacuation** : elle n'a pas de J et ne compte ni comme victoire ni comme défaite ;
- sur les 600 évaluations, 594 sont évacuées, et aucune de ces 594 ne bat l'ancien plan fixe sur J ; les 6 échecs ne sont pas comparables.

## Statut de chaque élément

**Exécuté et vérifié sur vos données :**
- vérification des chiffres ;
- diagnostic de l'échec ;
- ablation (600) et son analyse ;
- comparaison aux plans fixes ;
- figures ;
- vérification des checkpoints, manifestes et données réutilisées ;
- 11 tests unitaires sous votre pile Python 3.7 ;
- 4 simulations SUMO de rodage de l'outil de robustesse (sorties non interprétées).

**Testé seulement sur données synthétiques :**
- reconstruction des compteurs (aussi vérifiée ensuite sur 100 évaluations réelles) ;
- générateur de scénarios de robustesse ;
- adaptateur de dénominateur N ;
- garde-fous des scripts.

**Préparé, non exécuté :**
- validation de robustesse (`plans/PLAN_ROBUSTESSE.md`) ; son script d'analyse reste à écrire avant le lancement ;
- campagne de réentraînement (`plans/PLAN_CAMPAGNE_FUTURE.md`) ; elle demande d'ajouter un `run_kind` de campagne dans `QMIX_PROTECTED` ;
- compilation PDF : faite lors de la revue de passation (TeX Live sous Linux, 2026-10-30) ; `manuscript/main.pdf`, 12 pages, sans référence indéfinie. À refaire chez vous avec `ETAPES.cmd latex` si vous modifiez le texte.

**Manquant pour soutenir les conclusions :**
- un test final sur trafics nouveaux (3101–3120) ;
- le coût de la garantie pendant la demande ;
- un entraînement **avec** contraintes, sur plusieurs graines ;
- des références actionnée et max pressure sous les mêmes contraintes ;
- d'autres géométries et demandes ;
- la lecture intégrale des travaux proches, la matrice ne reposant que sur des résumés.

**Restant avant une soumission :**
- tout ce qui précède ;
- les auteurs ;
- la compilation ;
- la relecture des détails de la littérature ;
- les intervalles de confiance hiérarchiques prévus par le plan de campagne.

## Appréciation franche

**Contribution défendable aujourd'hui, mais de portée limitée :**
- un résultat négatif soigneusement contrôlé, mais asymétrique : les politiques historiques, entraînées sans contrainte puis contraintes à l'évaluation sans réentraînement, ne battent pas le plan fixe réoptimisé sous cette contrainte (0 sur 299 évaluations évacuées, 1 échec) ;
- les pilotes entraînés avec les deux protections (une graine par méthode) donnent un signal exploratoire défavorable ; ils ne permettent pas de prédire la réussite ou l'échec d'une campagne complète ;
- un mécanisme de défaillance documenté, invisible dans les moyennes usuelles ;
- une mesure appariée des protections.

**Preuves encore insuffisantes pour une revue Q1 :**
- un seul corridor ;
- des trafics de développement déjà vus ;
- des protections ajoutées sans réentraînement ;
- la garantie jamais sollicitée pendant la demande.

**Suite (mise à jour du 2026-10-31) :**
- d'abord la validation de robustesse et la lecture intégrale des travaux proches ;
- la décision sur de nouveaux entraînements viendra ensuite. Les deux options restent ouvertes : une campagne « les deux » (30 entraînements) suivie d'un test final, ou un article centré sur la méthodologie d'évaluation et le résultat négatif, les pilotes y étant présentés comme un signal exploratoire.

**Aucune publication ne peut être promise.**
