"""stone: the command line a small model drives. Every output ends with one NEXT line."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import match, check as checks
from . import colors as colortool
from . import config
from . import refs as reftool
from . import image as imagetool
from . import measure as measuretool
from . import find as findtool
from . import figure as figuretool
from . import catalog
from . import fitted
from . import recipes as rc
from . import printable
from . import scad
from .job import Job, read_json, write_json

MAX_LINES = 25
FAILS_BEFORE_RESET = 4
DONE_NEXT = "none, the part is ready"
NEW_NEXT = 'stone new "<what to make>"'
# stages before a plan exists; read-only commands may move NEXT only here
EARLY_STAGES = {"new", "image", "recipes", "show", "no_recipe", "ask", "product"}  # no plan yet: the last step says what is next


@dataclass
class Out:
    lines: list[str] = field(default_factory=list)
    next: str = "stone status"
    code: int = 0
    result: str = ""  # short text for status.json last_result
    stage: str | None = None  # new stage for status.json, None keeps it
    owns_next: bool = True  # False: do not overwrite status next after a plan exists
    raw: str | None = None  # machine output (show --json): printed as is, no NEXT line, no job update
    after: list[str] = field(default_factory=list)  # lines printed after NEXT: what to do later, not now

    def add(self, *lines: str) -> "Out":
        self.lines.extend(lines)
        return self

    def fix(self, text: str) -> "Out":
        self.lines.append(f"FIX: {text}")
        self.code = 1
        return self

    def render(self) -> str:
        if self.raw is not None:
            return self.raw
        body = [ln for ln in self.lines if ln is not None]
        room = MAX_LINES - 1
        passes = [ln for ln in body if ln.startswith("PASS ")]
        if len(body) > room and len(passes) > 1:
            # a passing check asks for nothing; the lines after the checks (the STL, the views)
            # are the ones a reader acts on, so the first passes (loads, watertight...) fold into
            # one line before anything is cut, just enough of them to fit
            fold = set(passes[: min(len(passes), len(body) - room + 1)])
            at = body.index(passes[0])
            body = [ln for ln in body if ln not in fold]
            body.insert(at, f"PASS {len(fold)} checks: " + ", ".join(ln[5:].split(":")[0] for ln in passes if ln in fold))
        if len(body) > room:
            cut = len(body) - (room - 1)
            body = body[: room - 1] + [f"({cut} more lines in log.txt)"]
        return "\n".join(body + [f"NEXT: {self.next}"] + self.after)


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):  # never print usage dumps to a small model
        m = re.search(r"invalid choice: '([^']*)'", message)
        if m:
            message = f"unknown command {m.group(1)}"
        raise UsageError(message)


def fmt_size(v) -> str:
    return " x ".join(f"{float(x):.1f}" for x in v) + " mm"


def short_size(v) -> str:
    return " x ".join(rc.fmt_num(round(float(x), 1)) for x in v) + " mm"


def default_size(r: rc.Recipe) -> str:
    if not r.dims:
        return ""
    try:
        d = r.expected_dims(r.defaults())
    except (ValueError, TypeError, ZeroDivisionError, KeyError):
        return ""
    if len(d) < 3:
        return ""
    return short_size([d["x"], d["y"], d["z"]])


def changed_params(r: rc.Recipe, params: dict) -> list[str]:
    defaults = r.defaults()
    out = []
    for p in r.params:
        if p.name in params and params[p.name] != defaults.get(p.name):
            out.append(f"{p.name}={param_text(p, params[p.name])}")
    return out


def param_text(p: rc.Param, v) -> str:
    if p.type == "image" and isinstance(v, str) and v:
        return "image"
    return rc.fmt_value(p, v)


def params_summary(r: rc.Recipe, params: dict) -> str:
    ch = changed_params(r, params)
    rest = len(r.params) - len(ch)
    if not ch:
        return f"all {len(r.params)} at default"
    return " ".join(ch) + f" ({rest} more at default)"


def measured_size(job: Job | None, r: rc.Recipe) -> tuple[str, float, float] | None:
    """(param, value, measured mm): the size a measured object gives this picture recipe."""
    name = measuretool.SIZE_PARAMS.get(r.name)
    p = r.param(name) if name else None
    m = job.measured() if job and p is not None else None
    if m is None:
        return None
    mm = round(float(m["object"]["long_mm"]), 1)
    v = mm
    if p.min is not None:
        v = max(v, float(p.min))
    if p.max is not None:
        v = min(v, float(p.max))
    return p.name, v, mm


def _file_sig(path) -> str | None:
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else None


def build_stamp(job: Job, r: rc.Recipe, given: dict) -> dict:
    """Everything a build reads: the plan, the recipe source, and the contents of every file it
    uses (pictures, the figure mesh, the photos the figure is made from). Equal stamps make the
    same part."""
    params = build_params(job, r, given)
    files = {k: _file_sig(v) for k, v in sorted(params.items())
             if v and r.param(k) is not None and r.param(k).type == "image"}
    stamp = {"recipe": r.name, "params": params, "files": files, "source": _file_sig(r.scad),
             "photos": [_file_sig(p) for p in job.photos()], "print": printable.VERSION}
    own = catalog.job_products(job.root)
    if own and rc.catalog_param(r) is not None:
        stamp["products"] = {s: _file_sig(job.root / "products" / f"{s}.json") for s in sorted(own)}
    return stamp


def build_params(job: Job | None, r: rc.Recipe, given: dict) -> dict:
    """Defaults + plan, with the job image filled into unset image params and a measured size."""
    merged = r.merged(given)
    imgs = job.image_paths() if job else {}
    for p in r.params:
        if p.type == "image" and p.name not in given and p.image_kind in imgs:
            merged[p.name] = str(imgs[p.image_kind].resolve())
    ms = measured_size(job, r)
    if ms and ms[0] not in given:
        merged[ms[0]] = ms[1]
    return merged


def tier_lines(t: str) -> list[str]:
    rules = config.tier_rules(t)
    return [f"Tier: {t}"] + (["Rules:"] + rules if rules else [])


def need_job(job: Job, out: Out) -> bool:
    if job.exists():
        return True
    out.add(f"No job in {job.root}.")
    out.next = NEW_NEXT
    out.code = 1
    return False


# status


def cmd_status(args, job: Job) -> Out:
    out = Out(owns_next=False)
    t = config.tier(job.root)
    if not job.exists():
        out.add(f"No job in {job.root}.")
        out.add(*tier_lines(t))
        out.next = NEW_NEXT
        return out
    s = job.status()
    out.add(f"Job: {job.root}")
    out.add(*tier_lines(t))
    out.add(f"Request: {job.request() or '(empty)'}")
    info = read_json(job.image_dir / "info.json")
    if info:
        out.add(
            f"Image: {info.get('kind')}, aspect {float(info.get('aspect', 0)):.2f}, "
            f"{info.get('shapes')} shapes, param value: image"
        )
    m = job.measured()
    if m:
        o = m["object"]
        out.add(f"Measured: object {o['long_mm']:.1f} x {o['short_mm']:.1f} mm (from {m['method']})")
    notes = job.notes()
    if notes:
        out.add(f"Notes ({len(notes)}): " + " | ".join(notes[-8:]))
    plan = job.plan()
    if plan:
        r = rc.load(plan["recipe"])
        if r is None:
            out.add(f"Recipe: {plan['recipe']} (missing from the recipe folder)")
        else:
            out.add(f"Recipe: {r.name} ({r.title})")
            out.add(f"Params: {params_summary(r, plan['params'])}")
    else:
        out.add("Recipe: none yet")
    out.add(f"Builds: {s.get('builds', 0)}, passed: {'yes' if s.get('passed') else 'no'}")
    # after a compaction the model has lost stone show: repeat what the request still asks for
    nxt = s.get("next") or ""
    pick = plan["recipe"] if plan else (nxt.split()[2] if nxt.startswith("stone set ") and len(nxt.split()) > 2 else None)
    pr = rc.load(pick) if pick and not s.get("passed") else None
    if pr is not None:
        left = match.unplaced(pr, job.request())
        if left:
            out.add(f"Not placed yet: {'; '.join(left[:4])}. Names and meanings: stone show {pr.name}")
    if s.get("last_result"):
        out.add(f"Last: {s.get('last_command', '')} -> {s['last_result']}")
    out.add(f"Stage: {s.get('stage')}")
    if s.get("stage") == "done" and plan:
        out.add(f"Part: {job.root / (plan['recipe'] + '.stl')}")
    col = s.get("colors")
    if col and plan:
        out.add(f"Colors: {col.get('shares', '')} (stone colors {col.get('mapping', '')})")
        out.add(f"3MF: {col.get('file', '')}")
    out.next = s.get("next") or "stone recipes"
    return out


# new


def cmd_new(args, job: Job) -> Out:
    out = Out()
    request = " ".join(args.request).strip()
    if not request:
        out.fix('say what to make, in quotes')
        out.next = NEW_NEXT
        return out
    try:
        moved = job.create(request, force=args.force)
    except FileExistsError:
        out.owns_next = False
        out.add(f"A job already exists in {job.root}: {job.request()}")
        out.fix("add --force to start over (the old job is kept)")
        out.next = "stone status"
        return out
    out.add(f"Job: {job.root}")
    if moved:
        out.add(f"Old job moved to {moved}")
    out.add(f"Request: {request}")
    out.stage = "new"
    out.result = "job created"
    out.next = "stone recipes"
    if args.image:
        img = image_step(job, Path(args.image), out)
        if img is None:
            return out
    return out


# recipes


def cmd_recipes(args, job: Job) -> Out:
    out = Out(owns_next=False, stage="recipes")
    t = config.tier(job.root)
    allr = rc.load_all()
    vis = rc.visible(allr, t, show_all=args.all)
    if not vis:
        out.add(f"No recipes for tier {t} in {config.recipes_dir()}.")
        out.next = "stone status"
        out.code = 1
        return out
    words = " ".join(args.words).strip()
    query = words or (job.request() if job.exists() else "")
    ranked = rc.rank(vis, query)
    if query and not words:
        # a recipe that makes what the request names comes first, word for word before any order;
        # words the caller adds only narrow the list (stone recipes fan): they never stop the job
        fits = {r.name: rc.fit(r, query) for _, r in ranked}
        ranked.sort(key=lambda sr: -fits[sr[1].name])  # stable: keeps the word score within a fit
        top = ranked[0][1]
        if fits[top.name] == 0:
            # no recipe makes this: handing over the nearest one ready would be a wrong part
            what = top.title.lower()
            out.add("No recipe makes this yet. Recipes that share words with it:")
            for _, r in ranked[:5]:
                out.add(f"{r.name}  {r.title}")
            out.next = (f"ask the person: stone has no recipe for this yet; the nearest is {what} ({top.name}). "
                        f"Should I make {what}, or can you ask for it another way? "
                        f"If they say make it: stone show {top.name}. If they ask another way: stone new \"<their words>\"")
            out.owns_next = True
            out.stage = "no_recipe"
            out.result = "no recipe fits"
            return out
    if words and ranked[0][0] == 0:
        out.add(f'No recipe matches "{words}". All recipes:')
    else:
        out.add("All recipes, best match first:" if args.all else f"Recipes for tier {t}, best match first:")
    for _, r in ranked[:12]:
        size = default_size(r)
        out.add(f"{r.name}  {r.title}" + (f"  (default size {size})" if size else ""))
    if len(ranked) > 12:
        out.add(f"({len(ranked) - 12} more: add words to narrow the list)")
    top = ranked[0][1].name
    if query and not words:
        why = product_reason(ranked[0][1], query)
        if why:
            out.lines.insert(0, why)
    out.next = f"stone show {top}"
    out.result = f"listed recipes, top {top}"
    return out


def product_reason(r: rc.Recipe, request: str) -> str | None:
    """Why the first recipe is the one, when the request names a catalog product it takes: its title
    ("Fitted case for a product") does not say sleeve or stand, and a small model doubts a NEXT line
    whose recipe does not echo the request's words."""
    slug = catalog.find(request)
    prod = catalog.get(slug) if slug else None
    if prod is None or not takes(r, slug) or rc.fit(r, request) <= 0:
        return None
    h = rc.head(request)
    noun = h[-1] if h and h[-1].isalpha() and h[-1] not in rc.STOPWORDS else "part"
    whose = "the sizes the person gave" if prod.get("set") == "job" else "its published sizes"
    return f"For this request: {r.name} makes the {noun} for the {prod['name']} from {whose}."


# show


def request_recipe(request: str, t: str) -> rc.Recipe | None:
    """The recipe stone recipes puts first for the request when it makes what the request names
    (fit above 0), else None."""
    if not request:
        return None
    ranked = rc.rank(rc.visible(rc.load_all(), t), request)
    if not ranked:
        return None
    fits = {r.name: rc.fit(r, request) for _, r in ranked}
    ranked.sort(key=lambda sr: -fits[sr[1].name])
    top = ranked[0][1]
    return top if fits[top.name] > 0 else None


def unknown_recipe(name: str, out: Out, t: str, job: Job | None = None) -> Out:
    allr = rc.load_all()
    # hidden recipes (names starting with _) only when the model typed a _ name
    names = [r.name for r in rc.visible(allr, t, show_all=name.startswith("_"))] or list(allr)
    near = rc.closest(name, names)
    # a made up name ("power_bank_case") is not a typo of the nearest name (phone_case): the recipe
    # that makes what the request names comes first, so a guessed name never sends a power bank to a phone case
    best = request_recipe(job.request() if job is not None and job.exists() else "", t)
    typo = bool(near) and difflib.SequenceMatcher(None, name.lower(), near[0]).ratio() >= 0.85
    if near:
        out.fix(f'no recipe "{name}"; closest: {", ".join(near)}')
        out.next = f"stone show {near[0]}"
    else:
        out.fix(f'no recipe "{name}"; pick one from stone recipes')
        out.next = "stone recipes"
    if best is not None and not typo and (not near or best.name != near[0]):
        out.add(f"For this request: {best.name} ({best.title})")
        out.next = f"stone show {best.name}"
    out.result = f"unknown recipe {name}"
    return out


def product_param(r: rc.Recipe) -> rc.Param | None:
    """The parameter that names the real product the part fits (phone, product), if the recipe has one."""
    return next((p for p in r.params if p.product or p.catalog), None)


def takes(r: rc.Recipe, slug: str) -> bool:
    """The recipe's product parameter can be set to this catalog product."""
    pp = product_param(r)
    return pp is not None and slug in [str(c) for c in pp.choices]


def other_product_recipe(job: Job, r: rc.Recipe, t: str) -> tuple[rc.Recipe, dict, bool] | None:
    """When the request names a catalog product and the recipe stone recipes puts first takes it and
    fits the request better than this one, which either makes nothing the request names (phone_case
    for a Flipper Zero) or cannot take the product (a phone stand sized by guess for an iPhone 17 Pro
    the catalog holds): that recipe, the product, and whether this one could take it."""
    request = job.request() if job.exists() else ""
    if not request:
        return None
    slug = catalog.find(request)
    prod = catalog.get(slug) if slug else None
    if prod is None:
        return None
    best = request_recipe(request, t)
    if best is None or best.name == r.name or not takes(best, slug):
        return None
    own = rc.fit(r, request)
    if own >= rc.fit(best, request) or (own > 0 and takes(r, slug)):
        return None
    return best, prod, takes(r, slug)


def steer(out: Out, r: rc.Recipe, alt: tuple[rc.Recipe, dict, bool]) -> Out:
    best, prod, could = alt
    why = "does not make what the request names" if could else f"does not fit the {prod['name']} the request names"
    out.fix(f"{r.name} {why}; {best.name} ({best.title}) makes it to its published sizes")
    out.next = f"stone show {best.name}"
    out.result = f"{r.name} is not for this request, use {best.name}"
    return out


def example_items(r: rc.Recipe, limit: int | None = None) -> list[str]:
    if r.examples:
        params = r.examples[0].get("params", {})
        items = [
            f"{k}={rc.fmt_value(r.param(k), v)}" for k, v in params.items() if r.param(k)
        ]
    else:
        items = [
            f"{p.name}={rc.fmt_value(p, p.default)}"
            for p in r.params
            if p.type in ("number", "int")
        ]
    return items[:limit] if limit else items


def show_json(r: rc.Recipe | None, name: str, job: Job, t: str) -> Out:
    """stone show --json: one JSON object for programs such as Gantrel Studio. Read only."""
    out = Out(owns_next=False)
    if r is None:
        names = [x.name for x in rc.visible(rc.load_all(), t, show_all=name.startswith("_"))]
        out.raw = json.dumps({"error": f'no recipe "{name}"', "closest": rc.closest(name, names)})
        out.code = 1
        return out
    data = read_json(r.path / "recipe.json") or {}
    request = job.request() if job.exists() else ""
    sug = match.suggest_full(r, request)[0] if request else {}
    current: dict = {}
    if job.exists():
        built = read_json(job.build_dir / "params.json") or {}
        plan = job.plan() or {}
        if built.get("recipe") == r.name and isinstance(built.get("params"), dict):
            current = built["params"]
        elif plan.get("recipe") == r.name:
            current = r.merged(plan.get("params") or {})
    out.raw = json.dumps({
        "name": r.name,
        "title": r.title,
        "summary": r.summary,
        "tier": r.tier,
        "params": list(data.get("params") or []),
        "from_request": sug,
        "current": current,
    }, ensure_ascii=False)
    return out


