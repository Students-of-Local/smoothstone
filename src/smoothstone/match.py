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

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a dozen": 12, "dozen": 12}
UNITS = {"mm": 1.0, "millimeter": 1.0, "millimeters": 1.0, "cm": 10.0, "centimeter": 10.0,
         "centimeters": 10.0, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4}
STOP = {"a", "an", "the", "for", "of", "with", "and", "that", "is", "are", "to", "in", "on", "by",
        "it", "its", "my", "i", "need", "want", "make", "me", "please", "about", "around", "x",
        "mm", "cm", "inch", "inches", "deg", "degrees", "each", "be", "should", "has", "have"}
NUM_RE = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?)\s*(mm|millimeters?|cm|centimeters?|inches|inch|in\b|"|deg\b|degrees?|°)?',
                    re.I)


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("ness", "ing", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _words(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-zA-Z]+", text) if w.lower() not in STOP]


def _param_words(p: rc.Param, aliases: list[str]) -> set[str]:
    return set(_words(p.name.replace("_", " ")) + _words(p.help) + [_stem(a) for a in aliases])


def _numbers(text: str) -> list[tuple[float, str, int, int]]:
    """(value in mm or plain, unit kind, start, end) for every number in the text."""
    t = text
    for w, n in sorted(WORDS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{w}\b", lambda m, n=n: str(n).ljust(len(m.group(0))), t, flags=re.I)
    out = []
    for m in NUM_RE.finditer(t):
        v = float(m.group(1))
        u = (m.group(2) or "").lower()
        if u in ("deg", "degree", "degrees", "°"):
            kind = "deg"
        elif u:
            v *= UNITS.get(u, 1.0)
            kind = "len"
        else:
            kind = "count"
        out.append((v, kind, m.start(), m.end()))
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
    aliases = getattr(r, "aliases", {}) or {}
    out: dict = {}
    # quoted text -> first text parameter
    quoted = re.findall(r'["“‘\']([^"”’\']{1,40})["”’\']', request)
    texts = [p for p in r.params if p.type == "text"]
    if quoted and texts:
        out[texts[0].name] = quoted[0]
    # choice values named in the request
    req_words = set(_words(request))
    for p in r.params:
        if p.type == "choice":
            for c in p.choices:
                if _stem(str(c)) in req_words and str(c) != str(p.default):
                    out[p.name] = c
                    break
    # numbers: score every (number, param) pair by the words around the number
    nums = _numbers(request)
    cands = []
    for i, (v, kind, s, e) in enumerate(nums):
        before = _words(request[max(0, s - 40):s])[-3:]
        after = _words(request[e:e + 40])[:3]
        ctx = set(before) | set(after)
        near = set(after[:2]) | set(before[-1:])
        for p in r.params:
            if p.type not in ("number", "int") or p.name in out:
                continue
            if kind == "deg" and p.unit != "deg":
                continue
            if kind == "len" and p.unit not in ("mm", ""):
                continue
            if kind == "count" and p.type != "int" and p.unit == "mm" and not ctx & _param_words(p, aliases.get(p.name, [])):
                continue
            pw = _param_words(p, aliases.get(p.name, []))
            score = len(ctx & pw) + len(near & pw)
            if kind == "count" and p.type == "int":
                score += 0.5
            if score > 0 and _fits(p, v):
                cands.append((score, -i, i, p.name, v if p.type != "int" else int(round(v))))
    used_n, used_p = set(), set()
    for score, _, i, name, v in sorted(cands, reverse=True):
        if i in used_n or name in used_p:
            continue
        used_n.add(i)
        used_p.add(name)
        out[name] = int(v) if float(v).is_integer() else round(float(v), 2)
    return {p.name: out[p.name] for p in r.params if p.name in out}
