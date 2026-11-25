"""Grade a landmark built from source references and its finished print files."""

from __future__ import annotations

import json
import math
import shlex
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import trimesh

import models_grade
from smoothstone import modelprint

RATIO_TOL = 0.04
MIN_LIKENESS = 8


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
    drawn_from = {refs.get("geometry_source"), *(p.get("source") for p in refs.get("parts", []))}
    mapped = not refs.get("parts") or any(_domain(u, "openstreetmap.org") for u in drawn_from)
    if mapped and ("openstreetmap contributors" not in text.casefold() or "odbl" not in text.casefold()):
        why.append("credits must name OpenStreetMap contributors and ODbL")
    urls = {refs.get("source"), refs.get("wikipedia_url"), *refs.get("sources", {}).values(),
            *refs.get("feature_sources", [])}
    for url in sorted(u for u in urls if _domain(u, "wikidata.org") or _domain(u, "wikipedia.org")):
        if url not in text:
            why.append(f"credits missing {url}")
    return why


def standing_in_mesh(mesh: trimesh.Trimesh, parts: list[dict], scale: float, plinth: float) -> int:
    """How many parts are slender points in the printed mesh itself: the surface reaches the part's
    recorded top, and most of a ring just outside its footprint is at least 2 mm lower."""
    centres, reach, tops = [], [], []
    for part in parts:
        ring = np.asarray(max(part["footprint"], key=len), dtype=float)[:, :2] * scale
        centre = (ring.min(0) + ring.max(0)) / 2
        centres.append(centre)
        reach.append(np.linalg.norm(ring - centre, axis=1).max())
        tops.append(part["height"]["metres"] * scale + plinth)
    if not centres:
        return 0
    angles = np.linspace(0, 2 * math.pi, 12, endpoint=False)
    unit = np.column_stack([np.cos(angles), np.sin(angles)])
    near = np.vstack([[0, 0], .25 * unit])
    rays = np.array([c + d for c, r in zip(centres, reach) for d in [*near, *(unit * (r + 1.0))]])
    above = float(mesh.bounds[1, 2]) + 5
    origins = np.column_stack([rays, np.full(len(rays), above)])
    places, hit, _ = mesh.ray.intersects_location(
        origins, np.tile([0., 0., -1.], (len(origins), 1)), multiple_hits=True)
    level = np.full(len(origins), -np.inf)
    np.maximum.at(level, hit, places[:, 2])
    level = level.reshape(len(centres), len(near) + len(unit))
    found: list[np.ndarray] = []
    for centre, top, column in zip(centres, tops, level):
        peak = column[:len(near)].max()
        ringed = (column[len(near):] <= peak - 2).mean() >= .6
        if abs(peak - top) <= 1.5 and ringed and all(np.linalg.norm(centre - c) > .8 for c in found):
            found.append(centre)
    return len(found)


