"""stone: the command line a small model drives. Every output ends with one NEXT line."""

from __future__ import annotations

import argparse
import json
import math
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
from . import image as imagetool
from . import measure as measuretool
from . import find as findtool
from . import figure as figuretool
from . import recipes as rc
from . import scad
from .job import Job, read_json, write_json

MAX_LINES = 25
FAILS_BEFORE_RESET = 4
DONE_NEXT = "none, the part is ready"
NEW_NEXT = 'stone new "<what to make>"'
# stages before a plan exists; read-only commands may move NEXT only here
EARLY_STAGES = {"new", "image", "recipes", "show"}


@dataclass
class Out:
    lines: list[str] = field(default_factory=list)
    next: str = "stone status"
    code: int = 0
    result: str = ""  # short text for status.json last_result
    stage: str | None = None  # new stage for status.json, None keeps it
    owns_next: bool = True  # False: do not overwrite status next after a plan exists

    def add(self, *lines: str) -> "Out":
        self.lines.extend(lines)
        return self

    def fix(self, text: str) -> "Out":
        self.lines.append(f"FIX: {text}")
        self.code = 1
        return self

    def render(self) -> str:
        body = [ln for ln in self.lines if ln is not None]
        room = MAX_LINES - 1
        if len(body) > room:
            cut = len(body) - (room - 1)
            body = body[: room - 1] + [f"({cut} more lines in log.txt)"]
        return "\n".join(body + [f"NEXT: {self.next}"])


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
    out.next = f"stone show {top}"
    out.result = f"listed recipes, top {top}"
    return out


# show


def unknown_recipe(name: str, out: Out, t: str) -> Out:
    allr = rc.load_all()
    # hidden recipes (names starting with _) only when the model typed a _ name
    names = [r.name for r in rc.visible(allr, t, show_all=name.startswith("_"))] or list(allr)
    near = rc.closest(name, names)
    if near:
        out.fix(f'no recipe "{name}"; closest: {", ".join(near)}')
        out.next = f"stone show {near[0]}"
    else:
        out.fix(f'no recipe "{name}"; pick one from stone recipes')
        out.next = "stone recipes"
    out.result = f"unknown recipe {name}"
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


def cmd_show(args, job: Job) -> Out:
    out = Out(owns_next=False, stage="show")
    t = config.tier(job.root)
    r = rc.load(args.recipe)
    if r is None:
        return unknown_recipe(args.recipe, out, t)
    out.add(f"{r.name}: {r.title}")
    if r.summary:
        out.add(r.summary)
    size = default_size(r)
    out.add(f"Tier {r.tier}." + (f" Default size {size}." if size else ""))
    request = job.request() if job.exists() else ""
    sug, left = match.suggest_full(r, request) if request else ({}, [])
    if sug:
        items = [f"{k}={rc.fmt_value(r.param(k), v)}" for k, v in sug.items()]
        out.add(f"From the request: {' '.join(items)}")
    ms = measured_size(job, r) if job.exists() else None
    if ms and ms[0] not in sug:
        clamp = f", the measured {rc.fmt_num(ms[2])} mm is out of range" if ms[1] != ms[2] else ""
        out.add(f"From the picture: {ms[0]}={rc.fmt_num(ms[1])} (object long side in mm{clamp})")
    if left:
        out.add(f"Not placed yet: {'; '.join(left[:4])}. If one is a size of this part, add it with its parameter name.")
    elif request and not sug:
        out.add("Nothing in the request names a parameter; the defaults make a good part.")
    out.add("Parameters (name = default):")
    room = MAX_LINES - len(out.lines) - 3
    for i, p in enumerate(r.params):
        if i >= room:
            out.add(f"({len(r.params) - room} more parameters not shown)")
            break
        line = f"{p.name} = {rc.fmt_value(p, p.default)}  ({p.range_text()})"
        if p.help:
            line += f" {p.help}"
        out.add(line)
    ex = example_items(r)
    if ex:
        out.add(f"Example: stone set {r.name} {' '.join(ex)}")
    if request:
        out.next = f"stone set {r.name} {' '.join(items) if sug else ''}".rstrip()
    else:
        nxt = example_items(r, limit=3)
        out.next = f"stone set {r.name} {' '.join(nxt)}".rstrip()
    out.result = f"showed {r.name}"
    return out


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
            return unknown_recipe(name, out, t)
    given = [(k, v, r.param(k)) for k, v in (it.split("=", 1) for it in items if "=" in it)]
    # the set line answers the question when it names the product (phone=iphone_17_pro) or gives a length
    # (hole_d=60); so does a size measured from a photo
    named = [f"{k} {v.replace('_', ' ')}" for k, v, p in given if p is not None and p.product]
    sized = not any(p.product for p in r.params) and any(
        p is not None and p.type in ("number", "int") and p.unit == "mm" for _, _, p in given)
    ask = None if sized or job.measured() else match.missing_fit_size(r, job.request(), job.notes() + named)
    if ask:
        # never invent the size of the thing a part must fit: a small model would, so the tool stops it
        out.fix("this part must fit something real and the request gives no size for it; never guess one")
        out.add('When the person answers, run: stone note "<their answer>"')
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
    if p.type not in ("number", "int") or direction not in ("up", "down"):
        return None
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
        spec = _fix_spec(r, res.name)
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


