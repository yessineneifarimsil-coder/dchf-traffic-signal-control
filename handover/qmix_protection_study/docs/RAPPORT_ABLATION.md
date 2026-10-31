# Ablation des protections à l'inférence : résultats (2026-10-29)

**Nature :** évaluation de développement, exploratoire. Les trafics 9301–9305 ont déjà été inspectés. Ce n'est ni un test final ni une validation indépendante.

**Objet :** des politiques entraînées sans protection, auxquelles les protections sont ajoutées à l'évaluation. L'ablation ne dit rien d'un réentraînement ni de la coopération.

**Références :**
- plan figé avant les exécutions : `plans/PLAN_ABLATION_PROTECTIONS.md`, empreinte `c9a4c6d8…`, commit `e0557af` ;
- données : `analysis/ablation/{cells.csv, pairs.csv, summary.json, failures.json, reconstruction_check.json, fixed_plan_comparison.txt, service_details.txt}` ;
- figures : `figures/fig1`–`fig4` et leurs données dans `figures/data/`.

## Exécution et contrôles

**Évaluations :**
- 600 cellules = 30 modèles × 5 trafics × 4 bras ;
- 550 nouvelles, toutes terminées ;
- aucune reprise : 0 dossier `.incomplete` ;
- 50 réutilisées (QMIX, sans protection), dont les fichiers sont inchangés (`verify-reuse` : 0 fichier modifié).

**Contrôles :**
- écarts de feux SUMO, lus contre attendus : **0** sur les 550 nouvelles évaluations ;
- reconstruction des compteurs à partir des journaux : identique aux compteurs journalisés dans les **100/100** nouvelles cellules sans protection. Elle s'applique donc aussi aux 50 cellules réutilisées ;
- borne du compteur : ≤ 127 s dans toutes les évaluations avec garantie (maxima 125, 114 et 127 s) ;
- vert réalisé : ≥ 7 s dans toutes les évaluations avec vert minimal.

**Temps de calcul :**
- 13,2 s en moyenne par évaluation ;
- 4 processus, 30 min 41 s au total, de 04:59:57 à 05:30:38 ;
- 1,41 h CPU (temps processeur du processus Python ; SUMO tourne dans un processus séparé) ;
- 2,01 h de temps écoulé cumulé.

## Résultats par méthode et par bras

Le nombre d'évaluations est indiqué partout. J n'est jamais imputé : « J moyen » porte sur les seules évaluations évacuées.

| Méthode | Bras | Évacuées | J moyen (n) | D/N moyen (s) | Interventions garantie (dont pendant la demande) | Interventions vert minimal (dont pendant la demande) | Compteur max (s) | Attente max d'un véhicule (s) |
|---|---|---|---|---|---|---|---|---|
| QMIX | aucune | 49/50 | 3,106 (49) | 4,078 | 0 | 0 | 3 596 | 3 600 |
| QMIX | garantie | 50/50 | 3,104 (50) | 4,078 | 2 (0) | 0 | 125 | 128 |
| QMIX | vert minimal | 50/50 | 4,828 (50) | 5,795 | 0 | 17 827 (17 590) | 334 | 334 |
| QMIX | les deux | 50/50 | 4,827 (50) | 5,795 | 1 (0) | 17 827 (17 590) | 124 | 124 |
| VDN | aucune | 50/50 | 3,133 (50) | 4,108 | 0 | 0 | 114 | 118 |
| VDN | garantie | 50/50 | 3,133 (50) | 4,108 | 0 | 0 | 114 | 118 |
| VDN | vert minimal | 50/50 | 4,736 (50) | 5,702 | 0 | 16 479 (16 234) | 41 | 41 |
| VDN | les deux | 50/50 | 4,736 (50) | 5,702 | 0 | 16 479 (16 234) | 41 | 41 |
| IDQN | aucune | **46/50** | 6,123 (46) | 7,218 | 0 | 0 | 3 595 | 3 595 |
| IDQN | garantie | 50/50 | 6,306 (50) | 7,218 | 11 (0) | 0 | 127 | 169 |
| IDQN | vert minimal | **49/50** | 5,902 (49) | 6,892 | 0 | 8 928 (8 818) | 3 583 | 3 583 |
| IDQN | les deux | 50/50 | 5,973 (50) | 6,892 | 5 (0) | 8 881 (8 818) | 127 | 135 |

