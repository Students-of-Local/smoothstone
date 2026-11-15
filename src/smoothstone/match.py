"""Read sizes and choices out of a plain request, so a small model starts from good values.

suggest(recipe, request) -> dict of param name -> value

Each number in the request is matched to the number parameter whose name, help text or
aliases share the most words with the words just before and after the number. Choice values
named in the request ("honeycomb", "twisted") set their parameter, and quoted text sets the
first text parameter. A parameter is set at most once and a number is used at most once.
Values outside a parameter's range are left out, so the suggestion is always a valid `stone set`.
"""
from __future__ import annotations

import re

from . import recipes as rc

ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
WORDS = {w: i + 1 for i, w in enumerate(ONES)} | {w: i + 10 for i, w in enumerate(TEENS)} | {"a dozen": 12, "dozen": 12}
for _t, _tw in enumerate(TENS):
    WORDS[_tw] = 20 + 10 * _t
    for _o, _ow in enumerate(ONES):
        WORDS[f"{_tw}-{_ow}"] = WORDS[f"{_tw} {_ow}"] = 20 + 10 * _t + _o + 1
NEGATE = {"no", "without", "not", "skip", "omit", "drop", "dont", "doesnt", "nothing"}
NEGATE2 = {("leave", "off"), ("leave", "out"), ("don", "t"), ("doesn", "t"), ("won", "t"), ("no", "need")}


def _negated(raw: list[str], k: int) -> bool:
    """True when one of the 4 words before raw[k] says no: "no", "without", "don't need a", "leave off the"."""
    w = raw[max(0, k - 4):k]
    return bool(NEGATE & set(w)) or any(pair in NEGATE2 for pair in zip(w, w[1:]))
UNITS = {"mm": 1.0, "millimeter": 1.0, "millimeters": 1.0, "cm": 10.0, "centimeter": 10.0,
         "centimeters": 10.0, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4}
STOP = {"a", "an", "the", "for", "of", "with", "and", "that", "is", "are", "to", "in", "on", "by",
        "it", "its", "my", "i", "need", "want", "make", "me", "please", "about", "around", "x",
        "mm", "cm", "inch", "inches", "deg", "degrees", "each", "be", "should", "has", "have"}
# request words that name a kind of size, mapped to the words recipes use for it
SYN = {"long": ["length"], "length": ["long"], "tall": ["height"], "high": ["height"],
       "height": ["tall"], "wide": ["width"], "width": ["wide"], "across": ["width", "diameter", "size"],
       "diameter": ["across"], "thick": ["thickness"], "thickness": ["thick"], "deep": ["depth"],
       "big": ["size"], "square": ["width", "height"], "opening": ["top", "diameter"]}
# metric screw sizes -> clearance hole diameter, mm
SCREWS = {"2": 2.4, "2.5": 2.9, "3": 3.4, "4": 4.5, "5": 5.5, "6": 6.6, "8": 9.0}
NUM_RE = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?)\s*(mm|millimeters?|cm|centimeters?|inches|inch|in\b|"|deg\b|degrees?|°)?',
                    re.I)


def _stem(w: str) -> str:
    w = w.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("ches", "shes", "xes")):
        return w[:-2]  # switches, boxes, inches
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _words(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-zA-Z]+", text) if w.lower() not in STOP]


def _expand(words) -> set[str]:
    out = set(words)
    for w in words:
        out.update(SYN.get(w, []))
    return out


def _param_words(p: rc.Param, aliases: list[str]) -> set[str]:
    return set(_words(p.name.replace("_", " ")) + _words(p.help) + [_stem(a) for a in aliases])


def _numbers(text: str) -> list[tuple[float, str, int, int]]:
    """(value in mm or plain, unit kind, start, end) for every number in the text."""
    t = re.sub(r"\ban?(?=\s+(?:inch|inches|cm|mm|centimeters?|millimeters?)\b)",
               lambda m: "1".ljust(len(m.group(0))), text, flags=re.I)  # "an inch tall"
    for w, n in sorted(WORDS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{w}\b", lambda m, n=n: str(n).ljust(len(m.group(0))), t, flags=re.I)
    out = []
    for m in NUM_RE.finditer(t):
        v = float(m.group(1))
        u = (m.group(2) or "").lower()
        if text[m.start():m.start() + 1].isalpha() and u in ("", "in"):
            out.append((v, "word", m.start(), m.end()))  # "two", "eight": a count; "one inch" is a length, "four in a row" is not
            continue
        if u in ("deg", "degree", "degrees", "°"):
            kind = "deg"
        elif u:
            v *= UNITS.get(u, 1.0)
            kind = "len"
        else:
            kind = "count"
        out.append((v, kind, m.start(), m.end()))
    return out


UNIT = r"(mm|millimeters?|cm|centimeters?|inches|inch|in\b)?"
BY_RE = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*{UNIT}\s*(?:by|x|\u00d7)\s*(\d+(?:\.\d+)?)\s*{UNIT}"
                   rf"(?:\s*(?:by|x|\u00d7)\s*(\d+(?:\.\d+)?)\s*{UNIT})?", re.I)