def param_line(p: rc.Param, short: bool = False) -> str:
    """One parameter for stone show. A product the request or the person must name has no default
    shown: a default product (raspberry_pi_5) beside a request for a Flipper Zero reads as a contradiction."""
    rng = " | ".join(str(c) for c in p.choices) if short and p.type == "choice" else p.range_text()
    if p.product or p.catalog:
        line = f"{p.name} = (no default: the exact one the request names, else ask)  ({rng})"
    else:
        line = f"{p.name} = {rc.fmt_value(p, p.default)}  ({rng})"
    if p.help and not short:
        line += f" {p.help}"
    return line


OPEN_TOP = {"cup", "tray", "cradle", "holder", "stand", "dock", "nest", "base"}  # parts a product sits down into


def product_ask(job: Job, r: rc.Recipe, t: str, named: bool = False) -> str | None:
    """The product the request names a part for ("a mount for my Mac Studio (2025)"), when this recipe
    and the one stone recipes puts first both build from the catalog and the catalog (the job's own
    products included) has no such product: its size must come from the person. None otherwise, or
    when the set line names a product (named)."""
    request = job.request() if job.exists() else ""
    if not request or named or rc.catalog_param(r) is None:
        return None
    x = match.product_named(request)
    if x is None or catalog.find(" ".join([request, *job.notes()])):
        return None
    top = request_recipe(request, t)
    return x if top is not None and rc.catalog_param(top) is not None else None


def ask_product_size(out: Out, job: Job, x: str, t: str) -> Out:
    """NEXT asks the person for the product's size and where it comes from; their answer, through
    stone note, becomes the stone product add line."""
    top = request_recipe(job.request(), t)
    rnd = asks_round(job.request(), top)
    out.add(f"The catalog has no sourced sizes for {x}, and stone never guesses a product's size.")
    out.next = f"ask the person: {match.product_size_question(x, rnd)}"
    # NEXT comes first; what to do with the answer is for later, after the person has replied
    out.after.append('After the person answers (not before): stone note "<their answer>", then run the NEXT line it prints.')
    if t != "S":
        out.after.append('Their answer becomes: stone product add "<name>" --size W D H --source "<URL or measured by the person>"'
                         + " (--round with diameter and height for a round one)")
    out.owns_next = True
    out.stage = "ask"
    out.result = f"asked the person for the size of {x}"
    job.update(ask_recipe=top.name if top is not None else None, ask_product=x, ask_got=None, ask_round=rnd)
    return out


ROUND_WORDS = re.compile(r"\b(?:round|cup|puck|disc|disk|cylinder|cylindrical)\b", re.I)


def asks_round(request: str, top: rc.Recipe | None) -> bool:
    """A round product: the recipe stone ranks first is for round products, or the request says
    round, cup, puck or disc. Its size is a diameter and a height."""
    cp = rc.catalog_param(top) if top is not None else None
    return (cp is not None and cp.catalog == "round_case") or bool(ROUND_WORDS.search(request or ""))


SIZE_KEYS = {"w": ("width", "w", "wide", "x", "diameter", "dia", "d_mm"), "d": ("depth", "d", "deep", "y", "length", "long"),
             "h": ("height", "h", "high", "tall", "z", "thickness")}


def set_sizes(items: list[str]) -> dict:
    """Product sizes in a stone set line (width=197 depth=197 height=95, size=197x197x95, diameter=97.9),
    in mm: {"w", "d", "h"} for those given, "round" when a diameter is given."""
    got: dict = {}
    for it in items:
        if "=" not in it and ":" not in it:
            continue
        k, v = re.split(r"[=:]", it, maxsplit=1)
        k = k.strip().lower()
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", v)]
        if not nums:
            continue
        if k in ("size", "dims", "dimensions") and len(nums) in (2, 3):
            got.update(dict(zip(("w", "d", "h"), nums)) if len(nums) == 3 else {"w": nums[0], "h": nums[1]})
            continue
        for key, names in SIZE_KEYS.items():
            if k in names:
                got.setdefault(key, nums[0])
                if k in ("diameter", "dia"):
                    got["round"] = True
    return got


def open_for(request: str) -> list[str]:
    """The faces a part named in the request leaves clear: +z for one a product sits down into."""
    m = match.PRODUCT_RE.search(request or "")
    noun = m.group(0).split()[0].lower().rstrip("s") if m else ""
    return ["+z"] if noun in OPEN_TOP else []


# a request, or words to the person: the person answers as "I" and "my", stone's question says "you"
ASKING_RE = re.compile(r"\?|\b(?:please|provide|you|your|tell me|let me know|what (?:is|are))\b", re.I)
SIZE_WORDS_RE = re.compile(r"\b(?:width|depth|height|diameter|dimensions?|sizes?|measurements?)\b", re.I)


def is_the_question(text: str, asked: str) -> bool:
    """A note that is stone's own question, or restates it with no number of its own: a model noting
    the question instead of asking it. A note with no number and no URL that asks for a size ("please
    provide its width, depth and height", "where did you get them") is the question too, however it is
    worded."""
    q = asked[len("ask the person"):].lstrip(": ")
    words = lambda s: {w for w in re.findall(r"[a-z]+", s.lower()) if len(w) > 2} - rc.STOPWORDS  # noqa: E731
    nums = lambda s: set(re.findall(r"\d+(?:\.\d+)?", s))  # noqa: E731
    tw, qw = words(text), words(q)
    if not tw or not nums(text) <= nums(q) or catalog.first_url(text):
        return False
    if ASKING_RE.search(text) and SIZE_WORDS_RE.search(text):
        return True
    return len(tw) >= 4 and len(tw & qw) / len(tw) >= 0.7


def product_add_line(x: str, got: dict, round_: bool, open_faces: list[str]) -> str:
    """The stone product add command for the size the person gave."""
    w, h = got["w"], got["h"]
    d = w if round_ else got["d"]
    line = f'stone product add "{x.replace(chr(34), "")}" --size {rc.fmt_num(w)} {rc.fmt_num(d)} {rc.fmt_num(h)}'
    if round_:
        line += " --round"
    if open_faces:
        faces = ",".join(open_faces)
        line += f" --open={faces}" if faces.startswith("-") else f" --open {faces}"
    return line + f' --source "{got["source"]}"'


def note_product(out: Out, job: Job, st: dict, text: str) -> Out:
    """The person's answer to the product size question: once it gives every size and a source,
    NEXT is the stone product add line with their numbers; else NEXT asks for what is missing."""
    x = st["ask_product"]
    prev = st.get("ask_got") or {}
    new = match.size_answer(text, x)
    got = {**prev, **{k: v for k, v in new.items() if v}}
    got["round"] = bool(prev.get("round") or new.get("round"))
    ar = rc.load(st["ask_recipe"]) if st.get("ask_recipe") else None
    cp = rc.catalog_param(ar) if ar is not None else None
    round_ = got["round"] or bool(st.get("ask_round")) or (cp is not None and cp.catalog == "round_case")
    names = {"w": "diameter" if round_ else "width", "d": "depth", "h": "height"}
    missing = [names[k] for k in (("w", "h") if round_ else ("w", "d", "h")) if not got.get(k)]
    out.owns_next = True
    if missing or not got.get("source"):
        job.update(ask_got=got)
        what = f"{x}'s {' and '.join(missing)} in mm" if missing else f"where {x}'s numbers come from"
        if missing and not got.get("source"):
            what += ", and where the numbers come from"
        out.add(f"Still needed: {what}.")
        out.next = f"ask the person: {what} (the maker's spec page, or their own ruler)"
        out.result = "answer read: a size or its source is missing"
        return out
    line = product_add_line(x, got, round_, open_for(job.request()))
    d = got["w"] if round_ else got["d"]
    out.add(f"From the answer: {x}, {short_size([got['w'], d, got['h']])}" + (", round" if round_ else "")
            + f", source {got['source']}")
    job.update(ask_got=None)
    out.next = line
    out.result = "answer read: the product's size and source"
    return out


def cmd_show(args, job: Job) -> Out:
    out = Out(owns_next=False, stage="show")
    t = config.tier(job.root)
    r = rc.load(args.recipe)
    if getattr(args, "json", False):
        return show_json(r, args.recipe, job, t)
    if r is None:
        return unknown_recipe(args.recipe, out, t, job)
    alt = other_product_recipe(job, r, t)
    if alt is not None:
        return steer(out, r, alt)
    x = product_ask(job, r, t)
    if x is not None:
        out.add(f"{r.name}: {r.title}")
        return ask_product_size(out, job, x, t)
    request = job.request() if job.exists() else ""
    sug, left = match.suggest_full(r, request) if request else ({}, [])
    ms = measured_size(job, r) if job.exists() else None
    # tier S, and the request gives every value the part needs: what the request filled and the NEXT
    # line come first, the rest one short line each, so a small model is not made to re-read a long list
    pp = product_param(r)
    short = (bool(request) and not left and t == "S" and not getattr(args, "all", False)
             and not (ms and ms[0] not in sug) and (pp is None or pp.name in sug)
             and not (job.photos() and any(p.type == "image" for p in r.params)))
    out.add(f"{r.name}: {r.title}")
    if r.summary:
        out.add(r.summary)
    size = default_size(r)
    if not short:
        out.add(f"Tier {r.tier}." + (f" Default size {size}." if size else ""))
    items = [f"{k}={rc.fmt_value(r.param(k), v)}" for k, v in sug.items()]
    if sug:
        out.add(f"From the request: {' '.join(items)}")
    cp = rc.catalog_param(r)
    if cp is not None and sug.get(cp.name):
        prod = catalog.get(str(sug[cp.name]))
        if prod:
            src = ", ".join(prod.get("sources", [])[:1]) or "measured by the person"
            kind = "given by the person for this job" if prod.get("set") == "job" else "catalog"
            out.add(f"Product: {prod['name']} ({kind}, sourced: {src})")
    if ms and ms[0] not in sug:
        clamp = f", the measured {rc.fmt_num(ms[2])} mm is out of range" if ms[1] != ms[2] else ""
        out.add(f"From the picture: {ms[0]}={rc.fmt_num(ms[1])} (object long side in mm{clamp})")
    if left:
        out.add(f"Not placed yet: {'; '.join(left[:4])}. If one is a size of this part, add it with its parameter name.")
    elif short:
        out.add("The NEXT line below already holds " + ("every value the request gives" if sug else "the defaults, which make a good part")
                + "; run it as written.")
    elif request and not sug:
        out.add("Nothing in the request names a parameter; the defaults make a good part.")
    out.add(*reference_block(job, r, {p.name: p.default for p in r.params} | sug, request))
    rest = [p for p in r.params if p.name not in sug] if short else list(r.params)
    if short:
        out.add(f"Parameters left at their defaults (stone show {r.name} --all explains each):")
    else:
        out.add("Parameters (name = default):")
    room = MAX_LINES - len(out.lines) - 3
    for i, p in enumerate(rest):
        if i >= room:
            out.add(f"({len(rest) - room} more parameters not shown)")
            break
        out.add(param_line(p, short))
    ex = example_items(r)
    if pp is not None and pp.name in sug:
        # an example for another product (product=raspberry_pi_5) beside a Flipper Zero request misleads
        ex = [e for e in ex if e.split("=", 1)[0] != pp.name]
    if ex and not short:
        out.add(f"Example: stone set {r.name} {' '.join(ex)}")
    if request:
        out.next = f"stone set {r.name} {' '.join(items) if sug else ''}".rstrip()
    else:
        nxt = example_items(r, limit=3)
        out.next = f"stone set {r.name} {' '.join(nxt)}".rstrip()
    out.result = f"showed {r.name}"
    return out


def reference_block(job: Job, r: rc.Recipe, params: dict, request: str) -> list[str]:
    """References: the filament and the standards for this part, each with its source (refs.py)."""
    try:
        lines = reftool.show_lines(r, params, request)
    except Exception:  # a broken library costs the block, never the command
        if job.exists():
            job.log("references failed:\n" + traceback.format_exc())
        return []
    return ["References:", *lines] if lines else []


def build_references(job: Job, r: rc.Recipe, params: dict) -> list[str]:
    try:
        return reftool.build_lines(r, params, job.request())
    except Exception:
        job.log("references failed:\n" + traceback.format_exc())
        return []


# set


def split_items(items: list[str], r: rc.Recipe | None) -> tuple[list[tuple[str, str]], list[str]]:
    pairs, bad = [], []
    i = 0
    while i < len(items):
        it = items[i]
        if "=" in it:
            k, v = it.split("=", 1)
            pairs.append((k.strip(), v))
        elif ":" in it:
            k, v = it.split(":", 1)
            pairs.append((k.strip(), v))
        elif r is not None and r.param(it) and i + 1 < len(items) and "=" not in items[i + 1]:
            pairs.append((it, items[i + 1]))
            i += 1
        else:
            bad.append(it)
        i += 1
    return pairs, bad


def cmd_set(args, job: Job) -> Out:
    out = Out(stage="plan")
    if not need_job(job, out):
        return out
    t = config.tier(job.root)
    items = list(args.items)
    plan = job.plan()
    name = None
    if items and "=" not in items[0] and ":" not in items[0]:
        name = items.pop(0)
    elif items and "=" in items[0] and rc.load(items[0].split("=", 1)[0]):
        name = items.pop(0).split("=", 1)[0]  # "stone set cable_comb=100 ...": the recipe name came first
    elif plan:
        name = plan["recipe"]
    if name is None:
        if not items and args.reset:
            out.fix("there is no plan to reset; pick a recipe first")
            out.next = "stone recipes"
            return out
        out.fix("name the recipe first, like stone set <recipe> w=50")
        out.next = "stone recipes"
        return out
    r = rc.load(name)
    if r is None:
        # maybe the model wrote "w 50" with the plan's recipe implied
        if plan and rc.load(plan["recipe"]) and rc.load(plan["recipe"]).param(name):
            items.insert(0, name)
            r = rc.load(plan["recipe"])
        else:
            return unknown_recipe(name, out, t, job)
    alt = other_product_recipe(job, r, t)
    if alt is not None:
        return steer(out, r, alt)
    from_request = None
    if not items and not args.reset and not (plan and plan["recipe"] == r.name) and job.request():
        # a bare "stone set <recipe>" means the request's values, the ones stone show offers
        sug = match.suggest_full(r, job.request())[0]
        shown = [f"{k}={rc.fmt_value(r.param(k), v)}" for k, v in sug.items() if r.param(k) is not None]
        from_request = " ".join(shown) or None
        # fmt_value quotes text with a space for a command line; here no shell takes the quotes off
        items = [k + "=" + (json.loads(v) if v.startswith('"') else v)
                 for k, v in (it.split("=", 1) for it in shown)]
    given = [(k, v, r.param(k)) for k, v in (it.split("=", 1) for it in items if "=" in it)]
    x = product_ask(job, r, t, named=any(p is not None and p.catalog for _, _, p in given))
    if x is not None:
        sizes = set_sizes(list(args.items))
        st = job.status()
        rnd = bool(st.get("ask_round")) or asks_round(job.request(), request_recipe(job.request(), t)) or sizes.get("round")
        if sizes.get("w") and sizes.get("h") and (rnd or sizes.get("d")):
            # the sizes are the product's, not the part's: they go to stone product add with their source
            src = (st.get("ask_got") or {}).get("source") or next(
                (u for u in (catalog.first_url(n) for n in job.notes()) if u), None)
            got = {**sizes, "source": src or "<where the person said the numbers come from>"}
            line = product_add_line(x, got, bool(rnd), open_for(job.request()))
            out.fix(f"these are {x}'s sizes, not the part's: a product the catalog lacks goes in with stone product add")
            out.add(f"Run: {line}")
            out.next = line
            out.owns_next = True
            out.stage = "ask"
            out.result = "set refused: product sizes go to stone product add"
            return out
        # never build for a catalog product the person did not name: the default one is not theirs
        out.fix(f"the catalog has no sourced sizes for {x}; never guess them")
        return ask_product_size(out, job, x, t)
    # the set line answers the question when it names the product (phone=iphone_17_pro) or gives a length
    # (hole_d=60); so does a size measured from a photo
    named = [f"{k} {v.replace('_', ' ')}" for k, v, p in given if p is not None and p.product]
    sized = not any(p.product for p in r.params) and any(
        p is not None and p.type in ("number", "int") and p.unit == "mm" for _, _, p in given)
    ask = None if sized or job.measured() else match.missing_fit_size(r, job.request(), job.notes() + named)
    if ask:
        # never invent the size of the thing a part must fit: a small model would, so the tool stops it
        out.fix("this part must fit something real and the request gives no size for it; never guess one")
        out.after.append('After the person answers (not before): stone note "<their answer>", then run the NEXT line it prints.')
        out.next = f"ask the person: {ask}"
        out.result = "set refused: no size for the fit"
        job.update(ask_recipe=r.name)
        return out
    same = plan is not None and plan["recipe"] == r.name
    params = dict(plan["params"]) if same and not args.reset else {}
    pairs, loose = split_items(items, r)
    fixes: list[str] = []
    retry: dict[str, str] = {}
    hard = False
    if loose:
        # bare values: give back the whole line with names, read from the request
        fixes.append(f"write each value with its name, like name=value (not {' '.join(loose[:3])})")
        for k, v in match.suggest(r, job.request()).items():
            p = r.param(k)
            retry.setdefault(k, rc.fmt_value(p, v) if p else str(v))
        hard = not retry
    names = [p.name for p in r.params]
    imgs = job.image_paths()
    pics = [p.name for p in r.params if p.type == "image"]
    for k, raw in pairs:
        if r.param(k) is None and k.lower() in ("image", "picture", "pic", "img", "photo") and len(pics) == 1:
            k = pics[0]  # "image=" on a sign means its one picture parameter, icon
        p = r.param(k)
        if p is None:
            near = rc.closest(k, names)
            if near:
                fixes.append(f'no parameter "{k}" in {r.name}; closest: {", ".join(near)}')
                retry[near[0]] = raw
            else:
                fixes.append(f'no parameter "{k}" in {r.name}; see stone show {r.name}')
                hard = True
            continue
        try:
            params[k] = rc.coerce(p, raw, imgs)
            retry[k] = rc.fmt_value(p, params[k])
        except rc.ParamError as e:
            fixes.append(e.fix)
            if e.suggest is not None:
                retry[k] = rc.fmt_value(p, e.suggest)
            else:
                hard = True
    if fixes:
        out.add(f"Plan not changed ({len(fixes)} problem{'s' if len(fixes) > 1 else ''}):")
        for f in fixes[:6]:
            out.fix(f)
        if hard or not retry:
            out.next = f"stone show {r.name}"
        else:
            out.next = f"stone set {r.name} " + " ".join(f"{k}={v}" for k, v in retry.items())
        out.stage = None
        out.result = "set refused: " + fixes[0]
        return out
    job.save_plan(r.name, params)
    merged = build_params(job, r, params)
    out.add(f"Plan: {r.name} ({r.title})")
    if from_request:
        out.add(f"From the request: {from_request}")
    if args.reset:
        out.add("All parameters back to defaults.")
    shown = 0
    defaults = r.defaults()
    for p in r.params:
        if merged.get(p.name) != defaults.get(p.name):
            unit = f" {p.unit}" if p.unit and p.type in ("number", "int") else ""
            out.add(f"{p.name} = {param_text(p, merged[p.name])}{unit}")
            shown += 1
    out.add(f"{len(r.params) - shown} other parameters at default.")
    if r.dims:
        try:
            d = r.expected_dims(merged)
            if len(d) == 3:
                out.add(f"Expected size {short_size([d['x'], d['y'], d['z']])}.")
        except (ValueError, TypeError, ZeroDivisionError, KeyError):
            pass
    out.next = "stone build"
    # a figure with no photos would only build to a FIX that says stone find: go there directly,
    # a step a small model would otherwise spend (its runs ran out of steps at stone colors)
    who = photos_from(job) if r.name == "figure" and not job.photos() else None
    if who:
        out.add(f"Next the figure needs photos of {who}.")
        out.next = f'stone find "{who}"'
    out.result = "plan " + (" ".join(changed_params(r, merged)) or "defaults")
    if args.reset:
        job.update(failed_builds=0)
    job.update(passed=False)
    return out


