"""Small style relief kits over measured massing, with dimensions in millimetres."""
from __future__ import annotations

import math
import re

import numpy as np


def style_keys(styles):
    if isinstance(styles, str):
        styles = [styles]
    text = " ".join(str(s) for s in styles or []).lower()
    return {key for key, pattern in {
        "gothic": r"gothic", "romanesque": r"romanesque|norman",
        "byzantine": r"byzantine|ottoman", "mughal": r"mughal|islamic|indo-islamic",
        "baroque": r"baroque|renaissance|palladian", "russian": r"russian|onion",
        "steel": r"steel|lattice|structural expression|industrial|wrought iron|iron architecture",
    }.items() if re.search(pattern, text)}


def _place(solid, u, outward, origin):
    # Local profile axes are facade horizontal, vertical; extrusion points inward.
    A = np.array([[u[0], 0, -outward[0]], [u[1], 0, -outward[1]], [0, 1, 0.]])
    # Depending on contour winding this can be a reflection, accepted by Manifold.
    return solid.transform(np.c_[A, origin].tolist())


def _exposed(man, cs, z, *, min_span=7):
    """Broad edges with air outside at a mid-wall slice, not internal part seams."""
    import manifold3d as m3
    scene = man.slice(z)
    found = []
    for ring in cs.to_polygons():
        p = np.asarray(ring)
        for a, b in zip(p, np.roll(p, -1, axis=0)):
            size = float(np.linalg.norm(b - a))
            if size < min_span:
                continue
            u = (b - a) / size
            normal = np.array([u[1], -u[0]])
            mid = (a + b) / 2
            probe = m3.CrossSection.circle(.15, 8).translate((mid + normal * .35).tolist())
            if (probe ^ scene).area() > .001:
                normal = -normal
                probe = m3.CrossSection.circle(.15, 8).translate((mid + normal * .35).tolist())
            if (probe ^ scene).area() < .001:
                found.append((size, a, b, u, normal))
    return sorted(found, key=lambda item: -item[0])


def _arch(width, height, pointed):
    if pointed:
        return [(-width / 2, 0), (width / 2, 0), (width / 2, height * .68),
                (width * .30, height * .84), (0, height), (-width * .30, height * .84), (-width / 2, height * .68)]
    return [(-width / 2, 0), (width / 2, 0), (width / 2, height - width / 2),
            *[(width / 2 * math.cos(a), height - width / 2 + width / 2 * math.sin(a))
              for a in np.linspace(0, math.pi, 13)]]


def _relief_cut(profile, mid, u, outward, z, depth, *, chamfer=True):
    cut = profile.extrude(depth + .06)
    if chamfer:
        cut = cut.transform([[1, 0, 0, 0], [0, 1, -1, 0], [0, 0, 1, 0]])
    return _place(cut, u, outward, [*(mid + outward * .03), z])


def chhatri(cs, eave, height):
    """Open roof pavilion: eight columns carry a flat circular canopy plate."""
    import manifold3d as m3

    x0, y0, x1, y1 = cs.bounds()
    centre = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    radius = min(x1 - x0, y1 - y0) / 2
    disk = m3.CrossSection.circle(radius, 32).translate(centre.tolist())
    pieces = [disk.extrude(1).translate([0, 0, eave - .93]),
              disk.extrude(1).translate([0, 0, eave - height - .2])]
    for theta in np.linspace(0, 2 * math.pi, 8, endpoint=False):
        p = centre + radius * .76 * np.array([math.cos(theta), math.sin(theta)])
        pieces.append(m3.Manifold.cylinder(height + .2, max(.72, radius * .11), circular_segments=12)
                      .translate([*p, eave - height - .2]))
    return pieces


