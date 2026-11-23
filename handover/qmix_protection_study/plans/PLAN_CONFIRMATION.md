# Plan de confirmation pré-enregistré (B)

**Statut : pré-enregistrement amendé (2026-11-19), puis complété le 2026-11-23 (`plans/PROTOCOL_AMENDMENT_B.md`, qui fait foi en cas de contradiction). Non gelé, non lancé.** Aucune graine de confirmation n'a été générée et aucun manifeste de confirmation n'existe.

**Fichiers :**
- `tools/confirmation/confirmation_plan.json` : les paramètres, couverts par une empreinte (`fingerprint`) ;
- `tools/confirmation/b_runner.py` : plan, rodage, gel, préparation, exécution, avancement, analyse ;
- `tools/confirmation/confirmation_analysis.py` : les règles de décision ;
- `tools/confirmation/stats_reference.py` : la résolution de la référence statistique.

Empreinte de `confirmation_plan.json` : `693bab0a083e6415287b08148a888ba80197b426d19e7a5739a94f4c4f45e8e7`. L'empreinte du plan B (tâches, sélections, marges, checkpoints, code) est calculée par `b-plan` et scellée par `b-freeze` dans `freeze.json`.

## 1. Questions

1. Les politiques QMIX et VDN figées, avec la garantie seule, servent-elles tous les véhicules sur des trafics jamais utilisés ?
2. Que vaut leur J face au meilleur comparateur classique disponible pour chaque profil ?
3. Au scénario de référence, les méthodes complètes QMIX et VDN, sous garantie, font-elles mieux qu'IDQN sous garantie ? Cette question ne permet pas, à elle seule, une conclusion causale sur la coordination ou le mélangeur.

## 2. Ordre imposé avant le gel

1. A terminé, A-ext finalisée : toutes les sélections scellées et vérifiées.
2. Sous Windows, dans un nouveau dossier d'installation vérifié par son manifeste :
   - `ETAPES.cmd tests` ;
   - `verify_etapes_cmd.cmd`, sans échec ;
   - l'audit disque.
3. `b-plan`, puis `b-measure` : le rodage réel en parallèle, avec 16 cellules sur graines de conception.
4. La procédure statistique `b-crossed-bootstrap-1` : `b-stats-results` (reproduction des résultats de référence), puis `b-stats-resolve`.
5. `b-freeze`, une seule fois. Il refuse s'il manque une condition (amendement §9).
6. Ensuite seulement : `b-prepare <empreinte>` (manifestes de confirmation), `b-run`, `b-progress`, `b-analyse`.

## 3. Trafics, politiques et bras

**Trafics.** 8051–8060, 8151–8160, 8251–8260, 8351–8360 et 8451–8460, générés seulement par `b-prepare` après le gel. Ne sont jamais utilisés : 3001–3010, 3101–3120, 2201–2205, 8c01–8c05 et 8c11–8c25.

**Politiques.** Les 30 du plan de robustesse : 10 QMIX, 10 VDN et 10 IDQN, graines d'entraînement 101 à 110. Identités et SHA-256 sont contrôlés. Aucune nouvelle sélection, aucun entraînement.

**Bras.**
- QMIX et VDN, sur les 5 profils : garantie (décisions) et sans protection (descriptif).
- IDQN, en R0 seulement : garantie (décisions des deux contrastes) et sans protection (**descriptif uniquement**).

## 4. IDQN : pourquoi il est seulement au scénario de référence

IDQN n'est pas comparé aux contrôleurs classiques. Ce choix a été fait avant tout trafic de confirmation, pour trois raisons :
1. La question porte sur les méthodes coopératives à factorisation de valeur. IDQN est la référence non coopérative ; ses résultats de développement, d'ablation et de robustesse sont rapportés en entier.
2. Une instabilité connue avant la confirmation :
   - **Ablation, vérifiée le 2026-11-07.** C'est la seule méthode dont l'effet du vert minimal est irrégulier. Elle compte 4 échecs sur 50 sans protection.
   - **Robustesse, vérifiée ici.** Les 35 paires où la garantie seule a augmenté D̄ (définition D2) sont **toutes en R1 (17) et en R2 (18), aucune en R0**.
3. Le comparer aux classiques élargirait la famille de décision pour une configuration qui n'est pas candidate.

Il est évalué en R0 pour la question 3. **Le plan ne dit pas que la garantie pénalise IDQN en R0** : les seules interventions listées en R0 sont 2 interventions QMIX, après la demande (vérifié). L'absence d'intervention pendant la demande pour VDN et IDQN en R0 est rapportée, non vérifiée ; B la mesure.

## 5. Comparateurs par profil

| Profil | Principal (décisions) | Évalués |
|---|---|---|
| R0 | C19, verts 8/5, décalage 9 (J_val 2,765 ; δ 0,138 s) | C19 ; C25 12/7 D0 ; Max Pressure |
| R1 | plus faible J de validation parmi les sélections scellées (attendu sans A-ext : plan fixe optimisé g5, 1,940 ; δ 0,100 s) | OFT g5 ; OFT min7 ; actionné min7 ; actionné g5 ; C19 ; C25 ; Max Pressure |
| R2 | idem (attendu sans A-ext : actionné min7, 1,367 ; δ 0,100 s) | les mêmes |
| R3 | idem (attendu sans A-ext : plans par période g5, 2,722 ; δ 0,136 s) | les mêmes, plus les plans par période g5 et min7 |
| R4 | C19 : ancrage nominal, **non réoptimisé sur R4** (δ 0,138 s) | C19 ; C25 ; Max Pressure |

L'actionné g5 est une extension des références classiques. Il ne reproduit pas l'autorité de commande des apprenants, dont les verts peuvent finir après 2 s.

