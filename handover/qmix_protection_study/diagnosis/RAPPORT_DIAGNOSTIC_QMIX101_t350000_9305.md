# Diagnostic de l'échec d'évacuation : QMIX historique, graine 101, checkpoint 350 000, trafic 9305

**Nature :** lecture seule des traces existantes, aucune simulation.

**Script :** `diagnosis/diagnose_clearance_failure.py`. Sorties dans `diagnosis/out_qmix101_t350000_9305/diagnosis.json`, et extractions complémentaires reproduites dans ce rapport.

**Source :** `D:\QMIX_Results\fixed_timing_min7_2026-10-28\comparison\runs\C_qmix_seed101_t350000__traffic930{1..5}`.

**Provenance du run :**
- checkpoint sha256 `32d68e46…4b4473` ;
- commit gelé `8c14f32` ;
- SUMO 1.25.0, Python 3.7.16, PyTorch 1.13.1+cpu ;
- graine SUMO 732830 ;
- manifeste de trafic `aa2e9f8f…`.

## 1. Faits (lus dans les fichiers)

### Véhicules restants et attente d'insertion

**Un seul véhicule reste à 7 200 s :** `S2N2_v0299` (`clearance_failures.jsonl`, `episode_summary.csv`).
- C'est le dernier véhicule (rang 299/300) du flux secondaire sud→nord de J2, route `E6 → -E7`.
- Aucun véhicule en attente d'insertion : `pending_due` = 0, `departDelay` = 0. Les 2 800 véhicules ont été insérés.
- Aucune téléportation.

**Ce que dit `tripinfo` (véhicule inachevé) :**
- départ à 3 578 s sur `E6_1` ;
- `routeLength` = 183,5 m (la voie E6 mesure 189,6 m) ;
- `waitingTime` = 3 600 s ;
- `waitingCount` = 2 ;
- `vaporized="end"`.

**Où il se trouve.** Il est arrêté au bout de la voie d'approche `E6_0`, la ligne d'arrêt de J2 (`lane_states.csv` : `queue` = 1, vitesse 0). Il y est à l'arrêt sans interruption **de 3 605 s à 7 200 s**.

**Blocage physique.**
- Après 3 679 s, aucun autre véhicule n'est présent sur les voies journalisées.
- Rien ne bloque physiquement ce véhicule : il attend uniquement un feu.

### Chronologie à J2

C'est l'état **commandé** par l'exécuteur (voir § 3).

| Temps (s) | Phase commandée à J2 | Véhicules sur E6 |
|---|---|---|
| 3 581–3 583 | jaune | — |
| 3 584–3 585 | vert V (2 s) | — |
| 3 586–3 588 | jaune | — |
| 3 589–3 595 | vert H | — |
| 3 596–3 598 | jaune | — |
| **3 599–3 600** | **vert V (2 s)** | le véhicule roule encore à 13,9 m/s, non arrêté |
| 3 600 | décision CHANGER, avec `q_V` = 0 et `λ_V` = 0,09 : le véhicule approche mais n'est pas compté à l'arrêt | — |
| 3 601–3 603 | jaune | — |
| 3 604 → 7 200 | vert H commandé sans interruption ; plus aucune seconde de vert V | — |

### Dernières décisions, observations et valeurs Q à J2

Il y a 718 décisions après 3 605 s.

**Observation :** à partir de 3 640 s environ, elle ne change plus que par sa 4e composante :

> `[q_H=0, q_V=0,01, phase_H=1, elapsed/(elapsed+60), λ_H=0, λ_V=0, occ_H=0, occ_V=0]`

- 704 décisions ont exactement ce vecteur, hors temps écoulé.
- `q_V` = 0,01 correspond à 1 véhicule arrêté, normalisé par 100.

**Valeurs Q journalisées (aucune exploration, ε = 0) :**
- Q(PROLONGER) − Q(CHANGER) est positif ;
- il **croît** avec le temps de vert écoulé : +0,24 à 3 605 s, +0,37 à 3 705 s, +0,57 à 4 105 s, **+0,624 à 7 195 s** ;
- la composante de temps écoulé sature, à 0,9836 à 7 195 s ;
- l'action gloutonne est donc PROLONGER à toutes les décisions jusqu'à la coupure.

**Exemple de dernière décision (7 195 s) :** Q(PROLONGER) = −4,4447 ; Q(CHANGER) = −5,0686.

**J1 pendant la même période :** 714 PROLONGER et 15 CHANGER, sans rapport avec E6.

### Comparaison avec les quatre réussites du même checkpoint (9301–9304)

