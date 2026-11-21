"""Recipe loading, ranking, parameter validation and the safe dims evaluator."""

from __future__ import annotations

import ast
import difflib
import json
import math
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config

TIER_VISIBLE = {"S": {"S"}, "M": {"S", "M"}, "L": {"S", "M", "L"}}
PARAM_TYPES = ("number", "int", "bool", "text", "choice", "image")
STOPWORDS = {
    "a", "an", "the", "of", "for", "with", "and", "or", "to", "in", "on", "at",
    "my", "me", "make", "i", "want", "need", "please", "that", "this", "it",
    "is", "be", "can", "some", "one", "two", "small", "big", "large",
}


class RecipeError(Exception):
    """Problem with a recipe file (bad json, missing fields)."""


@dataclass
class Param:
    name: str
    type: str
    default: object
    min: float | None = None
    max: float | None = None
    choices: list = field(default_factory=list)
    unit: str = ""
    help: str = ""
    image_kind: str = "silhouette"
    required: bool = False
    required_unless: str = ""
    fit_add: float = 0.0  # clearance added to a size read from the request ("5 mm cables" -> 5.3 mm slots)
    product: bool = False  # a choice that names the real thing the part fits (phone=iphone_17_pro), so it is a size

    def range_text(self) -> str:
        if self.type in ("number", "int"):
            lo = fmt_num(self.min) if self.min is not None else ""
            hi = fmt_num(self.max) if self.max is not None else ""
            unit = f" {self.unit}" if self.unit else ""
            if lo or hi:
                return f"{self.type}, {lo}..{hi}{unit}"
            return f"{self.type}{unit}"
        if self.type == "choice":
            return "choice: " + " | ".join(str(c) for c in self.choices)
        if self.type == "bool":
            return "bool: true | false"
        if self.type == "image":
            return f"image, {self.image_kind}: use image"
        return self.type


@dataclass
class Recipe:
    name: str
    title: str
    summary: str
    tags: list[str]
    tier: str
    params: list[Param]
    dims: dict[str, str]
    dims_tol: float
    max_bodies: int
    max_overhang: float
    min_wall: float
    fix: dict
    examples: list[dict]
    path: Path
    aliases: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    size_order: list = field(default_factory=list)
    grow: dict = field(default_factory=dict)  # assert text -> {"param", "value"}: "the cutouts do not fit" widens the plate
    makes: list = field(default_factory=list)  # the objects it really makes: "phone stand"; none listed fits any request
    skip: dict = field(default_factory=dict)  # check name -> why this recipe does not run it
    phrases: dict = field(default_factory=dict)  # "with a saucer" -> {"part": "both"}, read before single words  # params for "A by B by C"; default: from dims x, y, z  # word -> [param, offset]: "3 compartments" sets div_x = 2

    @property
    def scad(self) -> Path:
        return self.path / "recipe.scad"

    @property
    def hidden(self) -> bool:
        return self.name.startswith("_")

    def param(self, name: str) -> Param | None:
        for p in self.params:
            if p.name == name:
                return p
        return None

    def defaults(self) -> dict:
        out = {}
        for p in self.params:
            v = p.default
            if p.type == "image" and isinstance(v, str) and v:
                cand = (self.path / v).resolve()
                if cand.exists():
                    v = str(cand)
            out[p.name] = v
        return out

    def merged(self, given: dict) -> dict:
        out = self.defaults()
        out.update({k: v for k, v in given.items() if self.param(k)})
        return out

    def expected_dims(self, params: dict) -> dict[str, float]:
        out = {}
        for axis in ("x", "y", "z"):
            expr = self.dims.get(axis)
            if expr is None:
                continue
            out[axis] = float(safe_eval(str(expr), params))
        return out


def fmt_num(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.4g}" if abs(v) < 1e-3 else str(round(v, 4))
    return str(v)


def fmt_value(p: Param | None, v) -> str:
    if p is not None and p.type in ("text", "choice", "image"):
        s = str(v)
        return s if s and " " not in s and "=" not in s else json.dumps(s)
    return fmt_num(v)


