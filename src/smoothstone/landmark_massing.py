"""Read structural relationships from mapped geometry when there is no reference pack."""
from __future__ import annotations

from itertools import combinations
import math
import re

import numpy as np


def _center(section):
    x0, y0, x1, y1 = section.bounds()
    return np.array([(x0 + x1) * .5, (y0 + y1) * .5])


def _west_towers(parts, frame, center, spans, peak):
    """Find the high, symmetric pair at the west end of a Gothic footprint. A plan whose long axis runs
    nearer north and south has no west end, so there a pair at either end counts."""
    east = frame[0][0]
    candidates = []
    for part, section in parts:
        h = part["height"]["metres"]
        width = math.sqrt(section.area()) / spans[1]
        position = (frame @ _center(section) - center) / spans
        if abs(east) >= .5 and position[0] * east > 0:
            continue
        if (not part["height"]["guessed"] and h >= peak * .77 and .04 <= width <= .26
                and part["min_height"]["metres"] < h * .3 and abs(position[0]) > .28):
            candidates.append((part, position, width, h))
    pairs = []
    for a, b in combinations(candidates, 2):
        _, p, w, h = a
        _, q, v, j = b
        if (abs(p[0] - q[0]) < .055 and .16 <= abs(p[1] - q[1]) < .72
                and abs(h - j) < .06 * max(h, j) and min(w, v) > .72 * max(w, v)):
            pairs.append((a, b))
    if not pairs:
        return None
    a, b = max(pairs, key=lambda pair: (min(p[3] for p in pair), min(p[2] for p in pair)))
    for part, _, _, _ in (a, b):
        part["feature"] = "west_spire" if part["spire"] else "west_tower"
    peak_part, peak_section = max(parts, key=lambda pair: pair[0]["height"]["metres"])
    if (peak_part["height"]["metres"] > max(a[3], b[3]) * 1.08
            and peak_part["spire"] and math.sqrt(peak_section.area()) > spans[1] * .04):
        peak_part["feature"] = "main_tower"
        if (peak_part["roof_shape"] == "onion"
                and peak_part["roof_height"]["metres"] > 2 * math.sqrt(peak_section.area())):
            # A tall onion tower spans several stages. Retain the mapped roof
            # height and put a shoulder, lantern and spire inside that envelope.
            peak_part["onion_profile"] = [(0, .88), (.11, 1), (.26, .74), (.33, .57), (.44, .52),
                                           (.49, .70), (.57, .61), (.64, .42), (.78, .38), (.84, .48), (1, 0)]
    return frame[0] * np.sign(a[1][0])


def _cupola(parts, source_height, notes):
    """Split a compound dome height at its co-centred, underspecified lantern."""
    from .landmark import _fact

    domes = [(p, cs) for p, cs in parts if p["roof_shape"] == "dome"]
    if not domes or not source_height:
        return parts
    dome, section = max(domes, key=lambda pair: pair[1].area())
    top = dome["height"]["metres"]
    roof = dome["roof_height"]["metres"]
    span = math.sqrt(section.area())
    octagon = section.simplify(span * .012)
    rings = octagon.to_polygons()
    if (abs(top - source_height) > source_height * .015 or roof < .60 * span
            or len(rings) != 1 or len(rings[0]) != 8):
        return parts
    for cap, cap_section in parts:
        if (not cap["height"]["guessed"] or cap["roof_shape"] not in ("pyramidal", "dome")
                or abs(cap["min_height"]["metres"] - top) > .1
                or np.linalg.norm(_center(section) - _center(cap_section)) > .08 * span):
            continue
        cap_span = math.sqrt(cap_section.area())
        if not .09 <= cap_span / span <= .23:
            continue
        rise = min(2.5 * cap_span, roof * .4)
        crown = top - rise
        eave = top - roof
        reason = "The mapped dome height includes the smaller co-centred cap. The split is inferred from the cap footprint."
        dome["height"] = _fact(crown + .01, dome["source"], True, reason)
        dome["roof_height"] = _fact(crown - eave + .01, dome["source"], True, reason)
        dome["cupola_seat"] = cap_span / span * 1.04
        dome["feature"] = "main_dome"
        cap["min_height"] = _fact(crown - .08, cap["source"], True, reason)
        cap["height"] = _fact(top, dome["source"], False, "Mapped compound dome and cap summit.")
        cap["roof_height"] = _fact(rise * .42, cap["source"], True, "Taper allowed for the mapped cupola cap.")
        cap["feature"] = "lantern"
        cap["feature_of"] = dome["id"]
        notes.append("Separated the octagonal cupola from its mapped lantern at an estimated shoulder and kept the documented summit.")
        return [(p, octagon if p is dome else cs) for p, cs in parts]
    return parts