## 6. Critères

| Rôle | Critère |
|---|---|
| Principal | J, le temps d'attente moyen par véhicule, par (modèle, trafic), avec N = total du manifeste. Jamais imputé |
| Service | échec d'évacuation ; échec avec attente ouverte ; au moins un véhicule en attente ≥ 300 s |
| Secondaires | D̄ (toutes les paires valides, échecs compris) ; temps perdu ; attente maximale |

## 7. Statistique

**Une seule famille de 12 contrastes confirmatoires :**
- 10 contrastes : QMIX et VDN, avec garantie, contre le principal de chacun des 5 profils ;
- 2 contrastes en R0 : QMIX et VDN, avec garantie, contre IDQN avec garantie.

**Niveaux et estimation.**
- Bonferroni, pour un risque familial de 5 % : intervalles bilatéraux à **1 − 0,05/12 = 99,5833… %**.
- Intervalles à 95 % pour la description.
- 10 000 réplicats du bootstrap croisé apparié.

**Hypothèses et limites du bootstrap** : graines d'entraînement et trafics rééchantillonnés indépendamment, considérés comme échangeables ; approximation, pas une garantie exacte en petit échantillon ; aucune cellule manquante.

**Marges.** δ = max(0,05 × J_val ; 0,10 s). Les contrastes avec IDQN reprennent la marge nominale de R0 (0,138 s), seuil d'intérêt pratique commun, non recalculé à partir des résultats.

**Procédure statistique.**
- **Vérifié :** B appelle `paired_crossed_bootstrap` du module figé (statistics-1.1, fichier `ed133bb2…`).
- **Procédure retenue :** `b-crossed-bootstrap-1`, c'est-à-dire cette implémentation statistics-1.1, avec la reproduction obligatoire de ses résultats de référence sous Windows.
- **Historique, non vérifié :** `8b6413a9…` est rapporté comme l'empreinte de protocole de statistics-1.2. Ce label n'est pas revendiqué, faute de preuve d'équivalence.
- Le gel exige la résolution `b-crossed-bootstrap-1` (amendement §8) et refuse toute autre procédure.

## 8. Règles de décision

Pour chacun des 12 contrastes, avec [L, U] l'intervalle à 99,5833 %, la première règle vérifiée l'emporte :
1. **ÉCHEC DE SERVICE** : un échec avec attente ouverte dans un bras avec garantie du contraste.
2. **NON ESTIMABLE** : un autre échec qui empêche le contraste complet. J n'est pas imputé. Une sensibilité descriptive est donnée (pour IDQN : les paires toutes deux évacuées, avec leur dénominateur).
3. **SUPÉRIEUR AU-DELÀ DE LA MARGE** : U < −δ.
4. **SUPÉRIEUR** : U < 0.
5. **ÉQUIVALENT** : −δ < L et U < δ.
6. **INFÉRIEUR AU-DELÀ DE LA MARGE** : L > δ.
7. **INFÉRIEUR** : L > 0.
8. **NON CONCLUANT** dans les autres cas.

**Portée des règles :**
- Un échec dans un bras sans protection, descriptif, ne change pas un contraste sous garantie.
- Un échec scientifique est une observation terminée, jamais relancée.
- **Si un contrôle technique échoue, aucune décision n'est rendue.**

**Énoncé de service.** Uniquement « aucun échec avec attente ouverte observé » sur le plan complet, toujours accompagné des effectifs par modèle et par trafic. Ce n'est jamais un risque nul.

## 9. Statistiques de service

- Effectifs bruts, présents et attendus, par profil, méthode et bras. IDQN n'est attendu qu'en R0.
- Aucun intervalle sur les cellules regroupées.
- Intervalles de Clopper-Pearson, bilatéraux à 95 %, avec en plus la borne unilatérale à 95 %, au niveau modèle (sur 10) et au niveau trafic (sur 10), stratifiés par profil.
- Ils portent sur la part de modèles ou de trafics touchés, pas sur une probabilité par véhicule ou par exécution.

## 10. Effets de la garantie (descriptifs)

Pour chaque profil et chaque méthode (IDQN en R0 seulement) :
- interventions pendant et après la demande, par bras ;
- J avec garantie − J sans protection, sur les paires toutes deux évacuées ;
- D̄ avec garantie − D̄ sans protection, sur toutes les paires valides ;
- effectifs présents et attendus, échecs compris.

## 11. Décompte et coût

| Élément | Exécutions |
|---|---|
| QMIX et VDN : 2 × 10 modèles × 2 bras × 5 profils × 10 trafics | 2000 |
| IDQN : 10 modèles × 2 bras × R0 × 10 trafics | 200 |
| Comparateurs : (3 + 7 + 7 + 7 + 3) spécifications distinctes × 10 trafics | 270 |
| **Total** | **2470** |

Le décompte est calculé par le code, sans être forcé.

**Coût.** La durée et le volume viennent du rodage en parallèle. Le **besoin disque définitif** est le volume mesuré par le rodage pour les exécutions restantes, plus une marge de 4 Go. Avant mesure, l'ordre de grandeur est de 2,5 h sur 4 processus et 8,4 Go (seuil de départ : 12,7 Go), et ces chiffres ne valent pas mesure. **Une nuit n'est pas garantie.**

## 12. Contrats techniques

Ils sont vérifiés sur chaque cellule, et de nouveau sur le résumé recalculé depuis les traces gzip (amendement §7) :
- compteur ≤ 127 s dans les bras avec garantie ;
- aucun écart de feux SUMO dans les bras appris ;
- vert minimal propre au contrôleur évalué ;
- cohérence des compteurs, de N et de J ;
- champs critiques présents.

Une violation est un échec technique, qui n'est jamais relancé et qui bloque les décisions.