def _load_one(d: Path) -> Recipe:
    j = d / "recipe.json"
    try:
        data = json.loads(j.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RecipeError(f"{j}: {e}") from e
    params = []
    for raw in data.get("params", []):
        t = raw.get("type", "number")
        if t not in PARAM_TYPES:
            raise RecipeError(f"{j}: param {raw.get('name')} has bad type {t}")
        params.append(
            Param(
                name=raw["name"],
                type=t,
                default=raw.get("default"),
                min=raw.get("min"),
                max=raw.get("max"),
                choices=list(raw.get("choices") or []),
                unit=raw.get("unit", "") or "",
                help=raw.get("help", "") or "",
                image_kind=raw.get("image_kind", "silhouette") or "silhouette",
                required=bool(raw.get("required", False)),
                required_unless=raw.get("required_unless", "") or "",
                fit_add=float(raw.get("fit_add", 0) or 0),
                product=bool(raw.get("product", False)),
            )
        )
    return Recipe(
        name=data.get("name") or d.name,
        title=data.get("title", d.name),
        summary=data.get("summary", ""),
        tags=list(data.get("tags", [])),
        tier=str(data.get("tier", "S")).upper(),
        params=params,
        dims=dict(data.get("dims") or {}),
        dims_tol=float(data.get("dims_tol", 0.6)),
        max_bodies=int(data.get("max_bodies", 1)),
        max_overhang=float(data.get("max_overhang", 0.05)),
        min_wall=float(data.get("min_wall", 0.8)),
        fix=dict(data.get("fix") or {}),
        makes=list(data.get("makes") or []),
        examples=list(data.get("examples") or []),
        aliases=dict(data.get("aliases") or {}),
        counts=dict(data.get("counts") or {}),
        size_order=list(data.get("size_order") or []),
        phrases=dict(data.get("phrases") or {}),
        grow=dict(data.get("grow") or {}),
        skip=dict(data.get("skip") or {}),
        path=d,
    )


def load_all(root: Path | None = None) -> dict[str, Recipe]:
    root = root or config.recipes_dir()
    out: dict[str, Recipe] = {}
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not (d / "recipe.json").is_file() or not (d / "recipe.scad").is_file():
            continue
        try:
            r = _load_one(d)
        except (RecipeError, KeyError, TypeError, ValueError):
            continue
        out[d.name] = r
    return out


def load(name: str, root: Path | None = None) -> Recipe | None:
    root = root or config.recipes_dir()
    d = root / name
    if not (d / "recipe.json").is_file() or not (d / "recipe.scad").is_file():
        return None
    return _load_one(d)


def visible(all_recipes: dict[str, Recipe], tier: str, show_all: bool = False) -> list[Recipe]:
    if show_all:
        return list(all_recipes.values())
    allowed = TIER_VISIBLE.get(tier, {"S"})
    return [r for r in all_recipes.values() if not r.hidden and r.tier in allowed]


def closest(word: str, names: list[str], n: int = 3) -> list[str]:
    got = difflib.get_close_matches(word, names, n=n, cutoff=0.3)
    if len(got) < n:
        for name in names:
            if name not in got and (word in name or name in word):
                got.append(name)
    return got[:n]


# ranking


def stem(word: str) -> str:
    w = word.lower()
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(text: str) -> set[str]:
    out = set()
    for w in re.split(r"[^A-Za-z0-9]+", text or ""):
        if not w:
            continue
        s = stem(w)
        if s and s not in STOPWORDS:
            out.add(s)
    return out


def _seq(text: str) -> list[str]:
    return [stem(w) for w in re.split(r"[^A-Za-z0-9]+", text or "") if w]


# words after which a request says where the part goes or what it holds, not what it is
CONTEXT = re.compile(r"\b(?:for|inside|in|into|on|onto|with|that|which|who|to|under|over|near|from|at|of|"
                     r"so|and|by|holding|wearing)\b", re.I)
SIZE_WORDS = {"mm", "cm", "in", "inch", "tall", "wide", "long", "high", "deep", "thick", "big", "small"}


def head(query: str) -> list[str]:
    """The words that name the part: the request up to its first comma or context word
    ("A guard for a 120 mm PC fan inside a box" is "a guard"), size words off the end."""
    first = re.split(r"[,.;:!?(]", query or "", maxsplit=1)[0]
    words = _seq(CONTEXT.split(first, maxsplit=1)[0])
    while words and (words[-1].isdigit() or words[-1] in SIZE_WORDS or re.fullmatch(r"\d+\w*", words[-1])):
        words.pop()
    return words


def fit(r: Recipe, query: str) -> int:
    """How well the request names what the recipe makes. 3 when a makes phrase ends in the noun the
    request starts with ("a guard for a PC fan" is a fan guard), 2 when a phrase is in the request
    word for word somewhere else ("a box" in "a guard ... inside a box"), 1 when all of a phrase's
    words are there in any order ("clips that hold the cables"), 0 when none is. A box is not a
    birdhouse: a recipe that fits 0 must not be handed over as the request. A recipe with no makes
    list fits any request (1)."""
    if not r.makes:
        return 1
    q = _seq(query)
    text = " " + " ".join(q) + " "
    h = head(query)
    noun = h[-1] if h else None
    best = 0
    for phrase in r.makes:
        ph = _seq(phrase)
        if not ph or not all(any(_same(w, x) for x in q) for w in ph):
            continue
        if noun and _same(ph[-1], noun):
            return 3
        best = max(best, 2 if " " + " ".join(ph) + " " in text else 1)
    return best


def _same(word: str, said: str) -> bool:
    """A word of a makes phrase in the request, through a typo in a longer word: "gaurd" is guard."""
    if word == said:
        return True
    # a typo keeps the length; a longer or shorter word is another word: plant is not planter
    if len(word) < 5 or abs(len(word) - len(said)) > 1 or word.startswith(said) or said.startswith(word):
        return False
    return difflib.SequenceMatcher(None, word, said).ratio() >= 0.8


def rank(recipes: list[Recipe], query: str) -> list[tuple[int, Recipe]]:
    q = tokens(query)
    scored = []
    for r in recipes:
        name_t = tokens(r.name.replace("_", " "))
        title_t = tokens(r.title)
        tag_t = set()
        for t in r.tags:
            tag_t |= tokens(t)
        sum_t = tokens(r.summary)
        score = (
            3 * len(q & name_t)
            + 2 * len(q & tag_t)
            + 2 * len(q & title_t)
            + len(q & sum_t)
        )
        scored.append((score, r))
    scored.sort(key=lambda sr: (-sr[0], sr[1].name))
    return scored


# value coercion


class ParamError(Exception):
    def __init__(self, fix: str, suggest=None):
        super().__init__(fix)
        self.fix = fix
        self.suggest = suggest


TRUE = {"true", "yes", "on", "1", "y"}
FALSE = {"false", "no", "off", "0", "n"}


def _num(p: Param, raw: str) -> float:
    s = raw.strip().lower()
    for suffix in filter(None, [p.unit.lower(), "mm", "deg", "%"]):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)].strip()
            break
    v = float(s)
    if not math.isfinite(v):
        raise ValueError(raw)
    return v


