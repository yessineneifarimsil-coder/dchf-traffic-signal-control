import ast, sys, os, warnings
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import old_rule as OLD, test_text_encoding as NEW
warnings.simplefilter("ignore"); OLD.ROOT = os.path.abspath(sys.argv[3])
real_parse = ast.parse
OLD.ast.parse = lambda src: NEW.as_python37(real_parse(src))      # the old rule, fed Python 3.7 trees
sample = ('open(p)\nopen(p, "w")\nopen(p, "rb")\nopen(p, mode="a", encoding="utf-8")\n'
          'gzip.open(p, "rt")\ngzip.open(p)\nos.open(p, 1)\nopen(p, m)\nq.read_text()\n'
          'NamedTemporaryFile("w")\n')
print("old rule, Python 3.7 form, sample:", sorted(l for l, _ in OLD.unencoded_text_opens(sample)))
bad = []
for rel, path in OLD.python_files():
    if rel in OLD.SEALED: continue
    bad += ["{}:{} {}".format(rel, l, w) for l, w in OLD.unencoded_text_opens(open(path, encoding="utf-8").read())]
print("old rule, Python 3.7 form, whole code:", len(bad), "| first:", bad[0] if bad else None)
others = [b for b in bad if not b.startswith("tests/test_text_encoding.py")]
print("excluding the new version of test_text_encoding.py itself:", len(others), "(Windows on b574cbd: 34)")
