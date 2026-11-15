"""Tabulate round 2 runs: uv run python evals/summary.py <runs dir> [--json]"""
import json
import sys
from collections import defaultdict
from pathlib import Path

runs = Path(sys.argv[1])
tab = defaultdict(lambda: [0, 0])
fails = defaultdict(list)
for f in sorted(runs.glob("*/log.json")):
    l = json.loads(f.read_text())
    k = (l["spec"], l["condition"])
    tab[k][1] += 1
    tab[k][0] += bool(l["pass"])
    if not l["pass"]:
        fails[k].append(f"s{l['seed']}: " + "; ".join(l["why"]))
if "--json" in sys.argv:
    print(json.dumps({f"{s}|{c}": v for (s, c), v in tab.items()}))
    sys.exit()
conds = sorted({c for _, c in tab})
specs = sorted({s for s, _ in tab})
print("spec".ljust(18) + "".join(c.ljust(18) for c in conds))
for s in specs:
    print(s.ljust(18) + "".join((f"{tab[(s, c)][0]}/{tab[(s, c)][1]}" if (s, c) in tab else "-").ljust(18) for c in conds))
tot = {c: [sum(tab[(s, c)][i] for s in specs if (s, c) in tab) for i in (0, 1)] for c in conds}
print("total".ljust(18) + "".join(f"{a}/{b}".ljust(18) for a, b in tot.values()))
for k, v in fails.items():
    print(f"\n{k[0]} {k[1]}:")
    for x in v:
        print("  " + x[:200])