def coerce(p: Param, raw: str, image_paths: dict[str, Path] | None = None):
    """Turn a command line string into a typed value or raise ParamError."""
    raw = raw.strip()
    if p.type in ("number", "int"):
        try:
            v = _num(p, raw)
        except ValueError:
            raise ParamError(f"{p.name} needs a number, got {raw!r}") from None
        if p.type == "int":
            if not float(v).is_integer():
                raise ParamError(
                    f"{p.name} needs a whole number, got {raw}", suggest=int(round(v))
                )
            v = int(v)
        unit = f" {p.unit}" if p.unit else ""
        if p.min is not None and v < p.min:
            lo, hi = fmt_num(p.min), fmt_num(p.max) if p.max is not None else ""
            raise ParamError(
                f"{p.name}={fmt_num(v)} is below the range {lo}..{hi}{unit}, use {lo} or more",
                suggest=p.min,
            )
        if p.max is not None and v > p.max:
            lo = fmt_num(p.min) if p.min is not None else ""
            hi = fmt_num(p.max)
            raise ParamError(
                f"{p.name}={fmt_num(v)} is above the range {lo}..{hi}{unit}, use {hi} or less",
                suggest=p.max,
            )
        return v
    if p.type == "bool":
        s = raw.lower()
        if s in TRUE:
            return True
        if s in FALSE:
            return False
        raise ParamError(f"{p.name} needs true or false, got {raw!r}")
    if p.type == "choice":
        for c in p.choices:
            if str(c).lower() == raw.lower():
                return c
        names = [str(c) for c in p.choices]
        near = difflib.get_close_matches(raw, names, n=1, cutoff=0.6)
        raise ParamError(
            f"{p.name} must be one of: {', '.join(names)}",
            suggest=near[0] if near else None,
        )
    if p.type == "image":
        if raw.lower().startswith("image="):
            raw = raw[6:] or "image"  # icon=image=<path>
        job_files = {Path(v).resolve() for v in (image_paths or {}).values()}
        sources = [f for d in {f.parent for f in job_files} for f in d.glob("source.*")]
        typed = Path(raw).expanduser()
        if raw.lower() != "image" and (typed.resolve() in job_files or typed.is_file()
                                       and any(typed.read_bytes() == f.read_bytes() for f in sources)):
            raw = "image"  # the picture given to stone new, or one of the job's own picture files, means the job image
        if raw.lower() == "image":
            img = (image_paths or {}).get(p.image_kind)
            if img is None or not Path(img).exists():
                raise ParamError(
                    f"{p.name} needs the job image, run stone image <path to picture> first"
                )
            return str(Path(img).resolve())
        f = Path(raw).expanduser()
        if not f.is_file():
            raise ParamError(f"{p.name}: no file at {raw}, use {p.name}=image after stone image")
        want = {"silhouette": ".svg", "outline": ".svg", "figure": ".stl"}.get(p.image_kind, ".png")
        if f.suffix.lower() != want:
            raise ParamError(
                f"{p.name} needs a {want} file, run stone image {raw} then set {p.name}=image"
            )
        return str(f.resolve())
    return raw