def _surveyed_west_facade(man, width, height, x, middle, along, across, facts, protected, notes):
    """Build the surveyed gable, portal bays and paired buttress spires."""
    import manifold3d as m3

    from .landmark import _section, _union

    silhouette = facts["west_facade_profile"]["value"]
    crown = [(p * width, h * height) for p, h in silhouette]
    right, left = crown[-1][0], crown[0][0]
    gable = _section([[(left, -.1), (right, -.1), *reversed(crown)]])
    point = x * along + middle * across
    z0 = 2.
    origin = [*point, z0]
    depth = max(5., width * .095)
    wall = _place(gable.extrude(depth), across, -along, origin)
    # The OSM west gable is generalized as a level block. The back of this
    # shallow replacement remains embedded in the surveyed building volume.
    envelope = m3.CrossSection.square([width + .04, height], True).translate([0, height / 2])
    trim = _place((envelope - gable).extrude(depth * .72), across, -along, [*(point - along * .01), z0])
    if protected:
        trim = trim - _union(protected)
    man = (man - trim) + wall

    additions, cuts = [], []
    for where, peak in facts["west_buttress_spires"]["value"]:
        shoulder = float(np.interp(where, *np.asarray(silhouette).T)) * height
        xy = point + where * width * across - along * .55
        section = m3.CrossSection.square([3.8, 3.4], True).translate(xy.tolist())
        foot = section.offset(.5).extrude(height * .09).translate([0., 0., z0 - .06])
        pier = section.extrude(shoulder + .1, scale_top=[.86, .86]).translate([0., 0., z0 - .04])
        additions.extend([foot, pier])
        for shift in (() if "spire_plan" in facts else (-1.05, 1.05)):
            spot = xy + shift * across
            tip_height = peak * height - abs(shift) * .12
            spire_height = tip_height - shoulder + 1.6
            spire = m3.Manifold.cylinder(spire_height, 1.30, .83, 8)
            additions.append(spire.translate([*spot, z0 + shoulder - 1.5]))

    for offset in np.arange(left + 2., right - 1.8, 2.45):
        crest = float(np.interp(offset, *np.asarray(crown).T))
        tip = _section([[(-.64, -.72), (.64, -.72), (.57, .26), (0, 1.74), (-.57, .26)]])
        xy = point + offset * across
        additions.append(_place(tip.extrude(1.25), across, -along, [*(xy - along * .65), z0 + crest]))

    for index, where in enumerate((-.36, -.21, 0, .21, .36)):
        central = index == 2
        inner = abs(where) < .3
        xy = point + where * width * across
        series = [(width * (.142 if central else .082), height * (.22 if central else .137), .006, False),
                  (width * (.105 if central else .071), height * .135, .28 if central else .175, False),
                  (width * (.138 if central else .069), height * (.25 if central else .11),
                   .51 if central else .35 if inner else .32, True)]
        for tier, (w, h, base, pointed) in enumerate(series):
            if w < .8 or h < 1.6:
                notes.append("Omitted detail below the print floor: surveyed facade portal or window.")
                continue
            z = z0 + base * height
            opening = _section([_arch(w, h, pointed)])
            recess = opening
            if tier > 0 and w >= 3.2:
                mullion = m3.CrossSection.square([.95, h * .88], True).translate([0, h * .41])
                recess = opening - mullion
            cut = _relief_cut(recess, xy, across, -along, z, 4.6 if central else 3.25)
            cuts.append(cut.trim_by_plane((0, 0, 1), z0 + .04) if tier == 0 else cut)
            outer = _section([_arch(w + 2.2, h + 1.65, pointed)]).translate([0, -.14])
            jamb = _place((outer - opening).extrude(1.45), across, -along, [*(xy - along * .78), z])
            additions.append(jamb)
    return _union([man - _union(cuts), *additions])


