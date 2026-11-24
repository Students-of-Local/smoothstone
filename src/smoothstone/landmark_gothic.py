"""Gothic features laid out on surveyed building parts."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from manifold3d import CrossSection, Manifold


def _centre(section: CrossSection) -> np.ndarray:
    x0, y0, x1, y1 = section.bounds()
    return np.array([(x0 + x1) / 2, (y0 + y1) / 2])


def reconcile_gothic(parts, refs: dict, facts: dict, notes: list[str]):
    from .landmark_architecture import _measurement

    annex = facts.get("annex_roofs")
    if annex:
        roofs = {entry["osm_id"]: entry for entry in annex["value"]}
        for part, _ in parts:
            roof = roofs.get(part["id"])
            if roof and roof["ridge_m"] > roof["eave_m"] > part["min_height"]["metres"]:
                part["roof_shape"] = roof["shape"]
                reason = "Estimated from the scaled section of the annex roof."
                part["height"] = _measurement(roof["ridge_m"], annex["source"], reason)
                part["roof_height"] = _measurement(roof["ridge_m"] - roof["eave_m"], annex["source"], reason)
                notes.append("Replaced an oversized flat annex with the pitched roof shown in the architectural section.")
    stages = facts.get("crossing_spire_stages")
    if stages:
        for part, _ in parts:
            top = part["height"]["metres"]
            spring = stages["value"]["spring_m"]
            if part["spire"] and abs(top - refs["height"]) <= .2 and part["min_height"]["metres"] < spring < top:
                part["roof_profile"] = stages["value"]["profile"]
                part["roof_height"] = _measurement(top - spring, stages["source"], "Documented crossing spire stages.")
                notes.append("Gave the crossing spire a stepped gallery and taper up to the restored height.")
    if "flying_buttress_survey" in facts:
        parts = _reconcile_buttresses(parts, facts, notes)
    if {"spire_plan", "spire_count", "spire_rise_m", "crossing_spire_rise_m",
            "crown_statue_height_m"} <= facts.keys():
        parts = _reconcile_spire_plan(parts, refs, facts, notes)
    wall = facts.get("aisle_wall_datum_m")
    if wall and wall["value"] > 0:
        from .landmark import _section
        from .landmark_architecture import _new_part

        outline = _section(refs["outline"])
        if not outline.is_empty():
            lower = _new_part("surveyed-aisle-walls", outline, 0, wall["value"], 0,
                              "flat", wall["source"], "aisle_walls")
            parts.append((lower, outline))
            notes.append("Recovered the parallel ground aisles and projecting transept from the surveyed outline.")
    return parts


def _reconcile_buttresses(parts, facts: dict, notes: list[str]):
    import manifold3d as m3

    from .landmark import _frame
    from .landmark_architecture import _measurement

    survey = facts["flying_buttress_survey"]
    nave_roof = facts.get("nave_ridge_m")
    transept_span = facts.get("transept_span_m")
    wanted = survey["value"]
    flying = []
    main_roofs = []
    for part, section in parts:
        if part["roof_shape"] == "skillion" and part["tags"].get("roof:direction"):
            try:
                bearing = float(part["tags"]["roof:direction"])
            except (ValueError, TypeError):
                continue
            _, _, (run, wide) = _frame(section, {})
            if math.isfinite(bearing) and run >= 5 and run >= wide * 8 and part["roof_height"]["metres"] >= run * .65:
                flying.append((part, section))
        if part["roof_shape"] in {"gabled", "cone"} and nave_roof:
            top = part["height"]["metres"]
            if abs(top - nave_roof["value"]) <= 2.1 and part["min_height"]["metres"] > 20:
                main_roofs.append((part, section))
    if not flying or not main_roofs:
        return parts

    core = m3.CrossSection.batch_boolean([section for _, section in main_roofs], m3.OpType.Add)
    nave_floor = min(p["min_height"]["metres"] for p, _ in main_roofs)
    cores = [(p, cs) for p, cs in parts if p["roof_shape"] == "flat"
             and abs(p["height"]["metres"] - nave_floor) < .1 and (cs ^ core).area() > core.area() * .75]
    for part, _ in flying:
        part["flying_buttress"] = True
        part["feature"] = "flying_buttress"
    if transept_span:
        arm = min(main_roofs, key=lambda entry: abs(_frame(entry[1], {})[2][0] - transept_span["value"]))
        if abs(_frame(arm[1], {})[2][0] - transept_span["value"]) < 4:
            arm[0]["feature"] = "transept"
    if cores:
        wall, surveyed = max(cores, key=lambda entry: entry[1].area())
        main_wall = (surveyed ^ core.offset(.28)) + core
        low_wall = dict(wall, id=f"{wall['id']}-aisles")
        low_wall["height"] = _measurement(wanted["aisle_eave_m"], survey["source"],
                                          "Aisle roofs are lower than the nave's clerestory.")
        low_wall["footprint"] = [ring.tolist() for ring in surveyed.to_polygons()]
        wall["footprint"] = [ring.tolist() for ring in main_wall.to_polygons()]
        parts = [(p, main_wall if p is wall else cs) for p, cs in parts]
        parts.append((low_wall, surveyed))
    notes.append(f"Opened {len(flying)} mapped flying buttresses above lower aisles with print-safe undersides.")
    return parts


def flying_buttress(section: CrossSection, part: dict, lo: float, eave: float,
                    top: float, notes: list[str]) -> list[Manifold]:
    """Replace a mapped narrow roof wedge with a rising arch and a pier."""
    from .landmark import _frame, _section

    frame, _, (run, width) = _frame(section, {})
    outward_bearing = math.radians(float(part["tags"]["roof:direction"]))
    outward = np.array([math.sin(outward_bearing), math.cos(outward_bearing)])
    inward = -frame[0] if frame[0] @ outward > 0 else frame[0]
    across = np.array([-inward[1], inward[0]])
    width = max(1.25, width)

    def prism(points, projection):
        local = _section([points]).extrude(width + projection).translate([0, 0, -(width + projection) / 2])
        start = _centre(section) - inward * run / 2
        transform = [[inward[0], 0., across[0], start[0]],
                     [inward[1], 0., across[1], start[1]], [0., 1., 0., 0.]]
        return local.transform(transform)

    # A monotone arch springs from the outer pier to the inner wall.
    # Every chord of the visible soffit rises at least as far as it advances.
    t = np.linspace(0., 1., 13)
    thickness = max(1.6, min(2.8, run * .13))
    rise = max(run * 1.04, top - eave)
    spring = top - thickness - rise
    underside = spring + t * run * 1.04 + (rise - run * 1.04) * (1 - (1 - t) ** 2)
    over = np.minimum(top, underside + thickness + .14 * run * t * (1 - t))
    profile = [(-.35, spring), *zip(t * run, underside),
               (run + .55, underside[-1]), (run + .55, top),
               *reversed(list(zip(t * run, over))), (-.35, over[0])]
    pier = max(1.6, min(3.8, run * .18))
    pier_profile = [(-.45, lo), (pier, lo), (pier * .8, spring + thickness * 1.5),
                    (-.35, spring + thickness * 1.5)]
    return [prism(pier_profile, .42), prism(profile, 0.)]


def _reconcile_spire_plan(parts, refs: dict, facts: dict, notes: list[str]):
    import manifold3d as m3

    from .landmark import _frame, _section
    from .landmark_architecture import _measurement, _new_part

    outline = _section(refs["outline"])
    frame, _, _ = _frame(outline, {})
    if frame[0, 0] < 0:
        frame = -frame
    low = (np.concatenate(outline.to_polygons()) @ frame.T).min(0)
    span = np.ptp(np.concatenate(outline.to_polygons()) @ frame.T, axis=0)
    plan = facts["spire_plan"]
    data = plan["value"]
    if len(data["pins"]) != facts["spire_count"]["value"]:
        return parts
    mapped, body = [], []
    for part, section in parts:
        x0, y0, x1, y1 = section.bounds()
        if part["roof_shape"] in {"pyramidal", "dome"} and max(x1 - x0, y1 - y0) < 6:
            mapped.append((part, section))
        else:
            body.append((part, section))
    if not mapped:
        return parts

    rise = facts["spire_rise_m"]
    crown = facts["crown_statue_height_m"]
    crossing_rise = facts["crossing_spire_rise_m"]
    summit = refs["height"]
    mapped_centres = np.array([_centre(section) for _, section in mapped])
    main = max(mapped, key=lambda item: item[0]["height"]["metres"])
    main_centre = _centre(main[1])
    tip_base = summit - crown["value"]
    main_spring = tip_base - crossing_rise["value"]
    supported_body = []
    for part, section in body:
        upper = part["height"]["metres"]
        if part["roof_shape"] == "flat" and upper > main_spring and (
                np.linalg.norm(_centre(section) - main_centre) < data["main_diameter_m"] * .25):
            if part["min_height"]["metres"] >= main_spring - .2:
                continue
            part["height"] = _measurement(main_spring, crossing_rise["source"],
                                            "The mapped crossing shaft ends at the tapered main spire.")
        supported_body.append((part, section))
    body = supported_body
    for part, section in body:
        top = part["height"]["metres"]
        bottom = part["min_height"]["metres"]
        same_center = np.linalg.norm(_centre(section) - main_centre) < data["main_diameter_m"] * .18
        if part["roof_shape"] == "flat" and same_center and main_spring - crossing_rise["value"] <= top <= main_spring + .1:
            part["feature"] = "crossing_lantern"
            part["lantern_rise_m"] = min(crossing_rise["value"] * .66, top - bottom)
    footprint = m3.CrossSection.batch_boolean(
        [section for part, section in body if part["min_height"]["metres"] < .1], m3.OpType.Add)
    if footprint.is_empty():
        return parts

    def anchored(point, diameter):
        disk = m3.CrossSection.circle(diameter / 2, 12).translate(point.tolist())
        support = [
            p["height"]["metres"] - p["roof_height"]["metres"]
            for p, section in body if (disk - section).area() < disk.area() * .30
        ]
        return disk, max(support, default=1) - 1

    out = list(body)
    matched = set()
    recorded = 0
    for number, along, across, level in data["pins"]:
        xy = (low + span * [along, across]) @ frame
        distances = np.linalg.norm(mapped_centres - xy, axis=1)
        index = int(distances.argmin())
        old = mapped[index][0]
        seen = index not in matched and distances[index] <= 1.95
        if level == "main":
            xy = main_centre
            old = main[0]
            disk, _ = anchored(xy, data["main_diameter_m"])
            record = _new_part(f"{old['id']}-main-spire", disk, main_spring - 1, tip_base,
                               crossing_rise["value"], "pyramidal", crossing_rise["source"], "pinnacle")
            record["spire_id"] = number
            record["roof_profile"] = data["main_profile"]
            out.append((record, disk))
            disk, _ = anchored(xy, data["statue_diameter_m"])
            figure = _new_part(f"{old['id']}-statue", disk, tip_base - .3, summit,
                               crown["value"] + .2, "pyramidal", crown["source"], "finial")
            figure["roof_profile"] = [(0, .64), (.23, 1), (.55, .82), (.77, .63), (1, .46)]
            figure["feature_of"] = number
            out.append((figure, disk))
            recorded += 1
            continue
        if seen:
            xy = mapped_centres[index]
            matched.add(index)
        base, nominal_rise = data["levels_m"][level]
        top = base + nominal_rise
        if seen:
            height = old["height"]["metres"]
            # The plan identifies the spire, and a localized surveyed height
            # takes precedence over a terrace's representative elevation.
            if abs(height - top) <= nominal_rise * .6:
                top = height
        diameter = min(data["diameter_m"], max(1.55, nominal_rise * .18))
        disk, support = anchored(xy, diameter)
        if (disk ^ footprint).area() < disk.area() * .05 and not seen:
            # No unsupported ground column for a map pin near an outside edge.
            for shift in (.4, .8, 1.2, 1.8, 2.6):
                direction = main_centre - xy
                inset = xy + direction / np.linalg.norm(direction) * shift
                candidate, candidate_support = anchored(inset, diameter)
                if (candidate ^ footprint).area() >= candidate.area() * .35:
                    disk, support = candidate, candidate_support
                    break
        top = max(top, support + nominal_rise * .52)
        spring = max(support, top - nominal_rise)
        source = old["source"] if seen else plan["source"]
        record = _new_part(f"terrace-spire-{number}", disk, max(0, support), top,
                           top - spring, "pyramidal", source, "pinnacle")
        record["height"] = _measurement(top, old["height"]["source"] if seen and top == height else rise["source"],
                                        "Mapped peak or the typical rise above its source terrace.")
        record["spire_id"] = number
        record["placement_guessed"] = number in data["inferred"]
        record["roof_profile"] = [(0, 1), (.08, .97), (.27, .85), (.60, .62), (.84, .4), (1, 0)]
        out.append((record, disk))
        recorded += 1
    notes.append(f"Placed {recorded} counted spires ({len(matched)} aligned to OSM; "
                 f"{len(data['inferred'])} pin locations reconstructed from adjacent rows and the crossing plan).")
    notes.append("Omitted detail below the print floor: modeled the summit statue as a finial silhouette.")
    return out


def rose_profile(radius: float) -> tuple[CrossSection, bool]:
    """A spoke rose sized for a flat-backed recess, in local XY."""
    import manifold3d as m3

    disk = m3.CrossSection.circle(radius, 48)
    bar = .9
    # At the inner end, each chord must hold one bar and .8 mm of open recess.
    # Leave another .8 mm radially between the hub and the outside of the rose.
    outside = radius * math.cos(math.pi / 48)
    max_hub = min(outside - .8, max(1.27, radius * .34))
    spoke = m3.CrossSection.square([radius + .05, bar]).translate([0, -bar / 2])
    for count in range(12, 3, -1):
        inner = (bar + .8) / (2 * math.sin(math.pi / count) * math.cos(math.pi / 24))
        if inner <= max_hub:
            hub = m3.CrossSection.circle(max(inner, radius * .27), 24)
            spokes = [spoke.rotate(a) for a in np.linspace(0, 360, count, endpoint=False)]
            return disk - m3.CrossSection.batch_boolean([hub, *spokes], m3.OpType.Add), True
    return disk, False


def _face_at(man: Manifold, axis: np.ndarray, lateral: np.ndarray, y: float, z: float):
    """First outer surface on an inward ray toward a plan section."""
    crossings = []
    for ring in man.slice(z).to_polygons():
        poly = np.asarray(ring)
        xx, yy = poly @ axis, poly @ lateral
        for a, b in zip(range(len(poly)), np.roll(np.arange(len(poly)), -1)):
            if (yy[a] > y) != (yy[b] > y):
                fraction = (y - yy[a]) / (yy[b] - yy[a])
                crossings.append(xx[a] + (xx[b] - xx[a]) * fraction)
    return min(crossings) if crossings else None


def west_details(man: Manifold, face, middle: float, width: float, height: float,
                 along: np.ndarray, across: np.ndarray, scale: float,
                 facts: dict, notes: list[str]):
    """Cut consecutive galleries or lancets into the measured facade planes."""
    import manifold3d as m3

    from .landmark import _section
    from .landmark_style import _arch, _place, _relief_cut

    cuts, additions = [], []
    omitted = False
    for low, rise, count, span in facts.get("west_gallery_bands", {}).get("value", []):
        z, h = 2 + low * scale, rise * scale
        run = span * width
        bays = min(count, int(run / 1.65))
        if bays < count:
            omitted = True
        if bays == 0 or h < 1.6:
            continue
        bay = run / bays
        recess = _section([_arch(min(bay - .84, bay * .66), h, True)])
        for i in range(bays):
            y = middle + (i + .5 - bays / 2) * bay
            x = face(y, z + h * .4)
            if x is not None:
                cuts.append(_relief_cut(recess, x * along + y * across, across, -along, z, 1.1))
    for low, rise, count, offset, span in facts.get("west_tower_windows", {}).get("value", []):
        z, h = 2 + low * scale, rise * scale
        pitch = span * width / count
        w = pitch * .70
        if w < .8 or pitch - w < .8 or h < 1.6:
            omitted = True
            continue
        opening = _section([_arch(w, h, True)])
        if w >= 2.5:
            bar = m3.CrossSection.square([.85, h * .82], True).translate([0, h * .39])
            opening = opening - bar
        for side in (-1, 1):
            for i in range(count):
                y = middle + side * offset * width + (i + .5 - count / 2) * pitch
                x = face(y, z + h * .43)
                if x is not None:
                    depth = max(.6, min(3.4, w * .65))
                    cuts.append(_relief_cut(opening, x * along + y * across, across, -along, z, depth))
    gable = facts.get("west_gable")
    if gable:
        width_ratio, rise_ratio = gable["value"]
        w, h = width * width_ratio, height * rise_ratio
        z = 2 + height - h
        x = face(middle, z - .8)
        if x is not None and min(w, h) >= 2.4:
            profile = _section([[(-w / 2, -1.4), (w / 2, -1.4), (0, h)]])
            origin = x * along + middle * across
            additions.append(_place(profile.extrude(2.15), across, -along, [*(origin - along * .65), z]))
    if omitted:
        notes.append("Omitted detail below the print floor: combined or dropped narrow west facade bays.")
    if cuts:
        notes.append("Recessed the sourced west facade galleries and tower tracery.")
    return cuts, additions


def transept_details(man: Manifold, records, sections, outline: CrossSection, scale: float,
                     facts: dict, notes: list[str]):
    from .landmark import _frame
    from .landmark_style import _relief_cut

    rose = facts.get("transept_rose_m")
    if not rose:
        return []
    church_frame, _, _ = _frame(outline, {})
    crosswise, lengthwise = church_frame[1], church_frame[0]
    cuts = []
    for record, section in zip(records, sections):
        if record.get("feature") != "transept":
            continue
        eave = 2 + (record["height"]["metres"] - record["roof_height"]["metres"]) * scale
        points = np.concatenate(section.to_polygons()) @ church_frame.T
        centre = (points[:, 0].min() + points[:, 0].max()) / 2
        radius = min(rose["value"] * scale / 2, np.ptp(points[:, 0]) * .44)
        if radius < .4:
            notes.append("Omitted detail below the print floor: transept rose window.")
            continue
        z = eave - radius * .88
        profile, tracery = rose_profile(radius)
        before = len(cuts)
        for sign in (-1, 1):
            axis = sign * crosswise
            x = _face_at(man, axis, lengthwise, centre, z)
            if x is None:
                continue
            nominal = (points[:, 1] * sign).min()
            if abs(x - nominal) <= max(2, scale * 1.8):
                cuts.append(_relief_cut(profile, axis * x + lengthwise * centre,
                                        lengthwise, -axis, z, 1.3))
        if not tracery and len(cuts) > before:
            notes.append("Omitted detail below the print floor: transept rose tracery.")
    if cuts:
        notes.append(f"Carved {len(cuts)} transept rose windows from their published diameter.")
    return cuts
