"""Apply sourced architectural measurements to incomplete OSM building parts."""
from __future__ import annotations

import math

import numpy as np


def _dimensions(cs):
    x, y, xx, yy = cs.bounds()
    return np.array([(x + xx) / 2, (y + yy) / 2]), max(xx - x, yy - y)


def _measurement(metres, source, reason):
    return {"metres": float(metres), "source": source, "guessed": False, "reason": reason}


def _moved(old, metres, source, reason):
    """A level raised by a sourced amount. A guess raised is still a guess."""
    return {**_measurement(metres, source, reason), "guessed": old["guessed"]}


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
        from .landmark_gothic import reconcile_gothic

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
                if rise and "spire_plan" not in facts and .27 * summit < p["height"]["metres"] < .73 * summit:
                    measured = p["roof_height"]["metres"]
                    if measured < rise["value"]:
                        delta = rise["value"] - measured
                        p["height"] = _moved(p["height"], p["height"]["metres"] + delta, rise["source"],
                                             "Typical pinnacle rise above the mapped shaft.")
                        p["roof_height"] = _measurement(rise["value"], rise["source"],
                                                         "Typical rise measured from the terrace.")
                    p["pinnacle_profile"] = True
        parts = reconcile_gothic(parts, refs, facts, notes)
    if "mughal" in styles:
        parts = _mughal(parts, refs, facts, notes)
    if "baroque" in styles:
        parts = _baroque(parts, facts, notes)
    if not parts:
        return [], [], notes
    records, sections = map(list, zip(*parts))
    return records, sections, notes


def _baroque(parts, facts, notes):
    domes = [(p, cs) for p, cs in parts if p["roof_shape"] == "dome"]
    if not domes:
        return parts
    main, dome = max(domes, key=lambda pair: pair[1].area())
    main["feature"] = "main_dome"
    centre, span = _dimensions(dome)
    tower_height = facts.get("west_tower_m", {}).get("value")
    if tower_height:
        peaks = []
        eligible = [(p, cs) for p, cs in parts
                    if abs(p["height"]["metres"] - tower_height) <= 2 and _dimensions(cs)[1] < span * .32]
        for p, cs in sorted(eligible, key=lambda pair: -pair[0]["height"]["metres"]):
            pos, _ = _dimensions(cs)
            if all(np.linalg.norm(pos - other) > span * .30 for other in peaks):
                p["feature"] = "west_tower"
                peaks.append(pos)
                if len(peaks) == facts.get("west_tower_count", {}).get("value", 2):
                    break

    lantern = facts.get("lantern_body")
    peristyle = facts.get("dome_peristyle")
    if not (lantern or peristyle):
        return parts
    import manifold3d as m3

    updated = []
    for p, cs in parts:
        pos, width = _dimensions(cs)
        lo, top = (p[key]["metres"] for key in ("min_height", "height"))
        distance = np.linalg.norm(pos - centre)
        if lantern and distance < span * .04:
            base, shaft_top, width_ratio = lantern["value"]
            if abs(lo - base) < 1 and abs(top - shaft_top) < 1 and width < span * .28:
                # Preserve the mapped centre and survey heights. The building section
                # shows a square tempietto instead of the rounded map approximation.
                width = span * width_ratio
                cs = m3.CrossSection.square([width, width], True).offset(-width * .08).offset(width * .08)
                cs = cs.translate(pos.tolist())
                p["footprint"] = [ring.tolist() for ring in cs.to_polygons()]
                p["lantern_body"] = True
                p["feature"] = "lantern"
                p["source"] = lantern["source"]
                notes.append("Rebuilt the dome's masonry lantern as a square tempietto with four recessed faces.")
        if peristyle:
            bottom, upper, count = peristyle["value"]
            if bottom - 2 <= lo <= bottom + 1 and abs(top - upper) < 1 and .53 * span < distance < .68 * span:
                p["peristyle_column"] = width < span * .065
            if .85 * span <= width <= 1.1 * span and distance < .1 * span and lo < bottom and top > upper:
                p["peristyle_core"] = count
        updated.append((p, cs))
    return updated


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
    return out + _twin_detail(out, centres, span, foot, notes)