**Le dernier véhicule `S2N2_v0299` :**
- part entre 3 584 et 3 593 s ;
- arrive entre 3 627 et 3 632 s ;
- attend 0 à 9 s.

**9303 est une réussite, mais contient un quasi-échec de même nature à l'autre carrefour.**
- Le véhicule principal `EW_v0697` attend **338 s** à J1, de 3 586 s jusqu'à son arrivée à 4 011 s.
- J1 tenait alors le vert secondaire avec un état local figé `[q_H=0,0067, 0, phase_H=0, elapsed, 0, …]`.
- Sur cette trajectoire, Q(PROLONGER) − Q(CHANGER) **décroît** avec le temps écoulé : +0,019 à 3 680 s, +0,0015 à 3 960 s. Il devient négatif à 3 980 s, ce qui déclenche CHANGER.
- L'attente s'est donc résorbée seulement parce que la dérive de la composante « temps écoulé » a fait basculer l'argmax.
- **Pour 9305 à J2, la même composante fait croître l'écart** : aucune bascule n'a lieu.

**Fréquence des changements :**
- environ 60 % des verts commandés pendant la demande durent 2 s, dans les cinq trafics et aux deux carrefours (59–62 %) ;
- 232 à 245 verts secondaires de moins de 7 s par carrefour et par trafic ;
- ce n'est pas spécifique à l'échec.

**Plus long refus de vert secondaire à J2 pendant la demande :** 23 s (9305), contre 18 à 28 s pour les réussites. **Aucun signe de famine pendant la demande** : le refus indéfini apparaît après la fin de la génération à 3 600 s, avec un seul véhicule isolé.

## 2. Hypothèses (non démontrées)

**H1 — état absorbant de la politique gloutonne.**
- L'échec résulte d'un point fixe : une observation locale quasi stationnaire, un seul véhicule arrêté, aucune arrivée, pour laquelle l'action gloutonne est PROLONGER.
- La seule composante qui évolue pousse l'écart vers PROLONGER.
- Les journaux le montrent pour cette trajectoire. Pour affirmer que l'écart reste positif pour toute valeur du temps écoulé (y compris 1), il faudrait une évaluation hors ligne du réseau sur cette observation. Elle n'a pas été faite ici.

**H2 — vert secondaire de 2 s juste avant la fin de la demande.**
- Le vert V de 2 s (3 599–3 600 s) a pris fin avant que le véhicule n'atteigne la ligne d'arrêt.
- Un vert minimal de 7 s aurait prolongé ce vert jusqu'à 3 605 s environ.
- **On ne sait pas si cela aurait suffi.** La position du véhicule seconde par seconde n'est pas journalisée.
- L'ablation (bras « vert minimal seul » sur 9305) le testera directement.

**H3 — la garantie à 120 s devrait forcer CHANGER au plus tard vers 3 604 + 120 + 4 s.** C'est une conséquence attendue de la règle, à vérifier par le bras « garantie seule ».

**Ce qui ne peut pas être affirmé :**
- que la cause est identique aux anciens échecs IDQN : leurs traces n'ont pas été relues ici ;
- que ce mode de défaillance n'existe pas pour les autres checkpoints sur d'autres trafics.

## 3. Informations manquantes

- **Phases réellement lues dans SUMO.** `signal_phases.actual_phase` est l'état commandé par l'exécuteur gelé (`environment.py`, `signal_executor.py`), pas une relecture de SUMO. Ces runs n'ont pas journalisé `sumo_signal_check.csv` ; cette relecture n'existe que dans la version protégée. Les phases SUMO ne sont donc pas établies pour ce run.
- **Position et vitesse du véhicule seconde par seconde.** Seuls des agrégats par voie sont disponibles, et `vehicle_crossings.csv` ne couvre que l'axe principal.
- **Valeurs Q hors trajectoire**, par exemple au temps écoulé limite. Seules les Q des états visités sont journalisées.
- **Le mélangeur QMIX** n'intervient pas dans l'action gloutonne : celle-ci est l'argmax de chaque utilité locale. Les sorties du mélangeur ne sont pas journalisées en évaluation.

## 4. Conséquence pour la suite

- L'échec est un **défaut de desserte post-demande** pour un véhicule isolé, sans blocage physique ni attente d'insertion.
- Il touche un checkpoint QMIX qui réussit les quatre autres trafics, dont un (9303) avec une attente de 338 s qui ne s'est résorbée que par une dérive des valeurs Q.
- C'est précisément le cas que la garantie de desserte vise.
- L'ablation à 4 bras sur ce couple (modèle, trafic) en donne le test direct.