**Attention aux moyennes de J sur effectifs différents.** Par exemple, IDQN sans protection donne 6,123 sur 46 évaluations, contre 6,306 sur 50 avec la garantie. La différence vient des 4 évaluations ajoutées, qui étaient des échecs sans garantie, et non d'une dégradation. Les comparaisons appariées ci-dessous en tiennent compte.

## Réponses aux questions

### 1. La garantie seule corrige-t-elle les défauts observés ?

**Oui, dans ces 150 couples (modèle, trafic).**
- Les **6 échecs** observés sont tous évacués avec la garantie :
  - QMIX, graine 101, 9305 ;
  - IDQN, graine 101, sur 9302, 9303 et 9305 ;
  - IDQN, graine 106, sur 9303 ;
  - IDQN, graine 101, 9304, échec **apparu sous le vert minimal seul**.
- Chaque échec concerne le **dernier véhicule d'un flux secondaire** (`v0298`/`v0299`) après la fin de la demande. C'est le mécanisme diagnostiqué pour QMIX 101 / 9305 : `diagnosis/RAPPORT_DIAGNOSTIC_QMIX101_t350000_9305.md`.
- **Interventions de la garantie :** exactement **une par évaluation concernée** (19 au total sur les deux bras), **toutes après 3 600 s**.

**Portée :** cinq trafics de développement déjà vus. Ce n'est pas une garantie de service en général ; le plan de robustesse est prévu pour cela.

### 2. Son coût est-il réellement testé pendant la demande ?

**Non.** La garantie **n'est jamais intervenue pendant la demande**, sur aucune des 300 évaluations des bras « garantie » et « les deux ».

**Conséquences :**
- les trajectoires pendant la demande sont identiques à celles sans protection ;
- **ΔD = 0 exactement** dans les 150 paires ;
- ΔJ est nul dans 48/49 paires QMIX, 50/50 VDN et 39/46 IDQN. Il n'est non nul, et alors faiblement négatif (au plus −0,075 s), que dans les paires où l'intervention tardive écourte une attente.

**Le coût de la garantie lorsqu'elle intervient pendant une demande chargée reste donc non mesuré.** Les scénarios R1, R2 et R4 du plan de robustesse sont conçus pour le provoquer.

### 3. Le vert minimal a-t-il un coût régulier ou variable ?

**Régulier et élevé pour QMIX et VDN :**

| Méthode | ΔD > 0 | ΔD/N moyen par modèle | ΔJ (paires comparables) | Perte de temps |
|---|---|---|---|---|
| QMIX | 50/50 paires (+3 596 à +6 359 véh·s) | +1,57 à +1,95 s, sur les 10 modèles | +1,29 à +2,28 s, 49/49 positives, médiane +1,70 s, soit +55 % | +1,4 à +3,3 s |
| VDN | 50/50 paires | +1,36 à +1,83 s | +1,20 à +2,30 s, 50/50 positives | — |

Ces politiques utilisent des verts de 2 s dans environ 57 à 61 % des cas. Le masque intervient environ 350 fois par évaluation (QMIX, médiane), ce qui les déplace hors du comportement appris.

**Variable pour IDQN :**
- ΔD : 25 positives et 25 négatives ; médiane +56,5 véh·s ; de −35 004 à +4 514 ;
- moyenne par modèle de −4,72 à +1,13 s ;
- ΔJ : médiane −0,06 s, de −12,5 à +1,35 s ;
- la perte de temps baisse dans 41/50 paires.

Le vert minimal **améliore** certaines politiques IDQN qui oscillaient, en dégrade d'autres, corrige 4 échecs et **en crée un** (graine 101, 9304).

### 4. Les deux protections interagissent-elles ?

**Pas sur ces trafics, faute d'occasion.**
- Interaction (les deux − vert minimal) − (garantie − aucune) sur D : **0 dans les 150 blocs**.
- Sur J : nulle dans 47/49 blocs QMIX, 50/50 VDN et 35/45 IDQN, et sinon inférieure à 0,14 s en valeur absolue. Ces écarts viennent des interventions tardives de la garantie.
- La garantie n'étant jamais due pendant la demande, aucune interaction ne pouvait s'y produire.
- Le bras « les deux » réunit le coût du vert minimal et la desserte de la garantie : 50/50 évacuations pour chaque méthode.

