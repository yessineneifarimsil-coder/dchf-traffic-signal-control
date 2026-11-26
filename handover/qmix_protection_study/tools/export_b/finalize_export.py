"""Last step of the export: README_EXPORT.md, MANIFEST_SHA256.txt, then B_export_<date>.zip and its .sha256.

    python tools/export_b/finalize_export.py --export <EXPORT> [--name B_export_2026-11-26]

README_EXPORT.md is filled from the files of the export only (reports, check_export.txt, comparison text): nothing
is estimated. The ZIP holds every file of the export folder except itself and its .sha256; it is re-opened and every
member is checked against MANIFEST_SHA256.txt. Refuses to overwrite.
"""
from __future__ import absolute_import, division, print_function

import argparse
import hashlib
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common as C  # noqa: E402

NA = "non disponible"
COLUMNS_DOC = [
    ("cell_id", "dossier de la cellule sous <BCONF> (plan.json, jobs[].directory)"),
    ("profile", "profil de demande (R0_reference … R4_isolated_tail)"),
    ("traffic_seed", "graine du trafic de confirmation"),
    ("controller_kind", "learned / fixed / actuated / tod / max_pressure (spec.kind : actuated et actuated_g5 -> actuated, canonical_mp -> max_pressure)"),
    ("method", "qmix / vdn / idqn ; pour un comparateur, ses étiquettes (séparées par ;)"),
    ("training_seed", "graine d'entraînement, lue dans l'étiquette du modèle (…_seed<n>_…)"),
    ("checkpoint", "<BCONF>/checkpoints/<modèle>.pth"),
    ("checkpoint_sha256", "SHA-256 du checkpoint scellé dans le plan"),
    ("comparator_spec", "spécification JSON du comparateur"),
    ("comparator_spec_sha256", "SHA-256 de la spécification (plan)"),
    ("arm", "guarantee / none ; vide pour un comparateur"),
    ("status", "clearance_status : CLEARED ou CLEARANCE_FAILURE"),
    ("N_scheduled", "N de cell_summary.json (comparé à scheduled_total du manifeste)"),
    ("J_s", "J_primary_s ; vide si la cellule n'est pas évacuée (jamais imputé)"),
    ("D_bar_s", "coût d'attente pendant la demande par véhicule"),
    ("mean_time_loss_s", "mean_completed_time_loss_s"),
    ("max_vehicle_wait_s", "max_vehicle_waiting_s (tripinfo)"),
    ("vehicles_wait_ge_300s", "véhicules ayant attendu au moins 300 s"),
    ("open_wait_at_end", "open_wait_at_end_s ; vide si aucun"),
    ("interventions_guarantee_demand", "interventions de la garantie avant 3600 s (bras appris)"),
    ("interventions_guarantee_after", "interventions après 3600 s (bras appris)"),
    ("max_counter_s", "compteur de service maximal"),
    ("shortest_green_s", "vert le plus court réalisé pendant la demande"),
    ("sumo_mismatch_s", "secondes d'écart feu commandé / feu SUMO (bras appris)"),
    ("end_time_s", "fin de l'épisode (episode_summary.csv)"),
    ("cell_state, comparator_labels, comparator_variant, model_tag", "colonnes ajoutées : état b_runner, étiquettes, spec.kind exact, étiquette du modèle"),
]


def read(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f) if path.endswith(".json") else f.read()


