"""Step A of the QMIX migration to GitHub: READ-ONLY inventory (2026-11-27).

    python inventory_qmix.py [--out C:\\research\\_migration_qmix] [--extra <path> ...]

Writes ONLY <out>\\INVENTAIRE.md and <out>\\inventaire.json (new files; a timestamp is added if they exist).
Never deletes, moves or modifies anything. Never opens a file whose name looks private or secret (correspondence,
salt, .env, key, token...): such files are listed by path and size only.

Git commands are read-only: `git --no-optional-locks status` (does not rewrite the index), `for-each-ref`,
`config --get`, `remote -v`, `ls-remote` (asks GitHub for its branch heads, changes nothing locally).
No `git fetch`. Prompts are disabled (GIT_TERMINAL_PROMPT=0).

Never entered, even if found: D:\\IEV_Results, C:\\research\\libsignal_repro.
"""
from __future__ import print_function

import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

BIG = 100 * 1024 * 1024
EXCLUDED = [r"D:\IEV_Results", r"C:\research\libsignal_repro"]
HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
ROOT_PATTERNS = [
    r"C:\research\qmix_protection_study*", r"C:\research\confirmation_B_*", r"C:\research\B_export_*",
    r"C:\research\*qmix*", r"C:\research\*QMIX*", r"C:\research\b_shard*_incident_*.log",
    os.path.join(HOME, "QMIX_PROTECTED"), os.path.join(HOME, "QMIX_Traffic_Coordination"),
    os.path.join(HOME, "QMIX_A003_P3"), os.path.join(HOME, "*QMIX*"), os.path.join(HOME, "*qmix*"),
    r"D:\QMIX_Results", r"D:\*QMIX*",
]
LOOSE_DIRS = [r"C:\research", os.path.join(HOME, "Desktop"), os.path.join(HOME, "Documents"),
              os.path.join(HOME, "Downloads"), os.path.join(HOME, "OneDrive")]
LOOSE_NAME = re.compile(r"qmix|protection[_ ]?study|comparateur|confirmation_B|B_export|ablation|robustness|"
                        r"A00[234]|handoff|passation|article|manuscri", re.I)
LOOSE_EXT = (".zip", ".7z", ".rar", ".tar", ".gz", ".pptx", ".ppt", ".pdf", ".docx", ".tex", ".md", ".odp", ".key")
SENSITIVE = re.compile(r"(^|[\\/._-])(\.?env)($|[._])|secret|token|credential|passw|id_rsa|id_ed25519|\.pem$|"
                       r"\.key$|\.pfx$|\.p12$|\.kdbx$|salt|\bsel\b|_sel[._]|correspond|courriel|\.eml$|\.msg$|"
                       r"\.mbox$|priv[eé]|private|3101|3120|reserved_seed|graines?_reserv", re.I)
FROZEN_HINT = re.compile(r"QMIX_PROTECTED|QMIX_Traffic_Coordination|A00[234]|confirmation_B|comparators_|"
                         r"robustness_validation|protection_ablation|fixed_timing_min7|QMIX_Results", re.I)


def norm(p):
    return os.path.normcase(os.path.abspath(p))


def excluded(p):
    n = norm(p)
    return any(n == norm(e) or n.startswith(norm(e) + os.sep) for e in EXCLUDED)


def run(cmd, cwd=None, timeout=120):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
        return p.returncode, p.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as error:
        return None, repr(error)


def walk(root):
    """Sizes, big files, sensitive names, nested git repositories; never follows excluded paths; opens nothing."""
    total, count, big, largest, sensitive, gits, errors = 0, 0, [], [], [], [], 0
    top = {}
    if os.path.isfile(root):
        s = os.path.getsize(root)
        return {"bytes": s, "files": 1, "big": [(root, s)] if s > BIG else [], "largest": [(root, s)],
                "sensitive": [(root, s)] if SENSITIVE.search(os.path.basename(root)) else [], "git_repos": [],
                "errors": 0, "top": {}}
    for base, dirs, files in os.walk(root, onerror=lambda e: None):
        if excluded(base):
            dirs[:] = []
            continue
        if ".git" in dirs:
            gits.append(base)
            dirs.remove(".git")
        dirs[:] = [d for d in dirs if not excluded(os.path.join(base, d))]
        rel_top = os.path.relpath(base, root).split(os.sep)[0]
        for f in files:
            p = os.path.join(base, f)
            try:
                s = os.path.getsize(p)
            except OSError:
                errors += 1
                continue
            total += s
            count += 1
            top[rel_top] = top.get(rel_top, 0) + s
            if s > BIG:
                big.append((p, s))
            if SENSITIVE.search(f) or SENSITIVE.search(os.path.relpath(p, root)):
                sensitive.append((p, s))
            if len(largest) < 15 or s > largest[-1][1]:
                largest.append((p, s))
                largest = sorted(largest, key=lambda x: -x[1])[:15]
    return {"bytes": total, "files": count, "big": big, "largest": largest, "sensitive": sensitive,
            "git_repos": gits, "errors": errors, "top": top}