def _west_facade(man, outline, facts, scale, notes, westward=None, *, records=(), sections=()):
    """Locate the facade on the foot survey and cut the portal bays into its wall."""
    import manifold3d as m3

    from .landmark import _frame, _section
    from .landmark_gothic import rose_profile, west_details

    if outline.is_empty():
        return man, [], []
    R, _, spans = _frame(outline, {})
    along = R[0] if R[0][0] >= 0 else -R[0]
    if westward is not None:
        along = -westward
    across = np.array([-along[1], along[0]])
    coords = np.concatenate(outline.to_polygons())
    x = coords @ along
    front = coords[x < x.min() + max(4, spans[0] * .055)] @ across
    if len(front) < 2 or np.ptp(front) < 12:
        return man, [], []
    width = min(float(np.ptp(front)), facts.get("west_facade_width_m", {}).get("value", math.inf) * scale)
    middle = (float(front.min()) + float(front.max())) / 2
    count = facts.get("west_portals", {}).get("value", 3)
    if not count:
        return man, [], []
    facade_h = facts.get("west_facade_height_m", {}).get("value", 0) * scale or width * .67
    if "west_facade_profile" in facts and "west_buttress_spires" in facts:
        plane = float(x.min())
        front_depth = max(5., width * .095)
        protected = [section.offset(.12).extrude(2 + facade_h)
                     for record, section in zip(records, sections) if record.get("spire_id") is not None
                     and (np.concatenate(section.to_polygons()) @ along).min() < plane + front_depth]
        man = _surveyed_west_facade(man, width, facade_h, plane + .2, middle, along, across, facts, protected, notes)
        return man, [], []
    gaps = width * .58 / max(2, count - 1)
    cavities, additions = [], []

    def face(y, z):
        # Intersect the measured slice with the local westward ray.
        xs = []
        for ring in man.slice(z).to_polygons():
            p = np.asarray(ring)
            xx, yy = p @ along, p @ across
            for a, b in zip(range(len(p)), np.roll(np.arange(len(p)), -1)):
                if (yy[a] > y) != (yy[b] > y):
                    xs.append(xx[a] + (xx[b] - xx[a]) * (y - yy[a]) / (yy[b] - yy[a]))
        return min(xs) if xs else None

    for index in range(count):
        offset = index - (count - 1) / 2
        y = middle + gaps * offset
        central = abs(offset) < .1
        h = facade_h * (.39 if central else .27)
        w = min(gaps * .7, width * (.18 if central else .115))
        if w < .8:
            notes.append("Omitted detail below the print floor: west facade portal.")
            continue
        z = 2.35
        x0 = face(y, z + h * .35)
        if x0 is None:
            continue
        p = x0 * along + y * across
        profile = _section([_arch(w, h, True)])
        relief = max(.6, min(1.5, w * .20))
        cut = _relief_cut(profile, p, across, -along, z, relief)
        rim = _section([_arch(w + 1.7, h + 1.2, True)]).translate([0, -.08]) - profile
        trim = _place(rim.extrude(.95), across, -along, [*(p - along * .48), z])
        cavities.append(cut)
        additions.append(trim)

    rose = facts.get("rose_width_ratio", {}).get("value", .19)
    radius = width * rose / 2
    z = 2 + facade_h * .64
    x0 = face(middle, z)
    if x0 is not None and radius >= .4:
        centre_xy = x0 * along + middle * across
        disk = m3.CrossSection.circle(radius, 32)
        profile, tracery = rose_profile(radius)
        cavities.append(_relief_cut(profile, centre_xy, across, -along, z, .95))
        if not tracery:
            notes.append("Omitted detail below the print floor: west rose tracery.")
        ring = m3.CrossSection.circle(radius + .85, 32) - disk
        additions.append(_place(ring.extrude(.9), across, -along, [*(centre_xy - along * .35), z]))
    elif rose > 0 and x0 is not None:
        notes.append("Omitted detail below the print floor: west rose window.")
    elif rose == 0 and x0 is not None:
        # Some surveys show a pointed west window in the position a rose occupies.
        w = width * .16
        h = facade_h * .32
        p = x0 * along + middle * across
        window = _section([_arch(w, h, True)])
        cavities.append(_relief_cut(window, p, across, -along, z - h * .45, 1.5))
        jambs = _section([_arch(w + 1.7, h + 1.2, True)]).translate([0, -.08]) - window
        mullions = m3.CrossSection.square([.8, h * .68]).translate([-.4, -.1])
        trim = _place((jambs + mullions).extrude(.9), across, -along,
                      [*(p - along * .35), z - h * .45])
        additions.append(trim)
    if facts.get("facade_pinnacles", {}).get("value"):
        for index in range(count + 1):
            offset = (index - count / 2) * width / (count + 1)
            y = middle + offset
            shoulder = 2 + facade_h * (1 - .15 * abs(offset) / (width / 2))
            position = next(((x, z) for z in np.arange(shoulder, max(12, shoulder - 14), -1.25)
                             if (x := face(y, z)) is not None), None)
            if position is None:
                continue
            x0, z = position
            p = (x0 + .55) * along + y * across
            radius = max(.85, min(1.6, width * .021))
            peak = m3.Manifold.cylinder(max(3.1, width * .085), radius, .8, 8)
            additions.append(peak.translate([*p, z - 1.8]))
    cuts, trim = west_details(man, face, middle, width, facade_h, along, across, scale, facts, notes)
    return man, cavities + cuts, additions + trim


