"""Build the verified delivery archive of the study workspace (code, tests, plans, logs, diagnosis, derived
analysis data, figures, manuscript). Raw simulation outputs stay on D: and are referenced by the plans' hashes.

    python tools/make_archive.py [--out D:\\QMIX_Results\\deliveries]

Writes <out>/qmix_protection_study_<git short sha>.zip containing MANIFEST_SHA256.txt (sha256 + size of every
member), refuses an existing destination, then re-opens the zip and verifies every member against the manifest.
Prints the archive's own sha256 (also written next to it as .sha256).
"""
import argparse
import hashlib
import io
import os
import subprocess
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXCLUDE_DIRS = {".git", "__pycache__", "outputs_local"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=r"D:\QMIX_Results\deliveries")
    a = ap.parse_args()
    head = subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"]).decode().strip()
    dirty = subprocess.check_output(["git", "-C", ROOT, "status", "--porcelain"]).decode().strip()
    if dirty:
        raise SystemExit("REFUSED: commit the workspace first (git status not clean)")
    os.makedirs(a.out, exist_ok=True)
    dest = os.path.join(a.out, "qmix_protection_study_{}.zip".format(head))
    if os.path.exists(dest):
        raise SystemExit("REFUSED: {} exists".format(dest))
    files = []
    for d, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(x for x in dirs if x not in EXCLUDE_DIRS)
        for n in sorted(names):
            if n.endswith(".pyc"):
                continue
            p = os.path.join(d, n)
            files.append((os.path.relpath(p, ROOT).replace("\\", "/"), p))
    lines = []
    with zipfile.ZipFile(dest, "x", zipfile.ZIP_DEFLATED) as z:
        for rel, p in files:
            data = open(p, "rb").read()
            z.writestr(rel, data)
            lines.append("{}  {:>10}  {}".format(sha(data), len(data), rel))
        manifest = "# git {} | {} files\n".format(head, len(lines)) + "\n".join(lines) + "\n"
        z.writestr("MANIFEST_SHA256.txt", manifest)
    bad = 0
    with zipfile.ZipFile(dest) as z:
        for line in z.read("MANIFEST_SHA256.txt").decode().splitlines()[1:]:
            h, size, rel = line.split(None, 2)
            data = z.read(rel)
            bad += sha(data) != h or len(data) != int(size)
    archive_sha = sha(open(dest, "rb").read())
    with open(dest + ".sha256", "w") as f:
        f.write("{}  {}\n".format(archive_sha, os.path.basename(dest)))
    print("archive {} | {} members verified, {} mismatches | sha256 {}".format(dest, len(lines), bad, archive_sha))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
