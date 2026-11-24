"""The reference library: filament, standards and design facts, each with its source.

A small model cannot research the web well, so stone carries the facts it needs and applies
them on its own. Every entry in recipes/lib/refs/*.json has a value, the page it came from
(source, cite, url) and the date it was checked; stone prints the cite next to every fact.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import config

FILES = ("filament", "standards", "design", "fit")


def refs_dir() -> Path:
    # beside the OpenSCAD library, not under STONE_RECIPES: a test or a user recipe folder
    # replaces the recipes, never the facts
    return config.REPO_ROOT / "recipes" / "lib" / "refs"


@lru_cache(maxsize=1)
def load() -> dict[str, dict]:
    """Every entry by id, in file order."""
    out: dict[str, dict] = {}
    for f in FILES:
        for e in json.loads((refs_dir() / f"{f}.json").read_text())["entries"]:
            out[e["id"]] = {**e, "file": f}
    return out


def get(ref_id: str) -> dict:
    return load()[ref_id]


def num(v) -> str:
    """12.0 -> 12, 82.5 -> 82.5."""
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def value_text(e: dict) -> str:
    """An entry's value as one short phrase."""
    v, unit = e["value"], e.get("unit") or ""
    if isinstance(v, list) and len(v) == 2:
        s = f"{num(v[0])} to {num(v[1])}"
    elif isinstance(v, dict):
        s = ", ".join(f"{k.replace('_', ' ')} {value_text({'value': x})}" for k, x in v.items() if x is not None)
        unit = unit if unit in ("mm", "in", "C") else ""
    else:
        s = num(v)
    return f"{s} {unit}".strip() if unit and unit not in ("rule", "formula", "hex", "thread") else s


# materials

@dataclass(frozen=True)
class Material:
    key: str  # the id prefix in filament.json
    name: str  # what stone prints
    words: str  # a regex that names it in a request


MATERIALS = {
    "PLA": Material("pla", "PLA", r"\bpla\b(?!\s*(\+|plus|pro))"),
    "PLA+": Material("pla-plus", "PLA+ (tough PLA)", r"\bpla\s*(\+|plus|pro)|\btough\s+pla\b"),
    "PETG": Material("petg", "PETG", r"\bpetg\b"),
    "ASA": Material("asa", "ASA", r"\basa\b"),
    "ABS": Material("abs", "ABS", r"\babs\b"),
    "TPU": Material("tpu", "TPU 95A", r"\btpu\b"),
    "PA": Material("pa", "nylon (PA11)", r"\bnylon\b|\bpa\s?(6|11|12)\b"),
    "PC": Material("pc", "PC Blend (polycarbonate)", r"\bpolycarbonate\b|\bpc\s+blend\b"),
}


@dataclass(frozen=True)
class Use:
    name: str
    words: str  # regex on the request
    material: str
    refuse: tuple[str, ...] = ()  # materials this use rules out, even when the request names one


# first match wins: heat beats everything, since a part that softens fails whatever else it does
USES = [
    Use("dishwasher", r"dish\s?washer", "ASA", ("PLA", "PLA+")),
    Use("car", r"(?<!toy\s)\bcars?\b|dashboard|\bdash\b|windshield|vehicle|\btruck\b", "ASA", ("PLA", "PLA+")),
    # "heat-set inserts" is how a part is built, not where it lives
    Use("hot", r"\bhot\b|\bheat(ed)?\b(?![- ]?set)|radiator|\bengine\b|\bstove\b", "ASA", ("PLA", "PLA+")),
    # "outside diameter" is a size, "card deck" a game
    Use("outdoor", r"outdoors?|outside(?!\s*(?:diameters?|dimensions?|walls?|edges?|width|size|corners?)\b)|"
                   r"\bsun\b|sunny|sunlight|patio|garden|\byard\b|porch|balcony|(?<!card\s)\bdeck\b|mailbox",
        "PETG", ("PLA", "PLA+")),
    Use("flexible", r"flexible|\bflex\b|bumper|squishy|rubbery|\bsoft\b|gasket", "TPU"),
    Use("heavy", r"\bheavy\b|load.bearing|\bloads?\b|mechanically stressed", "PC"),
    Use("toy", r"\btoys?\b|\bkids?\b|\bkid's\b|\bchild(ren)?\b", "PLA+"),
    Use("food", r"\bfood\b|cookie|\bkitchen\b|\bcups?\b|\bmugs?\b|\bbowls?\b|\bdrink|\beat\b|snack|candy|fondant|dough", "PLA"),
]
RECIPE_USE = {"cookie_cutter": "food"}
# a cup holder holds a cup: a food word naming what a holder is for is not food contact
HOLDS = re.compile(r"\b(?:food|cookie|kitchen|cups?|mugs?|bowls?|drinks?|snacks?|candy)\s+(?:holders?|stands?|racks?|"
                   r"hooks?|trees?|hangers?|caddy|caddies|organizers?|coasters?|mounts?|sleeves?|shel(?:f|ves)|labels?|signs?)\b")