# build


def _fix_spec(r: rc.Recipe, check_name: str) -> dict | None:
    raw = r.fix.get(check_name)
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"param": raw}
    if isinstance(raw, dict) and raw.get("param"):
        return raw
    return None


def _round_dir(v: float, step: float, up: bool) -> float:
    q = v / step
    q = math.ceil(q - 1e-3) if up else math.floor(q + 1e-3)
    return round(q * step, 6)


def suggest_value(r: rc.Recipe, params: dict, res: checks.Result, spec: dict):
    p = r.param(spec["param"])
    if p is None:
        return None
    cur = params.get(p.name, p.default)
    if "to" in spec:
        return spec["to"] if spec["to"] != cur else None
    direction = spec.get("dir") or res.direction
    if p.type == "bool":
        if direction in ("on", "off"):
            v = direction == "on"
            return v if v != cur else None
        return None
    if res.name == "text" and p.type == "choice":
        # no letter size passes in this font: the font with the thickest strokes does
        best = max(p.choices, key=lambda c: checks.TEXT_STROKE.get(str(c), 0))
        return best if best != cur else None
    if p.type not in ("number", "int") or direction not in ("up", "down"):
        return None
    if res.name == "finger_gap" and res.at and res.measured and res.need:
        # the openings shrink in proportion: more rings or blades, or smaller cells
        if direction == "up":
            v = math.ceil(res.at * res.measured / res.need - 1e-6)
        else:
            v = math.floor(res.at * res.need / res.measured + 1e-6)
        if (p.max is not None and v > p.max) or (p.min is not None and v < p.min) or v == res.at:
            return None
        return v
    if res.name == "text" and res.at and res.measured and res.need:
        # letter height grows in proportion to the setting; whole mm, so the next build passes
        v = math.ceil(res.at * res.need / res.measured - 1e-6)
        if p.max is not None and v > p.max:
            return None
        return v
    try:
        cur = float(cur)
    except (TypeError, ValueError):
        return None
    span = (p.max - p.min) if p.max is not None and p.min is not None else 10.0
    if direction == "up":
        if res.name == "min_wall" and res.measured is not None and res.need is not None:
            v = max(cur * 1.25, cur + (res.need - res.measured) + 0.2)
        elif res.name == "first_layer" and res.measured and res.need:
            v = max(cur * 1.25, cur * math.sqrt(res.need / max(res.measured, 1e-6)))
        else:
            v = cur * 1.25 if cur > 0 else cur + max(span / 10, 1)
    else:
        if res.name == "bed" and res.measured and res.measured > 1:
            v = cur / res.measured * 0.95
        else:
            v = cur * 0.8 if cur > 0 else cur - max(span / 10, 1)
    step = 1.0 if p.type == "int" else 0.1
    v = _round_dir(v, step, direction == "up")
    if p.min is not None:
        v = max(v, p.min)
    if p.max is not None:
        v = min(v, p.max)
    if p.type == "int":
        v = int(round(v))
    if abs(float(v) - cur) < 1e-9:
        return None
    return v


def plan_fix(r: rc.Recipe, params: dict, results: list[checks.Result]):
    """(fix texts by check name, next command or None)."""
    texts: dict[str, str] = {}
    nxt = None
    for res in results:
        if res.ok:
            continue
        spec = {"param": res.param} if res.param and r.param(res.param) else _fix_spec(r, res.name)
        if spec is None:
            if res.name == "dims" and "dims" not in texts:
                texts[res.name] = f"go back to the defaults with stone set {r.name} --reset"
            continue
        p = r.param(spec["param"])
        if p is None:
            continue
        cur = params.get(p.name, p.default)
        val = suggest_value(r, params, res, spec)
        unit = f" {p.unit}" if p.unit and p.type in ("number", "int") else ""
        if val is None:
            texts[res.name] = f"change {p.name} (now {rc.fmt_value(p, cur)}{unit})"
        else:
            texts[res.name] = (
                f"set {p.name}={rc.fmt_value(p, val)} (now {rc.fmt_value(p, cur)}{unit})"
            )
            if nxt is None:
                nxt = f"stone set {p.name}={rc.fmt_value(p, val)}"
    return texts, nxt


def _error_param(r: rc.Recipe, params: dict, err: str):
    defaults = r.defaults()
    hits = []
    for p in r.params:
        m = re.search(rf"(?<![A-Za-z0-9_]){re.escape(p.name)}(?![A-Za-z0-9_])", err)
        if m:
            hits.append((m.start(), p))
    hits.sort(key=lambda h: h[0])
    for _, p in hits:
        if params.get(p.name) != defaults.get(p.name):
            return p
    return None


def _grow(r: rc.Recipe, params: dict, err: str):
    """A failed assert the recipe knows how to fix by growing one size, like a plate too narrow for its cutouts."""
    for text, rule in r.grow.items():
        g = r.param(rule.get("param", ""))
        if text in err and g is not None:
            try:
                v = math.ceil(float(rc.safe_eval(str(rule["value"]), r.merged(params))))
            except (KeyError, ValueError, TypeError):
                continue
            if (g.max is None or v <= g.max) and v > float(params.get(g.name, g.default)):
                return g, v
    return None


def _clay(job: Job, m):
    """One clay color per face, with snap-off struts in blue so they do not read as drips."""
    import numpy as np

    rgb = np.tile([217.0, 160.0, 102.0], (len(m.faces), 1))
    struts = read_json(job.build_dir / "struts.json") or []
    if struts:
        rgb[printable.strut_faces(m.triangles_center, struts)] = printable.STRUT_RGB
    return rgb


def views_step(job: Job, stl: Path) -> Path | None:
    """build/views.png: the part from every side, so a person or a large model can look at it all."""
    png = job.build_dir / "views.png"
    try:
        m = colortool.load_stl(stl)
        colortool.render_views(m, _clay(job, m), png)
    except Exception:  # a picture is never worth failing a passing build
        job.log("views failed:\n" + traceback.format_exc())
        return None
    return png


def closeup_step(job: Job, stl: Path, params: dict) -> Path | None:
    """build/closeup.png for a figure: the face from the front and both sides, and the name on the
    plinth, lit from the side and big enough to judge, which views.png's small panels are not
    (random five, round 3: every craft judge called the face soft and the name faint there)."""
    import numpy as np

    png = job.build_dir / "closeup.png"
    try:
        m = colortool.load_stl(stl)
        spots = []
        g = printable.occupancy(m)
        h = printable.head(g) if g is not None else None
        if h is not None:
            half = max(h["hw"], h["hd"], (h["top"] - h["neck"]) / 2) * 1.2
            c = (h["cx"], h["cy"], (h["neck"] + h["top"]) / 2 + half * 0.1)
            spots += [(f"face {a} deg", c, half, np.radians(a), np.radians(8)) for a in (0, 35, 325)]
        scale, sink, _ = printable.plinth(params)
        bh = float(params.get("height") or 90) - scale + sink  # the plinth's top
        low = m.vertices[m.vertices[:, 2] < bh - 0.1]
        if str(params.get("name") or "") and bh > 0 and len(low):
            w = float(np.ptp(low[:, 0]))
            # from 20 degrees up: level, the tops of the strokes do not show and an L's foot reads as
            # a dot ("L.AMINE", random five round 5)
            spots.append(("name", (0.0, float(low[:, 1].min()), bh * 0.55), w * 0.32, 0.0, np.radians(20),
                          colortool.SIDE))
        if not spots or not colortool.render_closeup(m, _clay(job, m), png, spots):
            return None
    except Exception:  # a picture is never worth failing a passing build
        job.log("closeup failed:\n" + traceback.format_exc())
        return None
    return png


def cmd_build(args, job: Job) -> Out:
    out = Out()
    if not need_job(job, out):
        return out
    plan = job.plan()
    if not plan:
        out.fix("pick a recipe first")
        out.next = "stone recipes"
        out.result = "build refused: no plan"
        return out
    r = rc.load(plan["recipe"])
    if r is None:
        return unknown_recipe(plan["recipe"], out, config.tier(job.root))
    binary = config.find_openscad()
    if not binary:
        out.fix("install OpenSCAD or set STONE_OPENSCAD to its path")
        out.next = "stone build"
        out.result = "no OpenSCAD"
        return out
    given = {k: v for k, v in plan["params"].items() if r.param(k)}
    dropped = sorted(set(plan["params"]) - set(given))
    params = build_params(job, r, given)
    st0 = job.status()
    if (st0.get("passed") and (job.root / f"{r.name}.stl").exists()
            and (st0.get("colors") or str(st0.get("next") or "").startswith("stone colors"))
            and read_json(job.build_dir / "stamp.json") == build_stamp(job, r, given)):
        # the part already passed with this exact plan, recipe and files, and is being painted: a
        # rebuild would make the same part and throw the paint (or a stone colors retry) away.
        # Checked before the figure step, which takes minutes when it has to run.
        out.add(f"Recipe: {r.name}",
                "Nothing changed since the last build, which passed. The part and its colors stay as they are.")
        out.next = str(st0.get("next") or DONE_NEXT)
        out.result = "build skipped: nothing changed"
        return out
    fig = next((p for p in r.params if p.type == "image" and p.image_kind == "figure"), None)
    if fig is not None and fig.name not in given:
        made = figure_step(job, r, params, out)
        if made is None:
            return out
        params[fig.name] = str(made)
    for p in r.params:
        if p.required and not params.get(p.name) and not (p.required_unless and params.get(p.required_unless)):
            other = f" or set {p.required_unless}" if p.required_unless else ""
            out.add(f"Recipe: {r.name}")
            out.fix(f"{r.name} needs a picture: run stone image with the picture file{other}")
            out.next = "stone image <path to picture>"
            out.stage = "needs_image"
            out.result = "needs a picture"
            out.code = 1
            return out
    bd = job.build_dir
    bd.mkdir(parents=True, exist_ok=True)
    for f in ("part.stl", "part.off", "preview.png", "check.json", "openscad.log", "preview.scad", "stamp.json", "figure-braced.stl",
              "engineering.json"):
        (bd / f).unlink(missing_ok=True)
    for f in [*job.root.glob("*.stl"), *job.root.glob("*.3mf")]:
        f.unlink()  # the finished part always matches the last build
    for f in ("regions.json", "regions.npy", "regions.npz", "paint.npy", "slivers.json", "regions.png", "colors.png", "atlas.png", "views.png", "boundaries.png", "closeup.png"):
        (bd / f).unlink(missing_ok=True)
    if job.status().get("colors"):
        job.update(colors=None)
    write_json(bd / "params.json", {"recipe": r.name, "params": params})
    write_json(bd / "stamp.json", build_stamp(job, r, given))
    st = job.status()
    builds = int(st.get("builds", 0)) + 1
    fails = int(st.get("failed_builds", 0))
    out.add(f"Recipe: {r.name}")
    if dropped:
        out.add(f"Ignored old parameters: {', '.join(dropped)}")
    stl = bd / "part.stl"
    made = params
    if fig is not None and params.get(fig.name) and Path(params[fig.name]).is_file():
        made = {**params, fig.name: str(brace_step(job, Path(params[fig.name]), params, out))}
    defines = None
    if catalog.job_products(job.root) and rc.catalog_param(r) is not None:
        # the job's own products join the tables the recipe reads (lib/catalog.scad, products.scad)
        defines = {"CATALOG": catalog.catalog_value()}
        if "PRODUCTS" in Path(r.scad).read_text():
            defines["PRODUCTS"] = catalog.products_value()
    run = scad.build_stl(binary, r, made, stl, defines)
    (bd / "openscad.log").write_text(run.log)
    job.log(f"openscad build ({'ok' if run.ok else 'failed'}):\n{run.log}")
    if not run.ok:
        fails += 1
        out.add(f"Build failed: {run.error}")
        p = _error_param(r, params, run.error)
        quality = next(
            (q for q in r.params if q.name in ("quality", "detail", "fn") and q.type in ("int", "number")),
            None,
        )
        if run.timed_out and quality is not None:
            cur = float(params.get(quality.name, quality.default))
            lower = max(quality.min if quality.min is not None else 8, cur / 2)
            lower = int(lower) if quality.type == "int" else round(lower, 1)
            out.fix(f"lower {quality.name} to {lower} so it builds faster")
            out.next = f"stone set {quality.name}={lower}"
        elif run.error.startswith(scad.SETUP_ERROR):
            # a reset or another build fails the same way: stop and ask, as figure_step does
            fix = f"uv tool install --reinstall --editable {config.REPO_ROOT}"
            out.fix(f"{run.error}. This is the computer's setup, not the part: no setting fixes it")
            out.next = (f"ask the person: {run.error}. Please run {fix}, then tell me to go on. "
                        "When they say to go on: stone build")
            out.add(f"Log: {bd / 'openscad.log'}")
            out.stage = "needs_setup"
            out.result = run.error[:120]
            job.update(builds=builds, passed=False)
            return out
        elif run.error.startswith(scad.SLICER_ERROR):
            seed = r.param("seed")
            if seed is not None:
                nxt_seed = int(params.get("seed", seed.default) or 0) + 1
                out.fix(f"{run.error}; another seed makes another mesh: set seed={nxt_seed}")
                out.next = f"stone set seed={nxt_seed}"
            else:
                out.fix(f"{run.error}; return to defaults with stone set {r.name} --reset")
                out.next = f"stone set {r.name} --reset"
        elif grown := _grow(r, params, run.error):
            g, v = grown
            unit = f" {g.unit}" if g.unit else ""
            out.fix(f"{g.name} is too small for the rest of the part; set {g.name}={rc.fmt_value(g, v)}{unit}")
            out.next = f"stone set {g.name}={rc.fmt_value(g, v)}"
        elif p is not None:
            d = rc.fmt_value(p, p.default)
            unit = f" {p.unit}" if p.unit and p.type in ("number", "int") else ""
            out.fix(f"change {p.name} (now {rc.fmt_value(p, params[p.name])}{unit}, default {d}{unit})")
            out.next = f"stone set {p.name}={d}"
        else:
            out.fix(f"return to defaults with stone set {r.name} --reset")
            out.next = f"stone set {r.name} --reset"
        if fails >= FAILS_BEFORE_RESET and not out.next.endswith("--reset"):
            out.add(f"{fails} builds failed. Start again from the defaults.")
            out.next = f"stone set {r.name} --reset"
        out.add(f"Log: {bd / 'openscad.log'}")
        out.stage = "build_failed"
        out.result = f"compile error: {run.error[:80]}"
        job.update(builds=builds, failed_builds=fails, passed=False)
        return out

    bed = config.bed(job.root)
    results = checks.check_stl(stl, recipe=r, params=params, bed=bed, log=run.log)  # the file that ships
    ok = checks.passed(results)
    size = checks.measured_size(results)
    texts, nxt = plan_fix(r, params, results) if not ok else ({}, None)
    write_json(
        bd / "check.json",
        {"passed": ok, "size_mm": size, "results": [x.to_dict() for x in results]},
    )
    if size:
        out.add(f"Size: {fmt_size(size)}")
    out.add(*checks.format_results(results, fix_line=lambda x: texts.get(x.name)))
    pv = scad.render_preview(binary, stl, bd / "preview.png")
    job.log(f"openscad preview ({'ok' if pv.ok else 'failed'}):\n{pv.log}")
    out.add(f"STL: {stl}")
    out.add(f"Preview: {bd / 'preview.png'}" if pv.ok else f"Preview: not made ({pv.error[:60]})")
    if ok:
        # a passing build is the finished part: no last step for a small model to forget
        final = job.root / f"{r.name}.stl"
        shutil.copyfile(stl, final)
        eng = fitted.write(bd, r, params, run.log)
        if eng:
            out.add(f"Engineering: {eng} (where the product sits, what holds it, a source for every size)")
        views = views_step(job, stl)
        if views:
            out.add(f"Views: {views} (look at every panel before you call it done)")
        close = closeup_step(job, stl, params) if fig is not None else None
        if close:
            out.add(f"Close-up: {close} (the face and the name, lit from the side)")
        if views:
            show([views, *([close] if close else [])], "The finished part")
        out.add(*build_references(job, r, params))
        out.add(f"Part ready: {final}")
        out.next = DONE_NEXT
        if colortool.asks_for_color(_color_text(job)):
            if _many_colors(job, r, params):
                out.add("The request names colors: stone colors splits the figure into color regions.")
                out.next = "stone colors"
                try:  # the parts are known now: NEXT is the mapping the request asks for
                    res = _color_regions(job, r, params, colortool.load_stl(final))
                    out.next = _suggest_line(res["regions"], config.filaments(job.root), _color_text(job))
                except Exception:  # the list is still one stone colors away
                    job.log("colors in build failed:\n" + traceback.format_exc())
            else:
                named = colortool.request_colors(_color_text(job))
                out.add(f"This part prints in one color: {named[0]}. Load that filament."
                        if named else "This part prints in one color.")
        out.stage = "done"
        out.result = f"build passed, {fmt_size(size) if size else ''}".rstrip(", ")
        job.update(builds=builds, failed_builds=0, passed=True)
        return out
    fails += 1
    out.code = 1
    first = next(x for x in results if not x.ok)
    if fails >= FAILS_BEFORE_RESET:
        out.add(f"{fails} builds failed. Start again from the defaults.")
        out.next = f"stone set {r.name} --reset"
    else:
        out.next = nxt or f"stone show {r.name}"
    out.stage = "build_failed"
    out.result = f"checks failed: {first.name} {first.detail}"[:120]
    job.update(builds=builds, failed_builds=fails, passed=False)
    return out


