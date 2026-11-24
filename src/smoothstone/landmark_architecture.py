"""Apply sourced architectural measurements to incomplete OSM building parts."""
from __future__ import annotations

import math

import numpy as np


def _dimensions(cs):
    x, y, xx, yy = cs.bounds()
    return np.array([(x + xx) / 2, (y + yy) / 2]), max(xx - x, yy - y)


def _measurement(metres, source, reason):
    return {"metres": float(metres), "source": source, "guessed": False, "reason": reason}


def _new_part(identifier, cs, lo, top, roof, shape, source, feature):
    from .landmark import _fact

    return {"id": identifier, "type": "reference", "height": _fact(top, source),
            "min_height": _fact(lo, source), "roof_height": _fact(roof, source),
            "roof_shape": shape, "spire": shape == "pyramidal", "feature": feature,
            "source": source, "tags": {}, "footprint": [p.tolist() for p in cs.to_polygons()]}


def reconcile(records, sections, refs, facts, styles):
    """Identify structural features, replace only conflicting or missing detail."""
    parts = list(zip(records, sections))
    notes = []
    if "gothic" in styles:
        twin_heights = facts.get("west_spire_heights_m", {}).get("value")
        if twin_heights:
            parts = _matched_spires(parts, twin_heights, facts, notes)
        if "spire_height_m" in facts and "west_tower_m" in facts:
            parts = _flat_west_towers(parts, facts, notes)
        rise = facts.get("spire_rise_m")
        summit = max((p["height"]["metres"] for p, _ in parts), default=0.)
        for p, cs in parts:
            if p["spire"] and p.get("feature") is None and _dimensions(cs)[1] < 5:
                p["feature"] = "pinnacle"
                if rise and .27 * summit < p["height"]["metres"] < .73 * summit:
                    measured = p["roof_height"]["metres"]
                    if measured < rise["value"]:
                        delta = rise["value"] - measured
                        p["height"] = _measurement(p["height"]["metres"] + delta, rise["source"],
                                                   "Typical pinnacle rise above the mapped shaft.")
                        p["roof_height"] = _measurement(rise["value"], rise["source"],
                                                         "Typical rise measured from the terrace.")
                    p["pinnacle_profile"] = True
    if "mughal" in styles:
        parts = _mughal(parts, refs, facts, notes)
    if "baroque" in styles:
        domes = [(p, cs) for p, cs in parts if p["roof_shape"] == "dome"]
        if domes:
            max(domes, key=lambda pair: pair[1].area())[0]["feature"] = "main_dome"
        tower_height = facts.get("west_tower_m", {}).get("value")
        if tower_height:
            eligible = [(p, cs) for p, cs in parts
                        if abs(p["height"]["metres"] - tower_height) <= 2 and _dimensions(cs)[1] < 10]
            for p, cs in sorted(eligible, key=lambda pair: _dimensions(pair[1])[0][0])[:2]:
                p["feature"] = "west_tower"
    if not parts:
        return [], [], notes
    records, sections = map(list, zip(*parts))
    return records, sections, notes


def _matched_spires(parts, heights, facts, notes):
    # The full-width mapped roofs locate the two towers. The small polygons
    # near their tips are overlapping decorations from one tower's denser map.
    candidates = [(p, cs) for p, cs in parts if p["spire"] and p["height"]["metres"] > min(heights) * .88]
    if len(candidates) < 2:
        return parts
    seed = max(candidates, key=lambda pair: pair[1].area())
    centre, span = _dimensions(seed[1])
    other = [pair for pair in candidates if np.linalg.norm(_dimensions(pair[1])[0] - centre) > span]
    if not other:
        return parts
    pair = sorted([seed, max(other, key=lambda entry: entry[1].area())], key=lambda entry: _dimensions(entry[1])[0][1])
    centres = [_dimensions(cs)[0] for _, cs in pair]
    out = [(p, cs) for p, cs in parts if not (
        p["height"]["metres"] > min(heights) * .89
        and any(np.linalg.norm(_dimensions(cs)[0] - c) < span * .55 for c in centres)
    )]
    shape = seed[1].hull()
    template_centre = _dimensions(shape)[0]
    for (p, _), c, top in zip(pair, centres, heights):
        roof = min(entry[0]["roof_height"]["metres"] for entry in pair)
        foot = min(entry[0]["min_height"]["metres"] for entry in pair) - .08
        cs = shape.translate((c - template_centre).tolist())
        record = _new_part(p["id"], cs, foot, top, roof, "pyramidal",
                           facts["west_spire_heights_m"]["source"], "west_spire")
        record["spire_tracery"] = facts.get("spire_tracery", {}).get("value", True)
        out.append((record, cs))
    notes.append("Matched west spires share one shaft and tracery profile. The two mapped centres and sourced individual heights are retained.")
    return out