def _masonry_cut(profile, mid, u, outward, z, depth):
    cut = _place(profile.extrude(depth + .06).transform(
        [[1, 0, 0, 0], [0, 1, -1, 0], [0, 0, 1, 0]]), u, outward, [*(mid + outward * .03), z])
    return cut.trim_by_plane((0, 0, 1), z + profile.bounds()[1] - .04)


def _iwans(man, cs, base, height, facts, notes):
    import manifold3d as m3

    from .landmark import _section

    cuts, additions = [], []
    # OSM sometimes inserts a nearly collinear vertex where adjoining surveys
    # meet. Across that join the portal still belongs to a single facade.
    for span, a, b, u, outward in _exposed(man, cs.simplify(.15), base + height * .48, min_span=.8)[:4]:
        mid = (a + b) / 2
        width = span * facts["iwan_width_ratio"]["value"]
        rise = height * facts["iwan_height_ratio"]["value"]
        reach = width * .20
        frame = width * .062
        if min(reach, width, frame) < .8 or rise < reach + .8:
            notes.append("Omitted detail below the print floor: iwan moldings, openings and frames.")
            continue
        z = base + height * .035
        arch = _section([_arch(width, rise, True)])
        cuts.append(_masonry_cut(arch, mid, u, outward, z, reach))
        # The monument has a rectangular pishtaq around the curved arch,
        # and two smaller doorways on the back wall of the deep recess.
        frame_out = m3.CrossSection.square([width + 4 * frame, rise + 2 * frame], True)
        frame_in = m3.CrossSection.square([width + 2 * frame, rise], True)
        mold = (frame_out - frame_in).translate([0, rise / 2])
        additions.append(_place(mold.extrude(1.2), u, outward, [*(mid + outward * .8), z]))
        for shift, width_ratio, rise_ratio in ((.03, .43, .36), (.47, .31, .20)):
            back = _section([_arch(width * width_ratio, rise * rise_ratio, True)])
            door = mid - outward * (reach - .06)
            cuts.append(_masonry_cut(back, door, u, outward, z + shift * rise, reach * .32))
        # The tall central bay is flanked by a pair of stacked blind niches
        # on each side, with uninterrupted wall between the two storeys.
        for side in (-1, 1):
            pos = mid + side * span * .31 * u
            niche_w, niche_h = span * .115, height * .31
            for fraction in (.035, .445):
                niche = _section([_arch(niche_w, niche_h, True)])
                cuts.append(_masonry_cut(niche, pos, u, outward, base + height * fraction, reach * .45))
    if cuts:
        notes.append("Recessed the iwans, cut stacked doorways in their back walls and framed the flanking bays.")
    return cuts, additions