# check


def cmd_check(args, job: Job) -> Out:
    out = Out(owns_next=False)
    r = None
    params = None
    if args.file:
        f = Path(args.file).expanduser().resolve()
    else:
        f = job.build_dir / "part.stl"
        if not f.is_file():
            out.fix("no built part yet; build first or name an STL file")
            out.next = "stone build" if job.plan() else ("stone recipes" if job.exists() else NEW_NEXT)
            return out
        plan = job.plan()
        built = read_json(job.build_dir / "params.json") or {}
        if plan:
            r = rc.load(plan["recipe"])
            params = built.get("params") or (r.merged(plan["params"]) if r else None)
    if not f.is_file():
        out.fix(f"no file at {f}")
        out.next = "stone check <file.stl>"
        return out
    log = None
    if not args.file and (job.build_dir / "openscad.log").is_file():
        log = (job.build_dir / "openscad.log").read_text()
    results = checks.check_stl(f, recipe=r, params=params, bed=config.bed(job.root), log=log)
    ok = checks.passed(results)
    size = checks.measured_size(results)
    texts, nxt = plan_fix(r, params or {}, results) if (r and not ok) else ({}, None)
    out.add(f"File: {f}")
    if size:
        out.add(f"Size: {fmt_size(size)}")
    out.add(*checks.format_results(results, fix_line=lambda x: texts.get(x.name)))
    out.code = 0 if ok else 1
    out.result = "check passed" if ok else "check failed"
    if args.file:
        out.next = "none, the file passes" if ok else f"stone check {f}"
    else:
        out.next = "stone done" if ok else (nxt or f"stone show {r.name}" if r else "stone status")
    return out


# slice


def cmd_slice(args, job: Job) -> Out:
    """Cut the part into layers the way a slicer does and name what would print wrong, with no
    slicer installed: works the same for Creality Print, Orca, Prusa, Bambu or Cura users."""
    from . import slicer

    out = Out(owns_next=False)
    f = Path(args.file).expanduser().resolve() if args.file else job.build_dir / "part.stl"
    if not f.is_file():
        out.fix(f"no file at {f}" if args.file else "no built part yet; build first or name an STL file")
        out.next = "stone slice <file.stl>" if args.file else "stone build"
        return out
    rep = slicer.slice_stl(f, layer=args.layer, nozzle=args.nozzle, bed=config.bed(job.root))
    out.code = 0 if rep.ok else 1
    if args.json:  # machine output alone on stdout, like show --json
        out.raw = json.dumps(rep.to_dict(), indent=1)
        return out
    out.add(f"File: {f}")
    out.add(*slicer.summary(rep))
    out.code = 0 if rep.ok else 1
    out.result = "slices cleanly" if rep.ok else "a slicer prints this wrong"
    out.next = "none, the file slices cleanly" if rep.ok else ("stone build" if not args.file else f"stone slice {f}")
    return out


# image


def measured_crop(job: Job, path: Path) -> list[int] | None:
    """The measured object's box when stone measure ran on this same photo, else None."""
    m = job.measured() if job.exists() else None
    src = Path((m or {}).get("source", ""))
    box = ((m or {}).get("object") or {}).get("bbox_px")
    try:
        same = src.is_file() and path.is_file() and src.read_bytes() == path.read_bytes()
    except OSError:
        same = False
    return box if same and box else None


def image_step(job: Job, path: Path, out: Out):
    path = path.expanduser()
    crop = measured_crop(job, path)
    try:
        info = imagetool.process(path, job.image_dir, box=crop)
    except imagetool.ImageProblem as e:
        job.log("image failed:\n" + traceback.format_exc())
        out.fix(f"{e}; give a PNG or JPG picture")
        out.next = "stone image <path to picture>"
        out.result = f"image failed: {e}"
        return None
    w, h = info["svg_size_mm"]
    out.add(f"Image: {info['source']}" + (" (cropped to the measured object)" if crop else ""))
    out.add(
        f"Aspect {info['aspect']:.2f} (subject width / height), picture {info['image_aspect']:.2f}"
    )
    holes = "with holes" if info["has_holes"] else "no holes"
    out.add(f"Fill {info['fill'] * 100:.0f}% of the picture, {info['shapes']} shapes, {holes}")
    if info["kind"] == "silhouette":
        out.add("Looks like a silhouette (high contrast, clear outline).")
    else:
        out.add("Looks like a photo (many tones).")
    out.add(f"Silhouette: {info['silhouette']} ({w:.0f} x {h:.1f} units)")
    out.add(f"Height map: {info['height']}")
    out.add(f"Good recipes: {', '.join(info['recipes'])}")
    out.add("For image parameters use name=image.")
    # the request names the part ("lithophane", "cookie cutter"): go straight to that recipe
    pic = [r for r in rc.visible(rc.load_all(), config.tier(job.root)) if any(p.type == "image" for p in r.params)]
    ranked = rc.rank(pic, job.request() if job.exists() else "")
    plan = job.plan() if job.exists() else None
    if plan and plan.get("recipe") == "figure":
        out.owns_next = True  # the photo is what the figure plan was waiting for
        out.next = "stone build"
    elif ranked and ranked[0][0] > 0 and not plan:
        out.next = f"stone show {ranked[0][1].name}"
    else:
        words = " ".join(w.replace("_", " ") for w in info["recipes"])
        out.next = f"stone recipes {words}"
    out.stage = "image" if not job.plan() else None
    out.result = f"image {info['kind']}, aspect {info['aspect']:.2f}"
    return info


ANIMALS = {"dog", "puppy", "cat", "kitten", "pet", "bird", "horse", "rabbit", "bunny", "fox",
           "bear", "lion", "tiger", "owl", "parrot", "hamster", "corgi", "pug", "frog", "turtle",
           "retriever", "terrier", "poodle", "elephant", "monkey", "penguin", "dolphin", "shark",
           "giraffe", "panda", "koala", "deer", "cow", "pig", "goat", "sheep", "chicken", "duck",
           "lizard", "snake", "wolf", "dinosaur"}


def figure_who(job: Job, style: str) -> str:
    if style == "object":
        return "object"
    found = read_json(job.image_dir / "found" / "found.json") or {}
    if found.get("kind") in ("person", "animal", "character", "object") and not list(job.image_dir.glob("source.*")):
        return found["kind"]  # what Wikidata says the found subject is
    words = set(re.findall(r"[a-z]+", job.request().lower())) if job.exists() else set()
    return "animal" if words & ANIMALS else "person"


def figure_seed(job: Job, params: dict) -> int:
    """The figure's seed: the one set with stone set seed=, else STONE_FIGURE_SEED (the eval
    harness sets it to the run's seed, so two seeds of a case are two figures, not one figure
    painted twice), else the recipe's default."""
    plan = job.plan() or {}
    if "seed" in (plan.get("params") or {}):
        return int(plan["params"]["seed"])
    env = os.environ.get("STONE_FIGURE_SEED", "")
    return int(env) if env.isdigit() else int(params.get("seed") or 7)


# stone go sets these for a person at a terminal: "progress" takes a step's progress line,
# "show" takes pictures and a caption; a model's run leaves them unset
HOOKS: dict = {}


def progress(job: Job, text: str) -> None:
    """A step that takes minutes says so as it starts: on stderr, so the person at the terminal
    sees the build working and stdout still ends with the NEXT line, and in log.txt."""
    job.log(text)
    if HOOKS.get("progress"):
        HOOKS["progress"](text)
    else:
        print(text, file=sys.stderr, flush=True)


def show(paths: list, caption: str) -> None:
    """Pictures a person at a terminal sees as soon as they exist (stone go draws them inline)."""
    if HOOKS.get("show"):
        try:
            HOOKS["show"]([Path(p) for p in paths], caption)
        except Exception:  # a picture is a bonus: never a failed step
            pass


def brace_step(job: Job, fig: Path, params: dict, out: Out) -> Path:
    """Struts under every spot of the figure that would start in mid-air, so it prints without
    slicer supports. Returns the figure to build: braced, or as it was when bracing failed."""
    braced = job.build_dir / "figure-braced.stl"
    drawn = job.build_dir / "struts.json"  # where views.png draws them
    drawn.unlink(missing_ok=True)
    try:
        person = figure_who(job, str(params.get("style") or "chibi")) == "person"
        struts, held, spots, cut = printable.brace_figure(fig, braced, params, hair=person)
    except Exception:  # a figure that will not brace still builds; the islands check names the spots
        job.log("brace failed:\n" + traceback.format_exc())
        return fig
    if cut:
        out.add(f"Loose ends: {cut} hair strands under {2 * printable.STRAND:.1f} mm thick or tips that hung in the "
                "air were cut back to where they join, so they print clean and no strut runs across the face.")
    if struts:
        drawn.write_text(json.dumps(printable.part_struts(struts, params)))
        at = ", ".join(sorted(set(held), key=lambda h: float(h.split()[0])))
        out.add(f"Built-in supports: {len(struts)} thin struts hold up the spots that would print onto air "
                f"(at {at}; blue in views.png). They print with the figure; snip them off after, or keep them.")
    if spots:
        out.add(f"In the slicer: supports on, everywhere. No strut reaches {'; '.join(spots[:4])}.")
    return braced


def photos_from(job: Job) -> str | None:
    """Who stone find looks up for a figure with no photos; set and build both point there."""
    return findtool.subject_from_request(job.request()) if job.exists() else None


def figure_step(job: Job, r: rc.Recipe, params: dict, out: Out) -> Path | None:
    """Photos -> styled render -> 3D figure, cached in images/figure. None after a FIX."""
    photos = job.photos()
    if not photos:
        who = photos_from(job)
        out.add(f"Recipe: {r.name}")
        out.fix("the figure needs photos" + (f" of {who}" if who else "") + " first")
        out.next = f'stone find "{who}"' if who else "stone image <path to photo>"
        out.stage = "needs_image"
        out.result = "needs photos"
        return None
    style = str(params.get("style") or "chibi")
    who = figure_who(job, style)
    t0 = time.time()
    try:
        made = figuretool.make(photos, job.image_dir / "figure", style_name=style, who=who,
                               seed=figure_seed(job, params), say=lambda s: progress(job, s),
                               shown=lambda p: show([p], "Styled picture, lifted to 3D next"))
    except figuretool.FigureProblem as e:
        job.log("figure failed:\n" + traceback.format_exc())
        out.add(f"Recipe: {r.name}")
        out.fix(str(e))
        if e.setup:
            # the tools miss a part: a build again fails the same way, so stop and ask
            out.add(f"This is the computer's setup, not the request: stone build again fails the same way. "
                    f"The person runs {config.REPO_ROOT / figuretool.SETUP} once, then says to go on.")
            out.next = (f"ask the person: the figure tools on this computer are not set up ({e}). "
                        f"Please run {config.REPO_ROOT / figuretool.SETUP}, then tell me to go on. "
                        "When they say to go on: stone build")
            out.stage = "needs_setup"
            out.result = f"figure not set up: {e}"[:120]
            out.code = 1
            return None
        out.next = "stone build"
        out.stage = "build_failed"
        out.result = f"figure failed: {e}"[:120]
        out.code = 1
        return None
    secs = time.time() - t0
    out.add(f"Figure: {style} {who} from {len(photos)} photos"
            + (f" ({secs:.0f} s)" if secs > 2 else " (made before)"))
    return made


