"""Measured OSM building parts, assembled in millimetres for the shared print path.

References remain on disk even when the mapped geometry is insufficient.
Mapped geometry and sourced architectural corrections retain their provenance.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np


from .landmark_refs import LandmarkProblem


def length(value):
    """OSM metres, metric units, feet/inches, or a feet and inches pair.

    Reject ranges, lists, unknown units and nonfinite values rather than silently
    interpreting the first number as a measured height.
    """
    if value is None or isinstance(value, bool):
        return None
    s = str(value).strip().lower().replace("′", "'").replace("″", '"')
    pair = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:'|ft|feet)\s*(\d+(?:\.\d+)?)\s*(?:\"|in|inches)?", s)
    if pair:
        return float(pair[1]) * .3048 + float(pair[2]) * .0254
    m = re.fullmatch(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(m|metres?|meters?|cm|mm|km|ft|feet|foot|'|in|inch|inches|\")?", s)
    if not m:
        return None
    n = float(m[1]) * {"cm": .01, "mm": .001, "km": 1000, "ft": .3048, "feet": .3048,
                       "foot": .3048, "'": .3048, "in": .0254, "inch": .0254,
                       "inches": .0254, '"': .0254}.get(m[2], 1)
    return n if math.isfinite(n) else None


parse_length = length


def _section(rings):
    """Keep surveyed coordinates, clean repeats, and give holes opposite winding."""
    import manifold3d as m3

    contours = []
    for i, ring in enumerate(rings or []):
        p = np.asarray(ring, float)
        if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
            continue
        if len(p) > 1:
            p = p[np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-8]]
        if len(p) > 2 and np.linalg.norm(p[0] - p[-1]) < 1e-8:
            p = p[:-1]
        if len(p) < 3:
            continue
        area = float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1))) / 2
        if abs(area) < 1e-8:
            continue
        if (area > 0) != (i == 0):
            p = p[::-1]
        contours.append(p)
    return m3.CrossSection(contours)


def _union(solids):
    import manifold3d as m3
    return m3.Manifold.batch_boolean([s for s in solids if not s.is_empty()], m3.OpType.Add)


def _fact(metres, source, guessed=False, reason=None):
    out = {"metres": float(metres), "source": source, "guessed": bool(guessed)}
    if reason:
        out["reason"] = reason
    return out


def _levels(value):
    v = length(value)
    return v if v is not None and 0 < v < 300 else None


def _same_plan(a, b):
    """Whether two footprints have the same size, wherever they stand."""
    ax, bx = np.subtract(a.bounds()[2:], a.bounds()[:2]), np.subtract(b.bounds()[2:], b.bounds()[:2])
    return abs(a.area() / b.area() - 1) < .035 and bool((np.abs(ax / bx - 1) < .017).all())


def _level_from_twin(i, prepared):
    """A part drawn with no height inside a repeated element (one of four minarets) takes the level its
    same-plan twins elsewhere share. Returns (min_height, height, id), "duplicate" when every such level
    is already drawn here, or None when nothing repeats it."""
    part, cs, _, lo = prepared[i]
    if lo:
        return None
    levels, here = {}, []
    for other, other_cs, h, other_lo in prepared:
        if other is part or h is None or h <= other_lo or not _same_plan(cs, other_cs):
            continue
        if (cs ^ other_cs).area() > cs.area() * .8:
            here.append((other_lo, h))
        else:
            levels.setdefault((round(other_lo, 1), round(h, 1)), []).append((other_lo, h, other.get("id")))
    # One stray match is a coincidence. A set repeats at least twice and stands in for a stack here.
    levels = [v[0] for v in levels.values() if len(v) >= 2]
    stack = [1 for _, other_cs, h, other_lo in prepared
             if h is not None and other_lo and (cs ^ other_cs).area() > cs.area() * .6]
    if not levels or len(stack) < 2:
        return None
    missing = [v for v in levels if not any(abs(v[0] - a) < .3 and abs(v[1] - b) < .3 for a, b in here)]
    if not missing:
        return "duplicate"
    return missing[0] if len(missing) == 1 else None


def resolve_parts(parts, refs):
    """Resolve dimensions conservatively and return public records plus sections."""
    prepared = []
    for part in parts:
        cs = _section(part.get("footprint", []))
        if cs.is_empty() or cs.area() < .001:
            continue
        tags = part.get("tags", {})
        h = length(tags.get("height") or tags.get("building:height"))
        levels = _levels(tags.get("building:levels"))
        lo = length(tags.get("min_height"))
        if lo is None:
            ml = _levels(tags.get("building:min_level"))
            lo = ml * 4 if ml else 0
        if h is None and levels:
            h = max(lo + 4, levels * 4)
        prepared.append((part, cs, h, lo))
    known = [h for _, _, h, lo in prepared if h is not None and h > lo]
    if not known:
        return [], []
    median = float(np.median(known))
    real = length(refs.get("height"))
    # A source-wide height belongs only to a plausible mapped roof or tower.
    # Never add another co-dominant spire when measured heights already reach it.
    candidate = None
    if real and max(known) < real * .94:
        ranked = []
        for i, (p, cs, h, lo) in enumerate(prepared):
            if h is not None:
                continue
            t = p.get("tags", {})
            roof = t.get("roof:shape", "flat").lower()
            title = " ".join(str(t.get(k, "")) for k in ("name", "building:part", "building", "tower:type"))
            evidence = int(roof in ("pyramidal", "onion", "dome")) + int(bool(re.search(r"tower|spire|dome|steeple", title, re.I)))
            if evidence:
                ranked.append(((evidence, lo, cs.area()), i))
        if ranked:
            candidate = max(ranked)[1]
    records, sections = [], []
    for i, (part, cs, h, lo) in enumerate(prepared):
        t = part.get("tags", {})
        source = part.get("source") or refs.get("geometry_source") or "https://www.openstreetmap.org/copyright"
        raw_h = length(t.get("height") or t.get("building:height"))
        reason = twin_reason = None
        hsource = source
        if raw_h is None:
            if _levels(t.get("building:levels")):
                reason = "building:levels multiplied by 4 metres per level"
            elif i == candidate:
                h = real
                hsource = refs.get("sources", {}).get("height", refs.get("source"))
                reason = "landmark height assigned to the strongest mapped tower or roof candidate"
            elif (twin := _level_from_twin(i, prepared)) == "duplicate":
                continue
            elif twin:
                lo, h, twin_id = twin
                reason = twin_reason = f"level shared by the same-plan parts of its twins, such as {twin_id}"
            else:
                h = max(median, lo + 4)
                reason = "median known part height, raised above min_height when necessary"
        if h is None or h <= lo:
            continue
        roof = str(t.get("roof:shape", "flat")).lower().replace("_", "-")
        rh = length(t.get("roof:height"))
        rreason = None
        if rh is None:
            rl = _levels(t.get("roof:levels"))
            if rl:
                rh, rreason = rl * 4, "roof:levels multiplied by 4 metres per level"
            elif roof != "flat" and any(
                other is not part and other_h is not None and abs(other_lo - h) <= .05
                and other_h > other_lo + 1 and other_cs.area() >= 4
                and (cs ^ other_cs).area() >= other_cs.area() * .5
                for other, other_cs, other_h, other_lo in prepared
            ):
                rh, rreason = 0, "mapped upper tier begins on this roof, kept a flat landing"
            elif roof != "flat":
                x0, y0, x1, y1 = cs.bounds()
                rh = min((h - lo) * .5, min(x1 - x0, y1 - y0) * .55)
                rreason = "non-flat roof estimated from mapped width and available height"
            else:
                rh = 0
        if rh > h - lo:
            rh = h - lo
            rreason = "roof height limited to the mapped part's total vertical span"
        raw_lo = length(t.get("min_height"))
        loreason = twin_reason or ("building:min_level multiplied by 4 metres" if raw_lo is None and lo else None)
        rec = {"id": part.get("id"), "type": part.get("type", "way"),
               "height": _fact(h, hsource, reason is not None, reason),
               "min_height": _fact(lo, source, loreason is not None, loreason or ("ground datum" if raw_lo is None else None)),
               "roof_height": _fact(rh, source, rreason is not None, rreason or ("flat roof" if not rh else None)),
               "roof_shape": roof, "spire": bool(roof in ("pyramidal", "onion") and rh > math.sqrt(cs.area())),
               "source": source, "tags": dict(t), "footprint": part.get("footprint", [])}
        records.append(rec)
        sections.append(cs)
    return records, sections


_COMPASS = {point: i * 22.5 for i, point in enumerate(
    "n nne ne ene e ese se sse s ssw sw wsw w wnw nw nnw".split())}


def bearing(tags):
    """OSM's roof:direction in degrees: the way the roof face looks and a skillion roof descends. None if absent."""
    value = str(tags.get("roof:direction", "")).strip().lower()
    try:
        degrees = _COMPASS[value] if value in _COMPASS else float(value)
    except ValueError:
        return None
    return degrees if math.isfinite(degrees) else None


