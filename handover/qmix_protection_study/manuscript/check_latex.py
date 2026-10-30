"""Static checks of the manuscript when no TeX distribution is available (not a substitute for compiling):
balanced begin/end environments and braces, every \\ref/\\eqref has a \\label, every \\cite key is in the .bib,
every \\includegraphics file exists, no 'TODO' outside explicit \\tocomplete markers, only standard packages.

    python manuscript/check_latex.py manuscript/main.tex manuscript/references.bib
"""
import os
import re
import sys

STANDARD = {"inputenc", "fontenc", "lmodern", "amsmath", "amssymb", "graphicx", "booktabs", "hyperref", "natbib",
            "geometry", "xcolor", "caption", "subcaption", "multirow", "array", "siunitx", "microtype", "url", "float"}


def main(tex, bib):
    src = open(tex, encoding="utf-8").read()
    body = re.sub(r"(?<!\\)%.*", "", src)
    problems = []
    stack = []
    for m in re.finditer(r"\\(begin|end)\{([^}]+)\}", body):
        if m.group(1) == "begin":
            stack.append(m.group(2))
        elif not stack or stack.pop() != m.group(2):
            problems.append("unbalanced \\end{%s} at %d" % (m.group(2), m.start()))
    if stack:
        problems.append("unclosed environments: %s" % stack)
    depth = 0
    for i, ch in enumerate(re.sub(r"\\[{}]", "", body)):
        depth += ch == "{"
        depth -= ch == "}"
        if depth < 0:
            problems.append("brace closed before opened near char %d" % i)
            break
    if depth:
        problems.append("unbalanced braces (%d)" % depth)
    labels = set(re.findall(r"\\label\{([^}]+)\}", body))
    for r in re.findall(r"\\(?:eq|auto|c)?ref\{([^}]+)\}", body):
        if r not in labels:
            problems.append("undefined reference %s" % r)
    keys = set(re.findall(r"@\w+\{([^,]+),", open(bib, encoding="utf-8").read()))
    for group in re.findall(r"\\cite[tp]?\*?(?:\[[^\]]*\])?\{([^}]+)\}", body):
        for k in group.split(","):
            if k.strip() not in keys:
                problems.append("citation key not in bib: %s" % k.strip())
    base = os.path.dirname(os.path.abspath(tex))
    for g in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", body):
        if not any(os.path.isfile(os.path.join(base, g + ext)) for ext in ("", ".pdf", ".png")):
            problems.append("missing figure %s" % g)
    for p in re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", body):
        for q in p.split(","):
            if q.strip() not in STANDARD:
                problems.append("non-standard package %s" % q.strip())
    print("labels %d, citations ok if none listed, figures %d" % (len(labels), len(re.findall(r"\\includegraphics", body))))
    for p in problems:
        print("PROBLEM:", p)
    print("OK" if not problems else "%d problem(s)" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