def cmd_find(args, job: Job) -> Out:
    out = Out(owns_next=False)
    if not need_job(job, out):
        return out
    plan = job.plan()
    recipe = plan.get("recipe") if plan else None
    other = None  # a part recipe the request names, ahead of figure
    if not recipe:
        ranked = rc.rank(rc.visible(rc.load_all(), config.tier(job.root)), job.request())
        fig = next((s for s, r in ranked if r.name == "figure"), 0)
        if ranked and ranked[0][0] > fig and ranked[0][1].name != "figure":
            other = ranked[0][1].name
    elif recipe != "figure":
        other = recipe
    if other:
        out.fix(f"stone find gets photos for the figure recipe, and this job is {other}")
        out.next = _fallback_next(job, []) if plan else f"stone show {other}"
        if out.next.startswith("stone find"):
            out.next = f"stone show {other}"
        out.result = "find refused: the job is not a figure"
        return out
    query = " ".join(args.query).strip().strip('"\'')
    if not query and (subject := findtool.subject_from_request(job.request())):
        # the rest of the request may say which one ("the Berkeley computer scientist")
        hint = findtool.hint_after(job.request(), subject)
        query = f"{subject}, {hint}" if hint else subject
    if not query:
        out.fix('say who or what to find, like stone find "Ada Lovelace"')
        out.next = 'stone find "<who or what>"'
        return out
    try:
        got = findtool.fetch(query, job.image_dir / "found", n=args.n)
    except findtool.WhichOne as e:
        # the wrong person's figure is the worst result: ask which one before any photo is taken
        out.add(f"Several well known people are called {e.name}:")
        for p in e.people[:4]:
            out.add(f"- {p['label']}, {p['description'] or 'no description'} (wikidata {p['id']})")
        out.fix(f"say which {e.name}; stone takes photos of one person only")
        choices = " or ".join(f"{p['label']}, {p['description']}" for p in e.people[:3])
        out.next = (f"ask the person: which {e.name} do you mean: {choices}? "
                    f'When they answer: stone find "{e.name}, <what that one is known for>"')
        out.owns_next = True
        out.stage = "needs_image"
        out.result = f"find asks which {e.name}"
        return out
    except findtool.FindProblem as e:
        out.fix(f"{e}; give your own photo with stone image <path to photo>")
        out.next = "stone image <path to photo>"
        out.result = f"find failed: {e}"
        return out
    try:
        who = json.loads((job.image_dir / "found" / "found.json").read_text())
    except (OSError, ValueError):
        who = {}
    name = who.get("subject") or query
    if who.get("wikidata"):
        desc = f", {who['description']}" if who.get("description") else ""
        out.add(f"Who: {name}{desc} (wikidata {who['wikidata']}). Not them? stone find \"{name}, <what they are known for>\"")
    out.add(f"Found {len(got)} free-licensed photos of {name} on Wikimedia Commons:")
    for g in got:
        out.add(f"{Path(g['file']).name}: {g['license']}, by {g['author'] or 'unknown'}")
    left = findtool.left_out_line(who.get("left_out") or [], name)
    if left:
        out.add(left)
    if str(who.get("faces") or "").startswith("not checked"):
        # the find still works without the face models; the person should know it went unchecked
        out.add(f"Faces {who['faces']}; look that every photo shows {name} alone.")
    out.add(f"Credits: {job.image_dir / 'found' / 'credits.txt'} (name them when you share the part)")
    show([g["file"] for g in got], f"Photos found of {query}")
    out.owns_next = True  # the photos are what the plan was waiting for
    if plan and plan.get("recipe") == "figure":
        out.next = "stone build"
        out.stage = "plan"
    else:
        out.next = "stone show figure"
        out.stage = "image"
    out.result = f"found {len(got)} photos of {name}"
    return out


def cmd_image(args, job: Job) -> Out:
    out = Out(owns_next=False)
    if not job.exists():
        out.add(f"No job in {job.root}.")
        out.next = f'stone new "<what to make>" --image {args.path}'
        out.code = 1
        return out
    if not Path(args.path).expanduser().is_file() and read_json(job.image_dir / "info.json"):
        out.add("The picture is already in the job; recipes use it with image=image.")
        out.next = _fallback_next(job, [])
        return out
    image_step(job, Path(args.path), out)
    return out


# measure


def cmd_measure(args, job: Job) -> Out:
    out = Out(owns_next=False)
    path = args.path
    if not path:
        info = read_json(job.image_dir / "info.json") if job.exists() else None
        if info and Path(info.get("source", "")).is_file():
            path = info["source"]
        else:
            out.fix("name the photo, like stone measure photo.jpg")
            out.next = "stone measure <path to photo>"
            return out
    known = None
    if args.known:
        try:
            known = measuretool.parse_known(args.known)
        except measuretool.MeasureProblem as e:
            out.fix(str(e))
            out.next = f"stone measure {path} --known 120mm"
            return out
    try:
        res = measuretool.measure(Path(path).expanduser(), ref=args.ref, known_mm=known)
    except measuretool.MeasureProblem as e:
        out.fix(str(e))
        out.next = f"stone measure {path} --ref card"
        return out
    except imagetool.ImageProblem as e:
        job.log("measure failed:\n" + traceback.format_exc())
        out.fix(f"{e}; give a PNG or JPG photo")
        out.next = "stone measure <path to photo>"
        return out
    out.add(f"Photo: {path}")
    ru = res.get("ruler")
    if ru:
        out.add(f"Ruler: {res['unit']}, ticks {ru['tick']} apart, {ru['ticks']} ticks, at {ru['angle_deg']:g} deg.")
    out.add(res["assumed"])
    o = res.get("object")
    if res["mm_per_px"] is None:
        out.fix("add --known <long side>mm, or --ref card or --ref coin-us-quarter if one is in the photo")
        out.next = f"stone measure {path} --known <long side>mm"
        out.result = "measure: no scale"
        return out
    out.add(f"Scale: {res['mm_per_px']:.4f} mm per pixel ({1 / res['mm_per_px']:.2f} pixels per mm).")
    if not o or not o.get("long_mm"):
        out.fix("found no object apart from the reference; the object needs a plain surface around it")
        out.next = "stone measure <path to photo>"
        out.result = "measure: no object"
        return out
    out.add(f"Object: {o['long_mm']:.1f} x {o['short_mm']:.1f} mm (long x short side), "
            f"box {o['bbox_mm'][0]:.1f} x {o['bbox_mm'][1]:.1f} mm.")
    out.add(f"Confidence: {res['confidence']:.2f}" + (" (low, check the size)" if res["confidence"] < 0.5 else ""))
    for n in res.get("notes", [])[:3]:
        out.add(n)
    out.result = f"measured {o['long_mm']:.1f} x {o['short_mm']:.1f} mm ({res['method']})"
    if not job.exists():
        out.add("No job, so the size is not saved.")
        out.next = f'stone new "<what to make>" --image {path}'
        return out
    write_json(job.measure_file, res)
    out.add(f"Saved to the job: picture recipes take {o['long_mm']:.1f} mm as their size.")
    info = read_json(job.image_dir / "info.json")
    traced = Path(info["source"]) if info and info.get("source") else None
    crop = measured_crop(job, traced) if traced and not info.get("crop") else None
    if crop:
        try:
            imagetool.process(traced, job.image_dir, box=crop)
            out.add("Traced the outline again around the object only, without the ruler or card.")
        except imagetool.ImageProblem:
            job.log("retrace after measure failed:\n" + traceback.format_exc())
    plan = job.plan()
    r = rc.load(plan["recipe"]) if plan else None
    ms = measured_size(job, r) if r else None
    if r and ms and ms[0] not in plan["params"]:
        out.add(f"Plan size now {ms[0]}={rc.fmt_num(ms[1])}.")
        out.next = "stone build"
        out.owns_next = True
        job.update(passed=False)
    elif not read_json(job.image_dir / "info.json"):
        out.next = f"stone image {path}"
    elif plan:
        out.next = "stone build" if not job.status().get("passed") else DONE_NEXT
    else:
        pic = [x for x in rc.visible(rc.load_all(), config.tier(job.root)) if x.name in measuretool.SIZE_PARAMS]
        ranked = rc.rank(pic, job.request())
        out.next = f"stone show {ranked[0][1].name}" if ranked and ranked[0][0] > 0 else "stone recipes"
    return out


# done


def cmd_note(args, job: Job) -> Out:
    """Keep a researched fact and its source in the job, so it survives a compaction."""
    out = Out(owns_next=False)
    if not need_job(job, out):
        return out
    text = " ".join(args.text).strip()
    if not text:
        out.add('Write the fact and where it came from: stone note "width = 71.9 mm, apple.com/iphone/compare"')
        out.code = 1
        out.next = job.status().get("next") or "stone status"
        return out
    st = job.status()
    asked = str(st.get("next", ""))
    if asked.startswith("ask the person") and is_the_question(text, asked):
        out.fix("that is your question, not the person's answer; write the question as your reply and stop")
        out.add("Note only what the person says back.")
        out.next = asked
        out.owns_next = True
        out.result = "note refused: it was the question"
        return out
    notes = job.add_note(text)
    out.add(f"Noted ({len(notes)} notes): {text}")
    if str(st.get("next", "")).startswith("ask the person") and st.get("ask_product"):
        # the answer is the product's size: it is kept as a note, never read into the request as a part size
        return note_product(out, job, st, text)
    if str(st.get("next", "")).startswith("ask the person") and st.get("ask_recipe"):
        # the answer to stone's question is part of the request now, so show places its size
        with job.brief_file.open("a") as f:
            f.write(f"\nAnswer: {text}\n")
        out.owns_next = True
        out.next = f"stone show {st['ask_recipe']}"
        return out
    out.next = st.get("next") or "stone recipes"
    return out


FACE_WORDS = {"top": "+z", "bottom": "-z", "front": "-y", "back": "+y", "rear": "+y", "right": "+x", "left": "-x"}


def cmd_product(args, job: Job) -> Out:
    """stone product add: a product the catalog does not have, from the size the person gave and
    where it comes from, written to job/products/<slug>.json. stone never estimates a size, so a
    product with no source is refused."""
    out = Out(stage="product")
    if not need_job(job, out):
        return out
    name = " ".join(args.name).strip().strip('"')
    st = job.status()
    again = job.status().get("next") or "stone recipes"
    size = list(args.size or [])
    usage = f'stone product add "{name or "<name>"}" --size W D H --source "<URL or measured by the person>"'
    if not args.source or not str(args.source).strip():
        out.fix("give --source: the maker's spec page URL, or \"measured by the person\"; "
                "stone never estimates a size, so a size with no source is not used")
        out.next = (f"ask the person: where do {name or 'the product'}'s numbers come from "
                    f"(the maker's spec page, or their own ruler)?")
        out.result = "product refused: no source"
        return out
    if args.round and len(size) == 2:
        size = [size[0], size[0], size[1]]  # a disc: diameter and height
    if len(size) != 3 or not name:
        out.fix(("name the product and " if not name else "") + "give --size with width, depth and height in mm"
                + " (a round one: --round with its diameter and height)")
        out.next = usage
        out.result = "product refused: no size"
        return out
    w, d, h = size
    if min(size) <= 0 or max(size) > 2000:
        out.fix("each size is in mm, above 0 and at most 2000")
        out.next = usage
        out.result = "product refused: size out of range"
        return out
    if args.round and abs(d - w) > 0.01:
        out.fix(f"a round product's depth is its diameter: give --size {rc.fmt_num(w)} {rc.fmt_num(w)} {rc.fmt_num(h)}")
        out.next = usage.replace("W D H", f"{rc.fmt_num(w)} {rc.fmt_num(w)} {rc.fmt_num(h)} --round")
        out.result = "product refused: round with two widths"
        return out
    faces = []
    for f in re.split(r"[,\s]+", (args.open or "").strip().lower()):
        f = FACE_WORDS.get(f, f)
        if f and f not in catalog.FACES:
            out.fix(f"--open takes faces like +z or -y,+y (or top, front, back), not {f}")
            out.next = usage
            out.result = "product refused: bad face"
            return out
        if f:
            faces.append(f)
    have = catalog.find(name, list(catalog.shipped()))
    if have is not None or catalog.slug_of(name) in catalog.shipped():
        prod = catalog.get(have or catalog.slug_of(name))
        out.fix(f"the catalog already has the {prod['name']} with its published sizes ({prod['slug']}); use it")
        out.next = again if not again.startswith("stone product") else "stone recipes"
        out.result = "product refused: already in the catalog"
        return out
    if catalog.slug_of(name) == "":
        out.fix("name the product with letters or numbers")
        out.next = usage
        return out
    rec = catalog.make_product(name, w, d, h, str(args.source).strip(), args.corner_r, args.round, faces)
    path = job.root / "products" / f"{rec['slug']}.json"
    write_json(path, rec)
    b = rec["body"]
    out.add(f"Product: {rec['name']}, slug {rec['slug']} (written to {path})")
    out.add(f"Size: {short_size([b['w'], b['d'], b['h']])}" + (", round" if args.round else f", corner_r {rc.fmt_num(b['corner_r'])}")
            + (f", open {' '.join(faces)}" if faces else "") + f"; source: {args.source}")
    kinds = catalog.kinds_for(rec["slug"])
    takers = [r for r in rc.load_all().values() if rc.catalog_param(r) is not None and rc.catalog_param(r).catalog in kinds]
    out.add("Parts that take it: " + (", ".join(r.name for r in takers) or "none yet"))
    plan = job.plan()
    pick = (plan or {}).get("recipe") or st.get("ask_recipe")
    r = rc.load(pick) if pick else None
    job.update(ask_product=None, ask_got=None)
    out.result = f"product {rec['slug']} added"
    if r is None or not takes(r, rec["slug"]):
        if r is not None:
            out.add(f"{r.name} cannot take it ({'a round body' if args.round else 'a box'}); pick one that does.")
        out.next = "stone recipes"
        return out
    cp = rc.catalog_param(r)
    sug = match.suggest_full(r, job.request())[0] if job.request() else {}
    sug[cp.name] = rec["slug"]
    out.next = f"stone set {r.name} " + " ".join(f"{k}={rc.fmt_value(r.param(k), v)}" for k, v in sug.items() if r.param(k))
    return out


def cmd_refs(args, job: Job) -> Out:
    """The reference library: facts stone applies on its own, each with its source."""
    out = Out(owns_next=False)
    topic = " ".join(args.topic).strip()
    out.next = (job.status().get("next") or "stone status") if job.exists() else NEW_NEXT
    if not topic:
        lib = reftool.load()
        out.add(f"Reference library: {len(lib)} facts, each with its source and the date it was checked.",
                "Filaments: " + " ".join(reftool.MATERIALS) + " (stone refs PETG)",
                "Standards: clearance us fdm finger wallplate fan gridfinity keystone ada",
                "Design: contrast colors harmony edges text legibility food",
                "Each passing build prints the filament it picked and why; stone show prints the references.")
        out.result = "listed reference topics"
        return out
    found = reftool.topic_entries(topic)
    if not found:
        out.add(f'No reference matches "{topic}". Topics: filament ' + " ".join(reftool.MATERIALS)
                + " clearance fan gridfinity keystone ada contrast colors edges text food")
        out.code = 1
        return out
    room = MAX_LINES - 2
    for e in found[:room]:
        out.add(reftool.entry_line(e))
    if len(found) > room:
        out.add(f"({len(found) - room} more: add a word, like stone refs {topic} nozzle)")
    out.result = f"refs {topic}"
    return out


def cmd_video(args, job: Job) -> Out:
    """A vertical clip of a finished painted job for X, from the run log of the model that made it.
    The log defaults to log.json beside the job folder, where evals/run.py writes it."""
    out = Out(owns_next=False)
    if not need_job(job, out):
        return out
    log = Path(args.log).expanduser() if args.log else job.root.parent / "log.json"
    dest = Path(args.out).expanduser() if args.out else job.root / "video"
    nxt = job.status().get("next") or "stone status"
    if not log.exists():
        out.fix(f"no run log at {log}: pass the log.json the model run wrote, stone video <log.json>")
        out.next = nxt
        return out
    others = [Path(r).expanduser() for r in args.runs or []]
    for r in others:
        if not (r / "job").is_dir() or not (r / "log.json").is_file():
            out.fix(f"no run at {r}: --with takes a run folder holding job/ and log.json")
            out.next = nxt
            return out
    from . import video
    turn = args.turn if args.turn is not None else video.SERIES_TURN if others else video.TURN
    try:
        if others:
            items = [(job.root, log)] + [(r / "job", r / "log.json") for r in others]
            rep = video.make_series(items, dest, turn=turn)
        else:
            rep = video.make(job.root, log, dest, turn=turn)
    except video.VideoProblem as e:
        out.fix(str(e))
        out.next = nxt
        return out
    s = rep["spec"]
    out.add(f"Clip: {rep['clip']} ({rep['seconds']:.1f} s, {s['width']}x{s['height']}, {s['lufs']:.1f} LUFS)")
    out.add(f"Stills and contact sheet: {dest / 'stills'}")
    for f in rep["faults"]:
        out.fix(f)
    if not rep["faults"]:
        out.add("PASS video: spec, safe areas, glyphs and terminal lines all check")
    out.result = "video made" if not rep["faults"] else f"video faults: {rep['faults'][0]}"
    out.next = nxt
    return out


def cmd_done(args, job: Job) -> Out:
    out = Out()
    if not need_job(job, out):
        return out
    plan = job.plan()
    s = job.status()
    if not plan:
        out.add("Not done: no recipe picked yet.")
        out.next = "stone recipes"
        out.code = 1
        return out
    r = rc.load(plan["recipe"])
    if r is None:
        return unknown_recipe(plan["recipe"], out, config.tier(job.root))
    stl = job.build_dir / "part.stl"
    built = read_json(job.build_dir / "params.json") or {}
    current = build_params(job, r, {k: v for k, v in plan["params"].items() if r.param(k)})
    if not stl.is_file() or built.get("recipe") != r.name:
        out.add("Not done: the plan has not been built yet.")
        out.next = "stone build"
        out.code = 1
        return out
    if built.get("params") != current:
        out.add("Not done: the plan changed after the last build.")
        out.next = "stone build"
        out.code = 1
        return out
    if not s.get("passed"):
        out.add(f"Not done: the last build did not pass ({s.get('last_result', '')[:80]}).")
        nxt = s.get("next")
        out.next = nxt if nxt and nxt not in ("stone done", DONE_NEXT) else "stone build"
        out.code = 1
        out.owns_next = False
        return out
    final = job.root / f"{r.name}.stl"
    shutil.copyfile(stl, final)
    cj = read_json(job.build_dir / "check.json") or {}
    size = cj.get("size_mm")
    out.add(f"Done: {r.name} ({r.title})" + (f", {fmt_size(size)}" if size else "") + ", all checks pass.")
    out.add(f"Request: {job.request()}")
    out.add(f"Params: {params_summary(r, current)}")
    out.add(f"STL: {final}")
    pv = job.build_dir / "preview.png"
    if pv.is_file():
        out.add(f"Preview: {pv}")
    out.next = DONE_NEXT
    out.stage = "done"
    out.result = f"done, {final.name}"
    return out


