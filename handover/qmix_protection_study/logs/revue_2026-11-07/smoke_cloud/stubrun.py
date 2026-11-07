"""Cloud-only wrapper: registers an empty stand-in for the absent protected package (the N adapter imports it),
then runs comparator_search.py with the given arguments. Never used on Windows."""
import os, runpy, sys, types
for name in ("adaptive_qmix_protected", "adaptive_qmix_protected.evaluation"):
    sys.modules.setdefault(name, types.ModuleType(name))
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
