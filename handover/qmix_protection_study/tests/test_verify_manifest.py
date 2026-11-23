"""Tests of tools/verify_manifest.py (read-only check of a working copy against MANIFEST_SHA256.txt)."""
import hashlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import verify_manifest as VM  # noqa: E402


class Manifest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "tools"))
        lines = ["# base"]
        for rel, data in (("a.txt", b"alpha"), ("tools/b.py", b"print(1)\r\n")):
            with open(os.path.join(self.root, *rel.split("/")), "wb") as f:
                f.write(data)
            lines.append("{} {:>11}  {}".format(hashlib.sha256(data).hexdigest(), len(data), rel))
        with open(os.path.join(self.root, "MANIFEST_SHA256.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_main(self):
        with redirect_stdout(io.StringIO()) as out:
            code = VM.main(["--root", self.root])
        return code, out.getvalue()

    def test_clean_copy_passes_and_extras_do_not_fail(self):
        with open(os.path.join(self.root, "logs.txt"), "w") as f:
            f.write("later")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("MANIFEST OK", out)
        self.assertIn("1 extra", out)

    def test_changed_or_missing_file_fails(self):
        with open(os.path.join(self.root, "tools", "b.py"), "wb") as f:
            f.write(b"print(1)\n")                         # CRLF lost: detected
        os.remove(os.path.join(self.root, "a.txt"))
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("different: tools/b.py", out)
        self.assertIn("missing: a.txt", out)


if __name__ == "__main__":
    unittest.main()