def git_info(repo):
    info = {"path": repo}
    _, info["head"] = run(["git", "-C", repo, "log", "-1", "--format=%h %ad %s", "--date=short"])
    _, out = run(["git", "-C", repo, "remote", "-v"])
    info["remotes"] = sorted(set(l.split()[0] + " " + l.split()[1] for l in out.splitlines() if len(l.split()) >= 2))
    _, info["autocrlf"] = run(["git", "-C", repo, "config", "--get", "core.autocrlf"])
    ga = os.path.join(repo, ".gitattributes")
    info["gitattributes"] = ""
    if os.path.isfile(ga):
        with open(ga, encoding="utf-8", errors="replace") as f:
            info["gitattributes"] = f.read().strip()[:300]
    _, out = run(["git", "-C", repo, "--no-optional-locks", "status", "--porcelain", "--untracked-files=normal"], timeout=600)
    lines = [l for l in out.splitlines() if l.strip()]
    info["uncommitted"] = len([l for l in lines if not l.startswith("??")])
    info["untracked"] = len([l for l in lines if l.startswith("??")])
    _, out = run(["git", "-C", repo, "for-each-ref", "--format=%(refname:short)|%(objectname)|%(upstream:short)", "refs/heads"])
    branches = [l.split("|") for l in out.splitlines() if "|" in l]
    _, out = run(["git", "-C", repo, "for-each-ref", "--format=%(refname:short)|%(objectname)", "refs/tags"])
    tags = [l.split("|") for l in out.splitlines() if "|" in l]
    info["branches_local"], info["tags_local"] = len(branches), len(tags)
    remote_heads, reach = {}, {}
    for r in sorted(set(x.split()[0] for x in info["remotes"])):
        code, out = run(["git", "-C", repo, "ls-remote", "--heads", "--tags", r], timeout=120)
        reach[r] = "ok" if code == 0 else "unreachable or not authorised: " + out[:160]
        if code == 0:
            for l in out.splitlines():
                sha, ref = l.split("\t")
                remote_heads.setdefault(r, {})[ref] = sha
    not_pushed = []
    for name, sha, _up in branches:
        on = [r for r, h in remote_heads.items() if h.get("refs/heads/" + name) == sha]
        if not on:
            not_pushed.append(name)
    tags_missing = [t for t, sha in tags if not any("refs/tags/" + t in h for h in remote_heads.values())]
    info["remote_reach"] = reach
    info["branches_not_on_remote_at_same_commit"] = not_pushed
    info["tags_not_on_remote"] = tags_missing
    info["on_github"] = ("non (aucun remote)" if not info["remotes"] else
                         "oui, à jour" if not not_pushed and not tags_missing and all(v == "ok" for v in reach.values())
                         else "partiel ou non vérifiable")
    return info


def manifest_check(root):
    """If root holds a delivery MANIFEST_SHA256.txt: files equal to it, differing, missing, and files not in it."""
    path = os.path.join(root, "MANIFEST_SHA256.txt")
    if not os.path.isfile(path):
        return None
    listed, header = {}, ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f):
            if n == 0 and line.startswith("#"):
                header = line.strip()
                continue
            parts = line.rstrip("\n").split(None, 2)
            if len(parts) == 3:
                listed[parts[2].replace("\\", "/")] = parts[0]
    same, diff, missing = 0, [], []
    for rel, sha in listed.items():
        p = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(p):
            missing.append(rel)
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() == sha:
            same += 1
        else:
            diff.append(rel)
    extra = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), root).replace(os.sep, "/")
            if rel not in listed and rel != "MANIFEST_SHA256.txt" and not rel.endswith(".pyc"):
                extra.append(rel)
    return {"header": header, "listed": len(listed), "identical": same, "differing": diff[:50],
            "missing": missing[:50], "not_in_manifest": sorted(extra)[:200], "not_in_manifest_count": len(extra)}