def _platform_arcade(man, cs, base, height, facts, notes):
    import manifold3d as m3

    from .landmark import _section

    cuts = []
    depth = min(1.6, height * .18)
    if depth < .6 or height * .19 < .8:
        notes.append("Omitted detail below the print floor: the platform arcading.")
        return cuts
    edges = _exposed(man, cs, base + height * .5)
    if not edges:
        return cuts
    longest = edges[0][0]
    for span, a, b, u, outward in edges:
        # The terrace stairwell interrupts two lengths of the facade. Keep
        # those panels on the same pitch without forcing them across the stair.
        if span < longest * .24:
            break
        count = max(1, round(facts["platform_arcade"]["value"] * span / longest))
        pitch = span / (count + 1)
        width = pitch * .67
        if min(width, pitch - width) < .8:
            notes.append("Omitted detail below the print floor: the platform arcading.")
            continue
        arch = _section([_arch(width, height * .55, True)])
        panel = m3.CrossSection.square([width, height * .19], True)
        for i in range(1, count + 1):
            mid = a + (b - a) * i / (count + 1)
            cuts.extend([_masonry_cut(arch, mid, u, outward, base + height * .05, depth),
                         _masonry_cut(panel, mid, u, outward, base + height * .75, .65)])
    if cuts:
        notes.append("Recessed the platform's blind arcades and rectangular upper panels.")
    return cuts


def _classical_details(man, rec, cs, lo, eave, scale, notes):
    import manifold3d as m3

    from .landmark import _section

    additions, cuts = [], []
    height = eave - lo
    if rec.get("peristyle_column"):
        span = min(np.ptp(np.asarray(cs.bounds()).reshape(2, 2), axis=0))
        if span < 1.35:
            notes.append("Omitted detail below the print floor: the colonnade bases and capitals.")
        else:
            for z in (lo, eave - 1.02):
                additions.append(cs.offset(.32).extrude(1.05).translate([0, 0, z]))
            notes.append("Shaped bases and capitals on the open lower drum colonnade.")
    if rec.get("peristyle_core"):
        # The mapped core runs up behind the freestanding columns and above
        # their entablature. The attic's upper row reads as punched openings.
        x, y, xx, yy = cs.bounds()
        centre = np.array([(x + xx) / 2, (y + yy) / 2])
        radius = min(xx - x, yy - y) / 2
        count = rec["peristyle_core"]
        pitch = 2 * math.pi * radius / count
        if pitch * .45 < .8 or 1.1 * scale < .8:
            notes.append("Omitted detail below the print floor: upper drum window bays.")
        else:
            for theta in np.linspace(0, 2 * math.pi, count, endpoint=False):
                normal = np.array([math.cos(theta), math.sin(theta)])
                u = np.array([-normal[1], normal[0]])
                window = m3.CrossSection.square([pitch * .45, 2.3 * scale], True)
                cuts.append(_masonry_cut(window, centre + normal * (radius + .12), u, normal,
                                          eave - 3.15 * scale, .9))
            notes.append("Recessed the upper drum's window bays above the stone gallery.")
    if rec.get("lantern_body"):
        if height < 2.8:
            notes.append("Omitted detail below the print floor: the lantern windows.")
            return cuts, additions
        for span, a, b, u, outward in _exposed(man, cs, lo + height * .5, min_span=.8)[:4]:
            width = span * .55
            if width < .8:
                notes.append("Omitted detail below the print floor: the lantern windows.")
                continue
            window = _section([_arch(width, height * .66, False)])
            cuts.append(_masonry_cut(window, (a + b) / 2, u, outward, lo + height * .17, 1.0))
        if cuts:
            notes.append("Cut four shadowed openings in the square lantern.")
    if rec.get("cupola_seat"):
        cut_count = 0
        for span, a, b, u, outward in _exposed(man, cs, eave - height * .085):
            radius = min(span * .17, height * .054)
            if radius < .8:
                continue
            oculus = m3.CrossSection.circle(radius, 24)
            cuts.append(_relief_cut(oculus, (a + b) / 2, u, outward, eave - radius * 1.5, 1.05))
            cut_count += 1
        if cut_count:
            notes.append(f"Recessed {cut_count} round windows in the exposed faces of the octagonal drum.")
        else:
            notes.append("Omitted detail below the print floor: the octagonal drum windows.")
    return cuts, additions


