"""Free space on D: without losing information: archive the design-stage run folders of campaign A in a zip.

    python tools/disk/archive_campaign_A.py archive  --a-root <A root> [--zip <path>]
    python tools/disk/archive_campaign_A.py --dry-run --a-root <A root> [--zip <path>]
    python tools/disk/archive_campaign_A.py --delete ...   DISABLED in this delivery (refused, nothing deleted)

DELETION IS DISABLED (rectificatif of 2026-11-23): no data of campaign A is deleted by this delivery. The audit and
the creation of verified archives stay allowed. The two-step deletion logic below is kept, tested, and refused at
run time while DELETION_ENABLED is False; enabling it needs a new, explicitly authorised delivery.

Without --zip, archive chooses the drive with the most free space and records the path in
logs\campaignA_archive.json; --dry-run and --delete then read it from there.

Archived: the run folders listed by orders\\coarse.json, fine-g5.json, fine-min7.json, actuated-design.json,
tod-design-g5.json and tod-design-min7.json.
NEVER archived nor deleted: plan.json, orders\\, selections\\, run_log_*.jsonl, manifests\\, and every run folder
listed by validation-*, actuated-validation, tod-validation-* or robustness-eval (a folder listed by one of these
protected stages is excluded even if a design stage also lists it).

archive: writes <zip> (members under the A root, .gz members stored, others deflated) and <zip>.manifest.json
  (member, size, SHA-256 of the source file), then re-opens the zip and checks the member count and the SHA-256
  of every member read back, and writes <zip>.verification.json with the SHA-256 of the zip. Refuses an
  existing zip. Default zip location: the drive (C: or D:) with the most free space.
--dry-run: lists the folders a later, authorised deletion would remove and the space it would free (nothing
  is changed).
--delete --confirm <sha256>: deletes the archived folders only if the verification file says OK, the zip still
  has that SHA-256, and every source file still has the size and SHA-256 recorded in the manifest.
After deletion campaign A's `comparators-progress` no longer finds these folders (they read "not started"):
the zip restores them (tar -xf or any unzip).
"""
from __future__ import absolute_import, division, print_function

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile

ARCHIVED_STAGES = ("coarse", "fine-g5", "fine-min7", "actuated-design", "tod-design-g5", "tod-design-min7")
PROTECTED_STAGES = ("validation-g5", "validation-min7", "actuated-validation", "tod-validation-g5",
                    "tod-validation-min7", "robustness-eval")
PROTECTED_TOP = ("plan.json", "orders", "selections", "manifests")
DELETION_ENABLED = False      # rectificatif 2026-11-23: no deletion of campaign A data in this delivery
DELETION_DISABLED_MESSAGE = ("deletion of campaign A data is disabled in this delivery (rectificatif of 2026-11-23): "
                             "audit and verified archives only; nothing was deleted")


class ArchiveError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def stage_dirs(root, stages):
    out = set()
    for stage in stages:
        path = os.path.join(root, "orders", stage + ".json")
        if os.path.isfile(path):
            out.update(os.path.normpath(j["directory"]) for j in read_json(path)["jobs"])
    return out


def selected_folders(root):
    """Run folders to archive: listed by an archived stage, not by a protected stage, existing on disk."""
    missing = [s for s in ARCHIVED_STAGES if not os.path.isfile(os.path.join(root, "orders", s + ".json"))]
    if missing:
        raise ArchiveError("orders missing for {}: the stage of a run folder cannot be established".format(missing))
    wanted = stage_dirs(root, ARCHIVED_STAGES) - stage_dirs(root, PROTECTED_STAGES)
    folders = []
    for rel in sorted(wanted):
        parts = rel.split(os.sep)
        if parts[0] != "runs" or len(parts) != 4:
            raise ArchiveError("unexpected run folder {}".format(rel))
        if os.path.isdir(os.path.join(root, rel)):
            folders.append(rel)
    return folders


def files_of(root, folders):
    out = []
    for rel in folders:
        for directory, _dirs, names in os.walk(os.path.join(root, rel)):
            for name in sorted(names):
                out.append(os.path.relpath(os.path.join(directory, name), root))
    for f in out:
        top = f.split(os.sep)[0]
        if top in PROTECTED_TOP or os.path.basename(f).startswith("run_log_"):
            raise ArchiveError("refusing to archive a protected file: {}".format(f))
    return out


def default_zip(root):
    best, best_free = None, -1
    for drive in ("C:\\", "D:\\"):
        try:
            free = shutil.disk_usage(drive).free
        except OSError:
            continue
        if free > best_free:
            best, best_free = drive, free
    base = best or os.path.dirname(os.path.abspath(root))
    return os.path.join(base, "QMIX_archives", "campaignA_design_runs.zip")


def archive(root, zip_path):
    if os.path.exists(zip_path):
        raise ArchiveError("{} exists: refused".format(zip_path))
    folders = selected_folders(root)
    files = files_of(root, folders)
    if not os.path.isdir(os.path.dirname(os.path.abspath(zip_path))):
        os.makedirs(os.path.dirname(os.path.abspath(zip_path)))
    manifest = []
    with zipfile.ZipFile(zip_path, "x", allowZip64=True) as z:
        for rel in files:
            src = os.path.join(root, rel)
            member = rel.replace(os.sep, "/")
            mode = zipfile.ZIP_STORED if rel.endswith(".gz") else zipfile.ZIP_DEFLATED
            z.write(src, member, compress_type=mode)
            manifest.append({"member": member, "bytes": os.path.getsize(src), "sha256": sha256_file(src)})
    with open(zip_path + ".manifest.json", "w", encoding="utf-8") as handle:
        json.dump({"a_root": os.path.abspath(root), "folders": [f.replace(os.sep, "/") for f in folders],
                   "files": manifest}, handle, indent=0)
    return verify(root, zip_path)


