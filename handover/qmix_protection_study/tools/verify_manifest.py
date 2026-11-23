"""Read-only check of a working copy against its MANIFEST_SHA256.txt (sha256, size, path per line).

    python tools/verify_manifest.py [--root <working copy>]

Exit 0 when every listed file exists with its size and SHA-256; 1 otherwise (each difference is printed).
Files not listed (logs written later, __pycache__) are reported as extra but do not fail the check.
"""
from __future__ import absolute_import, print_function

import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def check(root):
    listed, problems = set(), []
    with open(os.path.join(root, "MANIFEST_SHA256.txt")) as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            digest, size, path = line.split(None, 2)
            path = path.strip()
            listed.add(path)
            full = os.path.join(root, *path.split("/"))
            if not os.path.isfile(full):
                problems.append("missing: " + path)
                continue
            with open(full, "rb") as f:
                data = f.read()
            if len(data) != int(size) or hashlib.sha256(data).hexdigest() != digest:
                problems.append("different: " + path)
    extra = []
    for a, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            rel = os.path.relpath(os.path.join(a, f), root).replace(os.sep, "/")
            if rel != "MANIFEST_SHA256.txt" and rel not in listed:
                extra.append(rel)
    return len(listed), problems, sorted(extra)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=os.path.dirname(HERE))
    a = ap.parse_args(argv)
    n, problems, extra = check(a.root)
    for p in problems:
        print(p)
    print("{} files listed, {} problems, {} extra files (not failing)".format(n, len(problems), len(extra)))
    print("MANIFEST OK" if not problems else "MANIFEST NOT OK")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