def _matches(use: Use, text: str) -> bool:
    return bool(re.search(use.words, HOLDS.sub(" ", text) if use.name == "food" else text))
HEAT = ("dishwasher", "car", "hot", "outdoor")  # uses PLA is too soft for
WHERE = {"dishwasher": "a dishwasher", "car": "a hot car", "hot": "heat", "outdoor": "sun outdoors"}


@dataclass
class Pick:
    material: str  # a MATERIALS key
    use: str  # a Use name, "named" or "default"
    reason: str
    cites: list[str] = field(default_factory=list)
    refused: str | None = None  # a line saying which named material the use rules out, and why
    extra: list[str] = field(default_factory=list)  # more lines with their sources (food contact)

    @property
    def info(self) -> Material:
        return MATERIALS[self.material]

    def fact(self, key: str) -> dict | None:
        return load().get(f"{self.info.key}.{key}")

    def line(self) -> str:
        """Material: PETG, nozzle 240 to 260 C, bed 70 to 90 C (reason; sources)."""
        parts = [f"Material: {self.info.name}"]
        for key, label in (("nozzle", "nozzle"), ("bed", "bed")):
            e = self.fact(key)
            if e:
                parts.append(f"{label} {value_text(e)}")
        enc = self.fact("enclosure")
        if enc and not str(enc["value"]).startswith("not"):
            v = str(enc["value"])
            parts.append(v if "enclosure" in v else f"enclosure {v}")
        cites = list(dict.fromkeys(self.cites))
        return ", ".join(parts) + f" ({self.reason}; {', '.join(cites)})"

    def lines(self) -> list[str]:
        return ([self.refused] if self.refused else []) + [self.line()] + self.extra


def _words(request: str) -> str:
    return " " + (request or "").lower().replace("’", "'") + " "


def named_material(request: str) -> str | None:
    text = _words(request)
    for k, m in MATERIALS.items():
        if re.search(m.words, text):
            return k
    return None


def _hdt_value(mat: str) -> float | None:
    e = load().get(f"{MATERIALS[mat].key}.hdt")
    try:
        return float(e["value"]) if e else None
    except (TypeError, ValueError):
        return None


def _softer(named: str, wanted: str) -> bool:
    """named softens at a lower temperature than the material this use calls for."""
    a, b = _hdt_value(named), _hdt_value(wanted)
    return a is not None and b is not None and a < b


def _not_for_food(mat: str) -> bool:
    e = load().get(f"{MATERIALS[mat].key}.food")
    return bool(e) and "should not" in str(e["value"]).lower()


def _hdt(mat: str) -> str:
    return num(get(f"{MATERIALS[mat].key}.hdt")["value"])


def _cite(ref_id: str) -> str:
    return get(ref_id)["cite"]


