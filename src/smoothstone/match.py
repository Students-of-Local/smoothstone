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
    if not quoted:  # a case with DONOVAN on the back: a word in capitals placed on a face
        m = re.search(r"\bwith\s+([A-Z][A-Z0-9&-]{1,15})\s+(?:on|across)\s+(?:the\s+)?"
                      r"(?:back|front|lid|top|bottom|side)\b", request)
        if m:
            quoted = [m.group(1)]
    if quoted and texts:
        out[texts[0].name] = quoted[0]
    asks = []
    if texts and texts[0].name not in out and re.search(r"\bmy name\b", request, re.I):
        asks.append(f"my name (ask for it, then stone set {texts[0].name}=NAME)")
    # phrases, longest first; a matched phrase is used up, so "17" in "iPhone 17 Pro" is not left as a size
    phrases = getattr(r, "phrases", {}) or {}
    for phrase in sorted(phrases, key=len, reverse=True):
        pat = r"(?<![a-z0-9])" + r"\s+".join(re.escape(w) for w in phrase.lower().split()) + r"(?![a-z0-9])"
        m = re.search(pat, request, re.I)
        if not m:
            continue
        for k, v in phrases[phrase].items():
            if r.param(k) is not None and k not in out:
                out[k] = v
        request = request[:m.start()] + " " * (m.end() - m.start()) + request[m.end():]
    cp = rc.catalog_param(r)
    if cp is not None and cp.name not in out:
        # a catalog product named with punctuation the phrases do not read: "Mac mini (M4, 2024)"
        from . import catalog

        slug = catalog.find(request, list(cp.choices))
        if slug:
            out[cp.name] = slug
    if cp is not None and out.get(cp.name):
        # the product's name is used up: its model numbers ("M4, 2024", "4020S") are not sizes
        from . import catalog

        for a in sorted((catalog.get(str(out[cp.name])) or {}).get("aliases", []), key=len, reverse=True):
            words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", a.lower())
            if not words:
                continue
            pat = r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(re.escape(w) for w in words) + r"(?![a-z0-9])"
            m = re.search(pat, request, re.I)
            if m:
                request = request[:m.start()] + " " * (m.end() - m.start()) + request[m.end():]
        # a year or model number from the product's own name is not a size: "(the 2021 one)" is the Apple AirTag (2021)
        prod = catalog.get(str(out[cp.name])) or {}
        for n in set(re.findall(r"\d{4,}", " ".join([prod.get("name", "")] + prod.get("aliases", [])))):
            request = re.sub(rf"(?<![\w.]){re.escape(n)}(?![\w.])(?:\s+one\b)?(?!\s*(?:mm|cm|in\b|inch))",
                             lambda m: " " * len(m.group(0)), request, flags=re.I)
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
    return {p.name: out[p.name] for p in r.params if p.name in out}, left + asks


# A part that has to fit a real thing: "a case for my phone", "a cover for the cable hole in my desk".
FIT_RE = re.compile(r"\b(?:case|cover|lid|cap|mount|holder|bracket|adapter|sleeve|plug|grommet|insert|spacer|shim|"
                    r"knob|clip|replacement)s?\s+(?:for|to fit|that fits)\s+(?P<thing>[^,.;!?]+)|"
                    r"\b(?:to fit|that fits|fits)\s+(?P<thing2>[^,.;!?]+)", re.I)


TRAY_RE = re.compile(r"\b(?:tray|enclosure)s?\b", re.I)  # a fitted case's own words: it holds a product


def missing_fit_size(r: rc.Recipe, request: str, notes: list[str] | None = None) -> str | None:
    """The question to ask when the part must fit something real and nothing says how big it is.

    None when the request is not about a fit, or it has a number. A recipe with a product choice
    (phone_case phone) needs one of its products named instead, as a number there is no size."""
    if r.name == "figure":
        return None
    text = " ".join([request, *(notes or [])])
    low = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    m = FIT_RE.search(request) or TRAY_RE.search(request)
    if not m:
        return None
    cat = rc.catalog_param(r)
    if cat is not None:
        # a part built from the catalog's sourced sizes: the product must be one it has, by name,
        # model number or slug; any other product's sizes come from the person, never a guess
        from . import catalog

        if catalog.find(text, list(cat.choices)) or any(
                " " + str(c).replace("_", " ") + " " in low for c in cat.choices):
            return None
        other = catalog.find(text)
        if other:  # a product with sourced sizes that this part cannot hold (the AirTag's round body)
            p = catalog.get(other)
            return (f"I have the {p['name']}'s sizes, but this {r.title.lower()} cannot hold it "
                    f"({p.get('fitted_case_why', 'not a body a tray holds')}). Should I make something else?")
        if not notes:
            return "Which product is it, exactly (its maker and model number)?"
        # the person answered and still named no product it has: this recipe takes no sizes, so asking
        # again would loop; say what it builds for and where a custom size goes
        have = ", ".join(catalog.get(c)["name"] for c in list(cat.choices)[:4])
        return (f"{r.name} builds only for products whose sizes it has sourced from the maker "
                f"({have} and others), and this is not one of them. For a part to your own measurements, "
                f"the box recipe takes a size: stone show box")
    if not FIT_RE.search(request):
        return None
    m = FIT_RE.search(request)
    product = next((p for p in r.params if p.product), None)
    if product:
        # only a product the recipe knows is a size: "iPhone 15" has a number but no case here fits it,
        # and "cover" or "tpu" names no phone at all
        def plain(c):
            return " " + re.sub(r"[^a-z0-9]+", " ", str(c).lower()).strip() + " "
        if any(plain(c) in low for c in product.choices):
            return None
        known = ", ".join(str(c).replace("_", " ") for c in product.choices)
        return f"Which {product.name} is it, exactly? This part is drawn for: {known}."
    if _numbers(text):
        return None
    thing = (m.group("thing") or m.group("thing2") or "it").strip()
    thing = re.sub(r"\bmy\b", "your", re.sub(r"\bour\b", "your", thing, flags=re.I), flags=re.I)
    return (f"What are the measurements of {thing}, in mm? A photo with a ruler in it works too, "
            f"or the exact product name and model.")