def printed_mesh(generated: trimesh.Trimesh, parts: list[dict]) -> trimesh.Trimesh | None:
    """The files that print, put back together where the generator built them. The print step turns the
    model about the vertical and never scales a landmark, so the same turn taken back lines them up.
    None when they do not line up, because then nothing can be counted at its recorded place."""
    turned = modelprint.footprint_turn(generated, [])
    back = np.linalg.inv(trimesh.registration.procrustes(
        generated.vertices, turned.vertices, reflection=False, scale=False)[0])
    meshes = []
    for part in parts:
        mesh = trimesh.load(part["file"], force="mesh", process=False)
        meshes.append(mesh.apply_transform(back @ np.linalg.inv(np.asarray(part["to_print"], float))))
    mesh = trimesh.util.concatenate(meshes)
    plan = np.abs(mesh.bounds - generated.bounds)[:, :2]
    return mesh if plan.max() < 1 else None


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
    want = spec["expect"]["landmarks"]
    refs = _read(job / "refs" / "landmark.json")
    why = credits_why(job, refs)
    references = want.get("references", {})
    for fact, field in (("identity", "source"), ("footprint", "geometry_source")):
        if references.get(fact) and refs.get(field) != references[fact]:
            why.append(f"wrong landmark reference for {fact}")
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
    # A linked tower prints with the building, so its plan counts only where the spec names the tower.
    plan = refs.get("plan_dimensions_m") or {}
    linked = plan.get("associated_outlines", [])
    if plan and set(linked) <= set(references.get("linked_outlines", [])):
        dimensions = {**dimensions, "length": plan["length"], "width": plan["width"]}
    elif plan:
        why.append("linked towers the spec does not name: " + ", ".join(linked))
    # A landmark redrawn from engineering figures has no mapped outline, or not the one it prints (a lean).
    drawn = want.get("dimensions") or {}
    if drawn.get("source") and drawn.get("why"):
        dimensions = drawn
    named = want.get("tallest") or {}
    standard = named.get("m") if named.get("source") else refs.get("height")
    if (_positive(standard) and _positive(dimensions.get("length")) and _positive(dimensions.get("width"))
            and (dimensions is drawn or _domain(dimensions.get("source"), "openstreetmap.org"))):
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
    for axis, span in (("length", length), ("width", width)):
        cited = references.get(f"{axis}_m")
        if cited and _positive(scale):
            allowed = cited.get("tolerance", RATIO_TOL)
            error = abs(span / scale / cited["value"] - 1)
            out.setdefault("cited", {})[axis] = {"built": span / scale, "reference": cited["value"], "error": error}
            if error > allowed:
                why.append(f"built {axis} is {span / scale:.1f} m at scale, {cited['source']} says "
                           f"{cited['value']:g} m ({allowed:.0%} tolerance)")
    out["features"], failures = feature_grade(refs.get("parts", []), want.get("features", {}))
    why.extend(failures)
    for feature, rule in want.get("features", {}).items():
        if "in_mesh" not in rule:
            continue
        stl = job / "model" / "generated.stl"
        named_parts = [p for p in refs.get("parts", []) if p.get("feature") == feature]
        mesh = printed_mesh(trimesh.load(stl, force="mesh", process=False), parts) if stl.is_file() else None
        if not stl.is_file():
            why.append("no generated model to find the print's frame from")
        elif mesh is None:
            why.append("the print files do not line up with the generated model")
        stands = (standing_in_mesh(mesh, named_parts, scale, refs.get("plinth_height_mm", 2))
                  if mesh is not None and _positive(scale) else 0)
        out.setdefault("in_mesh", {})[feature] = stands
        if stands < rule["in_mesh"]:
            why.append(f"{stands} {feature} stand in the printed mesh (want at least {rule['in_mesh']})")
    return {**out, "pass": not why, "why": why or ["all checks pass"]}


def missing_parts_result(job: Path, spec: dict, steps: list[dict]) -> dict | None:
    want = spec["expect"]["landmarks"]
    if not want.get("allow_missing_parts") or (job / "model" / "generated.stl").exists():
        return None
    refs = _read(job / "refs" / "landmark.json")
    sources = want.get("references", {})
    if (not _domain(refs.get("geometry_source"), "openstreetmap.org")
            or refs.get("geometry_source") != sources.get("footprint")
            or refs.get("source") != sources.get("identity")
            or not isinstance(refs.get("mapped_parts"), list)):
        return None
    known = refs.get("height_source_parts")
    coverage = refs.get("height_source_coverage")
    parts = refs.get("parts", [])
    if type(known) is not int or known < 0 or not (isinstance(coverage, (int, float)) and 0 <= coverage < .45):
        return None
    if known and (not parts or known / len(parts) >= .35):
        return None
    for step in steps:
        for call in step.get("tool_calls", []):
            try:
                command = shlex.split(call.get("args", {}).get("command", ""))
                lines = call.get("result", "").splitlines()
                next_command = shlex.split(lines[-1]) if lines else []
            except (TypeError, ValueError):
                continue
            if command[:1] == ["stone"]:
                command = command[1:]
            if (command[:1] == ["landmark"] and
                    any(line.startswith("FIX: insufficient mapped 3D parts") for line in lines) and
                    next_command == ["NEXT:", "stone", "models", refs.get("requested_name")]):
                return {"pass": True, "why": ["OSM lacks measured 3D parts. stone landmark gave FIX and NEXT stone models."],
                        "fallback": "missing_mapped_parts", "parts": 0, "judge": None, "likeness": None}
    return None


def run(rdir: Path, job: Path, spec: dict, steps: list[dict] | None = None) -> dict:
    fallback = missing_parts_result(job, spec, steps or [])
    if fallback:
        return fallback
    result = grade(job, spec)
    result = models_grade.judged(rdir, job, spec, result, suite="landmarks", save_reference=True,
                                 minimum=MIN_LIKENESS)
    return {**result, "judge": result["likeness"]}


def summary(result: dict) -> str:
    if result.get("fallback"):
        return "verified fallback"
    ratios = result.get("ratios", {})
    spans = ", ".join(f"H/{axis} {v['built']:.3f} (ref {v['reference']:.3f})" for axis, v in ratios.items())
    score = result.get("judge")
    judge = f"{score}/10" if score is not None else "unavailable"
    return f"{spans or 'ratios unavailable'}, Opus {judge}"