def proposal(root, w, gits, mani):
    big = sum(s for _p, s in w["big"])
    frozen = bool(FROZEN_HINT.search(root))
    if gits:
        g = gits[0]
        if "oui" in g["on_github"]:
            dest = "déjà sur GitHub : vérifier par reclonage (étape C)"
        elif g["remotes"]:
            dest = "pousser toutes les branches et étiquettes vers le remote existant (sans --force)"
        else:
            dest = "nouveau dépôt privé (gh repo create --private), puis pousser branches et étiquettes"
    elif mani:
        dest = ("copie d'une livraison du code ({}) : les fichiers du manifeste sont sur GitHub si ce commit l'est ; "
                "les {} fichiers hors manifeste vont dans un dépôt privé d'artefacts (ou l'archive s'ils sont gros)").format(
                    mani["header"][:60], mani["not_in_manifest_count"])
    elif big or w["bytes"] > 2 * 1024 ** 3:
        dest = "archive externe avec manifeste SHA-256 ; un petit dépôt privé pour les fichiers < 100 Mo utiles à l'article"
    else:
        dest = "nouveau dépôt privé (fichiers < 100 Mo)"
    if frozen:
        dest += " ; FIGÉ : core.autocrlf false et .gitattributes « * -text »"
    risks = []
    if w["big"]:
        risks.append("{} fichier(s) > 100 Mo ({:.1f} Go) : hors Git".format(len(w["big"]), big / 1e9))
    if w["sensitive"]:
        risks.append("{} fichier(s) au nom sensible : exclus, jamais ouverts".format(len(w["sensitive"])))
    if len(w["git_repos"]) > 1:
        risks.append("{} dépôts Git imbriqués".format(len(w["git_repos"])))
    for g in gits:
        if g.get("uncommitted"):
            risks.append("{} : {} modification(s) non validée(s)".format(g["path"], g["uncommitted"]))
        if g.get("autocrlf") not in ("false", "") and frozen:
            risks.append("{} : core.autocrlf = {!r} (les SHA-256 peuvent changer)".format(g["path"], g["autocrlf"]))
    if w["errors"]:
        risks.append("{} fichier(s) illisible(s) (droits ou chemin trop long)".format(w["errors"]))
    if mani and (mani["differing"] or mani["missing"]):
        risks.append("copie différente de son manifeste : {} différent(s), {} manquant(s)".format(
            len(mani["differing"]), len(mani["missing"])))
    return dest, risks