def scad_literal(p: Param | None, v) -> str:
    """Value as an OpenSCAD literal for -D name=value."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if p is not None and p.type in ("text", "choice", "image"):
        return json.dumps(str(v), ensure_ascii=False)
    if isinstance(v, (int, float)):
        return fmt_num(v) if isinstance(v, int) or float(v).is_integer() else repr(float(v))
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return "undef"
    return json.dumps(v)


# safe arithmetic for dims


_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_FUNCS = {"min": min, "max": max, "abs": abs, "round": round}


def safe_eval(expr: str, names: dict):
    """Evaluate arithmetic over param names. Raises ValueError on anything else."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"bad expression {expr!r}") from e

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, bool, str)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in names:
                return names[n.id]
            if n.id in ("true", "True"):
                return True
            if n.id in ("false", "False"):
                return False
            raise ValueError(f"unknown name {n.id}")
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 16:
                raise ValueError("exponent too large")
            return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UNARY:
            return _UNARY[type(n.op)](ev(n.operand))
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, right in zip(n.ops, n.comparators):
                if type(op) not in _CMP:
                    raise ValueError("bad comparison")
                r = ev(right)
                if not _CMP[type(op)](left, r):
                    return False
                left = r
            return True
        if isinstance(n, ast.IfExp):
            return ev(n.body) if ev(n.test) else ev(n.orelse)
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in _FUNCS
            and not n.keywords
        ):
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError(f"not allowed in dims: {ast.dump(n)[:40]}")

    return ev(tree)