def _bell_tower_details(man, cs, lo, height, notes):
    from .landmark import _section

    cuts, additions = [], []
    for span, a, b, u, outward in _exposed(man, cs.simplify(.12), lo + height * .74):
        width = span * .20
        if width < .8 or height * .09 < 1.6:
            continue
        for fraction, rise in ((.36, .09), (.54, .10), (.72, .16)):
            recess = _section([_arch(width, height * rise, True)])
            for bay in (.33, .67):
                cuts.append(_relief_cut(recess, a + (b - a) * bay, u, outward,
                                        lo + fraction * height, 1.25))
    if cuts:
        from .landmark import _loft

        radius = max(np.ptp(np.asarray(cs.bounds()).reshape(2, 2), axis=0)) / 2
        for fraction in (.34, .52, .70, .99):
            additions.append(_loft(cs, lo + height * fraction - 1., 1., [(0, 1), (1, 1 + .8 / radius)], notes))
        notes.append("Set back pointed belfry openings between the cornices of the mapped bell tower.")
    else:
        notes.append("Omitted detail below the print floor: belfry openings and cornices.")
    return cuts, additions


def _aisle_and_lantern_windows(man, rec, cs, lo, eave, scale, bay, notes):
    import manifold3d as m3

    from .landmark import _frame, _section

    aisle = rec["feature"] == "aisle_walls"
    height = eave - lo if aisle else rec["lantern_rise_m"] * scale
    if height < 3.2:
        notes.append("Omitted detail below the print floor: aisle or lantern windows.")
        return []
    frame, _, _ = _frame(cs, {})
    cuts = []
    contour = cs.simplify(.16 if aisle else .28)
    for span, a, b, u, normal in _exposed(man, contour, eave - height * .36, min_span=2.8):
        if aisle and abs(frame[0] @ u) < .92:
            continue
        count = max(1, round(span / (bay * scale))) if aisle else 1
        pitch = span / count
        width = pitch * (.67 if aisle else .61)
        if width < 1.8:
            continue
        rise = height * (.62 if aisle else .68)
        arch = _section([_arch(width, rise, True)])
        if width >= 3.3:
            arch = arch - m3.CrossSection.square([.9, rise]).translate([-.45, 0])
        for index in range(count):
            mid = a + (b - a) * ((index + .5) / count)
            cuts.append(_relief_cut(arch, mid, u, normal, eave - .85 * height, 2.2 if aisle else 1.5))
    if cuts:
        notes.append(f"Cut {len(cuts)} pointed {'aisle' if aisle else 'crossing lantern'} window recesses from the surveyed plan.")
    return cuts


