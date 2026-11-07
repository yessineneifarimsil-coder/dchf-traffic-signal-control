import csv, sys, collections
def segments(path):
    seq = collections.defaultdict(list)
    for r in csv.DictReader(open(path)):
        seq[r["intersection"]].append((int(float(r["time"])), r["actual_phase"]))
    out = {}
    for tl, s in seq.items():
        s.sort(); segs = []
        for t, p in s:
            if segs and segs[-1][0] == p: segs[-1][2] = t
            else: segs.append([p, t, t])
        out[tl] = [(p, a, b - a + 1) for p, a, b in segs]
    return out
if __name__ == "__main__":
    for tl, segs in sorted(segments(sys.argv[1]).items()):
        bad = [(segs[i-1][0], segs[i][0]) for i in range(1, len(segs)) if segs[i][0] != "Y" and segs[i-1][0] != "Y"]
        ylen = collections.Counter(d for p, a, d in segs if p == "Y")
        greens = [d for p, a, d in segs[:-1] if p != "Y"]
        hv = collections.Counter(p for p, a, d in segs if p != "Y")
        print(tl, "segments", len(segs), "direct green-green", len(bad), "yellow lengths", dict(ylen),
              "min green (complete)", min(greens[1:]) if len(greens) > 1 else None, "max green", max(greens), dict(hv))
        if len(sys.argv) > 2:
            lo, hi = map(int, sys.argv[2].split(","))
            print("   ", [(p, a, d) for p, a, d in segs if lo <= a <= hi])
