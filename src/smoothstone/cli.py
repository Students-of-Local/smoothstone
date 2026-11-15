"""stone: the command line a small model drives. Every output ends with one NEXT line."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import check as checks
from . import config
from . import image as imagetool
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


def build_params(job: Job | None, r: rc.Recipe, given: dict) -> dict:
    """Defaults + plan, with the job image filled into unset image params."""
    merged = r.merged(given)
    imgs = job.image_paths() if job else {}
    for p in r.params:
        if p.type == "image" and p.name not in given and p.image_kind in imgs:
            merged[p.name] = str(imgs[p.image_kind].resolve())
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
    if s.get("last_result"):
        out.add(f"Last: {s.get('last_command', '')} -> {s['last_result']}")
    out.add(f"Stage: {s.get('stage')}")
    if s.get("stage") == "done" and plan:
        out.add(f"Part: {job.root / (plan['recipe'] + '.stl')}")
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
    same = plan is not None and plan["recipe"] == r.name
    params = dict(plan["params"]) if same and not args.reset else {}
    pairs, loose = split_items(items, r)
    fixes: list[str] = []
    retry: dict[str, str] = {}
    hard = False
    for it in loose:
        fixes.append(f"write each change as name=value, like {it}=<value>")
        hard = True
    names = [p.name for p in r.params]
    imgs = job.image_paths()
    for k, raw in pairs:
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
    bd = job.build_dir
    bd.mkdir(parents=True, exist_ok=True)
    for f in ("part.stl", "part.off", "preview.png", "check.json", "openscad.log", "preview.scad"):
        (bd / f).unlink(missing_ok=True)
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
    off = stl.with_suffix(".off")
    results = checks.check_stl(off if off.is_file() else stl, recipe=r, params=params, bed=bed)
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
        out.next = "stone done"
        out.stage = "built"
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


def image_step(job: Job, path: Path, out: Out):
    try:
        info = imagetool.process(path.expanduser(), job.image_dir)
    except imagetool.ImageProblem as e:
        job.log("image failed:\n" + traceback.format_exc())
        out.fix(f"{e}; give a PNG or JPG picture")
        out.next = "stone image <path to picture>"
        out.result = f"image failed: {e}"
        return None
    w, h = info["svg_size_mm"]
    out.add(f"Image: {info['source']}")
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
    words = " ".join(w.replace("_", " ") for w in info["recipes"])
    out.next = f"stone recipes {words}"
    out.stage = "image" if not job.plan() else None
    out.result = f"image {info['kind']}, aspect {info['aspect']:.2f}"
    return info


def cmd_image(args, job: Job) -> Out:
    out = Out(owns_next=False)
    if not job.exists():
        out.add(f"No job in {job.root}.")
        out.next = f'stone new "<what to make>" --image {args.path}'
        out.code = 1
        return out
    image_step(job, Path(args.path), out)
    return out


# done


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

    sub.add_parser("done", parents=[common], help="finish the job")
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
    "done": cmd_done,
}


def _guess_job(argv: list[str]) -> Path:
    for i, a in enumerate(argv):
        if a == "--job" and i + 1 < len(argv):
            return config.job_dir(argv[i + 1])
        if a.startswith("--job="):
            return config.job_dir(a.split("=", 1)[1])
    return config.job_dir(None)


def run(argv: list[str]) -> tuple[str, int]:
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
        out.fix(f"{e}; commands: status new recipes show set build check image done")
        out.next = "stone status"
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
        if out.owns_next or early:
            upd["next"] = out.next
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