def decorate(man, records, sections, scale, styles, facts=None, outline=None, *, westward=None):
    import manifold3d as m3
    from .landmark import _loft, _section, _union

    keys = style_keys(styles)
    facts = facts or {}
    if not keys:
        return man, ["No recognized style kit: retained measured massing without invented ornament."]
    additions, cavities, notes = [], [], []
    maximum_top = max((2 + r["height"]["metres"] * scale for r in records), default=0)
    facade = keys & {"gothic", "romanesque", "mughal", "byzantine", "baroque"}
    # Work from the unadorned union so neighboring parts mask their shared walls.
    if "gothic" in keys and outline is not None:
        from .landmark_gothic import transept_details

        man, front_cuts, front_trim = _west_facade(
            man, outline, facts, scale, notes, westward, records=records, sections=sections)
        cavities.extend(front_cuts)
        additions.extend(front_trim)
        cavities.extend(transept_details(man, records, sections, outline, scale, facts, notes))
        if front_cuts:
            notes.append("Recessed the west facade portals and any sourced rose window.")
        if "west_facade_profile" in facts:
            notes.append("Rebuilt the west gable, portal bays and buttress piers from the facade survey.")
    for rec, cs in zip(records, sections):
        lo = 2 + rec["min_height"]["metres"] * scale
        top = 2 + rec["height"]["metres"] * scale
        eave = top - rec["roof_height"]["metres"] * scale
        wall_height = eave - lo
        if rec.get("main_faces") and {"iwan_width_ratio", "iwan_height_ratio"} <= facts.keys():
            platform = next((2 + p["height"]["metres"] * scale for p in records if p.get("platform_arcade")),
                            lo + wall_height * .165)
            cuts, frames = _iwans(man, cs, platform, eave - platform, facts, notes)
            cavities.extend(cuts)
            additions.extend(frames)
        if rec.get("platform_arcade"):
            cavities.extend(_platform_arcade(man, cs, lo, wall_height, facts, notes))
        if "baroque" in keys:
            cuts, trim = _classical_details(man, rec, cs, lo, eave, scale, notes)
            cavities.extend(cuts)
            additions.extend(trim)
        if rec.get("feature") == "bell_tower" and "gothic" in keys:
            cuts, trim = _bell_tower_details(man, cs, lo, wall_height, notes)
            cavities.extend(cuts)
            additions.extend(trim)
        if rec.get("feature") in {"aisle_walls", "crossing_lantern"} and "aisle_bay_m" in facts:
            cavities.extend(_aisle_and_lantern_windows(man, rec, cs, lo, eave, scale,
                                                        facts["aisle_bay_m"]["value"], notes))
        if rec.get("dome_drum_m"):
            drum = rec["dome_drum_m"] * scale
            for z in (eave - drum, eave - .45):
                additions.append(cs.offset(.42).extrude(.78).translate([0, 0, z - .22]))
        if (facade and wall_height > 9 and rec.get("feature") not in {"bell_tower", "aisle_walls", "crossing_lantern"} and
                not (rec.get("main_faces") or rec.get("platform_arcade") or rec.get("lantern_body"))):
            exposed = _exposed(man, cs, lo + wall_height * .5)
            for span, a, b, u, outward in exposed[:6]:
                count = min(12, max(1, int(span / 9)))
                bay = span / (count + 1)
                for i in range(1, count + 1):
                    mid = a + (b - a) * i / (count + 1)
                    width = min(3.4, bay * .50)
                    height = min(10, wall_height * .48)
                    z = lo + wall_height * .28
                    # A recess only enters a sufficiently broad backing wall.
                    inside = m3.CrossSection.square([1.8, 1.8], True).translate((mid - outward * 1.3).tolist())
                    scene = man.slice(z + height * .5)
                    if (inside - scene).area() < .01 and width >= 1.4:
                        profile = _section([_arch(width, height, "gothic" in keys or "mughal" in keys)])
                        depth = .6
                        # Lower the complete cavity profile by its inward depth.
                        # This keeps every ceiling shoulder at least 45 degrees.
                        cut = profile.extrude(depth + .04).transform(
                            [[1, 0, 0, 0], [0, 1, -1, 0], [0, 0, 1, 0]])
                        cavities.append(_place(cut, u, outward, [*(mid + outward * .02), z]))
                    if "gothic" in keys and wall_height > 14:
                        ribmid = a + (b - a) * (i - .45) / (count + 1)
                        projection, height_rib = .9, wall_height * .92
                        profile = _section([[(-.20, lo - .02), (0, lo - .02),
                                             (projection, lo + projection),
                                             (projection, lo + height_rib - projection),
                                             (0, lo + height_rib)]])
                        rib = profile.extrude(1.2).translate([0, 0, -.6])
                        # rib profile horizontal -> outward, extrusion -> facade
                        A = [[outward[0], 0, u[0], ribmid[0]],
                             [outward[1], 0, u[1], ribmid[1]], [0, 1, 0, 0]]
                        additions.append(rib.transform(A))
        title = " ".join(str(rec["tags"].get(k, "")) for k in ("building:part", "tower:type", "name"))
        if ("gothic" in keys and "spire_plan" not in facts and rec.get("feature") != "bell_tower"
                and wall_height > 14 and top > maximum_top * .40):
            # Corners are inset into the shaft so each base has a full-width bond.
            # Limit the tops to the tallest measured part.
            x0, y0, x1, y1 = cs.bounds()
            broad = min(x1 - x0, y1 - y0)
            if broad >= 7 and (rec["spire"] or re.search(r"tower|turm|spire|steeple", title, re.I)):
                centre = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
                ring = max(cs.to_polygons(), key=len)
                corners = []
                for target in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
                    vertex = min(ring, key=lambda p: np.linalg.norm(np.asarray(p) - target))
                    vector = centre - vertex
                    if np.linalg.norm(vector) < .01:
                        continue
                    point = np.asarray(vertex) + vector / np.linalg.norm(vector) * 1.5
                    if any(np.linalg.norm(point - prior) < 1.8 for prior in corners):
                        continue
                    base = m3.CrossSection.circle(.85, 12).translate(point.tolist())
                    if (base - man.slice(eave - .2)).area() > .02:
                        continue
                    height = min(4, max(0, maximum_top - eave), wall_height * .25)
                    if height < 1:
                        continue
                    pinnacle = base.extrude(height + .25, scale_top=[.95, .95]).translate([0, 0, eave - .25])
                    additions.append(pinnacle)
                    corners.append(point)
        if keys & {"byzantine", "baroque", "russian"} and rec["roof_shape"] in ("dome", "onion"):
            rh = top - eave
            if rh > 4:
                # The support-safe band grows out of the dome wall over its own height.
                drum_h = min(1.2, rh * .12)
                x0, y0, x1, y1 = cs.bounds()
                radius = max(x1 - x0, y1 - y0) / 2
                flare = min(.06, drum_h / max(radius, .01))
                drum = _loft(cs, eave - .04, drum_h, [(0, 1), (1, 1 + flare)], notes)
                additions.append(drum)
                if "russian" in keys and rec["roof_shape"] == "dome":
                    notes.append("Russian style retained the mapped dome profile; onion shapes require an onion roof tag.")
                # The narrow lantern is wider than the truncated roof tip and ends at its original height.
                x0, y0, x1, y1 = cs.bounds()
                centre = [(x0 + x1) / 2, (y0 + y1) / 2]
                cap_h = max(.2, min(1.8, rh * .16))
                lantern = (m3.CrossSection.circle(.85, 20).extrude(cap_h + .02,
                           scale_top=[1.05 / .85, 1.05 / .85])
                           .translate([*centre, top - cap_h - .02]))
                additions.append(lantern)
        if "mughal" in keys and re.search("minaret", title, re.I) and wall_height > 8:
            for fraction in (.33, .66):
                z = lo + fraction * wall_height
                # Bands flare no faster than their rise and remain attached.
                x0, y0, x1, y1 = cs.bounds()
                radius = max(x1 - x0, y1 - y0) / 2
                flare = min(.04, .8 / max(radius, .01))
                additions.append(_loft(cs, z, .8, [(0, 1), (1, 1 + flare)], notes))
        if "steel" in keys and wall_height > 8:
            for span, a, b, u, outward in _exposed(man, cs, lo + wall_height * .5)[:4]:
                h = min(wall_height - 2.1, span)
                slope_rise = math.sqrt(1 + (h / (span * .8)) ** 2)
                for sign in (-1, 1):
                    mid = (a + b) / 2
                    # Diagonal relief on measured solid backing, not invented voids.
                    profile = _section([[(-span * .4, 0), (-span * .4 + 1.2, 0),
                                         (span * .4, sign * h), (span * .4 - 1.2, sign * h)]])
                    rib = profile.extrude(.65).transform(
                        [[1, 0, 0, 0], [0, 1, slope_rise, 0], [0, 0, 1, 0]])
                    z = lo + .5 if sign > 0 else lo + h + .5
                    additions.append(_place(rib, u, -outward, [*(mid - outward * .10), z]))
    # Never union style fragments that do not overlap the existing measured mass.
    attached = [solid for solid in additions if not solid.is_empty() and (solid ^ man).volume() > 1e-5]
    discarded = len(additions) - len(attached)
    additions = attached
    if discarded:
        notes.append(f"Left out {discarded} style solids that did not meet the mapped massing.")
    if cavities:
        man = man - _union(cavities)
        notes.append(f"Cut {len(cavities)} chamfered architectural recesses into exposed walls.")
    if additions:
        man = _union([man, *additions])
        notes.append(f"Added {len(additions)} supported style ribs, dome bands or lantern details inside mapped top heights.")
    notes.append("Style kit: " + ", ".join(sorted(keys)) + "; measured massing takes precedence over ornament.")
    return man, notes