# --- a product the catalog does not have: its size comes from the person ------------------------
# "a mount for my Mac Studio (2025)", "a cup that holds my HomePod mini on a shelf": a part named for
# a product. The product's name runs to a word that says where the part goes or a punctuation mark.
PART_WORDS = (r"case|sleeve|holder|stand|mount|cradle|tray|dock|cover|bracket|cup|hanger|enclosure|"
              r"shell|bumper|nest|base|rack|shelf|clip|adapter|plate|box")
PRODUCT_RE = re.compile(
    rf"\b(?:{PART_WORDS})(?:es|s)?\b(?:\s+(?:that|which|to|will))?\s+"
    r"(?:for|holds?|holding|fits?|fitting|takes?)\s+(?:my|our|his|her|their|a|an|the)\s+"
    r"(?P<x>(?:\([^)]*\)|[^,;:!?()])+?)"
    r"(?=\s+(?:on|in|into|onto|under|over|at|to|with|so|that|which|from|by|inside|near|and|design|designed|"
    r"using|made|printed|for)\b|\s*[,;:!?]|\.(?!\d)|\s*$)", re.I)


def product_named(request: str) -> str | None:
    """The product the request names a part for ("Mac Studio (2025)" in "an under desk mount for my
    Mac Studio (2025)"), or None when it names none."""
    m = PRODUCT_RE.search(request or "")
    if not m:
        return None
    x = re.sub(r"\s+", " ", m.group("x")).strip(" .")
    return x if re.search(r"[A-Za-z]", x) else None


def product_size_question(name: str, round_: bool = False) -> str:
    """What stone asks the person for a product the catalog does not have: never a guessed size. A
    round one has a diameter and a height, no depth."""
    what = "diameter and height" if round_ else "width, depth and height"
    return (f"{name}'s {what} in mm, and where the numbers come from "
            f"(the maker's spec page, or their own ruler)")


SIZE_KEYS = {"w": r"width|wide|across|diameter|dia", "d": r"depth|deep|length|long",
             "h": r"height|high|tall|thick|thickness"}
QTY_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|inches|inch|in\b|\")?",
                    re.I)
# W x D x H; a "?" in the middle is a depth not known (a round product's)
BY3_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:by|x|×)\s*(\d+(?:\.\d+)?|\?)\s*(?:by|x|×)\s*"
                    r"(\d+(?:\.\d+)?)\s*(mm|cm|inches|inch|in\b|\")?", re.I)
MEASURED_RE = re.compile(r"\b(?:ruler|measured|measure|calipers?|caliper|tape)\b", re.I)


def _mm(v: str, unit: str | None) -> float:
    u = (unit or "mm").lower()
    k = 10.0 if u.startswith("c") else 25.4 if u.startswith("in") or u == '"' else 1.0
    return round(float(v) * k, 2)


def size_answer(text: str, name: str | None = None) -> dict:
    """The person's answer to product_size_question, read: {"w", "d", "h" in mm (those given),
    "source" (the first URL, or "measured by the person" when they say they measured it), "round"
    (they gave a diameter or said round)}. A size given in more than one unit ("7.7 inches (19.7 cm)")
    is read in the metric one, as the maker printed it; a number with no unit is mm. The product's
    own name (name) holds no size: "Mac Studio (2025)" is not 2025 mm wide."""
    from .catalog import first_url

    out: dict = {}
    url = first_url(text)
    if url:
        out["source"] = url
    elif MEASURED_RE.search(text or ""):
        out["source"] = "measured by the person"
    rest = re.sub(r"https?://\S+", " ", text or "")
    if name:
        rest = re.sub(re.escape(name), " ", rest, flags=re.I)
    out["round"] = bool(re.search(r"\b(?:diameter|round|across|disc|circular)\b|Ø", rest, re.I))
    found = list(BY3_RE.finditer(rest))
    # "3.7 x 7.7 x 7.7 in (9.5 x 19.7 x 19.7 cm)": the metric triple is the one the maker printed
    m = next((t for t in found if t.group(4) and t.group(4).lower()[0] in "mc"), found[0] if found else None)
    if m:
        out.update(w=_mm(m.group(1), m.group(4)), h=_mm(m.group(3), m.group(4)))
        if m.group(2) != "?":
            out["d"] = _mm(m.group(2), m.group(4))
        return out
    for part in re.split(r"[,;\n]|\band\b", rest):
        keys = [k for k, pat in SIZE_KEYS.items() if re.search(rf"\b(?:{pat})\b", part, re.I)]
        qty = [(v, u) for v, u in QTY_RE.findall(part)]
        if len(keys) != 1 or not qty:
            continue
        metric = [(v, u) for v, u in qty if u and u.lower()[0] in "mc"]
        v, u = (metric or qty)[0]
        out.setdefault(keys[0], _mm(v, u))
    return out