def _twin_detail(parts, centres, span, foot, notes):
    """The gables, pinnacles and bands a map draws around only one of two matched towers, for the other."""
    from .landmark import bearing

    def around(c):
        return [(p, cs) for p, cs in parts if p.get("feature") != "west_spire" and p["height"]["metres"] > foot + 1
                and np.linalg.norm(_dimensions(cs)[0] - c) < span * .75]

    near = [around(c) for c in centres]
    dense = int(len(near[1]) > len(near[0]))
    if len(near[dense]) < 3 * max(1, len(near[1 - dense])):
        return []
    bare = near[1 - dense]
    axis = centres[1] - centres[0]
    axis = axis / np.linalg.norm(axis)
    mirror = np.eye(2) - 2 * np.outer(axis, axis)
    shift = (centres[0] + centres[1]) / 2 - mirror @ ((centres[0] + centres[1]) / 2)
    added = []
    for p, cs in near[dense]:
        twin = cs.transform([[*mirror[0], shift[0]], [*mirror[1], shift[1]]])
        top = p["height"]["metres"]
        if any((twin ^ other).area() > twin.area() * .5 and abs(q["height"]["metres"] - top) < 3 for q, other in bare):
            continue
        record = {**p, "id": f"{p['id']}-twin", "footprint": [ring.tolist() for ring in twin.to_polygons()],
                  "tags": dict(p["tags"])}
        way = bearing(p["tags"])
        if way is not None:
            east, north = mirror @ [math.sin(math.radians(way)), math.cos(math.radians(way))]
            record["tags"]["roof:direction"] = str(round(math.degrees(math.atan2(east, north)) % 360, 2))
        for key in ("height", "min_height", "roof_height"):
            record[key] = {**p[key], "guessed": True, "reason": "Mirrored from the matched tower, which the map draws in detail."}
        added.append((record, twin))
    if added:
        notes.append(f"Mirrored {len(added)} mapped details from one matched west tower onto its twin.")
    return added


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
        if facts.get("platform_arcade") and p["tags"].get("building:part") and width > 3 * span and top < .25 * drum_top:
            p["platform_arcade"] = True
        out.append((p, cs))
    height_fact = facts.get("minaret_rise_m")
    if height_fact:
        out = _minaret_levels(out, height_fact, notes)
    notes.append("Modeled the main onion dome above the measured drum, a tip at the sourced finial height, and four raised dome canopies on the mapped corner pavilions.")
    return out


def _minaret_levels(parts, fact, notes):
    platform = next((p["height"]["metres"] for p, _ in parts if p.get("platform_arcade")), 0)
    minarets = [(p, cs) for p, cs in parts if p.get("feature") == "minaret"]
    if not (platform and minarets):
        return parts
    changed = False
    for cap, section in minarets:
        centre, span = _dimensions(section)
        mapped_top = cap["height"]["metres"]
        mapped_base = cap["min_height"]["metres"]
        # The source gives the tower rise above the terrace. Raise the canopies
        # and distribute the added rise through the mapped shaft and balconies.
        if mapped_base <= platform:
            continue
        stretch = (fact["value"] + platform - mapped_top) / (mapped_base - platform)
        if not 0 < stretch < .35:
            continue
        for p, cs in parts:
            pos, width = _dimensions(cs)
            if width > 1.6 * span or np.linalg.norm(pos - centre) > .68 * span:
                continue
            for key in ("min_height", "height"):
                z = p[key]["metres"]
                if z > platform:
                    p[key] = _moved(p[key], z + stretch * (min(z, mapped_base) - platform),
                                    fact["source"], "Adjusted mapped level to the sourced minaret rise.")
                    changed = True
    if changed:
        notes.append("Retained the surveyed minaret footprints and distributed their sourced rise above the platform through the shafts.")
    return parts