CHURCHES = {"cathedral", "church", "basilica", "abbey", "chapel"}


def _is_church(data, refs):
    tags = data.get("tags", {})
    words = re.findall(r"[a-z]+", f"{refs.get('label', '')} {refs.get('requested_name', '')}".lower())
    return tags.get("building") in CHURCHES or bool(CHURCHES & set(words))


def _merge_split_nave(parts, frame, center, notes):
    """Give a nave mapped as two gabled halves one ridge. Both halves lie along the church's long
    axis, match in height, length and width, and meet on it; any other pair keeps its own roofs."""
    import manifold3d as m3

    from .landmark import _fact

    along, across = frame
    gabled = []
    for index, (part, section) in enumerate(parts):
        if part["roof_shape"] == "gabled" and not section.is_empty():
            points = np.concatenate(section.to_polygons())
            u, v = points @ along, points @ across
            gabled.append((index, np.ptp(u), np.ptp(v), (v.min() + v.max()) / 2 - center[1], (u.min() + u.max()) / 2))
    for a, b in combinations(gabled, 2):
        (i, la, wa, va, ua), (j, lb, wb, vb, ub) = a, b
        p, q = parts[i][0], parts[j][0]
        level = p["height"]["metres"]
        if (abs(level - q["height"]["metres"]) > .02 * level
                or abs(p["min_height"]["metres"] - q["min_height"]["metres"]) > .1
                or min(la, lb) < .95 * max(la, lb) or min(wa, wb) < .85 * max(wa, wb)
                or min(la, lb) < 2 * max(wa, wb) or abs(ua - ub) > .05 * max(la, lb)
                or va * vb >= 0 or abs(va + vb) / 2 > .3 * max(wa, wb)):
            continue
        # Close the hairline between the two surveys, then require one solid, near-rectangular plan.
        joined = (parts[i][1] + parts[j][1]).offset(.6).offset(-.6)
        if len(joined.decompose()) != 1 or joined.area() < .95 * joined.hull().area():
            continue
        reason = "The nave is mapped as two gabled halves about the church's axis. One ridge over both is inferred."
        roof = max(p["roof_height"]["metres"], q["roof_height"]["metres"])
        merged = {**p, "merged_parts": [p["id"], q["id"]],
                  "roof_height": _fact(roof, p["source"], True, reason),
                  "footprint": [ring.tolist() for ring in joined.to_polygons()]}
        notes.append(f"Joined gabled parts {p['id']} and {q['id']} under one inferred nave ridge.")
        return [(merged, joined) if k == i else item for k, item in enumerate(parts) if k != j]
    return parts


