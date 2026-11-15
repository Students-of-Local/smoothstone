"""One HTML page with every round 2 result table, built from the run logs.

uv run python tools/results_page.py <out.html> <label>=<runs dir> [<label>=<runs dir> ...]
"""
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

ORDER = ["next", "cardnone", "cardS", "cardS_compact3"]
NAMES = {"next": "NEXT lines only, no model", "cardnone": "LFM3, no card", "cardS": "LFM3, S card",
         "cardS_compact3": "LFM3, S card, compacted after step 3"}


def table(label, runs):
    tab = defaultdict(lambda: [0, 0])
    toks = defaultdict(list)
    fails = []
    for f in sorted(Path(runs).glob("*/log.json")):
        l = json.loads(f.read_text())
        k = (l["spec"], l["condition"])
        tab[k][1] += 1
        tab[k][0] += bool(l["pass"])
        toks[l["condition"]].append(sum((s.get("tokens_predicted") or 0) for s in l["steps"]))
        if not l["pass"]:
            fails.append((l["spec"], l["condition"], l["seed"], "; ".join(l["why"])))
    conds = [c for c in ORDER if any(k[1] == c for k in tab)]
    specs = sorted({s for s, _ in tab})
    head = "".join(f"<th>{html.escape(NAMES.get(c, c))}</th>" for c in conds)
    rows = ""
    for s in specs:
        rows += f"<tr><td>{s}</td>" + "".join(
            f"<td class='{cls(tab[(s, c)])}'>{tab[(s, c)][0]}/{tab[(s, c)][1]}</td>" if (s, c) in tab else "<td>-</td>"
            for c in conds) + "</tr>"
    tot = {c: [sum(tab[(s, c)][i] for s in specs if (s, c) in tab) for i in (0, 1)] for c in conds}
    rows += "<tr class='tot'><td>total</td>" + "".join(f"<td>{a}/{b}</td>" for a, b in tot.values()) + "</tr>"
    rows += "<tr class='tok'><td>tokens a run</td>" + "".join(
        f"<td>{round(sum(toks[c]) / len(toks[c])) if toks[c] and c != 'next' else '-'}</td>" for c in conds) + "</tr>"
    fl = "".join(f"<li><b>{s}</b> {html.escape(NAMES.get(c, c))}, seed {sd}: {html.escape(w)}</li>" for s, c, sd, w in fails)
    return f"<h2>{html.escape(label)}</h2><table><tr><th>task</th>{head}</tr>{rows}</table>" + (
        f"<details><summary>{len(fails)} failed runs</summary><ul>{fl}</ul></details>" if fails else "")


def cls(v):
    a, b = v
    return "ok" if a == b else ("bad" if a == 0 else "mid")


out = Path(sys.argv[1])
parts = [table(*a.split("=", 1)) for a in sys.argv[2:]]
out.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>smoothstone results</title><style>
:root{{--bg:#fbfaf7;--fg:#1d1d1f;--mut:#6b6b70;--line:#e2e0da;--ok:#d9f2df;--mid:#fdf0cc;--bad:#f8d9d6}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16171a;--fg:#ececef;--mut:#9a9aa2;--line:#2c2d31;--ok:#1f3a27;--mid:#3d3418;--bad:#43201d}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:900px;padding:24px 16px}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px}} p{{color:var(--mut)}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}} th{{font-weight:600;font-size:13px}}
td.ok{{background:var(--ok)}} td.mid{{background:var(--mid)}} td.bad{{background:var(--bad)}}
tr.tot td{{font-weight:600}} tr.tok td{{color:var(--mut)}} details{{margin-top:8px}} li{{font-size:13px}}
.wrap{{overflow-x:auto}}
</style></head><body><h1>smoothstone, round 2</h1>
<p>LFM3-1.7B Q4_K_M on llama.cpp (CPU), 10 steps of 2048 tokens, temperature 0.1, 5 seeds. A run passes when the
finished part exists, passes every print check, uses the right recipe and has the sizes the request asked for.</p>
<div class="wrap">{''.join(parts)}</div></body></html>""")
print(out)