# colors


REST_KEYS = ("rest", "others", "other", "all", "else", "*")


def _style_pictures(job: Job, params: dict) -> tuple[Path | None, Path | None]:
    """The figure step's style picture (and back view) for this build: the cache folder named
    like the built figure's, in this job first, so a copied job still finds its own."""
    fig = params.get("figure") or ""
    if not fig:
        return None, None
    d = Path(fig).parent
    for c in (job.image_dir / "figure" / d.name, d):
        if (c / "style.png").is_file():
            back = c / "back.png"
            return c / "style.png", back if back.is_file() else None
    return None, None


def _many_colors(job: Job, r: rc.Recipe, params: dict) -> bool:
    """True when the part can have more than one color region: a figure with a style picture."""
    is_fig = any(p.type == "image" and p.image_kind == "figure" for p in r.params)
    return is_fig and _style_pictures(job, params)[0] is not None


def _look(job: Job, params: dict) -> str:
    """The figure step's one-sentence look (look.txt), or ""."""
    front, _ = _style_pictures(job, params)
    if front is None:
        return ""
    p = front.parent / "look.txt"
    return p.read_text().strip() if p.is_file() else ""


def _names(job: Job) -> list[str]:
    """The subject's names: the one stone find searched, and capitalized names in the request."""
    found = read_json(job.image_dir / "found" / "found.json") or {}
    return colortool.subject_names(job.request(), [found.get("query") or ""])


def _color_text(job: Job) -> str:
    """The request with the subject's name taken out, so "Jack Black" names no color."""
    return colortool.without_names(job.request(), _names(job))


def _color_regions(job: Job, r: rc.Recipe, params: dict, mesh) -> dict:
    """colors.find_regions for the built part, cached in build/ for this exact STL: the mesh the
    regions are on (a figure's is cut along its hem, neck and wrists), the region number per face,
    the region list and the faces whose edge is a line of the shape."""
    import hashlib

    import numpy as np

    bd = job.build_dir
    stamp = hashlib.sha1((bd / "part.stl").read_bytes()).hexdigest()
    cached = read_json(bd / "regions.json") or {}
    if (cached.get("stl") == stamp and cached.get("version") == colortool.REGIONS_VERSION
            and (bd / "regions.npz").is_file()):
        d = np.load(bd / "regions.npz")
        m = colortool.load_stl_mesh(d["V"], d["F"]) if len(d["F"]) != len(mesh.faces) else mesh
        if len(d["num"]) == len(m.faces):
            fixed = d["fixed"] if d["fixed"].any() else None
            return {"mesh": m, "num": d["num"], "regions": cached["regions"], "fixed": fixed,
                    "anatomy": cached.get("anatomy")}
    front, back = _style_pictures(job, params) if any(
        p.type == "image" and p.image_kind == "figure" for p in r.params) else (None, None)
    res = colortool.find_regions(mesh, r.name, params, front, back, bd / "atlas.png", look=_look(job, params))
    m = res["mesh"]
    fixed = res["fixed"] if res["fixed"] is not None else np.zeros(len(m.faces), bool)
    np.savez(bd / "regions.npz", V=np.asarray(m.vertices, np.float32), F=np.asarray(m.faces, np.int32),
             num=res["num"], fixed=fixed)
    write_json(bd / "regions.json", {"stl": stamp, "version": colortool.REGIONS_VERSION, "picture": str(front) if front else None, "regions": res["regions"],
                                     "anatomy": res["anatomy"]})
    colortool.render(m, colortool.region_tints(res["num"], res["regions"]), bd / "regions.png", numbers=res["num"],
                     show=set(range(1, colortool.LIST_MAX + 1)))
    return res


def _fil_value(fil: list[str]) -> list[str]:
    """How each filament is written in a stone colors line: its name, or its number when the name has spaces."""
    return [f if re.fullmatch(r"[A-Za-z#0-9_-]+", f) else str(i) for i, f in enumerate(fil, 1)]


NAMED_DE = 45.0  # a region takes a named color only when its photo color is this close (delta E)


def _rest_color(request: str, named: list[str]) -> str | None:
    """The color the request gives to everything not named, or None when it gives none:
    "all white", "white everywhere else", "the rest white", "white with a red dress"."""
    words = re.findall(r"[a-z]+(?:-[a-z]+)?", request.lower())
    for i, w in enumerate(words):
        c = colortool.word_color(w)
        if c not in named:
            continue
        before, after = words[max(0, i - 3):i], words[i + 1:i + 3]
        if (i and words[i - 1] == "all") or {"rest", "else", "otherwise"} & set(before):
            return c
        if after and (after[0] in ("everywhere", "everything", "otherwise", "with") or after[:2] == ["for", "the"]):
            return c
    return None


def _picture_filament(rgb, fil: list[str], rest: int) -> int:
    """A part that keeps its picture color: the nearest loaded filament, or when that is the rest
    color, the next nearest, so the part still stands out."""
    import numpy as np

    have = [(i, colortool.filament_rgb(f)) for i, f in enumerate(fil, 1)]
    have = [(i, c) for i, c in have if c is not None]
    if rgb is None or not have:
        return rest
    d = [float(np.sqrt(((colortool._lab(c) - colortool._lab(rgb)) ** 2).sum())) for _, c in have]
    order = [have[k][0] for k in np.argsort(d)]
    return next((i for i in order if i != rest), order[0])


def _suggest(info: list[dict], fil: list[str], request: str) -> tuple[dict, int, list[str]]:
    """(region -> filament, rest filament, extra filaments). On a figure whose request names parts
    ("a black jacket", "all white but the jacket"), exactly that: each named part its color, a
    part after "but" its picture color, every other part the rest color. Otherwise _suggest_colors."""
    from . import parts

    pc = {k: v for k, v in colortool.part_colors(request).items() if not k.startswith("word:")}
    if "name" in pc and not any(d.get("part") == "name" for d in info):
        c = pc.pop("name")  # no name raised on the plinth: "a red name" is the plinth, as it always was
        pc.setdefault("base", c)
    named = colortool.request_colors(request)
    figure = any(d.get("part") not in (None, "name") for d in info)  # a name on a plinth is no figure
    if not pc and len(named) == 1 and figure:
        # one color and no part given a color ("Jensen Huang in white", even with "on the base"
        # or "his face" said along the way): the whole figure is that color
        n = _match_filament(named[0], fil)
        if n is None:
            return {}, len(fil) + 1, [named[0]]
        return {}, n, []
    if not pc or not figure:
        pick, rest, extra = _suggest_colors(info, fil, request)
        # the name's color is picked to stand out from the plinth, never from the photo
        return {k: v for k, v in pick.items() if not any(d["n"] == k and d.get("part") == "name" for d in info)}, rest, extra

    extra: list[str] = []
    allf = list(fil)

    def num(c: str) -> int:
        n = _match_filament(c, allf)
        if n is None:
            allf.append(c)
            extra.append(c)
            n = len(allf)
        return n

    rest_c = _rest_color(request, named)
    if rest_c is None:
        plain = [c for c in named if c not in pc.values()]
        rest_c = plain[0] if plain else None
    # with no rest color in the request, rest is the photo color of the parts it does not name:
    # a named part's own color (a long black coat) must not become everything else's
    unnamed = [d for d in info if (parts.part_of(d.get("part") or "") or d.get("part")) not in pc]
    _, rest_p, _ = _suggest_colors(unnamed or info, fil, "")
    rest = num(rest_c) if rest_c else rest_p
    pick: dict[int, int] = {}
    for d in info:
        p = parts.part_of(d.get("part") or "") or d.get("part")
        if d["base"] and p not in pc:
            continue
        if p == "name" and pc.get(p, "picture") == "picture":
            continue  # stone colors gives the name a color that stands out from the plinth
        if p in pc:
            pick[d["n"]] = _picture_filament(d["rgb"], allf, rest) if pc[p] == "picture" else num(pc[p])
        else:
            pick[d["n"]] = rest  # every part not named takes rest (the photo's when none is named)
    return pick, rest, extra


def _suggest_colors(info: list[dict], fil: list[str], request: str) -> tuple[dict, int, list[str]]:
    """(region -> filament, rest filament, extra filaments). Each region starts from its photo
    color, mapped to the nearest loaded filament. A region takes a color the request names when
    that named color is nearest its photo color, under NAMED_DE. Rest (and the base) is the color
    the request gives to everything else ("all white", "white everywhere else", "white with a red
    dress"); then the other regions take rest too, except, after "but" or "except", the ones far
    from rest, which keep their photo color. With no such phrase, rest is the photo color that
    covers the most surface among the regions no named color took."""
    import numpy as np

    pick: dict[int, int] = {}
    extra: list[str] = []
    allf = list(fil)

    def num(c: str) -> int:
        n = _match_filament(c, allf)
        if n is None:
            allf.append(c)
            extra.append(c)
            n = len(allf)
        return n

    named = colortool.request_colors(request)
    if not any(d["rgb"] is not None for d in info):
        return pick, (num(named[0]) if named else 1), extra
    rest_c = _rest_color(request, named)
    others = [c for c in named if c != rest_c]
    ref = colortool._lab([colortool.NAMES[c] for c in others]) if others else None
    taken: set[int] = set()
    for d in info:
        if d["rgb"] is None or d["base"]:
            continue
        pick[d["n"]] = colortool.nearest_filament(d["rgb"], fil)
        if ref is not None:
            dist = np.sqrt(((ref - colortool._lab(d["rgb"])) ** 2).sum(1))
            k = int(dist.argmin())
            if dist[k] < NAMED_DE:
                pick[d["n"]] = num(others[k])
                taken.add(d["n"])
    if rest_c is not None:
        rest = num(rest_c)
        keep = bool({"but", "except"} & set(re.findall(r"[a-z]+", request.lower())))
        rlab = colortool._lab([colortool.NAMES[rest_c]])
        for d in info:
            if d["n"] not in pick or d["n"] in taken:
                continue
            far = float(np.sqrt(((rlab - colortool._lab(d["rgb"])) ** 2).sum())) >= NAMED_DE
            if not (keep and far):
                pick[d["n"]] = rest
        return pick, rest, extra
    share: dict[int, float] = {}
    for d in info:
        if d["n"] in pick and d["n"] not in taken:
            share[pick[d["n"]]] = share.get(pick[d["n"]], 0.0) + d["share"]
    if not share:
        for d in info:
            if d["n"] in pick:
                share[pick[d["n"]]] = share.get(pick[d["n"]], 0.0) + d["share"]
    rest = max(share, key=share.get) if share else 1
    return pick, rest, extra


def _match_filament(v: str, fil: list[str]) -> int | None:
    """Filament number for a color word or a filament's name, or None when none is loaded."""
    v = v.strip().lower()
    for i, f in enumerate(fil, 1):
        if f.lower() == v:
            return i
    c = colortool.word_color(v)
    if c:
        for i, f in enumerate(fil, 1):
            if any(colortool.word_color(w) == c for w in re.findall(r"[a-z]+", f.lower())):
                return i
    return None


def _mapping_items(info: list[dict], pick: dict[int, int], rest: int, names: list[str]) -> list[str]:
    """key=filament for every region not in the rest color: by part name when all of that part's
    regions take one filament ("hands=white"), else by region number."""
    items: list[str] = []
    done: set[str] = set()
    listed = {d["n"] for d in info[:colortool.LIST_MAX]}
    for d in info:  # every region, not only the listed ones: a part asked for is never dropped
        f = pick.get(d["n"], rest)
        part = d.get("part")
        if part in done:
            continue  # its key=filament is already in the line
        if part and part not in ("other", "base"):
            same = {pick.get(e["n"], rest) for e in info if e.get("part") == part}
            if len(same) == 1:
                done.add(part)
                if f != rest:
                    items.append(f"{part}={names[f - 1]}")
                continue
        if f != rest and d["n"] in listed:  # a numbered region only when the listing showed it
            items.append(f"{d['n']}={names[f - 1]}")
    return items


def _suggest_line(info: list[dict], fil: list[str], request: str) -> str:
    pick, rest, extra = _suggest(info, fil, request)
    names = _fil_value(fil + extra)
    return "stone colors " + " ".join(_mapping_items(info, pick, rest, names) + [f"rest={names[rest - 1]}"])


def _part_regions(info: list[dict], key: str) -> list[int]:
    """The region numbers a part name stands for ("jacket", or "top" for the jacket). With no name
    raised on the plinth, "name" is the plinth, as it was before the name was a region."""
    from . import parts

    key = key.strip().lower()
    want = parts.part_of(key)
    got = [d["n"] for d in info if d.get("part") and d["part"] not in ("other",)
           and (d["part"] == key or (want is not None and parts.part_of(d["part"]) == want))]
    if not got and want == "name":
        got = [d["n"] for d in info if d["base"] and d.get("part")]
    return got


def _named_words(request: str) -> list[tuple[str, str]]:
    """(the word the request used, its color) for every part the request gives a color of its own
    ("jacket", "black"), in the request's order; a part "but" leaves to the picture is not one."""
    pc = colortool.part_colors(request)
    return [(pc.get(f"word:{k}", k), v) for k, v in pc.items() if not k.startswith("word:") and v != "picture"]


def _named_regions(info: list[dict], request: str) -> dict[int, str]:
    """Region number -> the color the request gives its part. With no name raised on the plinth a
    name's color is the plinth's, as _suggest takes it."""
    pc = {k: v for k, v in colortool.part_colors(request).items() if not k.startswith("word:") and v != "picture"}
    if "name" in pc and not any(d.get("part") == "name" for d in info):
        pc.setdefault("base", pc.pop("name"))
    out: dict[int, str] = {}
    for k, c in pc.items():
        regs = [d["n"] for d in info if d["base"]] if k == "base" else _part_regions(info, k)
        for g in regs:
            out.setdefault(g, c)
    return out


def _named_missing(info: list[dict], request: str) -> list[str]:
    """The words of the parts the request gives a color that the figure has no region for (shoes
    the region finder merged into the trousers): no mapping can paint those."""
    pc = colortool.part_colors(request)
    out = []
    for k, c in pc.items():
        if k.startswith("word:") or c == "picture" or k == "name" and not any(d.get("part") == "name" for d in info):
            continue
        regs = [d["n"] for d in info if d["base"]] if k == "base" else _part_regions(info, k)
        if not regs:
            out.append(pc.get(f"word:{k}", k))
    return out


def _named_lost(info: list[dict], per, fil: list[str], request: str, skip: set = frozenset()) -> list[str]:
    """What a mapping gives up of the colors the request names: one line per named part that has a
    region in another color, or no region at all. `per` is the filament per region number; `skip`
    the slivers that take the color of the part boxing them in."""
    named = _named_regions(info, request)
    pc = colortool.part_colors(request)
    lost = []
    for k, c in pc.items():
        if k.startswith("word:") or c == "picture" or k == "name" and not any(d.get("part") == "name" for d in info):
            continue
        word = pc.get(f"word:{k}", k)
        regs = [g for g, cc in named.items() if (k == "base" and next(d for d in info if d["n"] == g)["base"])
                or g in _part_regions(info, k)]
        if not regs:
            lost.append(f'the request makes the {word} {c}, but no region of the part is the {word}')
            continue
        want = colortool.word_color(c) or c
        for g in regs:
            if g in skip:
                continue
            got = fil[int(per[g]) - 1]
            if _match_filament(c, [got]) is None and (colortool.word_color(got) or got) != want:
                d = next(d for d in info if d["n"] == g)
                lost.append(f"the request makes the {word} {c}, but region {g} ({d.get('part') or d['color']}) "
                            f"takes {got}; every part the request colors keeps its color")
    return lost


def _name_filament(info: list[dict], per, fil: list[str], request: str) -> int | str | None:
    """The filament for the name raised on the plinth when the mapping gives it none, or None when
    there is no name. The color the request names for it ("red lettering", "the name in red"), else
    one that stands out from the plinth's (colors.name_contrast): a filament the rest of the print
    already uses, else black or white, whichever stands out more. A filament number, or the color
    word when no loaded filament is that color. `per` is the filament per region number. A print in
    one color stays in one color. None too when the plinth's filament is no color this can read
    ("Ivory PLA"): a guess would print the name in the plinth's own color."""
    nm = next((d["n"] for d in info if d.get("part") == "name"), None)
    base = next((d["n"] for d in info if d["base"]), None)
    if nm is None or base is None:
        return None
    c = colortool.part_colors(request).get("name")
    if c and c != "picture":
        return _match_filament(c, fil) or c
    used = sorted({int(per[d["n"]]) for d in info if d["n"] != nm})
    if len(used) == 1:
        return used[0]
    plinth = colortool.filament_rgb(fil[int(per[base]) - 1])
    if plinth is None:
        return None
    k = colortool.name_contrast(plinth, [colortool.filament_rgb(fil[i - 1]) for i in used])
    if k is not None:
        return used[k]
    c = max(("black", "white"), key=lambda w: colortool.contrast_ratio(colortool.NAMES[w], plinth))
    return _match_filament(c, fil) or c