def _frame(cs, tags):
    """Long roof ridge axis in east/north coordinates, then its projected extent."""
    import trimesh
    points = np.concatenate(cs.to_polygons())
    T, ext = trimesh.bounds.oriented_bounds_2D(points)
    u = T[:2, :2][int(ext[1] > ext[0])].copy()
    a = bearing(tags)
    if a is not None:
        slope = np.array([math.sin(math.radians(a)), math.cos(math.radians(a))])
        u = np.array([slope[1], -slope[0]])
    elif tags.get("roof:orientation") == "across":
        u = np.array([-u[1], u[0]])
    v = np.array([-u[1], u[0]])
    R = np.array([u, v])
    pp = points @ R.T
    centre = (pp.min(0) + pp.max(0)) / 2
    return R, centre, np.ptp(pp, axis=0)


def _profile_prism(profile, run, R, centre, perpendicular=False):
    """A closed cross-slope profile extruded along the ridge, then placed in XY."""
    import manifold3d as m3
    solid = _section([profile]).extrude(float(run + .04)).translate([0, 0, -run / 2 - .02])
    # profile x -> v, profile y -> z, extrusion -> u
    A = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float)
    if perpendicular:
        A = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], float)
        # Reflection needs a sign change to remain a proper rotation.
        A[1, 2] = -1
    Q = np.eye(3)
    Q[:2, :2] = R.T
    xy = R.T @ centre
    return solid.transform(np.c_[Q @ A, [*xy, 0]].tolist())