def verify(root, zip_path):
    manifest = read_json(zip_path + ".manifest.json")
    problems = []
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if len(names) != len(manifest["files"]):
            problems.append("zip has {} members, manifest {}".format(len(names), len(manifest["files"])))
        for entry in manifest["files"]:
            try:
                data = z.read(entry["member"])
            except KeyError:
                problems.append("missing member " + entry["member"])
                continue
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                problems.append("member differs: " + entry["member"])
    result = {"zip": os.path.abspath(zip_path), "zip_sha256": sha256_file(zip_path), "members": len(names),
              "folders": len(manifest["folders"]), "bytes_archived": sum(e["bytes"] for e in manifest["files"]),
              "ok": not problems, "problems": problems[:50]}
    with open(zip_path + ".verification.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)
    return result


def dry_run(root, zip_path):
    folders = selected_folders(root)
    total = sum(os.path.getsize(os.path.join(root, f)) for f in files_of(root, folders))
    verified = None
    if os.path.isfile(zip_path + ".verification.json"):
        verified = read_json(zip_path + ".verification.json")
    return {"folders_to_delete": len(folders), "bytes_freed": total, "gb_freed": round(total / 1e9, 3),
            "examples": [f.replace(os.sep, "/") for f in folders[:10]],
            "zip_verified": bool(verified and verified["ok"]), "zip_sha256": verified["zip_sha256"] if verified else None}


def delete(root, zip_path, confirm):
    if not DELETION_ENABLED:
        raise ArchiveError(DELETION_DISABLED_MESSAGE)
    if not os.path.isfile(zip_path + ".verification.json"):
        raise ArchiveError("no verification file: run archive first")
    verification = read_json(zip_path + ".verification.json")
    if not verification["ok"]:
        raise ArchiveError("the zip verification failed: nothing deleted")
    if confirm != verification["zip_sha256"]:
        raise ArchiveError("--confirm must be the verified zip SHA-256 {}".format(verification["zip_sha256"]))
    if sha256_file(zip_path) != confirm:
        raise ArchiveError("the zip changed since its verification: nothing deleted")
    manifest = read_json(zip_path + ".manifest.json")
    protected = stage_dirs(root, PROTECTED_STAGES)
    for entry in manifest["files"]:
        src = os.path.join(root, entry["member"].replace("/", os.sep))
        if not os.path.isfile(src) or os.path.getsize(src) != entry["bytes"] or sha256_file(src) != entry["sha256"]:
            raise ArchiveError("source changed or missing since the archive: {} (nothing deleted)".format(entry["member"]))
    freed = 0
    for rel in manifest["folders"]:
        rel = os.path.normpath(rel)
        if rel in protected or rel.split(os.sep)[0] != "runs":
            raise ArchiveError("refusing to delete {}".format(rel))
        freed += sum(os.path.getsize(os.path.join(d, n)) for d, _s, ns in os.walk(os.path.join(root, rel)) for n in ns)
        shutil.rmtree(os.path.join(root, rel))
    with open(zip_path + ".deleted.json", "w", encoding="utf-8") as handle:
        json.dump({"folders_deleted": len(manifest["folders"]), "bytes_freed": freed, "zip_sha256": confirm}, handle)
    return {"folders_deleted": len(manifest["folders"]), "gb_freed": round(freed / 1e9, 3)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", choices=("archive",))
    ap.add_argument("--a-root", default=r"D:\QMIX_Results\comparators_robustness_profiles")
    ap.add_argument("--zip")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--confirm")
    a = ap.parse_args(argv)
    pointer = os.path.join("logs", "campaignA_archive.json")
    if a.zip:
        zip_path = a.zip
    elif os.path.isfile(pointer):
        zip_path = read_json(pointer)["zip"]
    else:
        zip_path = default_zip(a.a_root)
    try:
        if a.delete:
            if not DELETION_ENABLED:
                raise ArchiveError(DELETION_DISABLED_MESSAGE)
            if not a.confirm:
                raise ArchiveError("--delete needs --confirm <sha256 of the verified zip>")
            result = delete(a.a_root, zip_path, a.confirm)
        elif a.dry_run:
            result = dry_run(a.a_root, zip_path)
        elif a.action == "archive":
            result = archive(a.a_root, zip_path)
            if not os.path.isdir("logs"):
                os.makedirs("logs")
            with open(pointer, "w", encoding="utf-8") as handle:
                json.dump({"zip": os.path.abspath(zip_path), "zip_sha256": result["zip_sha256"]}, handle)
        else:
            ap.error("choose archive or --dry-run (--delete is disabled in this delivery)")
    except ArchiveError as error:
        print("STOP:", error)
        return 1
    print(json.dumps(dict(result, zip=os.path.abspath(zip_path)), indent=1))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
