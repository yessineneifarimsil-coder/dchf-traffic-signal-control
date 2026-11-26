"""Shared helpers of the public export of B (2026-11-26). Read-only on every source; writes only in the export folder.

Paths in exported text: the home folder (C:\\Users\\<user>, or $HOME) becomes <home>, the root of B becomes <BCONF>,
the export folder <EXPORT>. Every file is written once (mode "x"): an existing file is never overwritten.
"""
from __future__ import absolute_import, division, print_function

import csv
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
CONF = os.path.join(TOOLS, "confirmation")
for p in (CONF,):
    if p not in sys.path:
        sys.path.insert(0, p)

HOME_PATTERNS = (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.I),)


class ExportError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Scrubber(object):
    """Replaces personal and machine-specific paths. Longest prefixes first; both slash styles; any case."""

    def __init__(self, bconf=None, export=None, extra=()):
        pairs = []
        for value, token in ((bconf, "<BCONF>"), (export, "<EXPORT>")) + tuple(extra):
            if value:
                forms = {value.rstrip("\\/")}
                if not re.match(r"^[A-Za-z]:[\\/]", value):
                    forms.add(os.path.abspath(value))
                for a in list(forms):
                    for form in {a, a.replace("\\", "/"), a.replace("/", "\\")}:
                        pairs.append((form, token))
        home = os.path.expanduser("~")
        if home and home not in ("~", "/", "\\") and len(home) > 3:
            for form in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
                pairs.append((form, "<home>"))
        self.pairs = sorted(set(pairs), key=lambda p: -len(p[0]))

    def __call__(self, text):
        if not isinstance(text, str):
            return text
        for value, token in self.pairs:
            text = re.sub(re.escape(value), token.replace("\\", "\\\\"), text, flags=re.I)
        for pattern in HOME_PATTERNS:
            text = pattern.sub("<home>", text)
        # JSON-escaped Windows paths (C:\\Users\\name)
        text = re.sub(r"[A-Za-z]:(\\\\)+Users(\\\\)+[^\\\"\s]+", "<home>", text, flags=re.I)
        return text

    def obj(self, value):
        if isinstance(value, dict):
            return dict((self(k), self.obj(v)) for k, v in value.items())
        if isinstance(value, list):
            return [self.obj(v) for v in value]
        if isinstance(value, tuple):
            return [self.obj(v) for v in value]
        return self(value)


def write_text_once(path, text):
    with open(path, "x", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json_once(path, payload, scrub):
    write_text_once(path, json.dumps(scrub.obj(payload), indent=1, sort_keys=True) + "\n")


def write_csv_once(path, fields, rows, scrub):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(dict((k, scrub(r.get(k, "")) if isinstance(r.get(k, ""), str) else r.get(k, "")) for k in fields))
    write_text_once(path, buf.getvalue())


def fnum(x):
    """Exact text of a number (repr round-trips a float), '' for None."""
    if x is None:
        return ""
    if isinstance(x, bool):
        return "1" if x else "0"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return repr(x)
    return str(x)


def find_lines(path, pattern, flags=0):
    """[(line number, text)] of the lines of path matching the regex (read-only)."""
    out = []
    rx = re.compile(pattern, flags)
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            if rx.search(line):
                out.append((n, line.rstrip("\n")))
    return out


def ensure_export_dir(path, must_be_new=False):
    if must_be_new and os.path.exists(path) and os.listdir(path):
        raise ExportError("{} exists and is not empty: the export goes into a NEW folder".format(path))
    os.makedirs(path, exist_ok=True)
    return path