def _reason(use: str, mat: str) -> tuple[str, list[str]]:
    """Why this material for this use, from the library's own numbers."""
    m = MATERIALS[mat].key
    if use in HEAT and mat not in ("PLA", "PLA+"):
        where = {"dishwasher": "dishwasher heat", "car": "in a hot car", "hot": "near heat",
                 "outdoor": "outdoors in sun"}[use]
        text = f"{where}: PLA softens near {_hdt('PLA')} C, {MATERIALS[mat].name} holds to {_hdt(mat)} C"
        cites = [_cite(f"{m}.hdt"), _cite("pla.hdt")]
        if use == "car" and f"{m}.uv" in load():
            text += f" and is {'UV stable' if load()[f'{m}.uv']['value'] == 'good' else 'not UV stable'}"
            cites.append(_cite(f"{m}.uv"))
        return text, cites
    if mat == "TPU":
        return f"flexible: Shore A {num(get('tpu.flex')['value'])} measured", [_cite("tpu.flex")]
    if use == "heavy" and mat == "PC":
        return "heavy load: Prusa calls it an excellent choice for mechanically stressed parts, with good creep resistance", [_cite("pc.use")]
    if use == "toy" and mat == "PLA+":
        return "kid's toy: tough PLA makes drop-resistant prints; plain PLA has very low impact resistance", [_cite("pla-plus.impact")]
    if use == "food":
        return "food contact: no FDM print is certified food safe, and layer grooves hold bacteria", [_cite("any.food.layers")]
    if use == "named":
        return "named in the request", [_cite(f"{m}.nozzle")]
    return "indoors: easiest to print, no enclosure needed", [_cite("pla.nozzle")]


def material_for(request: str, recipe=None, params: dict | None = None) -> Pick:
    """The filament for this job, from the request's words and the recipe's use, with its reason.

    A material the request names wins unless the use rules it out (PLA in a dishwasher or in the sun);
    then the pick says which it refused and why. A phone case follows its material setting, since
    the case's fit is cut for it: 0.05 mm of room for TPU, 0.25 mm for a rigid case.
    """
    name = getattr(recipe, "name", recipe) or ""
    params = params or {}
    text = _words(request)
    use = next((u for u in USES if _matches(u, text)), None)
    if use is None and name in RECIPE_USE:
        use = next(u for u in USES if u.name == RECIPE_USE[name])
    named = named_material(request)
    if name == "phone_case":
        if params.get("material") == "tpu":
            named = "TPU"
        elif params.get("material") == "rigid":
            named = None if named == "TPU" else named
            use = None if use is not None and use.material == "TPU" else use
    refused = None
    if named and use and use.name in HEAT and _softer(named, use.material):
        # by the numbers: a named material that softens below what this use calls for is ruled out
        refused, mat, kind = named, use.material, use.name
    elif named and use and named in use.refuse:
        refused, mat, kind = named, use.material, use.name
    elif named:
        mat = named
        kind = use.name if use and (use.material == named or use.name in HEAT + ("food",)) else "named"
    elif use:
        mat, kind = use.material, use.name
    else:
        mat, kind = "PLA", "default"
    food = kind == "food" or _matches(USES[-1], text) or RECIPE_USE.get(name) == "food"
    swapped = None
    if food and _not_for_food(mat):
        # a cup for the dishwasher: the heat pick (ASA) is one its maker says not to use with food
        swapped, mat = mat, "PETG"
    reason, cites = _reason(kind, mat)
    pick = Pick(mat, kind, reason, cites)
    if swapped:
        pick.extra.append(f"Not {swapped}: its maker says not to use it for food ({_cite(MATERIALS[swapped].key + '.food')}); "
                          f"no filament here is both heat-rated and food-suitable, PETG softens near {_hdt('PETG')} C, "
                          f"so wash it by hand ({_cite('petg.hdt')})")
    if refused:
        pick.refused = (f"Not {refused}: it softens near {_hdt(refused)} C, too soft for {WHERE[use.name]} "
                        f"({_cite(MATERIALS[refused].key + '.hdt')})")
    lib = load()
    if food:
        if kind != "food":
            pick.extra.append(f"Food contact: no FDM print is certified food safe; layer grooves hold bacteria "
                              f"({_cite('any.food.layers')})")
        fe = lib.get(f"{MATERIALS[mat].key}.food")
        if fe:
            pick.extra.append(f"Food contact, {MATERIALS[mat].name}: {fe['value']} ({fe['cite']})")
    return pick


# standards