def _region_line(d: dict, name: str) -> str:
    if d.get("part"):  # a figure's region says which part it is
        return f"{d['n']}  {name:<8}{d['share'] * 100:.0f}% of surface  {d['part']}"
    return (f"{d['n']}  {name:<8}{d['share'] * 100:.0f}% of surface  "
            f"z {d['z0']:.0f}-{d['z1']:.0f} mm  {d['pos']}")


def cmd_colors(args, job: Job) -> Out:
    import numpy as np

    out = Out()
    if not need_job(job, out):
        return out
    plan = job.plan()
    r = rc.load(plan["recipe"]) if plan else None
    st = job.status()
    bd = job.build_dir
    stl = bd / "part.stl"
    built = read_json(bd / "params.json") or {}
    if r is not None and stl.is_file() and built:
        # the same check as stone done: the 3MF must be the part the plan describes
        current = build_params(job, r, {k: v for k, v in plan["params"].items() if r.param(k)})
        if built.get("recipe") != r.name or built.get("params") != current:
            out.fix("the plan changed after the last build")
            out.next = "stone build"
            out.owns_next = False
            out.result = "colors refused: the plan changed after the last build"
            return out
    if r is None or not st.get("passed") or not stl.is_file() or built.get("recipe") != r.name:
        out.fix("stone colors needs a passing build first")
        out.next = "stone build" if plan else "stone recipes"
        out.owns_next = False
        out.result = "colors refused: no passing build"
        return out
    params = built.get("params") or {}
    res = _color_regions(job, r, params, colortool.load_stl(stl))
    mesh, num, info = res["mesh"], res["num"], res["regions"]
    fil = config.filaments(job.root)
    request = _color_text(job)
    pick, rest_s, extra_s = _suggest(info, fil, request)
    shown = _fil_value(fil + extra_s)

    def name_of(d):
        if d["color"]:
            return d["color"]
        n = pick.get(d["n"], rest_s)
        if d.get("part") == "name" and d["n"] not in pick:
            per_s = np.array([0] + [pick.get(i, rest_s) for i in range(1, len(info) + 1)])
            f = _name_filament(info, per_s, fil + extra_s, request)
            if isinstance(f, str):
                return f
            n = f or n
        return colortool.word_color((fil + extra_s)[n - 1]) or shown[n - 1]

    if not args.items:
        out.add(f"Color regions of {r.name}.stl, largest first:")
        for d in info[:colortool.LIST_MAX]:
            out.add(_region_line(d, name_of(d)))
        if len(info) > colortool.LIST_MAX:
            out.add(f"({len(info) - colortool.LIST_MAX} smaller regions take the rest= color)")
        out.add(f"Regions picture: {bd / 'regions.png'}")
        out.add("Filaments: " + ", ".join(f"{i} {f}" for i, f in enumerate(fil, 1)) + " (stone.toml [filaments])")
        if any(d.get("part") for d in info):
            out.add("Give each part or region a color, by name or filament number (like jacket=black); "
                    "rest= colors the others.")
        else:
            out.add("Give each region a color, by name or filament number; rest= colors the others.")
        out.next = _suggest_line(info, fil, request)
        out.stage = "colors"
        out.result = f"{len(info)} color regions"
        return out

    # the mapping
    fil = list(fil)
    added: list[str] = []
    assign: dict[int, int] = {}
    rest = None
    fixes: list[str] = []
    base = next((d["n"] for d in info if d["base"]), None)
    for it in args.items:
        sep = "=" if "=" in it else ":" if ":" in it else None
        if sep is None:
            fixes.append(f"write region=color, like 1=black rest=white (not {it})")
            continue
        k, v = (x.strip().lower() for x in it.split(sep, 1))
        if v.isdigit():
            n = int(v)
            if not 1 <= n <= len(fil):
                fixes.append(f"there is no filament {n}; loaded: " + ", ".join(f"{i} {f}" for i, f in enumerate(fil, 1)))
                continue
        else:
            n = _match_filament(v, fil)
            if n is None:
                c = colortool.word_color(v)
                if c is None:
                    fixes.append(f'"{v}" is not a color; use a filament number or one of: {", ".join(colortool.NAMES)}')
                    continue
                fil.append(c)
                added.append(c)
                n = len(fil)
        if k in REST_KEYS:
            rest = n
        elif k == "base":
            if base is None:
                fixes.append("this part has no base region; use region numbers and rest=")
            else:
                assign[base] = n
        elif k.isdigit() and 1 <= int(k) <= len(info):
            assign[int(k)] = n
        elif _part_regions(info, k):
            for g in _part_regions(info, k):
                assign[g] = n
        else:
            known = sorted({d["part"] for d in info if d.get("part") and d["part"] not in ("other", "base")})
            fixes.append(f'no region "{k}"; regions are 1 to {len(info)}' + (", base" if base else "")
                         + (", " + ", ".join(known) if known else "") + " and rest")
    if len(fil) > colortool.MAX_FILAMENTS:
        fixes.append(f"at most {colortool.MAX_FILAMENTS} filaments")
    if fixes:
        for f in fixes[:4]:
            out.fix(f)
        out.next = _suggest_line(info, config.filaments(job.root), request)
        out.result = "colors refused: " + fixes[0]
        return out
    if rest is None:
        rest = 1
        if len(assign) < len(info):
            out.add(f"No rest= given: the other regions take filament 1 {fil[0]}.")
    per = np.array([0] + [assign.get(d, rest) for d in range(1, len(info) + 1)])
    # a sliver of a garment's edge that a line of the shape boxed in (a jacket's lip under the
    # hem's level, a collar's top over the neck's) takes the color round it, not the rest color
    boxed: dict[int, int] = {}
    for s, host in colortool.boxed_slivers(mesh, num, info, per, set(assign), rest,
                                           colortool.filament_rgb(fil[rest - 1])):
        per[s] = per[host]
        boxed[int(s)] = int(host)
        hd = next(d for d in info if d["n"] == host)
        out.add(f"Region {s}, a sliver boxed in by region {host} ({hd.get('part') or hd['color']}), "
                f"takes its color, {_fil_value(fil)[per[s] - 1]}.")
    # the name raised on the plinth: the color asked for, else one that stands out from the plinth
    nm = next((d["n"] for d in info if d.get("part") == "name"), None)
    if nm is not None and nm not in assign:
        f = _name_filament(info, per, fil, request)
        if isinstance(f, str) and len(fil) < colortool.MAX_FILAMENTS:
            fil.append(f)
            added.append(f)
            f = len(fil)
        if f is None:
            out.add(f"The plinth's filament, {fil[int(per[next(d['n'] for d in info if d['base'])]) - 1]}, is no color "
                    "I can read, so the name keeps the plinth's color; give it one with name=<color>.")
        if isinstance(f, int) and f != per[nm]:
            per[nm] = f
            out.add(f"The name on the plinth takes {_fil_value(fil)[f - 1]} (filament {f}), so it reads "
                    f"on the {_fil_value(fil)[per[base] - 1]} plinth.")
    names = _fil_value(fil)

    def mapping_line(a: dict) -> str:
        return " ".join(_mapping_items(info, a, rest, names) + [f"rest={names[rest - 1]}"])

    # every part the request gives a color keeps it: a mapping that leaves one out is no print of
    # what the person asked for, so it is refused, never painted and called ready
    named = _named_regions(info, request)
    part_at = {d["n"]: d.get("part") or ("base" if d["base"] else None) for d in info}
    lost = _named_lost(info, per, fil, request, skip=set(boxed))
    plan_params = (job.plan() or {}).get("params") or {}
    made = "figure" not in plan_params  # the figure step made it, so another seed makes another

    def ask_answers(what: str) -> None:
        """The person's answers, as commands that carry them out. No stone colors line gives a named
        part another color: only the person changes what the request asks for (review second-F1)."""
        out.add(f"If the person wants the {what} in another color, that is a new request: "
                'stone new --force "<the request, with the color they name>", and the figure is made again.')
        if made:
            out.add(f"If the person wants the figure made again: stone set seed="
                    f"{figure_seed(job, plan_params) + 1}, then stone build")
    if lost:
        (job.root / f"{r.name}.3mf").unlink(missing_ok=True)
        if st.get("colors"):
            job.update(colors=None)
        for x in lost[:4]:
            out.fix(x)
        pick_s, rest_s, extra_s = _suggest(info, config.filaments(job.root), request)
        fil_s = config.filaments(job.root) + extra_s
        per_s = np.array([0] + [pick_s.get(d, rest_s) for d in range(1, len(info) + 1)])
        sug = _suggest_line(info, config.filaments(job.root), request)
        missing = _named_missing(info, request)
        if missing:
            # no mapping paints a part the figure has no region for: only another figure can
            what = " and ".join(missing)
            if made:
                out.add(f"If the person wants the figure made again: stone set seed="
                        f"{figure_seed(job, plan_params) + 1}, then stone build")
                out.next = (f"ask the person: the figure has no separate {what} to paint the color the request "
                            f"names. Should I make the figure again from another seed?")
            else:
                out.add("If the person gives another figure: stone set figure figure=<path to the figure>, then stone build")
                out.next = (f"ask the person: the figure file has no separate {what} to paint the color the request "
                            f"names. Can you give a figure where the {what} is a part of its own?")
            out.stage = "needs_person"
        elif not _named_lost(info, per_s, fil_s, request, skip=set(boxed)) and sug != "stone colors " + mapping_line(assign):
            out.next = sug
        else:
            ask_answers("parts")
            out.next = ("ask the person: the request gives " + ", ".join(f"the {w} {c}" for w, c in _named_words(request))
                        + ", and I found no mapping that keeps them all. Which part should take another color, "
                        "and which color?")
            out.stage = "needs_person"
        out.result = "colors refused: " + lost[0]
        return out
    face_fil0 = per[num]
    # cut along smooth boundaries, so a color edge runs as a curve through the triangles
    # the plinth's edge and a figure's hem, neck and wrists are lines of the shape: keep them there
    fixed = res["fixed"] if res["fixed"] is not None else (num == base if base else None)
    anat_lines = (res.get("anatomy") or {}).get("lines") or []

    def paint(radius: float):
        V, F, face_fil, parent = colortool.smooth_cut(mesh.vertices, mesh.faces, face_fil0, radius=radius, fixed=fixed)
        _, lines = colortool.color_edges(V, F, face_fil)
        colortool.mark_grooves(lines, anat_lines, (res.get("anatomy") or {}).get("hairline"))
        colortool.mark_name_edges(lines, F, num[parent], nm, base)
        faults = colortool.edge_faults(lines)
        one_color = len(np.unique(face_fil)) == 1  # no color edge, so nothing can climb a ledge
        ledge = (colortool.ledge_faults(colortool.ledges(V, F, face_fil, anat_lines))
                 if anat_lines and not faults and not one_color else [])
        return V, F, face_fil, parent, lines, faults, ledge

    # a boundary that is not smooth is first faired: cut again along the level of a wider smoothing,
    # before any color is given up (a line of the shape stays where it is)
    for k, radius in enumerate(colortool.FAIR_RADII):
        V, F, face_fil, parent, lines, faults, ledge = paint(radius)
        if not faults and not ledge:
            if k:
                out.add(f"The color edges were faired: smoothed over {radius:g} mm instead of {colortool.FAIR_RADII[0]:g} mm.")
            break
    cut = colortool.load_stl_mesh(V, F)  # the float32 mesh the 3MF holds
    worst = colortool.worst_ratio(lines)
    wob = colortool.worst_wobble(lines)
    fil_rgb = np.array([colortool.filament_rgb(f) or (150, 150, 150) for f in fil], float)
    reg_of = num[parent]

    def smallest_painted(near: np.ndarray) -> tuple[int | None, list[int]]:
        """The smallest region off the rest color among the faces `near` a failing edge that the
        request gives no color, and the regions there it does (those are never given up)."""
        cand = [int(g) for g in np.unique(reg_of[near]) if assign.get(int(g), rest) != rest]
        free = [g for g in cand if g not in named]
        g = min(free, key=lambda k: next(d["share"] for d in info if d["n"] == k)) if free else None
        return g, [g for g in cand if g in named]

    def retry(drop: list[int], held: list[int]) -> None:
        """A NEXT that changes the outcome: the regions on the failing edges take the rest color;
        with none to give, the part prints in one color. Never the mapping that just failed, and
        never one that gives up a color the request names: then the person decides."""
        failed = mapping_line(assign)
        nxt = mapping_line({k: v for k, v in assign.items() if k not in drop}) if drop else failed
        part_of = {d["n"]: d.get("part") or d["color"] or "base" for d in info}
        if not drop and (held or any(per[g] != rest for g in named)):
            parts_w = sorted({part_at.get(g) or part_of[g] for g in (held or named)})
            what = ", ".join(parts_w)
            out.add(f"The edge is at the {what}, whose color the request names, so no color is given up.")
            ask_answers(what)
            out.next = (f"ask the person: the color edge of the {what} is not clean enough to print even after "
                        f"fairing (picture: {bd / 'boundaries.png'}). Should the {what} take another color"
                        + (", or should I make the figure again from another seed?" if made else "?"))
            out.stage = "needs_person"
            return
        if drop:
            names_d = ", ".join(f"region {g} ({part_of[g]})" for g in drop)
            out.add(f"The paint of {names_d} does not follow a clean line; it takes the rest color.")
        if nxt == failed:
            nxt = f"rest={names[rest - 1]}"
            out.add(f"No region can take the rest color to clear it, so the part prints in one color, "
                    f"{names[rest - 1]}.")
        out.next = "stone colors " + nxt

    if radius != colortool.FAIR_RADII[0] and not faults and not ledge:
        # review first-F2: a wide fairing can shrink a small part the request colors away (black
        # glasses under a 6 mm smoothing); its color is checked on the paint itself, not the mapping
        a = cut.area_faces
        thin = [g for g in named if g not in boxed and a[reg_of == g].sum() > 0
                and a[(reg_of == g) & (face_fil == per[g])].sum() < colortool.NAMED_KEPT * a[reg_of == g].sum()]
        if thin:
            (job.root / f"{r.name}.3mf").unlink(missing_ok=True)
            if st.get("colors"):
                job.update(colors=None)
            colortool.render_boundaries(V, F, fil_rgb[face_fil - 1], lines, bd / "boundaries.png", anatomy=anat_lines)
            what = ", ".join(sorted({part_at.get(g) or str(g) for g in thin}))
            out.fix(f"fairing the color edges over {radius:g} mm leaves the {what} with under "
                    f"{colortool.NAMED_KEPT:.0%} of its own color; no file written")
            out.add(f"Boundaries picture: {bd / 'boundaries.png'}")
            retry([], thin)
            out.result = f"colors failed: the {what} lost its color to fairing"
            return out
    if ledge:
        x = ledge[0]
        (job.root / f"{r.name}.3mf").unlink(missing_ok=True)
        if st.get("colors"):
            job.update(colors=None)
        colortool.render_boundaries(V, F, fil_rgb[face_fil - 1], lines, bd / "boundaries.png",
                                    anatomy=anat_lines)
        out.fix(f"the {x['name']} color edge climbs onto a ledge: {x['area']:.2f} mm2 of up-facing filament "
                f"{x['fil']} faces seen next to it at {x['angle']:.0f} degrees (max {colortool.LEDGE_AREA}); "
                "no file written")
        out.add(f"Boundaries picture: {bd / 'boundaries.png'}")
        from . import parts

        ln = next(a for a in anat_lines if a["name"] == x["name"] and a.get("side") == x["side"])
        cc = cut.triangles_center
        near = (np.abs(parts.field(ln, cc)) < parts.SNAP + colortool.LEDGE_MM) & \
            (np.hypot(cc[:, 0] - ln["center"][0], cc[:, 1] - ln["center"][1]) < ln["rmax"] + colortool.LEDGE_MM)
        g, held = smallest_painted(near)
        retry([g] if g is not None else [], held)
        out.result = f"colors failed: {x['name']} edge on a ledge ({x['area']:.2f} mm2 seen)"
        return out
    if faults:
        # paint that cannot follow a clean line (often a feature the picture puts beside the shape)
        drop: list[int] = []
        held: list[int] = []
        bad_lines = faults
        for ln in bad_lines:
            g, h = smallest_painted(np.isin(F, ln["verts"]).any(1))
            if g is not None and g not in drop:
                drop.append(g)
            held += [x for x in h if x not in held]
        (job.root / f"{r.name}.3mf").unlink(missing_ok=True)  # no painted file with a jagged edge
        if st.get("colors"):
            job.update(colors=None)
        colortool.render_boundaries(V, F, fil_rgb[face_fil - 1], lines, bd / "boundaries.png", anatomy=anat_lines)
        ln = bad_lines[0]
        z = ln["pts"][:, 2].mean()
        if (ln.get("ratio") or 0) > colortool.JAGGED:
            out.fix(f"color boundary is jagged: filament {ln['pair'][0]}/{ln['pair'][1]} at z {z:.0f} mm is "
                    f"{ln['ratio']:.2f} times its smoothed length (max {colortool.JAGGED}); no file written")
        else:
            out.fix(f"color boundary is wavy: filament {ln['pair'][0]}/{ln['pair'][1]} at z {z:.0f} mm strays "
                    f"{ln['wobble']:.2f} mm from a straight course within {colortool.EDGE_SPAN:.0f} mm "
                    f"(max {colortool.WOBBLE}); no file written")
        out.add(f"Boundaries picture: {bd / 'boundaries.png'}")
        retry(drop, held)
        out.result = f"colors failed: color boundary not smooth (ratio {worst:.2f}, wobble {wob:.2f} mm)"
        return out
    area = cut.area_faces
    total = area.sum()
    used = sorted(set(int(x) for x in face_fil))
    shares = "; ".join(
        f"filament {n} {fil[n - 1]}: {area[face_fil == n].sum() / total * 100:.0f}%" + (" of surface" if i == 0 else "")
        for i, n in enumerate(used))
    final = job.root / f"{r.name}.3mf"
    tmp = bd / "check.3mf"
    final.unlink(missing_ok=True)
    main_fil = colortool.write_3mf(tmp, V, F, face_fil, f"{r.name}.stl", bed=config.bed(job.root))
    bad = colortool.check_3mf(tmp, len(F), len(fil), volume=mesh.volume)
    if bad:
        tmp.unlink(missing_ok=True)
        for b in bad[:3]:
            out.fix(b)
        out.next = "stone build"
        out.result = "colors failed: " + bad[0]
        return out
    tmp.replace(final)
    np.save(bd / "paint.npy", num[parent])  # the region of each 3MF triangle, in file order
    write_json(bd / "slivers.json", {str(k): v for k, v in boxed.items()})  # sliver -> the region it is part of
    for c in added:
        out.add(f"{c} is not in stone.toml [filaments], so it is filament {fil.index(c) + 1} here: load it in that slot.")
    out.add(shares)
    out.add(f"Object filament {main_fil}; the other filaments are painted on, triangle by triangle.")
    out.add(f"Checked: the 3MF reads back watertight and clean for a slicer, {len(F)} faces, volume as the STL.")
    in_groove = sum(1 for ln in lines if ln.get("groove"))
    on_name = sum(1 for ln in lines if ln.get("name_edge"))
    out.add(f"PASS color_edges: every color boundary is a smooth curve (worst {worst:.3f}, max {colortool.JAGGED}; "
            f"wobble {wob:.2f} mm, max {colortool.WOBBLE}"
            + (f"; {in_groove} edges follow the shape (a sculpted groove, a shoe's rim or the hairline), which the wobble limit does not apply to" if in_groove else "")
            + (f"; {on_name} edges are the outline of the raised name, the shape's own crease, which neither limit "
               "applies to" if on_name else "") + ")")
    if anat_lines:
        grooves = [f"{x['name']}{'' if x.get('side') is None else (' left' if x['side'] < 0 else ' right')} "
                   f"{'up' if x['groove']['side'] > 0 else 'down'}" for x in anat_lines if (x.get("groove") or {}).get("used")]
        nostep = [f"{x['name']} {len(x['nostep'])}" for x in anat_lines if x.get("nostep")]
        out.add("PASS ledges: no up-facing face of the wrong color is seen next to a part's edge"
                + (f"; edges in the groove: {', '.join(grooves)}" if grooves else "")
                + (f"; bins of 10 degrees where the slope runs on into the head with no step, which the check "
                   f"skips: {', '.join(nostep)} of 36" if nostep else ""))
    mixed, changes = colortool.layer_changes(cut, face_fil)
    if mixed >= colortool.MANY_LAYERS:
        out.add(f"Warning: the colors alternate on {mixed} layers: about {changes} filament changes "
                f"and {changes * colortool.PURGE_G:.0f} g purge.")
    rgb = fil_rgb[face_fil - 1]
    colortool.render(cut, rgb, bd / "colors.png",
                     views=(("front", 0.0, 0.0), ("side", np.pi / 2, 0.0), ("back", np.pi, 0.0)))
    colortool.render_views(cut, rgb, bd / "views.png")
    (bd / "boundaries.png").unlink(missing_ok=True)
    if colortool.render_boundaries(V, F, rgb, lines, bd / "boundaries.png", anatomy=anat_lines):
        out.add(f"Boundaries: {bd / 'boundaries.png'} (each color edge close up from 8 sides)")
    out.add(f"3MF: {final} (Orca, Bambu Studio, Creality Print and PrusaSlicer open it with the paint)")
    out.add(f"Views: {bd / 'views.png'} (look at every panel before you call it done)")
    show([bd / "views.png"], "The painted part")
    out.add("In the slicer: " + ", ".join(f"filament {i} must be {fil[i - 1]}" for i in used)
            + ". The 3MF names slots, not colors; set them in stone.toml [filaments] to match the printer.")
    mapping = mapping_line(assign)
    job.update(colors={"mapping": mapping, "filaments": fil, "shares": shares, "file": str(final),
                       "changes": changes, "mixed_layers": mixed, "color_edges": round(worst, 3),
                       "wobble": round(wob, 3)})
    out.next = DONE_NEXT
    out.stage = "done"
    out.result = f"3MF written, {shares}"[:120]
    return out