### 5. Les conclusions dépendent-elles de l'indicateur ?

**QMIX et VDN :** non. J, D/N et la perte de temps varient dans le même sens pour le vert minimal (100 % des paires).

**IDQN :** oui. La médiane de ΔJ est légèrement négative, celle de ΔD légèrement positive, et la perte de temps baisse dans 41/50 paires.

**Plans fixes :** les indicateurs divergent.
- L'ancien plan a le J le plus bas (2,772).
- Le plan contraint à des verts ≥ 7 s a une perte de temps plus faible (10,13 contre 11,74 s).

**La perte de temps des véhicules arrivés ne voit pas les échecs.** QMIX 101 / 9305 a une perte de temps moyenne de 11,9 s, alors qu'un véhicule attend 3 600 s.

### Compteur, accès au vert, franchissement, arrivée

**Avec garantie :**
- compteur ≤ 127 s ;
- accès au premier vert ≤ 127 s.

**Mais l'attente cumulée d'un véhicule (`waitingTime`) atteint 128 à 169 s dans 8 évaluations.** Exemple : IDQN 102 / 9305, véhicule `WE_v0898`, 169 s.

**Pourquoi l'écart :** l'attente d'un véhicule cumule ses arrêts aux deux carrefours, et le compteur se remet à zéro si la file se vide. La borne de 127 s porte sur le compteur, **pas** sur l'attente ou l'arrivée d'un véhicule, et les données le confirment.

**Franchissement de la ligne d'arrêt :** journalisé pour l'axe principal seulement (1 600 véhicules par évaluation).

## Comparaison descriptive avec les plans fixes sur les mêmes trafics

Source : `fixed_plan_comparison.txt`.

**Sous la même contrainte (vert ≥ 7 s : bras « vert minimal » et « les deux ») :** Cette comparaison est asymétrique : le plan fixe a été réoptimisé pour la contrainte, tandis que les politiques sont les politiques historiques, entraînées sans contrainte et contraintes seulement à l'évaluation, sans réentraînement.
- 299 des 300 évaluations apprises sont évacuées ; **aucune de ces 299** n'a un J inférieur à celui du plan contraint sur le même trafic ;
- aucune de ces 299 n'a non plus une perte de temps plus faible ;
- la 300e (IDQN graine 101, checkpoint 225 000, vert minimal seul, trafic 9304) est un échec d'évacuation, sans J, non comparable (précision ajoutée le 2026-10-30) ;
- écart moyen de J : +1,58 à +2,82 s selon la méthode.

**Sans contrainte :**
- QMIX et VDN battent le plan contraint dans 33/49 et 30/50 évaluations sur J, mais jamais sur la perte de temps. Ils le font en utilisant des verts de 2 s, interdits à ce plan ;
- **aucune des 594 évaluations apprises évacuées, tous bras confondus, ne bat l'ancien plan fixe sur J** ; les 6 échecs d'évacuation ne sont pas comparables.

**Limite :** le plan contraint a été choisi sur les mêmes trafics de conception et de validation que l'ancien plan ; ce n'est pas une validation indépendante. Ces groupes sont ceux fixés par le code gelé (`benchmark_design` 2001–2005, `benchmark_validation` 2101–2105, `integrity.py`), réutilisés explicitement par l'étude min-7 (`PROTOCOLE_MIN7.md`, § 4). *Correction du 2026-10-30 : la version précédente de ce rapport affirmait à tort que le plan d'origine visait 2011–2015 / 2111–2115 ; ni le code gelé ni `PROTOCOLE_MIN7.md` ne le disent.*

## Ce que l'ablation ne montre pas

- l'effet d'un **entraînement** avec protections : pour cela, les pilotes à une graine et la campagne préparée ;
- un effet de la **coopération** ;
- le coût de la garantie pendant la demande (non sollicité) ;
- une généralisation au-delà de ces cinq trafics.
