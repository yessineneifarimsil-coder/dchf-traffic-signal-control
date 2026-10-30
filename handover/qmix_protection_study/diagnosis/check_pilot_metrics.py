import json, glob, os, collections
g = collections.defaultdict(list)
for p in glob.glob(os.path.join('.', '*', 'evaluations', '*', '*', 'evaluation_metrics.json')):
    parts = os.path.normpath(p).split(os.sep)
    m = json.load(open(p))
    g[(parts[0], parts[2])].append((m['clearance_status'], m['J_primary_mean_scheduled_waiting_burden_s']))
for k, v in sorted(g.items()):
    print(k, len(v), sum(s == 'CLEARED' for s, _ in v), round(sum(j for _, j in v) / len(v), 6))