def _size_params(r: rc.Recipe) -> list:
    """The parameters "A by B by C" fills: the recipe's size_order, else the first parameter in dims x, y, z."""
    if getattr(r, "size_order", None):
        return [r.param(n) for n in r.size_order]
    out = []
    for axis in ("x", "y", "z"):
        names = re.findall(r"[A-Za-z_]\w*", str(r.dims.get(axis, "")))
        out.append(next((r.param(n) for n in names if r.param(n) and r.param(n).type in ("number", "int")), None))
    return out


def _fits(p: rc.Param, v: float) -> bool:
    if p.type == "int" and abs(v - round(v)) > 1e-9:
        return False
    if p.min is not None and v < float(p.min):
        return False
    if p.max is not None and v > float(p.max):
        return False
    return True


def suggest(r: rc.Recipe, request: str) -> dict:
    return suggest_full(r, request)[0]


def unplaced(r: rc.Recipe, request: str) -> list[str]:
    """Numbers in the request that no parameter took, with the words after them: "3 compartments"."""
    return suggest_full(r, request)[1]


def suggest_full(r: rc.Recipe, request: str) -> tuple[dict, list[str]]:
    aliases = getattr(r, "aliases", {}) or {}
    out: dict = {}
    # quoted text -> first text parameter
    quoted = re.findall(r'["“‘\']([^"”’\']{1,40})["”’\']', request)
    texts = [p for p in r.params if p.type == "text"]
    if not quoted:  # engrave SD on the lid, a sign that says OPEN
        m = re.search(r"\b(?:engraved?|engraves|emboss(?:ed)?|that says|saying|reads|with the text|labell?ed)\s+"
                      r"([A-Z0-9][A-Za-z0-9&-]{0,15})\b", request)
        if m and m.group(1).lower() not in STOP | {"it", "on", "my", "this", "that"}:
            quoted = [m.group(1)]
    if quoted and texts:
        out[texts[0].name] = quoted[0]
    # choice values named in the request
    low = " ".join(request.lower().split())
    for phrase, vals in (getattr(r, "phrases", {}) or {}).items():
        if phrase.lower() in low:
            for k, v in vals.items():
                if r.param(k) is not None and k not in out:
                    out[k] = v
    req_words = set(_words(request))
    own = set(_words(r.name.replace("_", " ") + " " + r.title))  # "box" names the recipe, not part=box
    for p in r.params:
        if p.type == "choice":
            for c in p.choices if p.name not in out else []:
                if _stem(str(c)) in req_words - own and str(c) != str(p.default):
                    out[p.name] = c
                    break
    # switches: "with magnets" turns magnets on, "no label" turns label off
    raw = [w.lower() for w in re.findall(r"[a-zA-Z]+", request)]
    stems = [_stem(w) for w in raw]
    for p in r.params:
        if p.type != "bool" or p.name in out:
            continue
        for words in [[_stem(w) for w in p.name.split("_")]] + [[_stem(w) for w in a.split()] for a in aliases.get(p.name, [])]:
            at = [k for k, w in enumerate(stems) if w == words[0]]
            hit = next((k for k in at if stems[k:k + len(words)] == words), None)
            if hit is None:
                continue
            on = not _negated(raw, hit)
            if on != bool(p.default):
                out[p.name] = on
            break
    # "no flange", "without lightening holes": a number that can be 0 goes to 0
    for p in r.params:
        if p.type in ("number", "int") and p.min == 0 and p.default and p.name not in out:
            first = _stem(p.name.split("_")[0])
            for k, w in enumerate(stems):
                if w == first and _negated(raw, k) and stems[k + 1:k + 2] != ["t"]:
                    out[p.name] = 0
                    break
    # "without hanging holes": a choice that has a "none" value goes to it
    for p in r.params:
        if p.type == "choice" and "none" in [str(c) for c in p.choices] and p.name not in out \
                and str(p.default) != "none":
            first = _stem(p.name.split("_")[0])
            if any(w == first and _negated(raw, k) for k, w in enumerate(stems)):
                out[p.name] = "none"
    # M3, M4 ... screws: clearance hole on the first parameter about screws or holes
    m = re.search(r"\bM(\d(?:\.5)?)\b", request)
    if m and m.group(1) in SCREWS:
        for p in r.params:
            if p.type == "number" and p.unit == "mm" and {"screw", "hole"} & set(_words(p.name.replace("_", " ") + " " + p.help)) \
                    and _fits(p, SCREWS[m.group(1)]):
                out[p.name] = SCREWS[m.group(1)]
                break
        request = request[:m.start()] + request[m.end():]
    # numbers: score every (number, param) pair by the words around the number
    nums = _numbers(request)
    has_units = any(k in ("len", "deg") for _, k, _, _ in nums)
    # "3 compartments": a count word the recipe maps to a parameter with an offset
    counts = {_stem(w): pv for w, pv in (getattr(r, "counts", {}) or {}).items()}
    taken = set()
    # "3 by 2", "60 x 40 mm", "120 by 80 by 50 mm": the recipe's size parameters in order
    slots = _size_params(r)
    for m in BY_RE.finditer(request):
        vals = [m.group(k) for k in (1, 3, 5)]
        units = [m.group(k) for k in (2, 4, 6)]
        last = next((u for u in reversed(units) if u), "")
        for (raw, u), p in zip(zip(vals, units), slots):
            if raw is None or p is None or p.name in out:
                continue
            v = float(raw) * UNITS.get((u or last).lower(), 1.0)
            if _fits(p, v):
                out[p.name] = int(v) if p.type == "int" or v.is_integer() else round(v, 2)
        taken.update(i for i, n in enumerate(nums) if n[2] < m.end() and n[3] > m.start())
    for i, (v, kind, s, e) in enumerate(nums):
        if i in taken:
            continue
        nxt = [_stem(w) for w in re.findall(r"[a-zA-Z]+", request[e:e + 30])[:2]]  # the next word, or one past it
        hit = next((w for w in nxt if w in counts), None)
        if kind in ("count", "word") and hit:
            name, off = counts[hit]
            p = r.param(name)
            if p is not None and name not in out and _fits(p, v + off):
                out[name] = int(v + off)
                taken.add(i)
    cands = []
    for i, (v, kind, s, e) in enumerate(nums):
        if i in taken:
            continue
        # the words around a number belong to it only up to the next number on each side
        lo = nums[i - 1][3] if i > 0 else 0
        hi = nums[i + 1][2] if i + 1 < len(nums) else len(request)
        if i + 1 < len(nums) and not request[e:hi].strip():
            # "two 16 mm cutouts": a count right before a size reaches past it to its noun
            hi = nums[i + 2][2] if i + 2 < len(nums) else len(request)
        before = _words(request[max(lo, s - 40):s])[-3:]
        after = _words(request[e:min(hi, e + 40)])[:3]
        ctx = _expand(set(before) | set(after))
        near = _expand(set(after[:2]) | set(before[-1:]))
        for p in r.params:
            if p.type not in ("number", "int") or p.name in out:
                continue
            if kind == "deg" and p.unit != "deg":
                continue
            if kind == "len" and (p.unit not in ("mm", "") or (p.type == "int" and not p.unit)):
                continue  # "6 mm slots" is a width, never the number of slots
            if kind == "word" and p.type != "int":
                continue
            pw = _param_words(p, aliases.get(p.name, []))

            def hits(ws):  # a word that names the recipe ("box", "fan") counts half
                return len((ws & pw) - own) + 0.5 * len(ws & pw & own)
            if kind == "count" and p.type != "int" and has_units and float(v).is_integer() \
                    and not hits(_expand(set(before[-1:]) | set(after[:1]))):
                continue  # a bare number is a count when the request gives sizes with units ("module 2", "120 tall" are not)
            score = hits(ctx) + hits(near)
            if score == 0:
                continue  # the words around the number must name the parameter
            if "position" in pw and not {"position", "x", "y"} & ctx:
                score -= 1  # placement parameters only when the request talks about placement
            if kind in ("count", "word") and p.type == "int":
                score += 0.5
            if kind == "len" and any(re.search(rf"\b{p.name}\b", e) for e in r.dims.values()):
                score += 0.5  # an overall size of the part wins a tie with a detail size
            if score > 0 and _fits(p, v):
                cands.append((score, -i, i, p.name, v if p.type != "int" else int(round(v))))
    used_n, used_p = set(), set()
    for score, _, i, name, v in sorted(cands, reverse=True):
        if i in used_n or name in used_p:
            continue
        used_n.add(i)
        used_p.add(name)
        p = r.param(name)
        add = float(getattr(p, "fit_add", 0) or 0)
        s_, e_ = nums[i][2], nums[i][3]
        at = _words(request[max(0, s_ - 20):s_])[-2:] + _words(request[e_:e_ + 25])[:1]
        if add and _stem(name.split("_")[0]) not in at:
            v = float(v) + add  # "5 mm cables": the slot gets the recipe's clearance on top
        out[name] = int(v) if float(v).is_integer() else round(float(v), 2)
        # "16 mm square": the same size for the matching _w and _h pair
        s0, e0 = nums[i][2], nums[i][3]
        if "square" in _words(request[e0:e0 + 20]) and name[-2:] in ("_w", "_h"):
            twin = name[:-2] + ("_h" if name.endswith("_w") else "_w")
            if r.param(twin) and twin not in out and _fits(r.param(twin), v):
                out[twin] = out[name]
                used_p.add(twin)
    left = []
    for i, (v, kind, s0, e0) in enumerate(nums):
        if i in used_n or i in taken:
            continue
        tail = " ".join(re.findall(r"[a-zA-Z]+", request[e0:e0 + 30])[:2])
        left.append((request[s0:e0].strip() + " " + tail).strip())
    return {p.name: out[p.name] for p in r.params if p.name in out}, left
