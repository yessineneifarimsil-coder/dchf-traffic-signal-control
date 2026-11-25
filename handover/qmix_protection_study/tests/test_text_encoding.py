"""Text encoding on Windows (retour of 2026-11-25).

Under Windows, Python 3.7 opens a text file without an explicit encoding in the ANSI code page (cp1252), and
write_report failed on "D̄" (D-bar). Rules checked here, statically, on the code of this delivery:

1. every text-mode open() / gzip.open(..., "rt"/"wt") / Path.read_text() / write_text() names its encoding;
2. the literal strings given to print() are ASCII, so a cp850/cp1252 console never makes a print fail
   (ETAPES.cmd also sets PYTHONIOENCODING=utf-8, checked in test_etapes_cmd).

SEALED files are exempt and must stay byte-for-byte unchanged: their SHA-256 is recorded in the plans of
campaigns already run (campaign A comparator_search CODE_FILES, robustness plan.json, ablation plan.json), and
robustness_analysis.py refuses to run when its own hash differs from the robustness plan. They only read and
write ASCII files (json.dump keeps ensure_ascii, numeric CSV, SUMO outputs). Historical review scripts
(review/, logs/) are evidence of earlier reviews and are not run by ETAPES.cmd.
"""
import ast
import os
import unittest
import warnings

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCOPE = ("tools", "tests", "diagnosis", "docs", "figures", "manuscript")
SEALED = {
    "tools/comparators/comparator_search.py", "tools/comparators/grids.py", "tools/comparators/controllers.py",
    "tools/comparators/evaluate_comparator.py", "tools/comparators/seeds.py",
    "tools/robustness/robustness_runner.py", "tools/robustness/evaluate_any.py", "tools/robustness/n_adapter.py",
    "tools/robustness/scenario_traffic.py", "tools/robustness/robustness_analysis.py",
    "tools/robustness/cell_state.py", "tools/ablation_runner.py",
}
COMPRESSED = ("gzip", "bz2", "lzma")


def python_files():
    for top in SCOPE:
        for d, dirs, names in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for n in sorted(names):
                if n.endswith(".py"):
                    p = os.path.join(d, n)
                    yield os.path.relpath(p, ROOT).replace(os.sep, "/"), p


def literal_str(node):
    """The value of a string literal, whatever the Python version: Python 3.7 parses it as ast.Str (field s),
    Python 3.8 and later as ast.Constant (field value). None for anything else."""
    if type(node).__name__ == "Constant":
        return node.value if isinstance(node.value, str) else None
    if type(node).__name__ == "Str":
        return node.s if isinstance(getattr(node, "s", None), str) else None
    return None


def parse(source):
    """Parse without warnings: a docstring such as "logs\\campaign" gives an invalid-escape warning on parse,
    which says nothing about the file's encoding."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(source)


def mode_of(node, position):
    for k in node.keywords:
        if k.arg == "mode":
            return k.value
    return node.args[position] if len(node.args) > position else None


def unencoded_text_opens(source):
    """(line, call) of every text-mode open-like call without encoding=; a non-literal mode is reported too.
    source: the text of a file, or an already parsed tree."""
    found = []
    tree = parse(source) if isinstance(source, str) else source
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or any(k.arg == "encoding" for k in node.keywords):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None
        if name in ("read_text", "write_text"):
            found.append((node.lineno, name))
            continue
        if name != "open" or owner not in (None, "io", "codecs") + COMPRESSED:
            continue
        mode = mode_of(node, 1)
        if mode is not None and literal_str(mode) is None:
            found.append((node.lineno, "open with a non-literal mode"))
            continue
        text = literal_str(mode) if mode is not None else ("rb" if owner in COMPRESSED else "r")
        if "b" not in text:
            found.append((node.lineno, "{}open({!r})".format(owner + "." if owner else "", text)))
    return found


def non_ascii_print_literals(source):
    found = []
    tree = parse(source) if isinstance(source, str) else source
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            for sub in ast.walk(node):
                text = literal_str(sub)
                if text is not None:
                    try:
                        text.encode("ascii")
                    except UnicodeEncodeError:
                        found.append((node.lineno, text[:40]))
    return found


class Str(ast.AST):
    """The string node of Python 3.7 (ast.Str, field s), rebuilt here so that the rule is checked on both forms."""
    _fields = ("s",)


def as_python37(tree):
    """The same tree with every string literal as Python 3.7 parses it (Str instead of Constant)."""
    class Back(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str):
                return ast.copy_location(Str(s=node.value), node)
            return node
    return Back().visit(tree)


class TextEncoding(unittest.TestCase):

    def test_every_text_open_names_its_encoding(self):
        bad = []
        for rel, path in python_files():
            if rel in SEALED:
                continue
            with open(path, encoding="utf-8") as f:
                bad += ["{}:{} {}".format(rel, line, what) for line, what in unencoded_text_opens(f.read())]
        self.assertEqual(bad, [])

    def test_the_rule_catches_what_it_should(self):
        sample = ('open(p)\nopen(p, "w")\nopen(p, "rb")\nopen(p, mode="a", encoding="utf-8")\n'
                  'gzip.open(p, "rt")\ngzip.open(p)\nos.open(p, 1)\nopen(p, m)\nq.read_text()\n'
                  'NamedTemporaryFile("w")\n')
        expected = [1, 2, 5, 8, 9]                        # NamedTemporaryFile is not used by this code
        for source in (sample, sample.replace("\n", "\r\n")):          # LF and CRLF files
            self.assertEqual(sorted(line for line, _ in unencoded_text_opens(source)), expected)
            # Python 3.7 form of the same code (ast.Str), whatever the Python running the test
            self.assertEqual(sorted(line for line, _ in unencoded_text_opens(as_python37(parse(source)))), expected)
        printed = 'print("ok")\nprint("D\u0304 {}".format(x))\n'
        self.assertEqual([line for line, _ in non_ascii_print_literals(printed)], [2])
        self.assertEqual([line for line, _ in non_ascii_print_literals(as_python37(parse(printed)))], [2])

    def test_the_whole_code_under_the_python37_form(self):
        """The rules give the same answer on the trees rebuilt as Python 3.7 parses them (retour of 2026-11-25:
        under Python 3.7 every literal mode was taken for a non-literal one)."""
        bad = []
        for rel, path in python_files():
            if rel in SEALED:
                continue
            with open(path, "rb") as f:
                source = f.read().decode("utf-8")
            bad += ["{}:{} {}".format(rel, line, what) for line, what in unencoded_text_opens(as_python37(parse(source)))]
            if rel.startswith("tools/"):
                bad += ["{}:{} {!r}".format(rel, line, t) for line, t in non_ascii_print_literals(as_python37(parse(source)))]
        self.assertEqual(bad, [])

    def test_paths_are_compared_with_forward_slashes(self):
        rels = dict(python_files())
        self.assertTrue(all("\\" not in rel for rel in rels))
        self.assertTrue(SEALED <= set(rels), sorted(SEALED - set(rels)))

    def test_the_sealed_files_exist(self):
        for rel in SEALED:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), rel)

    def test_print_literals_are_ascii(self):
        bad = []
        for rel, path in python_files():
            if rel in SEALED or not rel.startswith("tools/"):
                continue
            with open(path, encoding="utf-8") as f:
                bad += ["{}:{} {!r}".format(rel, line, text) for line, text in non_ascii_print_literals(f.read())]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