def _inradius(cs, centre):
    """Radius of a circle about the chosen loft centre contained by its boundary."""
    p = np.concatenate(cs.to_polygons())
    d = []
    for ring in cs.to_polygons():
        a = np.asarray(ring)
        b = np.roll(a, -1, axis=0)
        ab = b - a
        t = np.clip(np.sum((centre - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0, 1)
        d.extend(np.linalg.norm(a + ab * t[:, None] - centre, axis=1))
    return min(d) if len(p) else 0


def _loft(cs, z0, height, profile, notes):
    """Piecewise scaled sections keep curved roofs closed, including their caps."""
    x0, y0, x1, y1 = cs.bounds()
    centre = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    local = cs.translate((-centre).tolist())
    radius = _inradius(cs, centre)
    span = max(x1 - x0, y1 - y0)
    slender = span > 3 and radius < span * .15
    if radius < .8 and not slender:
        cs = cs.offset(.8 - radius + .01)
        local = cs.translate((-centre).tolist())
        radius = _inradius(cs, centre)
        notes.append("Widened a narrow roof footprint to retain a 1.6 mm tip without changing its height.")
    circumradius = max(np.linalg.norm(point - centre) for ring in cs.to_polygons() for point in ring)
    minimum = min(1, .8 / max(circumradius if slender else radius, .001))
    bands = []
    for (a, sa), (b, sb) in zip(profile[:-1], profile[1:]):
        sa, sb = max(minimum, sa), max(minimum, sb)
        band = local.scale([sa, sa]).extrude(height * (b - a) + .002, scale_top=[sb / sa, sb / sa])
        bands.append(band.translate([*centre, z0 + a * height - .001]))
    if slender:
        import manifold3d as m3
        core = m3.CrossSection.circle(.8 / math.cos(math.pi / 16) + .01, 16).translate(centre.tolist())
        if not (core ^ cs).is_empty():
            core_height = min(height, 3.0)
            bands.append(core.extrude(core_height).translate([0, 0, z0 + height - core_height]))
        notes.append("Tapered a narrow mapped roof outline toward a reinforced 1.6 mm tip without shortening it.")
    return _union(bands)


def _roof(cs, record, z0, height, notes, mughal=False):
    import manifold3d as m3
    shape = record["roof_shape"]
    if record.get("spire_rib"):
        shape = "pyramidal"
        notes.append("Tapered a narrow gabled spire rib to match its overlapping mapped spire.")
    if height <= .01 or shape == "flat":
        return cs.extrude(max(height, .01)).translate([0, 0, z0])
    if shape == "dome" and record.get("cupola_seat"):
        from .landmark_massing import ribbed_cupola

        return ribbed_cupola(cs, z0, height, record["cupola_seat"], notes)
    if shape in ("pyramidal", "cone", "dome", "onion"):
        if shape == "dome" and mughal:
            shape = "onion"
            notes.append("Used a bulb profile for an OSM dome in Mughal style, keeping the mapped height.")
        if shape in ("pyramidal", "cone"):
            profile = [(0, 1), (1, 0)]
            if record.get("spire_tracery"):
                return _traceried_spire(cs, z0, height, notes)
            if record.get("pinnacle_profile"):
                profile = [(0, 1), (.10, 1.04), (.24, .87), (.42, .77), (.66, .62), (.87, .37), (1, 0)]
            if record.get("finial"):
                profile = [(0, .8), (.13, .53), (.24, .72), (.35, .45), (.51, .59), (.68, .28), (1, 0)]
            profile = record.get("roof_profile", profile)
        elif shape == "dome":
            # A short lower skirt is visible on a broad cupola.
            profile = [(0, 1), (.10, 1)] + [(float(t), math.sqrt(max(0, 1 - ((t - .1) / .9) ** 2))) for t in np.linspace(.2, 1, 13)]
        else:
            profile = record.get("onion_profile") or [(0, .82), (.13, 1), (.32, 1.08), (.50, 1), (.70, .70), (.86, .31), (1, 0)]
            # Outward bands cannot grow faster than 45 degrees at print scale.
            radius = max(cs.bounds()[2] - cs.bounds()[0], cs.bounds()[3] - cs.bounds()[1]) / 2
            profile = [(t, min(s, profile[0][1] + height * t / max(radius, .01))) for t, s in profile]
        return _loft(cs, z0, height, profile, notes)
    R, centre, (run, width) = _frame(cs, record["tags"])
    w = width / 2 + .01
    tip = min(.8, w * .8)
    if shape == "skillion":
        # v points along roof:direction, so the roof is high behind it and descends toward it.
        high, low = (-w, w) if bearing(record["tags"]) is not None else (w, -w)
        profile = [(-w, z0 - .01), (w, z0 - .01), *sorted([(high, z0 + height), (low, z0)], reverse=True)]
    elif shape == "round":
        arc = [(float(w * math.cos(a)), z0 + height * math.sin(a)) for a in np.linspace(0, math.pi, 25)]
        profile = [(-w, z0 - .01), (w, z0 - .01), *arc]
    elif shape == "gambrel":
        profile = [(-w, z0 - .01), (w, z0 - .01), (w, z0), (.60 * w, z0 + .70 * height),
                   (tip, z0 + height), (-tip, z0 + height), (-.60 * w, z0 + .70 * height), (-w, z0)]
    elif shape == "mansard":
        profile = [(-w, z0 - .01), (w, z0 - .01), (w, z0), (.65 * w, z0 + .82 * height),
                   (tip, z0 + height), (-tip, z0 + height), (-.65 * w, z0 + .82 * height), (-w, z0)]
    else:
        if shape not in ("gabled", "hipped", "half-hipped", "half-hip"):
            notes.append(f"Unknown roof shape {shape!r}: used a conservative gable within its measured height.")
        profile = [(-w, z0 - .01), (w, z0 - .01), (w, z0), (tip, z0 + height), (-tip, z0 + height), (-w, z0)]
    roof = _profile_prism(profile, run, R, centre)
    if shape in ("hipped", "half-hipped", "half-hip", "mansard"):
        u = run / 2 + .01
        rise = .55 if shape.startswith("half") else 1
        top_run = max(tip, u - width / 2 * rise)
        end_profile = [(-u, z0 - .01), (u, z0 - .01), (u, z0 + height * (1 - rise)),
                       (top_run, z0 + height), (-top_run, z0 + height), (-u, z0 + height * (1 - rise))]
        roof = roof ^ _profile_prism(end_profile, width, R, centre, True)
    return roof ^ cs.extrude(height + .04).translate([0, 0, z0 - .02])


def _traceried_spire(cs, z, height, notes):
    """An octagonal stone spire with Gothic gables and ribs in printable relief."""
    import manifold3d as m3

    x, y, xx, yy = cs.bounds()
    centre = np.array([(x + xx) / 2, (y + yy) / 2])
    span = min(xx - x, yy - y)
    octagon = m3.CrossSection.circle(span * .49, 8).translate(centre.tolist())
    profile = [(0, 1), (.13, .86), (.48, .56), (.77, .27), (1, 0)]
    spire = _loft(octagon, z, height, profile, notes)
    ribs = []
    for vertex in octagon.to_polygons()[0]:
        vector = np.asarray(vertex) - centre
        reach = np.linalg.norm(vector)
        radial = vector / reach
        across = np.array([-radial[1], radial[0]])
        # Stay inside the tower outline while lifting the gable ridges from
        # the tapered core. Their valley overlaps the core from toe to tip.
        points = [(reach * .85, 0), (reach * 1.08, 0), (reach * .83, height * .32),
                  (reach * .61, height * .55), (reach * .23, height * .86), (reach * .14, height * .86),
                  (reach * .32, height * .45)]
        rib = _section([points]).extrude(max(1.2, span * .065)).translate([0, 0, -max(.6, span * .0325)])
        A = [[radial[0], 0., across[0], centre[0]], [radial[1], 0., across[1], centre[1]],
             [0., 1., 0., z - .12]]
        ribs.append(rib.transform(A))
    return _union([spire, *ribs])


def _target(size, bed):
    t = dict(size) if isinstance(size, dict) else {
        "mode": "max", "mm": float(size) if size is not None else min(200, *map(float, bed)),
        "bed": list(map(float, bed)), "said": "landmark size", "bed_said": None}
    t.setdefault("bed", list(map(float, bed)))
    if t.get("mode") not in ("max", "z", "long", "fit"):
        raise LandmarkProblem("unsupported size mode; use max, z, long or fit.")
    if len(t["bed"]) != 3 or any(not math.isfinite(float(v)) or float(v) <= 2 for v in t["bed"]):
        raise LandmarkProblem("printer bed dimensions must be greater than 2 mm.")
    if t["mode"] != "fit" and (not t.get("mm") or not math.isfinite(float(t["mm"])) or float(t["mm"]) <= 2):
        raise LandmarkProblem("landmark size must be greater than 2 mm.")
    return t


def _scale(sections, records, target, reach=0.):
    """Millimetres per metre; `reach` is fixed-size detail standing past one end of the long axis."""
    import trimesh
    points = np.concatenate([np.concatenate(cs.to_polygons()) for cs in sections])
    _, ext = trimesh.bounds.oriented_bounds_2D(points)
    high = max(p["height"]["metres"] for p in records)
    mode = target["mode"]
    if mode == "fit":
        # 0.98 matches the shared fitting allowance, including the plinth.
        bx, by = sorted(target["bed"][:2])
        ex, ey = sorted(ext)
        return min((bx * .98 - .04) / ex, (by * .98 - .04 - reach) / ey, (target["bed"][2] * .98 - 2) / high)
    mm = float(target["mm"])
    if mode == "z":
        return (mm - 2) / high
    if mode == "long":
        return (mm - .04 - reach) / max(ext)
    return min((mm - .04 - reach) / max(ext), (mm - 2) / high)


def _anchor(man, notes):
    """Join floating mapped levels only where a real lower surface overlaps."""
    import manifold3d as m3
    from .clean import SLIVER

    components = man.decompose()
    pieces = [piece for piece in components if not piece.is_empty() and piece.volume() >= SLIVER]
    removed = len(components) - len(pieces)
    if removed:
        notes.append(f"Removed {removed} disconnected slivers below {SLIVER:g} mm3.")
    if not pieces:
        raise LandmarkProblem("mapped geometry contains no printable solids; review refs/landmark.json.")
    pieces.sort(key=lambda c: c.bounding_box()[2])
    base = pieces[0]
    for piece in pieces[1:]:
        box = piece.bounding_box()
        bottom, height = box[2], box[5] - box[2]
        if not all(math.isfinite(v) for v in box) or height <= 0:
            raise LandmarkProblem("a mapped part has invalid bounds; review refs/landmark.json.")
        if bottom <= 2.02:
            base = _union([base, piece])
            continue
        foot = None
        for fraction in (.01, .05, .15, .35, .5):
            section = piece.slice(bottom + height * fraction)
            if not section.is_empty() and section.area() > 1e-8:
                foot = section
                break
        if foot is None:
            raise LandmarkProblem("an elevated mapped part has no usable bottom section; review refs/landmark.json.")
        landing, room = None, None
        for z in np.arange(bottom - .04, .5, -.5):
            overlap = foot ^ base.slice(float(z))
            if not overlap.is_empty() and overlap.area() > .2:
                landing, room = float(z), overlap
                break
        if room is None:
            raise LandmarkProblem("an elevated mapped part has no printable landing; review refs/landmark.json.")
        found = None
        contours = (c for c in room.decompose() if not c.is_empty() and c.area() > 1e-8)
        for c in sorted(contours, key=lambda c: -c.area()):
            bounds = c.bounds()
            if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
                continue
            x0, y0, x1, y1 = bounds
            if x1 <= x0 or y1 <= y0:
                continue
            for x in np.linspace(x0, x1, 9):
                for y in np.linspace(y0, y1, 9):
                    post = m3.CrossSection.circle(.8, 16).translate([float(x), float(y)])
                    intersection = post ^ c
                    area = intersection.area() if not intersection.is_empty() else 0
                    if area > 1 and (found is None or area > found[0]):
                        found = (area, post)
        if found is None:
            raise LandmarkProblem("an elevated mapped part has no printable landing wide enough for a support; review refs/landmark.json.")
        post = found[1].extrude(bottom - landing + .12).translate([0, 0, landing - .06])
        base = _union([base, piece, post])
        notes.append(f"Added a 1.6 mm vertical print support across a {bottom - landing:.2f} mm mapped level gap at an overlapping landing.")
    return base


def generate(name: str, job_root: Path, bed, size=None, detail=None, *, ref_pack=None):
    """Build sourced geometry, preserving references and handing scale to modelprint."""
    import manifold3d as m3
    from . import clean, landmark_architecture, landmark_refs, modelprint
    from .landmark_style import style_keys

    root = Path(job_root)
    rd = root / "refs"
    rd.mkdir(parents=True, exist_ok=True)
    refs = landmark_refs.resolve(name, root)
    refs["requested_name"] = name
    pack = landmark_refs.load_pack(name, ref_pack, label=refs.get("label"))
    refs["reference_pack"] = pack
    refs["feature_sources"] = sorted({entry["source"] for entry in pack.values()})
    if refs.get("wikipedia_url"):
        refs["feature_sources"].append(refs["wikipedia_url"])
    for key in ("osm_way", "osm_relation"):
        if key in pack:
            refs[key] = pack[key]["value"]
            refs["sources"][key] = pack[key]["source"]
    refs["wikidata_height_m"] = (refs["height"] if "wikidata.org/" in refs.get("sources", {}).get("height", "")
                                 else None)
    height = pack.get("expected_height_m", {})
    if height.get("value") and height["value"] != refs["height"]:
        if "wikidata.org/" in height["source"]:
            refs["wikidata_height_m"] = height["value"]
        elif refs["wikidata_height_m"] is not None:
            refs["wikidata_height_claim_m"] = refs["wikidata_height_m"]
            refs["wikidata_height_m"] = None
        refs["height"] = height["value"]
        refs["sources"]["height"] = height["source"]
    styles = refs.get("style", []) + pack.get("styles", {}).get("value", [])
    keys = style_keys(styles)
    refpath = rd / "landmark.json"

    def save():
        refpath.write_text(json.dumps(refs, indent=2, ensure_ascii=False) + "\n")

    save()
    data = landmark_refs.fetch(refs, root)
    refs.update(geometry_source=data.get("source"), outline=data.get("outline", []),
                mapped_parts=data.get("parts", []))
    save()
    outline = _section(data.get("outline", []))
    if not outline.is_empty():
        _, _, spans = _frame(outline, {})
        width, length_ = sorted(spans)
        refs["reference_dimensions_m"] = {"length": float(length_), "width": float(width), "source": data["source"]}
    records, sections = resolve_parts(data.get("parts", []), refs)
    refs["parts"] = records
    refs["parts_schema"] = {"id": "OSM or generated identifier", "type": "way, relation or reference", "height": "{metres, source, guessed, reason?}",
                            "min_height": "{metres, source, guessed, reason?}", "roof_height": "{metres, source, guessed, reason?}",
                            "roof_shape": "normalized OSM roof:shape", "spire": "boolean", "source": "reference URL",
                            "feature": "modeled architectural feature, when identified",
                            "tags": "all source tags", "footprint": "outer ring then holes, local east/north metres"}
    save()
    measured = [cs for p, cs in zip(records, sections) if not p["height"]["guessed"] or "building:levels" in p["tags"]]
    mapped = m3.CrossSection.batch_boolean(sections, m3.OpType.Add)
    sourced = m3.CrossSection.batch_boolean(measured, m3.OpType.Add)
    coverage = (sourced ^ outline).area() / outline.area() if outline.area() > 0 else sourced.area() / max(mapped.area(), .001)
    refs.update(height_source_coverage=coverage, height_source_parts=len(measured))
    save()
    if not measured or (len(measured) / len(records) < .35 and coverage < .45):
        raise LandmarkProblem("insufficient mapped 3D parts with heights across the landmark footprint. Use stone models " + json.dumps(name) + ".")
    towers, tower_sections = resolve_parts(data.get("linked_towers", []), refs)
    towers = [(p, cs) for p, cs in zip(towers, tower_sections) if not p["height"]["guessed"]]
    if towers:
        association = f"{refs['source']}#P527"
        refs["feature_sources"].append(association)
        for p, cs in towers:
            p.update(feature="bell_tower", association_source=association)
            records.append(p)
            sections.append(cs)
        surveyed_plan = m3.CrossSection.batch_boolean([outline, *(cs for _, cs in towers)], m3.OpType.Add)
        _, _, spans = _frame(surveyed_plan, {})
        width, length_ = sorted(spans)
        # The building's own outline stays the reference. This is the plan built here, towers included.
        refs["plan_dimensions_m"] = {"length": float(length_), "width": float(width),
                                     "associated_outlines": [p["source"] for p, _ in towers]}
    mapped_height = max([length(data.get("tags", {}).get("height")) or 0] +
                        [p["height"]["metres"] for p in records if not p["height"]["guessed"]])
    target = _target(size, bed)
    changes = []
    westward = None
    # A pack we ship covers the massing. Facts someone adds for another building do not switch it off.
    if not landmark_refs.load_pack(name, label=refs.get("label")) and not outline.is_empty():
        from .landmark_massing import infer_massing

        records, sections, westward, changes = infer_massing(records, sections, outline, data, refs, target, keys)
    records, sections, corrections = landmark_architecture.reconcile(records, sections, refs, pack, keys)
    changes.extend(corrections)
    if refs.get("height") and abs(mapped_height / refs["height"] - 1) > .03:
        recorded = max(p["height"]["metres"] for p in records)
        reason = ("The sourced top includes a style-appropriate finial above the mapped peak."
                  if any(p.get("finial") for p in records) and recorded > mapped_height
                  else "The mapped parts are retained because there is no sourced tip correction for the mapped peak.")
        refs["height_comparison"] = {"mapped_m": mapped_height, "reference_m": refs["height"],
                                     "chosen_m": recorded, "source": refs["sources"]["height"], "reason": reason}
    if "wikidata_height_claim_m" in refs:
        refs["height_comparison"] = {"mapped_m": mapped_height, "reference_m": refs["height"],
                                     "wikidata_m": refs["wikidata_height_claim_m"],
                                     "chosen_m": max(p["height"]["metres"] for p in records),
                                     "source": refs["sources"]["height"],
                                     "reason": height.get("reason", "The sourced height describes the complete landmark.")}
    is_lattice = "steel" in keys and all(fact in pack for fact in (
        "deck_widths_m", "deck_heights_m", "foot_width_m", "arch_height_m", "historic_top_m"))
    chosen = detail or ("high" if len(records) < 400 else "low")
    if chosen not in ("low", "high"):
        raise LandmarkProblem("detail must be low or high.")
    reach = 0.
    if chosen == "high" and "gothic" in keys and {"west_facade_profile", "west_buttress_spires"} <= pack.keys():
        from .landmark_style import WEST_PIER_REACH as reach
    scale = _scale([outline] if is_lattice and not outline.is_empty() else sections, records, target, reach)
    notes = ["Dimensions use local east/north metres, uniformly scaled to millimetres.",
             "Added a 2 mm convex footprint plinth to join detached ground parts.",
             "Mapped faces overlap by 0.01 metre at wall and roof joins; coordinates are otherwise unsnapped.",
             "Roof tips retain at least 1.6 mm across their loft centre; narrow walls are widened to 1.2 mm."]
    notes.extend(changes)
    solids, mm_sections = [], []
    mughal = "mughal" in keys
    for p, original in (() if is_lattice else zip(records, sections)):
        if p["roof_shape"] == "gabled":
            x0, y0, x1, y1 = original.bounds()
            width, span = sorted((x1 - x0, y1 - y0))
            if width > 0 and span >= width * 3 and p["roof_height"]["metres"] >= width * 2:
                p["spire_rib"] = any(
                    q["roof_shape"] == "pyramidal"
                    and abs(q["height"]["metres"] - p["height"]["metres"]) <= 3
                    and abs(q["roof_height"]["metres"] - p["roof_height"]["metres"]) <= 3
                    and (original ^ other).area() >= original.area() * .3
                    for q, other in zip(records, sections)
                )
        cs = original.scale([scale, scale])
        comps = []
        for c in cs.decompose():
            if c.offset(-.6).is_empty():
                # Preserve small mapped bodies by expanding, never replacing their plan.
                a, b = 0., .6
                for _ in range(12):
                    mid = (a + b) / 2
                    if c.offset(mid).offset(-.6).is_empty():
                        a = mid
                    else:
                        b = mid
                c = c.offset(b + .01)
                p.setdefault("print_modifications", []).append("Widened narrow mapped footprint to 1.2 mm.")
            comps.append(c)
        cs = m3.CrossSection.batch_boolean(comps, m3.OpType.Add)
        mm_sections.append(cs)
        lo = 2 + p["min_height"]["metres"] * scale
        top = 2 + p["height"]["metres"] * scale
        rh = p["roof_height"]["metres"] * scale
        eave = max(lo, top - rh)
        if p.get("flying_buttress"):
            from .landmark_gothic import flying_buttress

            solids.extend(flying_buttress(cs, p, lo, eave, top, notes))
            continue
        overlap = .01 * scale
        walls = cs.offset(overlap).extrude(max(.02, eave - lo + overlap)).translate([0, 0, lo - overlap])
        roof = _roof(cs, p, eave - .005, min(rh + .005, top - eave + .005), notes, mughal)
        if p.get("chhatri_columns"):
            from .landmark_style import chhatri

            solids.extend(chhatri(cs, eave, p["chhatri_columns"] * scale))
            continue
        solids.extend([walls, roof])
    if is_lattice:
        solids.append(landmark_architecture.lattice(outline, scale, refs, pack, notes))
        footprint = outline.scale([scale, scale])
        notes.append("Built four open cross-braced legs and arches with the documented platform heights and an antenna up to the current sourced top.")
    else:
        footprint = m3.CrossSection.batch_boolean(mm_sections, m3.OpType.Add)
    if towers or pack.get("aisle_wall_datum_m") or pack.get("plinth_follows_plan", {}).get("value"):
        from .landmark_massing import linked_plinth

        base = linked_plinth(footprint.offset(.02))
        notes[1] = "Added a 2 mm plinth following the mapped plan, with short joiners where needed."
        if towers:
            notes.append("Included measured bell towers explicitly listed as part of the landmark in Wikidata.")
    else:
        base = footprint.hull().offset(.02)
    solids.append(base.extrude(2.02))
    man = _union(solids)
    man = _anchor(man, notes)
    if chosen == "high" and not is_lattice:
        from .landmark_style import decorate
        man, additions = decorate(man, records, mm_sections, scale, styles, pack, outline.scale([scale, scale]),
                                  westward=westward)
        notes.extend(additions)
    if man.status() != m3.Error.NoError:
        raise LandmarkProblem(f"mapped geometry could not form a closed solid ({man.status().name}).")
    raw_mesh = modelprint.to_trimesh(man)
    try:
        mesh = clean.for_slicer(raw_mesh)
    except ValueError:
        # Quantize Boolean intersections that landed on opposite sides of a
        # float32 boundary. The 0.00001 mm grid stays far below print detail.
        raw_mesh.vertices = np.round(raw_mesh.vertices, decimals=5)
        mesh = clean.for_slicer(raw_mesh)
        notes.append("Snapped sub-micron intersections before rechecking the mesh for the slicer.")
    if len(modelprint.to_manifold(mesh).decompose()) != 1:
        raise LandmarkProblem("mapped parts remain disconnected after print support repair; review refs/landmark.json.")
    mesh.apply_translation([0, 0, -mesh.bounds[0, 2]])
    md = root / "model"
    md.mkdir(parents=True, exist_ok=True)
    stl = md / "generated.stl"
    mesh.export(stl)
    refs.update(parts=records, target=target, scale_mm_per_metre=scale, detail=chosen,
                modeling_additions=list(dict.fromkeys(notes)), size_mm=mesh.extents.tolist(), plinth_height_mm=2)
    save()
    credits = "© OpenStreetMap contributors. Building geometry: ODbL 1.0, https://www.openstreetmap.org/copyright\n"
    urls = {refs["source"], refs["geometry_source"], *refs["sources"].values(),
            *refs["feature_sources"], *(p["source"] for p in records)}
    credits += "\n".join(sorted(url for url in urls if url)) + "\n"
    credits_path = md / "credits.txt"
    credits_path.write_text(credits)
    omitted = [note for note in notes if note.startswith("Omitted detail below the print floor")]
    lines = [f"Built {len(records)} modeled 3D parts with {chosen} detail.",
             "© OpenStreetMap contributors, ODbL 1.0.", f"References and modeling notes: {refpath}"]
    if omitted:
        lines.append("Omitted architectural detail below the print floor. See the modeling notes for each feature.")
    return {"stl": str(stl), "subject": refs.get("label", name), "name": refs.get("label", name),
            "author": "OpenStreetMap contributors", "license": "Open Database License 1.0", "license_code": "ODbL-1.0",
            "source": "landmark", "url": refs.get("wikipedia_url") or refs.get("source"), "id": refs.get("id"),
            "credits": str(credits_path), "target": target, "scale": scale, "refs": str(refpath),
            "lines": lines}