def views_step(job: Job, stl: Path) -> Path | None:
    """build/views.png: the part from every side, so a person or a large model can look at it all."""
    import numpy as np

    png = job.build_dir / "views.png"
    try:
        m = colortool.load_stl(stl)
        colortool.render_views(m, np.tile([217.0, 160.0, 102.0], (len(m.faces), 1)), png)
    except Exception:  # a picture is never worth failing a passing build
        job.log("views failed:\n" + traceback.format_exc())
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
    for f in ("part.stl", "part.off", "preview.png", "check.json", "openscad.log", "preview.scad"):
        (bd / f).unlink(missing_ok=True)
    for f in [*job.root.glob("*.stl"), *job.root.glob("*.3mf")]:
        f.unlink()  # the finished part always matches the last build
    for f in ("regions.json", "regions.npy", "regions.npz", "paint.npy", "regions.png", "colors.png", "atlas.png", "views.png", "boundaries.png"):
        (bd / f).unlink(missing_ok=True)
    if job.status().get("colors"):
        job.update(colors=None)
    write_json(bd / "params.json", {"recipe": r.name, "params": params})
    st = job.status()
    builds = int(st.get("builds", 0)) + 1
    fails = int(st.get("failed_builds", 0))
    out.add(f"Recipe: {r.name}")
    if dropped:
        out.add(f"Ignored old parameters: {', '.join(dropped)}")
    stl = bd / "part.stl"
    run = scad.build_stl(binary, r, params, stl)
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
    results = checks.check_stl(stl, recipe=r, params=params, bed=bed)  # the file that ships
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
        views = views_step(job, stl)
        if views:
            out.add(f"Views: {views} (look at every panel before you call it done)")
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
    results = checks.check_stl(f, recipe=r, params=params, bed=config.bed(job.root))
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
           "bear", "lion", "tiger", "owl", "parrot", "hamster", "corgi", "pug", "frog", "turtle"}


def figure_who(job: Job, style: str) -> str:
    if style == "object":
        return "object"
    words = set(re.findall(r"[a-z]+", job.request().lower())) if job.exists() else set()
    return "animal" if words & ANIMALS else "person"


