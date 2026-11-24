"""Grade a landmark built from source references and its finished print files."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

import models_grade

RATIO_TOL = 0.04


def _domain(url, domain: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host == domain or host.endswith("." + domain))


def _positive(value) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and value > 0


def _close(actual: float, reference: float) -> bool:
    return abs(actual / reference - 1) <= RATIO_TOL


def credits_why(job: Path, refs: dict) -> list[str]:
    try:
        text = (job / "model" / "credits.txt").read_text()
    except OSError:
        return ["no landmark credits.txt"]
    why = []
    if "openstreetmap contributors" not in text.casefold() or "odbl" not in text.casefold():
        why.append("credits must name OpenStreetMap contributors and ODbL")
    urls = {refs.get("source"), refs.get("wikipedia_url"), *refs.get("sources", {}).values(),
            *refs.get("feature_sources", [])}
    for url in sorted(u for u in urls if _domain(u, "wikidata.org") or _domain(u, "wikipedia.org")):
        if url not in text:
            why.append(f"credits missing {url}")
    return why


def feature_grade(parts: list[dict], want: dict) -> tuple[dict, list[str]]:
    counts = Counter(p["feature"] for p in parts if p.get("feature"))
    why = []
    for feature, rule in want.items():
        count = counts[feature]
        if "count" in rule and count != rule["count"]:
            why.append(f"{count} {feature} (want {rule['count']})")
        if "min" in rule and count < rule["min"]:
            why.append(f"{count} {feature} (want at least {rule['min']})")
        if rule.get("tallest") and count:
            selected = [p["height"]["metres"] for p in parts if p.get("feature") == feature]
            other = [p["height"]["metres"] for p in parts
                     if p.get("feature") != feature and p.get("feature_of") is None]
            if other and min(selected) <= max(other):
                why.append(f"the {feature} parts must be taller than every other independent part")
    return dict(counts), why


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def grade(job: Path, spec: dict, checks: bool = True) -> dict:
    import trimesh

    want = spec["expect"]["landmarks"]
    refs = _read(job / "refs" / "landmark.json")
    why = credits_why(job, refs)
    data = _read(job / "build" / "model" / "parts.json")
    parts = data.get("parts") or []
    if not parts or data.get("model", {}).get("source") != "landmark":
        return {"pass": False, "why": ["no finished build from stone landmark", *why], "parts": 0}
    out = {"parts": len(parts)}
    if not all(Path(p["file"]).is_file() for p in parts):
        return {**out, "pass": False, "why": ["a part file is missing", *why]}
    if not data.get("passed"):
        why.append("stone landmark reported a print check failure")
    if checks:
        failures, out["checks"] = models_grade.checks_why(data, want["bed"], recorded=True)
        why.extend(failures)

    vertices = np.concatenate(list(models_grade.assembled_vertices(parts)))
    _, sides = trimesh.bounds.oriented_bounds_2D(vertices[:, :2])
    width, length = sorted(map(float, sides))
    size = np.array([length, width, np.ptp(vertices[:, 2])])
    out["size_mm"] = [round(float(x), 3) for x in size]
    why.extend(models_grade.size_why(size, want["size"], want["bed"]))
    height = float(size[2]) - refs.get("plinth_height_mm", 2)

    dimensions = refs.get("reference_dimensions_m", {})
    standard = refs.get("height")
    if (_positive(standard) and _positive(dimensions.get("length")) and _positive(dimensions.get("width"))
            and _domain(dimensions.get("source"), "openstreetmap.org")):
        out["ratios"] = {}
        for axis, span in (("length", length), ("width", width)):
            actual, reference = height / span, standard / dimensions[axis]
            out["ratios"][axis] = {"built": actual, "reference": reference,
                                    "error": abs(actual / reference - 1)}
            if not _close(actual, reference):
                why.append(f"height/{axis} is {actual:.3f}, reference {reference:.3f} (4% tolerance)")
    else:
        why.append("missing sourced OSM reference dimensions or comparable reference height")

    wd = refs.get("wikidata_height_m")
    if "wikidata_height_m" not in refs and _domain(refs.get("sources", {}).get("height"), "wikidata.org"):
        wd = standard
    scale = refs.get("scale_mm_per_metre")
    height_values = [p.get("height", {}).get("metres") for p in refs.get("parts", [])]
    tallest = max((h for h in height_values if _positive(h)), default=None)
    if refs.get("height_comparison"):
        out["height_comparison"] = refs["height_comparison"]
    if _positive(scale):
        out["height_m"] = {"built": height / scale, "tallest_part": tallest, "wikidata": wd}
    # Wikidata's height is not always the tallest point (Notre-Dame's is the 69 m towers, not the 96 m
    # spire); a spec may name the tallest point with its own source, and then that is the reference.
    named = want.get("tallest") or {}
    label = "Wikidata"
    if _positive(named.get("m")) and named.get("source"):
        wd, label = float(named["m"]), named["source"]
        out.setdefault("height_m", {})["reference"] = {"m": wd, "source": label}
    if not _positive(wd):
        why.append("no comparable current Wikidata height")
    elif not _positive(scale) or tallest is None:
        why.append("missing landmark scale or tallest part height")
    else:
        if not _close(height / scale, wd):
            why.append(f"built height is {height / scale:.2f} m at scale, {label} says {wd:g} m")
        if not _close(tallest, wd):
            why.append(f"tallest part is {tallest:.2f} m, {label} says {wd:g} m")
    out["features"], failures = feature_grade(refs.get("parts", []), want.get("features", {}))
    why.extend(failures)
    return {**out, "pass": not why, "why": why or ["all checks pass"]}


def run(rdir: Path, job: Path, spec: dict) -> dict:
    result = grade(job, spec)
    result = models_grade.judged(rdir, job, spec, result, suite="landmarks", save_reference=True)
    return {**result, "judge": result["likeness"]}


def summary(result: dict) -> str:
    ratios = result.get("ratios", {})
    spans = ", ".join(f"H/{axis} {v['built']:.3f} (ref {v['reference']:.3f})" for axis, v in ratios.items())
    score = result.get("judge")
    judge = f"{score}/10" if score is not None else "unavailable"
    return f"{spans or 'ratios unavailable'}, Opus {judge}"