def _flat_west_towers(parts, facts, notes):
    height = facts["west_tower_m"]["value"]
    towers = [(p, cs) for p, cs in parts if p["tags"].get("man_made") == "tower"
              and abs(p["height"]["metres"] - height) < 2 and p["roof_shape"] == "flat"]
    if len(towers) != 2:
        return parts
    for p, _ in towers:
        p["feature"] = "west_tower"
    keep = [(p, cs) for p, cs in parts if not (
        p["min_height"]["metres"] >= height - .1 and p["roof_shape"] == "pyramidal"
        and any((cs ^ tower).area() >= cs.area() * .8 for _, tower in towers)
    )]
    if len(keep) < len(parts):
        notes.append("Kept the two west bell towers at their sourced flat parapets and omitted conflicting mapped pyramids above them.")
    return keep


def _mughal(parts, refs, facts, notes):
    import manifold3d as m3

    domes = [(p, cs) for p, cs in parts if p["roof_shape"] in ("dome", "onion")]
    if not domes:
        return parts
    dome, circle = max(domes, key=lambda pair: pair[1].area())
    dome["feature"] = "main_dome"
    centre, span = _dimensions(circle)
    drum_fact = facts.get("dome_drum_m")
    canopy_fact = facts.get("chhatri_canopy_m")
    dome["onion_profile"] = facts.get("dome_profile", {}).get("value")
    out = []
    drum_top = dome["height"]["metres"] - dome["roof_height"]["metres"]
    mapped_top = max(p["height"]["metres"] for p, _ in parts)
    source = refs["sources"].get("height", refs["source"])
    real_height = refs.get("height") or mapped_top
    finials = [(p, cs) for p, cs in parts if p["spire"] and p["height"]["metres"] >= mapped_top - .1
               and np.linalg.norm(_dimensions(cs)[0] - centre) < span * .15]
    if finials and real_height > mapped_top * 1.03:
        finial, _ = finials[0]
        base = mapped_top - finial["roof_height"]["metres"]
        finial["height"] = _measurement(real_height, source, "Includes the full sourced finial.")
        finial["roof_height"] = _measurement(real_height - base,
                                              source, "Extended the finial alone to the sourced top.")
        finial["min_height"]["metres"] = base - .5
        finial["feature"] = "finial"
        finial["finial"] = True
    roof_fact = facts.get("dome_roof_m")
    if roof_fact:
        roof = roof_fact["value"]
        dome["roof_height"] = _measurement(roof, roof_fact["source"], "Exterior onion dome rise.")
        dome["height"] = _measurement(drum_top + roof, roof_fact["source"], "Onion dome above the mapped drum.")
        for finial, _ in finials:
            tip = finial["height"]["metres"]
            base = min(tip - 1, drum_top + roof - .4)
            finial["min_height"]["metres"] = base
            finial["roof_height"]["metres"] = tip - base + .02
    for p, cs in parts:
        c, width = _dimensions(cs)
        top = p["height"]["metres"]
        offset = np.linalg.norm(c - centre)
        if p is not dome and any(p is cap for cap, _ in domes) and offset > span:
            p["feature"] = "minaret"
        if (canopy_fact and p["roof_shape"] == "flat" and drum_top * .8 < top < drum_top * .92
                and .5 * span < offset < span and span * .2 < width < span * .39):
            rise = canopy_fact["value"]
            canopy = m3.CrossSection.circle(width * .46, 32).translate(c.tolist())
            columns = facts.get("chhatri_column_m", {}).get("value", 5.5)
            p["chhatri_columns"] = columns
            record = _new_part(f"{p['id']}-canopy-{len(out)}", canopy, top - .05, top + rise, rise,
                               "onion", canopy_fact["source"], "chhatri")
            out.append((record, canopy))
            finial_fact = facts.get("chhatri_finial_m")
            if finial_fact:
                finial = m3.CrossSection.circle(width * .095, 16).translate(c.tolist())
                h = finial_fact["value"]
                record = _new_part(f"{p['id']}-finial-{len(out)}", finial, top + rise - .35,
                                   top + rise + h, h + .32, "pyramidal", finial_fact["source"], "finial")
                out.append((record, finial))
        if drum_fact and top == drum_top and p is not dome and width > span and offset < span * .1:
            p["dome_drum_m"] = drum_fact["value"]
        if p["roof_shape"] == "flat" and .9 * span < width < 2.2 * span and offset < span * .15 and top < drum_top:
            p["main_faces"] = True
        out.append((p, cs))
    notes.append("Modeled the main onion dome above the measured drum, a tip at the sourced finial height, and four raised dome canopies on the mapped corner pavilions.")
    return out