def figure_step(job: Job, r: rc.Recipe, params: dict, out: Out) -> Path | None:
    """Photos -> styled render -> 3D figure, cached in images/figure. None after a FIX."""
    photos = job.photos()
    if not photos:
        who = findtool.subject_from_request(job.request()) if job.exists() else None
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
                               seed=int(params.get("seed") or 7), say=lambda s: job.log(s))
    except figuretool.FigureProblem as e:
        job.log("figure failed:\n" + traceback.format_exc())
        out.add(f"Recipe: {r.name}")
        out.fix(str(e))
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
    query = " ".join(args.query).strip().strip('"\'') or findtool.subject_from_request(job.request()) or ""
    if not query:
        out.fix('say who or what to find, like stone find "Ada Lovelace"')
        out.next = 'stone find "<who or what>"'
        return out
    try:
        got = findtool.fetch(query, job.image_dir / "found", n=args.n)
    except findtool.FindProblem as e:
        out.fix(f"{e}; give your own photo with stone image <path to photo>")
        out.next = "stone image <path to photo>"
        out.result = f"find failed: {e}"
        return out
    out.add(f"Found {len(got)} free-licensed photos of {query} on Wikimedia Commons:")
    for g in got:
        out.add(f"{Path(g['file']).name}: {g['license']}, by {g['author'] or 'unknown'}")
    out.add(f"Credits: {job.image_dir / 'found' / 'credits.txt'} (name them when you share the part)")
    out.owns_next = True  # the photos are what the plan was waiting for
    if plan and plan.get("recipe") == "figure":
        out.next = "stone build"
        out.stage = "plan"
    else:
        out.next = "stone show figure"
        out.stage = "image"
    out.result = f"found {len(got)} photos of {query}"
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
    notes = job.add_note(text)
    out.add(f"Noted ({len(notes)} notes): {text}")
    st = job.status()
    if str(st.get("next", "")).startswith("ask the person") and st.get("ask_recipe"):
        # the answer to stone's question is part of the request now, so show places its size
        with job.brief_file.open("a") as f:
            f.write(f"\nAnswer: {text}\n")
        out.owns_next = True
        out.next = f"stone show {st['ask_recipe']}"
        return out
    out.next = st.get("next") or "stone recipes"
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
    if cached.get("stl") == stamp and (bd / "regions.npz").is_file():
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
    write_json(bd / "regions.json", {"stl": stamp, "picture": str(front) if front else None, "regions": res["regions"],
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
    named = colortool.request_colors(request)
    if not pc and len(named) == 1 and any(d.get("part") for d in info):
        # one color and no part given a color ("Jensen Huang in white", even with "on the base"
        # or "his face" said along the way): the whole figure is that color
        n = _match_filament(named[0], fil)
        if n is None:
            return {}, len(fil) + 1, [named[0]]
        return {}, n, []
    if not pc or not any(d.get("part") for d in info):
        return _suggest_colors(info, fil, request)

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
    photo, rest_p, _ = _suggest_colors(info, fil, "")
    rest = num(rest_c) if rest_c else rest_p
    pick: dict[int, int] = {}
    for d in info:
        p = parts.part_of(d.get("part") or "") or d.get("part")
        if d["base"] and p not in pc:
            continue
        if p in pc:
            pick[d["n"]] = _picture_filament(d["rgb"], allf, rest) if pc[p] == "picture" else num(pc[p])
        else:
            pick[d["n"]] = rest if rest_c else photo.get(d["n"], rest)
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
    for d in info[:colortool.LIST_MAX]:
        f = pick.get(d["n"], rest)
        part = d.get("part")
        if part and part not in ("other", "base") and part not in done:
            same = {pick.get(e["n"], rest) for e in info if e.get("part") == part}
            if len(same) == 1:
                done.add(part)
                if f != rest:
                    items.append(f"{part}={names[f - 1]}")
                continue
        if f != rest:
            items.append(f"{d['n']}={names[f - 1]}")
    return items


def _suggest_line(info: list[dict], fil: list[str], request: str) -> str:
    pick, rest, extra = _suggest(info, fil, request)
    names = _fil_value(fil + extra)
    return "stone colors " + " ".join(_mapping_items(info, pick, rest, names) + [f"rest={names[rest - 1]}"])


def _part_regions(info: list[dict], key: str) -> list[int]:
    """The region numbers a part name stands for ("jacket", or "top" for the jacket)."""
    from . import parts

    key = key.strip().lower()
    want = parts.part_of(key)
    return [d["n"] for d in info if d.get("part") and d["part"] not in ("other",)
            and (d["part"] == key or (want is not None and parts.part_of(d["part"]) == want))]


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
    face_fil0 = per[num]
    # cut along smooth boundaries, so a color edge runs as a curve through the triangles
    # the plinth's edge and a figure's hem, neck and wrists are lines of the shape: keep them there
    fixed = res["fixed"] if res["fixed"] is not None else (num == base if base else None)
    V, F, face_fil, parent = colortool.smooth_cut(mesh.vertices, mesh.faces, face_fil0, fixed=fixed)
    cut = colortool.load_stl_mesh(V, F)  # the float32 mesh the 3MF holds
    names = _fil_value(fil)

    def mapping_line(a: dict) -> str:
        return " ".join(_mapping_items(info, a, rest, names) + [f"rest={names[rest - 1]}"])

    worst, lines = colortool.color_edges(V, F, face_fil)
    anat_lines = (res.get("anatomy") or {}).get("lines") or []
    colortool.mark_grooves(lines, anat_lines)
    faults = colortool.edge_faults(lines)
    wob = colortool.worst_wobble(lines)
    fil_rgb = np.array([colortool.filament_rgb(f) or (150, 150, 150) for f in fil], float)
    one_color = len(np.unique(face_fil)) == 1  # no color edge, so nothing can climb a ledge
    ledge = (colortool.ledge_faults(colortool.ledges(V, F, face_fil, anat_lines))
             if anat_lines and not faults and not one_color else [])
    reg_of = num[parent]

    def smallest_painted(near: np.ndarray) -> int | None:
        """The smallest region off the rest color among the faces `near` a failing edge."""
        cand = [int(g) for g in np.unique(reg_of[near]) if assign.get(int(g), rest) != rest]
        return min(cand, key=lambda k: next(d["share"] for d in info if d["n"] == k)) if cand else None

    def retry(drop: list[int]) -> None:
        """A NEXT that changes the outcome: the regions on the failing edges take the rest color;
        with none to give, the part prints in one color. Never the mapping that just failed."""
        failed = mapping_line(assign)
        nxt = mapping_line({k: v for k, v in assign.items() if k not in drop}) if drop else failed
        if drop:
            names_d = ", ".join(f"region {g} ({next(d.get('part') or d['color'] or 'base' for d in info if d['n'] == g)})"
                                for g in drop)
            out.add(f"The paint of {names_d} does not follow a clean line; it takes the rest color.")
        if nxt == failed:
            nxt = f"rest={names[rest - 1]}"
            out.add(f"No region can take the rest color to clear it, so the part prints in one color, "
                    f"{names[rest - 1]}.")
        out.next = "stone colors " + nxt

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
        g = smallest_painted(near)
        retry([g] if g is not None else [])
        out.result = f"colors failed: {x['name']} edge on a ledge ({x['area']:.2f} mm2 seen)"
        return out
    if faults:
        # paint that cannot follow a clean line (often a feature the picture puts beside the shape)
        drop: list[int] = []
        bad_lines = faults
        for ln in bad_lines:
            g = smallest_painted(np.isin(F, ln["verts"]).any(1))
            if g is not None and g not in drop:
                drop.append(g)
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
        retry(drop)
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
    for c in added:
        out.add(f"{c} is not in stone.toml [filaments], so it is filament {fil.index(c) + 1} here: load it in that slot.")
    out.add(shares)
    out.add(f"Object filament {main_fil}; the other filaments are painted on, triangle by triangle.")
    out.add(f"Checked: the 3MF reads back watertight and clean for a slicer, {len(F)} faces, volume as the STL.")
    in_groove = sum(1 for ln in lines if ln.get("groove"))
    out.add(f"PASS color_edges: every color boundary is a smooth curve (worst {worst:.3f}, max {colortool.JAGGED}; "
            f"wobble {wob:.2f} mm, max {colortool.WOBBLE}"
            + (f"; {in_groove} edges run in a sculpted groove, which the wobble limit does not apply to)" if in_groove else ")"))
    if anat_lines:
        grooves = [f"{x['name']}{'' if x.get('side') is None else (' left' if x['side'] < 0 else ' right')} "
                   f"{'up' if x['groove']['side'] > 0 else 'down'}" for x in anat_lines if (x.get("groove") or {}).get("used")]
        out.add("PASS ledges: no up-facing face of the wrong color is seen next to a part's edge"
                + (f"; edges in the groove: {', '.join(grooves)}" if grooves else ""))
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

    s = sub.add_parser("set", parents=[common], help="set recipe parameters")
    s.add_argument("items", nargs="*")
    s.add_argument("--reset", action="store_true")

    sub.add_parser("build", parents=[common], help="build and check the part")

    s = sub.add_parser("check", parents=[common], help="print checks on an STL")
    s.add_argument("file", nargs="?")

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

    sub.add_parser("done", parents=[common], help="finish the job")

    s = sub.add_parser("colors", parents=[common], help="color regions, then a painted 3MF: stone colors 1=black rest=white")
    s.add_argument("items", nargs="*")
    return p


COMMANDS = {
    "status": cmd_status,
    "new": cmd_new,
    "recipes": cmd_recipes,
    "show": cmd_show,
    "set": cmd_set,
    "build": cmd_build,
    "check": cmd_check,
    "image": cmd_image,
    "measure": cmd_measure,
    "find": cmd_find,
    "note": cmd_note,
    "done": cmd_done,
    "colors": cmd_colors,
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
            "color": "colors", "colour": "colors", "colours": "colors", "paint": "colors"}
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


def run(argv: list[str]) -> tuple[str, int]:
    argv = _tidy(argv)
    parser = make_parser()
    job = Job(_guess_job(argv))
    cmdline = "stone " + " ".join(argv)
    try:
        args = parser.parse_args(argv)
        if args.cmd is None:
            args = parser.parse_args(argv + ["status"])
        cmd = args.cmd
        job = Job(config.job_dir(getattr(args, "job", None) or args.job_top))
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
    text = out.render()
    if job.exists() and cmd not in ("status",):
        job.log(f"{cmdline}\n{text}")
        s = job.status()
        upd = {"last_command": cmdline}
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
    text, code = run(sys.argv[1:] if argv is None else argv)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