def lattice(outline, scale, refs, facts, notes=None):
    """Four battered legs, four curved arches, and cross-braced upper stages."""
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
    # The arches spring from the inner chord on the outer face of each leg.
    # Follow that chord in plan up to the crown near the edge of the first deck.
    spring = levels[0] * .24
    fraction = spring / (levels[0] * .45)
    distance = foot_centre * (1 - .22 * fraction)
    half = (foot / 2 - 1) * (1 - fraction) + foot * .36 * fraction
    arch_width = distance - half
    spring_outer = distance + half
    crown_outer = widths[0] * .425
    band = facts.get("arch_band_ratio", {}).get("value", .12) * (arch - spring)
    double_arch = band * scale >= 2.0
    if not double_arch and notes is not None:
        notes.append("Omitted detail below the print floor: the second arch rail and its braces.")

    def arch_point(t, rail, side, axis):
        curved = math.sqrt(max(0, 1 - t * t))
        x = arch_width * t
        y = side * (crown_outer + (spring_outer - crown_outer) * t * t)
        z = spring + (arch - spring) * curved + rail * band * curved
        return [y, x, z] if axis else [x, y, z]

    for axis in (0, 1):
        for side in (-1, 1):
            samples = np.linspace(-1, 1, 19)
            rails = [[arch_point(t, rail, side, axis) for t in samples] for rail in range(1 + double_arch)]
            for rail in rails:
                for a, b in zip(rail[:-1], rail[1:]):
                    beam(a, b, 1.25 if double_arch else 1.55)
            if double_arch:
                for i in range(1, len(samples) - 2):
                    beam(rails[0][i], rails[1][i + 1], 1.0)
            for i in range(2, len(samples) - 2, 2):
                a = rails[-1][i]
                b = list(a)
                b[axis] = a[axis] * .93
                b[1 - axis] = side * widths[0] * .457
                b[2] = levels[0]
                if abs(b[axis]) < widths[0] * .48:
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
    def tapered_stage(lo, hi, low_width, high_width):
        low = max(1.62, low_width * scale)
        ratio = max(1.62, high_width * scale) / low
        box = m3.CrossSection.square([low, low], True)
        pieces.append(box.extrude((hi - lo) * scale + .04, scale_top=[ratio, ratio])
                      .translate([*origin, 2 + lo * scale - .02]))

    modern = facts.get("summit_profile")
    if modern:
        cabin, taper, original, recent = modern["value"]
        stages = [(levels[2], widths[2]), (cabin[0], widths[2] * cabin[1]),
                  (taper[0], widths[2] * taper[1]), (historic, widths[2] * original),
                  (recent, widths[2] * .17), (top, 1.62 / scale)]
    else:
        stages = [(levels[2], widths[2]), (levels[2] + 12, widths[2] * .88),
                  (300, widths[2] * .62), (historic, max(2.6 / scale, widths[2] * .36)),
                  (top, 1.62 / scale)]
    for i, ((lo, low), (hi, high)) in enumerate(zip(stages[:-1], stages[1:])):
        if modern and i == 1 and high * scale >= 3.8:
            a = [(x * low * .43, y * low * .43, lo) for x, y in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
            b = [(x * high * .44, y * high * .44, hi) for x, y in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
            deck(high, hi, 1.5)
            for j in range(4):
                k = (j + 1) % 4
                beam(a[j], b[j], 1.15)
                beam(a[j], b[k], 1.0)
                beam(a[k], b[j], 1.0)
        else:
            if modern and i == 1 and notes is not None:
                notes.append("Omitted detail below the print floor: open crown bracing.")
            tapered_stage(lo, hi, low, high)
    # Orient the framework along the surveyed sidewalk and use the mapped base.
    A = np.c_[np.eye(3), np.zeros(3)]
    A[:2, :2] = R.T
    A[:2, 3] = origin - R.T @ origin
    return _union([solid.transform(A.tolist()) for solid in pieces])
