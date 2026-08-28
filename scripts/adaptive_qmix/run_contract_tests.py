"""Run the mandatory adaptive contract suite from an Anaconda Prompt."""

from __future__ import print_function

import os
import sys
import unittest


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPOSITORY_ROOT)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "src"))


def main():
    suite = unittest.defaultTestLoader.discover(
        os.path.join(REPOSITORY_ROOT, "tests"),
        pattern="test_*.py",
        top_level_dir=REPOSITORY_ROOT,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