# main


def make_parser() -> Parser:
    common = Parser(add_help=False)
    common.add_argument("--job", default=argparse.SUPPRESS, help="job folder (default ./stone-job)")
    p = Parser(prog="stone", description="Make print-ready parts from recipes.")
    # separate dest: argparse lets a subparser default clobber a top-level value
    p.add_argument("--job", dest="job_top", default=None, help="job folder (default ./stone-job)")
    sub = p.add_subparsers(dest="cmd", parser_class=Parser)

    sub.add_parser("status", parents=[common], help="where the job stands and what to do next")

    s = sub.add_parser("new", parents=[common], help='start a job: stone new "<request>"')
    s.add_argument("request", nargs="*")
    s.add_argument("--image")
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("recipes", parents=[common], help="list recipes")
    s.add_argument("words", nargs="*")
    s.add_argument("--all", action="store_true", help=argparse.SUPPRESS)

    s = sub.add_parser("show", parents=[common], help="show a recipe's parameters")
    s.add_argument("recipe")
    s.add_argument("--json", action="store_true", help="print the recipe and the job's values as one JSON object")
    s.add_argument("--all", action="store_true", help="every parameter with its meaning, even when the request fills the part")

    s = sub.add_parser("set", parents=[common], help="set recipe parameters")
    s.add_argument("items", nargs="*")
    s.add_argument("--reset", action="store_true")

    sub.add_parser("build", parents=[common], help="build and check the part")

    s = sub.add_parser("check", parents=[common], help="print checks on an STL")
    s.add_argument("file", nargs="?")

    s = sub.add_parser("slice", parents=[common], help="layer by layer, what a slicer would print wrong")
    s.add_argument("file", nargs="?")
    s.add_argument("--layer", type=float, default=0.2, help="layer height, mm")
    s.add_argument("--nozzle", type=float, default=0.4, help="nozzle width, mm")
    s.add_argument("--json", action="store_true", help="the full report as JSON")

    s = sub.add_parser("image", parents=[common], help="turn a picture into silhouette and height map")
    s.add_argument("path")

    s = sub.add_parser("measure", parents=[common], help="real size from a ruler in the photo")
    s.add_argument("path", nargs="?")
    s.add_argument("--ref", help="card or coin-us-quarter, when there is no ruler")
    s.add_argument("--known", help="the object's long side, like 120mm, when there is no ruler")

    s = sub.add_parser("find", parents=[common], help="free-licensed photos of a person or thing")
    s.add_argument("query", nargs="*")
    s.add_argument("-n", type=int, default=3)

    s = sub.add_parser("note", parents=[common], help="keep a researched fact and its source in the job")
    s.add_argument("text", nargs="*")

    s = sub.add_parser("product", parents=[common], help='a product the catalog lacks: stone product add "<name>" --size W D H --source "<URL>"')
    s.add_argument("action", choices=["add"])
    s.add_argument("name", nargs="+")
    s.add_argument("--size", nargs="+", type=float, help="width, depth and height in mm (a round one: diameter and height)")
    s.add_argument("--corner-r", type=float, help="the corner radius in mm, when the source gives one")
    s.add_argument("--round", action="store_true", help="a disc: the width is its diameter")
    s.add_argument("--source", help="the maker's spec page URL, or 'measured by the person'")
    s.add_argument("--open", default="", help="faces that stay clear, like +z or -y,+y")

    s = sub.add_parser("refs", parents=[common], help="sourced facts: filaments, standards, design (stone refs PETG)")
    s.add_argument("topic", nargs="*")

    sub.add_parser("done", parents=[common], help="finish the job")

    s = sub.add_parser("colors", parents=[common], help="color regions, then a painted 3MF: stone colors 1=black rest=white")
    s.add_argument("items", nargs="*")

    s = sub.add_parser("video", parents=[common], help="a vertical clip of a finished painted job for X")
    s.add_argument("log", nargs="?", help="the run log (default: log.json beside the job)")
    s.add_argument("--out", help="output folder (default: <job>/video)")
    s.add_argument("--turn", type=_turn_frames, default=None,
                   help="frames in one turn of the figure (8 or more; 144 for one run, 120 each in a series)")
    s.add_argument("--with", dest="runs", action="append", metavar="RUN",
                   help="another finished run (a folder with job/ and log.json); the clip shows every figure")
    return p


def _turn_frames(text: str) -> int:
    """--turn: a whole number of frames, at least 8, so the figure has something to turn through."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of frames") from None
    if n < 8:
        raise argparse.ArgumentTypeError(f"{n} is too few frames: one turn takes at least 8")
    return n


COMMANDS = {
    "status": cmd_status,
    "new": cmd_new,
    "recipes": cmd_recipes,
    "show": cmd_show,
    "set": cmd_set,
    "build": cmd_build,
    "check": cmd_check,
    "slice": cmd_slice,
    "image": cmd_image,
    "measure": cmd_measure,
    "find": cmd_find,
    "note": cmd_note,
    "product": cmd_product,
    "refs": cmd_refs,
    "done": cmd_done,
    "colors": cmd_colors,
    "video": cmd_video,
}


def _guess_job(argv: list[str]) -> Path:
    for i, a in enumerate(argv):
        if a == "--job" and i + 1 < len(argv):
            return config.job_dir(argv[i + 1])
        if a.startswith("--job="):
            return config.job_dir(a.split("=", 1)[1])
    return config.job_dir(None)


# words small models use for a command, and commands that take no words
SYNONYMS = {"create": "new", "make": "new", "start": "new", "list": "recipes",
            "search": "recipes", "info": "show", "scale": "measure", "describe": "show", "finish": "done", "check_status": "status",
            "color": "colors", "colour": "colors", "colours": "colors", "paint": "colors",
            "references": "refs", "reference": "refs", "material": "refs", "materials": "refs"}
NO_WORDS = ("status", "build", "done")


def _tidy(argv: list[str]) -> list[str]:
    """Forgive the slips small models make: a synonym for a command, or a path after build."""
    argv = list(argv)
    i = next((k for k, a in enumerate(argv) if not a.startswith("-") and (k == 0 or argv[k - 1] not in ("--job",))), None)
    if i is None:
        return argv
    argv[i] = SYNONYMS.get(argv[i].lower(), argv[i])
    if argv[i] in NO_WORDS:
        rest, keep, skip = argv[i + 1:], [], False
        for a in rest:
            if skip or a.startswith("-"):
                keep.append(a)
                skip = a == "--job"
            else:
                skip = False
        argv = argv[:i + 1] + keep
    return argv


def _fallback_next(job: Job, argv: list[str]) -> str:
    """After a slip, the one command that moves the job on: a recipe the model named, else the job's NEXT."""
    words = [a for a in argv if not a.startswith("-")]
    for w in words:
        if rc.load(w.split("=", 1)[0]):
            return f"stone show {w.split('=', 1)[0]}"
    if not job.exists():
        return NEW_NEXT
    nxt = job.status().get("next")
    if nxt and nxt != "stone status":
        return nxt
    return "stone build" if job.plan() else "stone recipes"


LOOK_ONLY = ("recipes", "show", "check", "note", "refs", "usage", "error")  # commands that change no build


def _fail_key(cmdline: str, out: Out) -> str | None:
    """What makes a failure the same as the last: the whole command line and its first FIX line
    (stone colors with a new mapping is a new try). None when the command did not fail."""
    first = next((ln for ln in out.lines if ln and ln.startswith("FIX: ")), None)
    if out.code == 0 or first is None:
        return None
    return f"{cmdline}: {first}"


def run(argv: list[str]) -> tuple[str, int]:
    argv = _tidy(argv)
    parser = make_parser()
    job = Job(_guess_job(argv))
    catalog.use_job(job.root)
    cmdline = "stone " + " ".join(argv)
    try:
        args = parser.parse_args(argv)
        if args.cmd is None:
            args = parser.parse_args(argv + ["status"])
        cmd = args.cmd
        job = Job(config.job_dir(getattr(args, "job", None) or args.job_top))
        catalog.use_job(job.root)
        out = COMMANDS[cmd](args, job)
    except UsageError as e:
        out = Out()
        out.fix(f"{e}; commands: status new recipes show set build check image measure colors done")
        out.next = _fallback_next(job, argv)
        out.owns_next = False
        cmd = "usage"
    except Exception as e:  # never show a traceback to the model
        job.log(f"{cmdline}\n{traceback.format_exc()}")
        out = Out()
        out.add(f"ERROR: stone hit an internal problem ({type(e).__name__}); details in {job.log_file}")
        out.fix("run stone status and follow its NEXT line")
        out.next = "stone status"
        out.owns_next = False
        cmd = "error"
    fail = None
    # a command that only looks (or a slip) changes nothing, so it neither counts as a try nor
    # ends a run of the same failure: build, show, build again is still twice in a row
    tries = job.exists() and cmd not in ("status",) + LOOK_ONLY and out.raw is None
    if tries:
        fail = _fail_key(cmdline, out)
        prev = job.status().get("last_fail")
        # a set that carried a product's sizes is sent to stone product add: repeating it is no new failure
        if fail and fail == prev and not out.next.startswith(("ask the person", "stone product add")):
            # the same failure twice in a row: a third try fails the same way, so stop and ask
            first = next(ln for ln in out.lines if ln and ln.startswith("FIX: "))[5:]
            out.add(f"FIX: stone {cmd} failed this same way twice in a row; do not run it again")
            out.next = (f"ask the person: stone {cmd} fails the same way every time ({first[:140]}). What should I do? "
                        f"When they have fixed it and say to try again: {cmdline}")
            out.stage = out.stage or "stuck"
    text = out.render()
    if job.exists() and cmd not in ("status",) and out.raw is None:
        job.log(f"{cmdline}\n{text}")
        s = job.status()
        upd = {"last_command": cmdline, **({"last_fail": fail} if tries else {})}
        if out.result:
            upd["last_result"] = out.result
        early = s.get("stage") in EARLY_STAGES and not job.plan()
        if (out.owns_next or early) and out.next != "stone status":
            upd["next"] = out.next  # status never sends a model back to status
        if out.stage and (out.owns_next or early):
            upd["stage"] = out.stage
        job.update(**upd)
    return text, out.code


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    first = next((a for a in argv if not a.startswith("-")), "")
    if first == "go" or (" " in first and first not in COMMANDS):
        # a person's one command: stone go "<request>", or the request alone
        from .go import go

        words = list(argv)
        if first == "go":
            words.remove("go")
        return go(words, run)
    text, code = _plain(argv)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    if first == "new" and sys.stdout.isatty() and code == 0:
        # a person typing the steps by hand: say once that one command runs all of them
        print('One command runs every step for you, with a live line: stone go', file=sys.stderr, flush=True)
    return code


def _plain(argv: list[str]) -> tuple[str, int]:
    """One command typed by a person at a terminal gets the live line stone go draws under a long
    step (a spinner, the time so far, what it took last time), so a build is never a silent wait.
    A model's run, with no terminal, gets the plain progress lines on stderr."""
    from . import term
    from .go import _live_wanted

    if HOOKS.get("progress") or not _live_wanted():
        return run(argv)
    live = term.Live()
    live.start("stone " + next((a for a in argv if not a.startswith("-")), ""))  # from the first second
    HOOKS["progress"] = live.note
    try:
        return run(argv)
    finally:
        HOOKS.pop("progress", None)
        live.stop()


if __name__ == "__main__":
    raise SystemExit(main())