def fmt(b):
    return "{:.2f} Go".format(b / 1e9) if b >= 1e9 else "{:.1f} Mo".format(b / 1e6)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=r"C:\research\_migration_qmix")
    ap.add_argument("--extra", nargs="*", default=[], help="other QMIX paths to inventory (e.g. a presentations folder)")
    a = ap.parse_args(argv)
    roots = []
    for pat in ROOT_PATTERNS + a.extra:
        for p in sorted(glob.glob(pat)):
            if not excluded(p) and norm(p) not in [norm(r) for r in roots] and norm(p) != norm(a.out) \
                    and not any(norm(p).startswith(norm(r) + os.sep) for r in roots):
                roots.append(p)
    loose = []
    for d in LOOSE_DIRS:
        if not os.path.isdir(d) or excluded(d):
            continue
        for base, dirs, files in os.walk(d):
            depth = os.path.relpath(base, d).count(os.sep)
            dirs[:] = [x for x in dirs if not excluded(os.path.join(base, x)) and depth < 2
                       and not any(norm(os.path.join(base, x)) == norm(r) for r in roots)]
            for f in files:
                p = os.path.join(base, f)
                if f.lower().endswith(LOOSE_EXT) and LOOSE_NAME.search(f) and not any(
                        norm(p).startswith(norm(r) + os.sep) or norm(p) == norm(r) for r in roots):
                    try:
                        loose.append((p, os.path.getsize(p)))
                    except OSError:
                        pass
    items = []
    for r in roots:
        print("inventory:", r)
        w = walk(r)
        gits = [git_info(g) for g in w["git_repos"]] if os.path.isdir(r) else []
        mani = manifest_check(r) if os.path.isdir(r) and w["bytes"] < 2 * 1024 ** 3 else None
        dest, risks = proposal(r, w, gits, mani)
        items.append({"path": r, "bytes": w["bytes"], "files": w["files"], "big_files": w["big"],
                      "largest": w["largest"], "sensitive_names": w["sensitive"], "git": gits, "manifest": mani,
                      "top_level_bytes": w["top"], "destination": dest, "risks": risks, "unreadable": w["errors"]})
    tools = {"git": run(["git", "--version"])[1], "gh": run(["gh", "--version"])[1].splitlines()[:1],
             "gh_auth": run(["gh", "auth", "status"])[1][:400], "python": sys.version.split()[0]}
    drives = {}
    for letter in "CDEFGHIJ":
        p = letter + ":\\"
        if os.path.exists(p):
            u = shutil.disk_usage(p)
            drives[p] = {"total": u.total, "free": u.free}
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"date": stamp, "excluded_never_entered": EXCLUDED, "roots": items, "loose_files": loose,
               "tools": tools, "drives": drives}
    L = ["# INVENTAIRE QMIX — lecture seule ({})".format(stamp), "",
         "Produit par `inventory_qmix.py`. Rien n'a été supprimé, déplacé ni modifié. Jamais parcourus : "
         + ", ".join("`{}`".format(e) for e in EXCLUDED) + ". Les fichiers au nom sensible sont listés, **jamais ouverts**.", "",
         "## Synthèse", "", "| Chemin | Taille | Fichiers | > 100 Mo | Git / GitHub | Destination proposée | Risques |",
         "|---|---|---|---|---|---|---|"]
    for it in items:
        g = "; ".join("{} : {}".format(os.path.relpath(x["path"], it["path"]) if x["path"] != it["path"] else "racine",
                                       x["on_github"]) for x in it["git"]) or "pas un dépôt Git"
        cells = [it["path"], fmt(it["bytes"]), it["files"], len(it["big_files"]), g, it["destination"],
                 "<br>".join(it["risks"]) or "—"]
        cells = [str(c).replace("|", "\\|") for c in cells]
        L.append("| `{}` | {} | {} | {} | {} | {} | {} |".format(*cells))
    L += ["", "## Détail par chemin", ""]
    for it in items:
        L += ["### `{}`".format(it["path"]), "", "- taille {} ; {} fichiers ; {} illisible(s)".format(
            fmt(it["bytes"]), it["files"], it["unreadable"])]
        if it["top_level_bytes"]:
            L.append("- sous-dossiers : " + ", ".join("`{}` {}".format(k, fmt(v)) for k, v in
                                                     sorted(it["top_level_bytes"].items(), key=lambda x: -x[1])[:12]))
        for x in it["git"]:
            L += ["- dépôt Git `{}` : HEAD {} ; remotes {} ; core.autocrlf {!r} ; .gitattributes {!r}".format(
                x["path"], x["head"], x["remotes"] or "aucun", x["autocrlf"], x["gitattributes"][:80]),
                "  - branches locales {} ; étiquettes {} ; non validé {} ; non suivi {}".format(
                    x["branches_local"], x["tags_local"], x["uncommitted"], x["untracked"]),
                "  - branches absentes du remote (ou à un autre commit) : {}".format(x["branches_not_on_remote_at_same_commit"] or "aucune"),
                "  - étiquettes absentes du remote : {}".format(x["tags_not_on_remote"] or "aucune"),
                "  - accès aux remotes : {}".format(x["remote_reach"] or "—")]
        if it["manifest"]:
            m = it["manifest"]
            L.append("- manifeste de livraison `{}` : {} listés, {} identiques, {} différents, {} manquants, {} fichiers hors manifeste".format(
                m["header"][:70], m["listed"], m["identical"], len(m["differing"]), len(m["missing"]), m["not_in_manifest_count"]))
            if m["not_in_manifest"]:
                L.append("  - hors manifeste (extrait) : " + ", ".join("`{}`".format(x) for x in m["not_in_manifest"][:30]))
        if it["big_files"]:
            L.append("- fichiers > 100 Mo : " + ", ".join("`{}` ({})".format(p, fmt(s)) for p, s in it["big_files"][:30]))
        L.append("- plus gros fichiers : " + ", ".join("`{}` ({})".format(os.path.relpath(p, it["path"]) if p != it["path"] else p, fmt(s))
                                                      for p, s in it["largest"][:8]))
        if it["sensitive_names"]:
            L.append("- **noms sensibles (non ouverts, à exclure)** : " + ", ".join("`{}`".format(p) for p, _s in it["sensitive_names"][:50]))
        L.append("")
    L += ["## Fichiers isolés au nom QMIX (ZIP, présentations, articles) — à confirmer", ""]
    L += ["- `{}` ({}){}".format(p, fmt(s), " — **nom sensible, non ouvert**" if SENSITIVE.search(p) else "") for p, s in loose] or ["- aucun trouvé"]
    L += ["", "## Outils et disques", "", "- git : {}".format(tools["git"]), "- gh : {}".format(tools["gh"]),
          "- gh auth status : `{}`".format(tools["gh_auth"].replace("\n", " | ")),
          "- disques : " + ", ".join("{} {} libres sur {}".format(k, fmt(v["free"]), fmt(v["total"])) for k, v in drives.items()),
          "", "## À valider avant l'étape B", "",
          "1. La liste des chemins est-elle complète (présentations QMIX, autres ZIP de l'article) ? Sinon, relancer avec `--extra <chemin>`.",
          "2. Le support de l'archive externe des gros volumes (disque externe ou service en ligne).",
          "3. Les noms des dépôts privés à créer.", ""]
    name = "INVENTAIRE.md"
    if os.path.exists(os.path.join(a.out, name)):
        name = "INVENTAIRE_{}.md".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(os.path.join(a.out, name), "x", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    jname = name.replace("INVENTAIRE", "inventaire").replace(".md", ".json")
    with open(os.path.join(a.out, jname), "x", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    print("written {} and {} in {}".format(name, jname, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
