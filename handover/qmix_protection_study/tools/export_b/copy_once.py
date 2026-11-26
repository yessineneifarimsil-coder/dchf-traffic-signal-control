"""Copy one file into the export, refusing to overwrite (python copy_once.py <source> <destination>)."""
import shutil
import sys

if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "rb") as a, open(dst, "xb") as b:
        shutil.copyfileobj(a, b)
    print("copied {} -> {}".format(src, dst))
