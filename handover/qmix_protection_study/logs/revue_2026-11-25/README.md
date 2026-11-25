# Contrôles du 2026-11-25 : retour Windows sur 1aa6731 (encodage du texte)

**Environnement de revue :** conteneur Linux, Python 3.11.17, numpy 2.4.6. Le paquet protégé `adaptive_qmix_protected` est absent ici.

| Fichier | Commande | Résultat observé |
|---|---|---|
| `cp1252_avant_1aa6731.log` | nouveau test `Analyse.test_the_report_is_written_when_the_default_encoding_is_cp1252`, sur une copie où `b_runner.py`, `confirmation_analysis.py` et `stats_reference.py` sont ceux de 1aa6731 | `UnicodeEncodeError: 'charmap' codec can't encode character '\u0304'` : **l'erreur Windows est reproduite** |
| `unittest_all_crlf.log` | `unittest discover -s tests -v`, code figé CRLF | `Ran 181 tests`, `FAILED (errors=2)` |
| `unittest_all_lf.log` | même suite, code figé LF | même résultat |
| `unittest_all_locale_ascii.log` | même suite sous `LC_ALL=C PYTHONUTF8=0 PYTHONIOENCODING=ascii:strict`. L'encodage par défaut de `open()` est alors `ANSI_X3.4-1968` (ASCII), plus strict que cp1252 | même résultat |
| `pyflakes.log` | sur les 37 fichiers modifiés ou ajoutés | 5 imports inutilisés : 4 imports de détection de disponibilité, et `io` dans `make_archive.py`, déjà présent avant cette version et laissé tel quel |
| `vermin.log` | mêmes fichiers | Python 3.6 minimum |

**Les 2 erreurs** de chaque suite sont `No module named 'adaptive_qmix_protected'`. Ce sont des contrôles non réalisés ici, pas des réussites ; ils passent sous Windows (rapporté).

**Non observé :** cette livraison n'a été lancée ni sous Windows, ni sous Python 3.7.

## Complément : test statique sous Python 3.7 (retour sur b574cbd)

| Fichier | Commande | Résultat observé |
|---|---|---|
| `regle_py37_avant.log` | `python regle_py37_repro.py <ancien test> tests .` : l'ancienne règle (b574cbd), sur des arbres reconstruits sous la forme de Python 3.7 (`ast.Str`) | échantillon `[1, 2, 3, 5, 8, 9]` ; 34 signalements, le premier étant `tools/make_archive.py:60`, comme sous Windows. Le 35e est le nouveau fichier de test lui-même |
| `unittest_all_crlf_v2.log` | suite complète, code figé CRLF | `Ran 183 tests`, `FAILED (errors=2)` (paquet protégé absent) |
| `unittest_all_locale_ascii_v2.log` | suite complète sous locale C, avec `PYTHONIOENCODING=ascii:strict` | même résultat |