def lattice(outline, scale, refs, facts):
    """Four battered Eiffel legs, four curved arches, and cross-braced upper stages."""
    import manifold3d as m3

    from .landmark import _frame, _union

    R, centre, spans = _frame(outline, {})
    widths = facts["deck_widths_m"]["value"]
    levels = facts["deck_heights_m"]["value"]
    foot = facts["foot_width_m"]["value"]
    historic = facts["historic_top_m"]["value"]
    top = refs["height"]
    arch = facts["arch_height_m"]["value"]
    # Use OSM's oriented plan for the foundation, then the surveyed stage widths.
    size = min(spans)
    foot_centre = (size - foot) / 2
    origin = R.T @ centre * scale
    pieces = []

    def beam(a, b, width):
        a, b = np.array(a, float), np.array(b, float)
        direction = b - a
        run = np.linalg.norm(direction)
        z = direction / run
        x = np.cross(z, [1, 0, 0] if abs(z[0]) < .85 else [0, 1, 0])
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        solid = m3.Manifold.cube([width, width, run * scale + width * .66], True)
        pos = (a + b) * scale / 2
        pos[:2] += origin
        pos[2] += 2
        pieces.append(solid.transform(np.c_[x, y, z, pos].tolist()))

    def deck(width, z, thickness):
        dims = [width * scale, width * scale, max(1.25, thickness * scale)]
        pieces.append(m3.Manifold.cube(dims, True).translate([*origin, 2 + z * scale]))

    for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        previous = None
        levels_and_widths = [
            (0., foot_centre, foot / 2 - 1),
            (levels[0] * .45, foot_centre * .78, foot * .36),
            (levels[0], widths[0] * .40, widths[0] * .08),
            (levels[1] * .75, widths[1] * .58, widths[1] * .08),
            (levels[1], widths[1] * .43, widths[1] * .07),
        ]
        for z, centre_distance, half in levels_and_widths:
            corners = [(sx * centre_distance + x * half, sy * centre_distance + y * half, z)
                       for x, y in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
            if previous:
                for i in range(4):
                    j = (i + 1) % 4
                    beam(previous[i], corners[i], 1.65)
                    beam(previous[i], corners[j], 1.1)
                    beam(previous[j], corners[i], 1.1)
            for i in range(4):
                beam(corners[i], corners[(i + 1) % 4], 1.1)
            previous = corners
    for axis in (0, 1):
        for side in (-1, 1):
            previous = None
            for j in range(17):
                t = j / 8 - 1
                height = levels[0] * .24 + (arch - levels[0] * .24) * math.sqrt(max(0, 1 - t * t))
                point = [foot_centre * .84 * t, side * (widths[0] * .39 + 6 * t * t), height]
                if axis:
                    point[:2] = reversed(point[:2])
                if previous:
                    beam(previous, point, 1.55)
                previous = point
            for t in (-.75, -.5, -.25, 0, .25, .5, .75):
                x = foot_centre * .84 * t
                y = side * (widths[0] * .39 + 6 * t * t)
                z = levels[0] * .24 + (arch - levels[0] * .24) * math.sqrt(1 - t * t)
                if abs(x) < widths[0] * .48:
                    a, b = [x, y, z], [x, y, levels[0]]
                    if axis:
                        a[:2], b[:2] = reversed(a[:2]), reversed(b[:2])
                    beam(a, b, 1.1)
    previous = None
    for i in range(13):
        t = i / 12
        z = levels[1] + (levels[2] - levels[1]) * t
        width = widths[2] + (widths[1] - widths[2]) * (1 - t) ** 2.25
        q = width * .45
        corners = [(q, q, z), (q, -q, z), (-q, -q, z), (-q, q, z)]
        for j in range(4):
            k = (j + 1) % 4
            beam(corners[j], corners[k], 1.1)
            if previous:
                beam(previous[j], corners[j], 1.5)
                beam(previous[j], corners[k], 1.1)
                beam(previous[k], corners[j], 1.1)
        previous = corners
    for width, level, thickness in zip(widths, levels, (5.5, 4.5, 5.5)):
        deck(width, level, thickness)
    heights = [(levels[2], widths[2]), (levels[2] + 12, widths[2] * .88),
               (300, widths[2] * .62), (historic, max(2.6 / scale, widths[2] * .36)),
               (top, 1.62 / scale)]
    for (lo, low_width), (hi, high_width) in zip(heights, heights[1:]):
        low = max(1.62, low_width * scale)
        ratio = max(1.62, high_width * scale) / low
        box = m3.CrossSection.square([low, low], True)
        pieces.append(box.extrude((hi - lo) * scale + .01, scale_top=[ratio, ratio]).translate([*origin, 2 + lo * scale]))
    # Orient the framework along the surveyed sidewalk and use the mapped base.
    A = np.c_[np.eye(3), np.zeros(3)]
    A[:2, :2] = R.T
    A[:2, 3] = origin - R.T @ origin
    return _union([solid.transform(A.tolist()) for solid in pieces])
