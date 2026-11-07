# Journaux du 2026-11-07 (comparateurs, confirmation, analyses sans simulation)

Environnement de revue : Linux, Python 3.11. SUMO 1.28 est installé ici, alors que ta pile utilise SUMO 1.25. Le code figé 8c14f32 est disponible ici ; `QMIX_PROTECTED` ne l'est pas.

**Ces fichiers ne sont pas des résultats.**
- Les exécutions SUMO ont été faites sur des graines de conception, uniquement pour le rodage.
- Le package protégé absent est remplacé par un module vide, et seulement dans les scripts du sous-dossier `smoke_cloud/`.

| Fichier | Contenu |
|---|---|
| `unittest_all_without_frozen.log` | suite complète, comme sur une machine sans la pile figée : les nouveaux tests sont ignorés |
| `unittest_all_with_frozen_code.log` | suite complète avec le code figé : seuls les 3 tests qui exigent `QMIX_PROTECTED` sont ignorés |
| `vermin.log`, `pyflakes.log` | compatibilité Python 3.7 et analyse statique des nouveaux fichiers |
| `etapes_harness_wine.log` | outil de vérification d'`ETAPES.cmd` sous Wine 9.0 (sans les contrôles CALL et conda) |
| `measure_cloud.json`, `comparators_real_pipeline_cloud.log`, `run_log_coarse_shard0of13844.jsonl` | chaîne réelle `measure` → `plan` → `prepare` → 4 exécutions grossières → `progress`, sur une racine jetable |
| `smoke_cloud/` | 9 exécutions de rodage (plan fixe, actionné, plans par période R3, Max Pressure) et contrôle des transitions de signal |
| `mp_check_static.json` | A4 : constats lus dans le code et les configurations figés |
| `mp_check_logs_design_seeds_cloud.json`, `mp_pressure_decomposition_R0_8011_cloud.json` | A4 : commutations et décomposition de la pression, sur graines de conception |
| `cp_ablation/` | C : intervalles de Clopper-Pearson sur les 600 évaluations de l'ablation (données lues) |
| `development_reference_9301_9305.json` | C : J de QMIX et des deux plans fixes sur 9301–9305 (données lues) |