@dataclass
class Ref:
    text: str
    cite: str
    flag: bool = False  # a problem with this part, printed after a build too

    def line(self) -> str:
        return f"{self.text} ({self.cite})"


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio of two sRGB hex colors (wcag.luminance, wcag.ratio)."""
    def lum(h: str) -> float:
        h = h.lstrip("#")
        ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        r, g, b_ = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


COLOR_WORDS = {"grey": "gray", "silver": "silver", "tan": "beige", "skin": "skin_tone"}


def request_colors(request: str) -> list[str]:
    """Filament color ids (design.json color.*) the request names, in the order it names them."""
    known = {k.split(".", 1)[1] for k in load() if k.startswith("color.")}
    found = []
    for m in re.finditer(r"[a-z]+", (request or "").lower()):
        w = COLOR_WORDS.get(m.group(0), m.group(0))
        if w in known and w not in found:
            found.append(w)
    return found


def _clearance(d: float) -> Ref | None:
    """The ISO 273 row whose fine, medium or coarse hole is nearest a hole diameter."""
    best = None
    for k, e in load().items():
        if not k.startswith("iso273."):
            continue
        for series, v in e["value"].items():
            gap = abs(v - d)
            if gap <= 0.2 and (best is None or gap < best[0]):
                best = (gap, k, e)
    if best is None:
        return None
    _, k, e = best
    size = k.split(".", 1)[1].upper()
    v = e["value"]
    return Ref(f"{size} clearance hole: {num(v['fine'])} fine, {num(v['medium'])} medium, "
               f"{num(v['coarse'])} coarse mm (ISO 273); FDM prints holes small, so drill critical ones",
               e["cite"])


def _text_height(name: str, params: dict) -> float | None:
    for key in ("text_size", "label_size"):
        v = params.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def standards_for(recipe, params: dict | None = None, request: str = "") -> list[Ref]:
    """The standards and published sizes that apply to this part, most specific first."""
    name = getattr(recipe, "name", recipe) or ""
    params = params or {}
    text = _words(request)
    lib = load()
    out: list[Ref] = []
    if name == "fan_guard":
        size = params.get("size")
        e = lib.get(f"fan.{num(size)}") if isinstance(size, (int, float)) else None
        if e:
            out.append(Ref(f"{num(size)} mm fan: screw holes {num(e['value']['hole_spacing'])} mm apart", e["cite"]))
        f = lib["ip2x.finger"]
        out.append(Ref(f"Finger test probe for IP2X: {num(f['value']['diameter'])} mm across, "
                       f"{num(f['value']['length'])} mm long", f["cite"]))
    if name == "gridfinity_bin":
        g, u = lib["gridfinity.grid"], lib["gridfinity.unit"]
        out.append(Ref(f"Gridfinity grid {value_text(g)}", g["cite"]))
        out.append(Ref(f"Gridfinity height unit {value_text(u)}", u["cite"]))
    if re.search(r"keystone", text) or (name == "panel" and re.search(r"keystone|network|ethernet|rj45", text)):
        e = lib["keystone.cutout"]
        out.append(Ref(f"Keystone jack cutout {num(e['value']['width'])} x {num(e['value']['height'])} mm", e["cite"]))
    if re.search(r"wall\s?plate|switch\s?plate|light switch|\boutlet (?:cover|plate)|receptacle|\bdecora\b", text):
        t, dcr, s = lib["wallplate.toggle"], lib["wallplate.decorator"], lib["wallplate.screw"]
        out.append(Ref(f"US wall plate screws {s['value']}, {num(t['value'])} in apart for a toggle switch", t["cite"]))
        out.append(Ref(f"Decorator (rocker) plate screws {num(dcr['value'])} in apart", dcr["cite"]))
    for key in ("hole_d", "screw_d"):
        v = params.get(key)
        if name in ("panel", "hook", "_demo") and isinstance(v, (int, float)) and v > 0:
            r = _clearance(float(v))
            if r:
                out.append(r)
    if name in ("sign", "keychain", "box", "phone_case") and (params.get("text") or params.get("label") or name == "sign"):
        ada, per = lib["legibility.visual_char_height_min"], lib["legibility.visual_char_height_per_ft"]
        h = _text_height(name, params)
        if h is not None and h < float(ada["value"]):
            out.append(Ref(f"Letters {num(h)} mm high read up close only: ADA 703.5.5 asks {num(ada['value'])} mm "
                           "(5/8 in) at least on a sign read from under 6 ft", ada["cite"], flag=name == "sign"))
        elif name == "sign":
            out.append(Ref(f"Sign letters at least {num(ada['value'])} mm (5/8 in) high, plus {num(per['value'])} mm "
                           "per foot past 6 ft of viewing distance (ADA 703.5.5)", ada["cite"]))
        st = lib["text.stroke_vs_nozzle"]
        out.append(Ref(f"Letter strokes at least {num(st['value'])} mm wide on a 0.4 mm nozzle", st["cite"]))
    cols = request_colors(request)
    # a figure's colors are clothes, not letters on a ground: no text contrast there
    if len(cols) >= 2 and name in ("sign", "keychain", "box", "phone_case"):
        a, b = cols[0], cols[1]
        r = contrast_ratio(lib[f"color.{a}"]["value"], lib[f"color.{b}"]["value"])
        floor = float(lib["wcag.contrast_text"]["value"])
        verdict = (f"at least the {num(floor)}:1 WCAG 1.4.3 asks for readable text" if r >= floor
                   else f"under the {num(floor)}:1 WCAG 1.4.3 asks for readable text")
        out.append(Ref(f"Contrast of {a} and {b} filament: {r:.1f}:1, {verdict}",
                       lib["wcag.contrast_text"]["cite"], flag=r < floor))
    if name in ("box", "grommet"):
        g, u = lib["fdm.gap.moving_prusa"], lib["fdm.gap"]
        out.append(Ref(f"Gap between parts that fit or move: {num(g['value'])} mm to start, {num(u['value'])} mm "
                       f"in the {u['cite']}", g["cite"]))
    if re.search(USES[3].words, text) and name in ("planter", "vase", "sign", "hook", "box"):
        e = lib["asa.uv"]
        out.append(Ref("For years in the sun, ASA is UV stable", e["cite"]))
    return sorted(out, key=lambda r: not r.flag)  # a problem first, so a short block keeps it


def show_lines(recipe, params: dict, request: str, limit: int = 3) -> list[str]:
    """The References block for stone show: the material, then the standards, at most `limit` lines."""
    pick = material_for(request, recipe, params)
    lines = pick.lines() + [r.line() for r in standards_for(recipe, params, request)]
    return lines[:limit]


def build_lines(recipe, params: dict, request: str) -> list[str]:
    """What a passing build prints: the material line, and any standard this part falls short of."""
    pick = material_for(request, recipe, params)
    return pick.lines() + [r.line() for r in standards_for(recipe, params, request) if r.flag]


# stone refs

TOPICS = {
    "filament": "filament.", "materials": "filament.",
    "clearance": "iso273.", "screws": "iso273.", "iso273": "iso273.", "us": "us_clearance.",
    "fdm": "fdm.", "finger": "ip2x.", "ip2x": "ip2x.", "wallplate": "wallplate.", "fan": "fan.",
    "gridfinity": "gridfinity.", "keystone": "keystone.", "ada": "ada.", "sign": "legibility.",
    "contrast": "wcag.", "wcag": "wcag.", "colors": "color.", "color": "color.", "harmony": "harmony.",
    "edges": "edge.", "edge": "edge.", "text": "text.", "legibility": "legibility.", "food": "any.food.",
    "fit": "fit.", "tolerance": "fit.", "bearing": "bearing.", "bearings": "bearing.",
}


def topic_entries(topic: str) -> list[dict]:
    t = (topic or "").strip().lower()
    lib = load()
    mat = next((m for k, m in MATERIALS.items() if k.lower() == t or m.key == t), None)
    if mat is None:
        mat = MATERIALS.get(named_material(t) or "")
    if mat is not None:
        return [e for k, e in lib.items() if k.startswith(mat.key + ".")]
    if t in ("filament", "materials"):
        return [e for e in lib.values() if e["file"] == "filament" and e["id"].endswith(".nozzle")]
    prefix = TOPICS.get(t)
    if prefix:
        return [e for k, e in lib.items() if k.startswith(prefix)]
    return [e for k, e in lib.items() if t and (t in k or t in e.get("source", "").lower())]


KEY_LABELS = {"hdt": "heat deflection", "flex": "flexibility", "uv": "UV", "moisture": "drying",
              "food": "food contact"}


def entry_line(e: dict) -> str:
    """One fact for stone refs: what it is, its value, its source."""
    mat = e.get("material")
    if mat and mat != "ANY":
        label = f"{mat} {KEY_LABELS.get(e['key'], e['key'])}"
    else:
        label = e["id"].replace("_", " ")
    return f"{label}: {value_text(e)} ({e['cite']})"