def infer_massing(records, sections, outline, data, refs, target, styles):
    """Use the mapped plan and part elevations to restore recognizable massing."""
    import manifold3d as m3

    from .landmark import _frame, _scale, length
    from .landmark_architecture import _new_part

    frame, center, spans = _frame(outline, {})
    size = _scale([outline], records, target)
    parts, notes = [], []
    for part, cs in zip(records, sections):
        area = cs.area()
        h = part["height"]["metres"] - part["min_height"]["metres"]
        if part["roof_shape"] == "flat" and area * size ** 2 < .8 ** 2 and h > 100 * math.sqrt(area):
            notes.append(f"Omitted detail below the print floor: mapped flat part {part['id']} is a near-zero-width extrusion.")
            continue
        parts.append((part, cs))
    if not parts:
        return records, sections, None, []
    peak = max(p["height"]["metres"] for p, _ in parts)
    westward = _west_towers(parts, frame, center, spans, peak) if "gothic" in styles else None
    if westward is not None:
        notes.append("Identified the matched west towers from their aligned, similarly sized mapped footprints and heights.")
    if _is_church(data, refs):
        parts = _merge_split_nave(parts, frame, center, notes)
    if "baroque" in styles:
        parts = _cupola(parts, refs.get("height"), notes)
    ground = m3.CrossSection.batch_boolean([cs for p, cs in parts if p["min_height"]["metres"] <= .1], m3.OpType.Add)
    height = length(data.get("tags", {}).get("height"))
    if height and .08 * peak <= height <= .60 * peak and ground.area() > .5 * outline.area():
        ground_spans = np.ptp(np.concatenate(ground.to_polygons()) @ frame.T, axis=0)
        if np.any(ground_spans < .97 * spans) or (outline - ground).area() > .12 * outline.area():
            source = data["source"]
            # A part mapped lower than these walls keeps its height. Taller parts simply stand in them.
            # A gap too narrow to print beside a low part is map noise, not wall.
            low = m3.CrossSection.batch_boolean([cs for p, cs in parts if p["height"]["metres"] < height], m3.OpType.Add)
            # A low part mapped off the ground with nothing under it stands on wall up to its own base.
            for part, section in list(parts):
                base = part["min_height"]["metres"]
                bare = (section ^ outline) - ground
                if .1 < base and part["height"]["metres"] < height and bare.area() * size ** 2 > .64:
                    parts.append((_new_part(f"wall-below-{part['id']}", bare, 0, base, 0, "flat", source, "lower_walls"), bare))
            missing = outline - low
            if not low.is_empty():
                grain = .3 / size
                missing = missing.offset(-grain).offset(grain + .05) ^ outline
            if not missing.is_empty():
                parts.append((_new_part("outline-lower-walls", missing, 0, height, 0, "flat", source, "lower_walls"), missing))
                notes.append("Kept the building outline's mapped low walls where the taller roof parts leave the plan incomplete.")
    updated, footprints = map(list, zip(*parts))
    return updated, footprints, westward, notes


def linked_plinth(footprint):
    """Join disjoint mapped footprints with narrow tabs at their nearest edges."""
    import manifold3d as m3

    main, *others = sorted(footprint.decompose(), key=lambda cs: -cs.area())
    disk = m3.CrossSection.circle(1.5, 12)
    for section in others:
        # Spacing at most 2 mm along each edge finds useful join positions
        # even when a long surveyed wall segment has only its endpoints.
        cloud = []
        for geometry in (main, section):
            ring = max(geometry.to_polygons(), key=lambda p: abs(np.dot(p[:, 0], np.roll(p[:, 1], 1)) -
                                                                np.dot(p[:, 1], np.roll(p[:, 0], 1))))
            cloud.append(np.concatenate([
                np.linspace(a, b, max(1, math.ceil(np.linalg.norm(a - b) / 2)), endpoint=False)
                for a, b in zip(ring, np.roll(ring, -1, axis=0))]))
        a, b = cloud
        i, j = np.unravel_index(np.argmin(np.sum((a[:, None] - b) ** 2, axis=2)), (len(a), len(b)))
        tab = (disk.translate(a[i].tolist()) + disk.translate(b[j].tolist())).hull()
        main = m3.CrossSection.batch_boolean([main, section, tab], m3.OpType.Add)
    return main


def ribbed_cupola(cs, z, height, seat, notes):
    """Pointed polygonal dome with full-width ridges bonded to its faces."""
    from .landmark import _loft, _section, _union

    profile = [(0, 1.), (.24, .94), (.49, .80), (.71, .60), (.88, .38), (1., seat)]
    solids = [_loft(cs, z, height, profile, notes)]
    center = _center(cs)
    for corner in cs.to_polygons()[0]:
        vector = corner - center
        radius = np.linalg.norm(vector)
        radial = vector / radius
        tangent = np.array([-radial[1], radial[0]])
        outer = [(radius * f + .64, t * height) for t, f in profile]
        inner = [(radius * f - 1., t * height) for t, f in reversed(profile)]
        rib = _section([outer + inner]).extrude(.95).translate([0, 0, -.475])
        solids.append(rib.transform([[radial[0], 0, tangent[0], center[0]],
                                     [radial[1], 0, tangent[1], center[1]],
                                     [0, 1, 0, z]]))
    return _union(solids)