def readme(export):
    rep = read(os.path.join(export, "B_episodes_report.json"), {}) or {}
    check = read(os.path.join(export, "check_export.txt"), NA) or NA
    cmp_text = read(os.path.join(export, "reestimation_vs_frozen.txt"), NA) or NA
    sc = read(os.path.join(export, "search_counts_details.json"), {}) or {}
    tf = read(os.path.join(export, "training_facts.json"), {}) or {}
    absent = rep.get("absent_columns") or {}
    L = ["# Export public de la campagne B (étude QMIX)", "",
         "Ce dossier est produit **en lecture seule** à partir de la racine de B (`<BCONF>`) et du code installé. "
         "Aucune simulation n'a été relancée, aucun fichier source n'a été modifié. Les chemins personnels sont "
         "remplacés par `<home>`, la racine de B par `<BCONF>`, ce dossier par `<EXPORT>`.", "",
         "## Provenance", "",
         "- empreinte du plan figé : `{}`".format(rep.get("plan_fingerprint", NA)),
         "- `margins.json` : SHA-256 `{}` (copie conforme : `B_margins.json`)".format(rep.get("margins_sha256", NA)),
         "- module statistique figé : SHA-256 `{}` (statistics-1.1, `paired_crossed_bootstrap`)".format(
             rep.get("statistics_module_sha256", NA)),
         "- cellules du plan : {} ; lignes écrites : {} ; relecture depuis les traces gzip : {}".format(
             rep.get("jobs_in_plan", NA), rep.get("rows_written", NA), "oui" if rep.get("recheck_from_gzip_traces") else "non (valeurs de cell_summary.json, déjà relues par b-analyse)"),
         "", "## Fichiers", "",
         "| Fichier | Contenu |", "|---|---|",
         "| `B_episodes.csv` | une ligne par cellule terminée de B |",
         "| `B_episodes_report.json` | sources, colonnes absentes, cellules non terminées, contrôle de N |",
         "| `B_margins.json` | copie conforme de `<BCONF>/margins.json` (scellé par le gel) |",
         "| `reestimate_B.py` | ré-estimation indépendante des 12 contrastes (Python 3.7, numpy, module statistique figé importé) |",
         "| `reestimate_B.csv`, `reestimation_vs_frozen.txt` | sa sortie et la comparaison à `decisions.csv` figé |",
         "| `sensitivity_B.csv` | sensibilités **non décisionnelles** (100 000 réplicats, 5 graines, graines d'entraînement non appariées) |",
         "| `search_counts.csv`, `search_counts_details.json` | décompte des recherches classiques de A et A-ext |",
         "| `network_facts.json` | réseau SUMO de B et zones de détection de l'actionné |",
         "| `training_facts.json` | entraînement et sélection des checkpoints, avec fichier et ligne |",
         "| `check_export.txt` | contrôle avant livraison |",
         "| `MANIFEST_SHA256.txt` | SHA-256 et taille de chaque fichier |", "",
         "## Colonnes de B_episodes.csv", "", "| Colonne | Source (cell_summary.json sauf mention) |", "|---|---|"]
    L += ["| `{}` | {} |".format(c, d) for c, d in COLUMNS_DOC]
    L += ["", "Colonnes absentes des sorties : " + (", ".join("`{}` ({} cellules)".format(k, len(v)) for k, v in sorted(absent.items()))
                                                  if absent else "aucune."),
          "", "## Ce qui a été vérifié", "", "```", check.strip(), "```", "",
          "Comparaison de la ré-estimation au fichier figé :", "", "```", cmp_text.strip(), "```", "",
          "Recherches de A : hypothèse et valeurs observées (`search_counts_details.json`) :", "", "```",
          json.dumps(sc.get("hypothesis_checked", NA), indent=1, sort_keys=True), "```", "",
          "## Ce qui n'est pas disponible", ""]
    nas = []

    def walk(x, path):
        if isinstance(x, dict):
            if x.get("value") == NA:
                nas.append("`{}` : {}".format(path, x.get("source", "")))
            for k, v in x.items():
                walk(v, path + "." + k if path else k)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, "{}[{}]".format(path, i))
        elif x == NA:
            nas.append("`{}`".format(path))
    walk(tf, "training_facts")
    L += ["- " + n for n in nas] or ["- rien de signalé"]
    L += ["- la provenance des 30 checkpoints (code d'entraînement réellement utilisé) n'est pas établie par ces fichiers : "
          "voir `training_facts.json`, `checkpoints_of_B`.",
          "- les sensibilités de `sensitivity_B.csv` ne changent aucune décision : les décisions de B sont celles de l'analyse figée."]
    return "\n".join(L) + "\n"


def manifest(export, exclude):
    lines = []
    for base, sub, names in os.walk(export):
        sub.sort()
        for n in sorted(names):
            p = os.path.join(base, n)
            rel = os.path.relpath(p, export).replace(os.sep, "/")
            if rel in exclude:
                continue
            lines.append("{}  {:>10}  {}".format(C.sha256_file(p), os.path.getsize(p), rel))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", required=True)
    ap.add_argument("--name", default="B_export_2026-11-26")
    a = ap.parse_args(argv)
    zname = a.name + ".zip"
    C.write_text_once(os.path.join(a.export, "README_EXPORT.md"), readme(a.export))
    lines = manifest(a.export, {"MANIFEST_SHA256.txt", zname, zname + ".sha256"})
    C.write_text_once(os.path.join(a.export, "MANIFEST_SHA256.txt"),
                      "# {} | {} files\n".format(a.name, len(lines)) + "\n".join(lines) + "\n")
    zpath = os.path.join(a.export, zname)
    members = [l.split(None, 2)[2] for l in lines] + ["MANIFEST_SHA256.txt"]
    with zipfile.ZipFile(zpath, "x", zipfile.ZIP_DEFLATED) as z:
        for rel in members:
            z.write(os.path.join(a.export, *rel.split("/")), a.name + "/" + rel)
    bad = 0
    with zipfile.ZipFile(zpath) as z:
        for line in lines:
            h, size, rel = line.split(None, 2)
            data = z.read(a.name + "/" + rel)
            bad += hashlib.sha256(data).hexdigest() != h or len(data) != int(size)
    digest = C.sha256_file(zpath)
    C.write_text_once(zpath + ".sha256", "{}  {}\n".format(digest, zname))
    print("{}: {} files + MANIFEST, {} mismatch(es) | sha256 {}".format(zname, len(lines), bad, digest))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
