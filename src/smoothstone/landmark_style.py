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


def _exposed(man, cs, z):
    """Broad edges with air outside at a mid-wall slice, not internal part seams."""
    import manifold3d as m3
    scene = man.slice(z)
    found = []
    for ring in cs.to_polygons():
        p = np.asarray(ring)
        for a, b in zip(p, np.roll(p, -1, axis=0)):
            size = float(np.linalg.norm(b - a))
            if size < 7:
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
        cut = cut.transform([[1, 0, 0, 0], [0, 1, -.65, 0], [0, 0, 1, 0]])
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


def _surveyed_west_facade(man, width, height, x, middle, along, across, facts):
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
    man = (man - trim) + wall

    additions, cuts = [], []
    for where, peak in facts["west_buttress_spires"]["value"]:
        shoulder = float(np.interp(where, *np.asarray(silhouette).T)) * height
        xy = point + where * width * across + along * .8
        section = m3.CrossSection.square([3.4, 3.0], True).translate(xy.tolist())
        foot = section.offset(.5).extrude(height * .09).translate([0., 0., z0 - .06])
        pier = section.extrude(shoulder + .1, scale_top=[.86, .86]).translate([0., 0., z0 - .04])
        additions.extend([foot, pier])
        for shift in (-1.05, 1.05):
            spot = xy + shift * across
            tip_height = peak * height - abs(shift) * .12
            spire_height = tip_height - shoulder + 1.6
            spire = m3.Manifold.cylinder(spire_height, 1.30, .83, 8)
            additions.append(spire.translate([*spot, z0 + shoulder - 1.5]))

    for index, where in enumerate((-.36, -.21, 0, .21, .36)):
        central = index == 2
        inner = abs(where) < .3
        xy = point + where * width * across
        series = [(width * (.106 if central else .066), height * (.178 if central else .126), .004, False),
                  (width * (.085 if central else .056), height * .135, .28 if central else .175, False),
                  (width * (.098 if central else .055), height * (.21 if central else .11),
                   .51 if central else .35 if inner else .32, True)]
        for w, h, base, pointed in series:
            z = z0 + base * height
            opening = _section([_arch(w, h, pointed)])
            cuts.append(_relief_cut(opening, xy, across, -along, z, 2.7))
            outer = _section([_arch(w + 1.8, h + 1.3, pointed)]).translate([0, -.12])
            jamb = _place((outer - opening).extrude(1.05), across, -along, [*(xy - along * .58), z])
            additions.append(jamb)
    return _union([man - _union(cuts), *additions])


def _west_facade(man, outline, facts, scale):
    """Locate the facade on the foot survey and cut the portal bays into its wall."""
    import manifold3d as m3

    from .landmark import _frame, _section

    if outline.is_empty():
        return man, [], []
    R, _, spans = _frame(outline, {})
    along = R[0] if R[0][0] >= 0 else -R[0]
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
        man = _surveyed_west_facade(man, width, facade_h, float(x.min()) + .2, middle, along, across, facts)
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
        z = 2.35
        x0 = face(y, z + h * .35)
        if x0 is None:
            continue
        p = x0 * along + y * across
        profile = _section([_arch(w, h, True)])
        relief = min(1.5, w * .20)
        cut = _relief_cut(profile, p, across, -along, z, relief)
        rim = _section([_arch(w + 1.5, h + 1, True)]).translate([0, -.12]) - profile
        trim = _place(rim.extrude(.95), across, -along, [*(p - along * .48), z])
        cavities.append(cut)
        additions.append(trim)

    rose = facts.get("rose_width_ratio", {}).get("value", .19)
    radius = width * rose / 2
    z = 2 + facade_h * .64
    x0 = face(middle, z)
    if x0 is not None and radius > 1.4:
        centre_xy = x0 * along + middle * across
        disk = m3.CrossSection.circle(radius, 32)
        cavities.append(_relief_cut(disk, centre_xy, across, -along, z, .9))
        ring = m3.CrossSection.circle(radius + .55, 32) - disk
        additions.append(_place(ring.extrude(.9), across, -along, [*(centre_xy - along * .35), z]))
    elif rose == 0 and x0 is not None:
        # Some surveys show a pointed west window in the position a rose occupies.
        w = width * .16
        h = facade_h * .32
        p = x0 * along + middle * across
        window = _section([_arch(w, h, True)])
        cavities.append(_relief_cut(window, p, across, -along, z - h * .45, 1.5))
        jambs = _section([_arch(w + 1.4, h + 1, True)]).translate([0, -.12]) - window
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
    return man, cavities, additions


def decorate(man, records, sections, scale, styles, facts=None, outline=None):
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
        man, front_cuts, front_trim = _west_facade(man, outline, facts, scale)
        cavities.extend(front_cuts)
        additions.extend(front_trim)
        if front_cuts:
            notes.append("Recessed the west facade portals and any sourced rose window.")
        if "west_facade_profile" in facts:
            notes.append("Rebuilt the west gable, its five portal bays and paired buttress spires from the facade survey.")
    for rec, cs in zip(records, sections):
        lo = 2 + rec["min_height"]["metres"] * scale
        top = 2 + rec["height"]["metres"] * scale
        eave = top - rec["roof_height"]["metres"] * scale
        wall_height = eave - lo
        if rec.get("main_faces"):
            body_edges = _exposed(man, cs, lo + wall_height * .58)
            for span, a, b, u, outward in body_edges[:4]:
                mid = (a + b) / 2
                width = span * facts.get("iwan_width_ratio", {}).get("value", .30)
                base = wall_height * .165
                height = (wall_height - base) * facts.get("iwan_height_ratio", {}).get("value", .80)
                z = lo + base + .25
                reach = min(3.2, width * .23)
                profile = _section([_arch(width, height, True)])
                cavities.append(_relief_cut(profile, mid, u, outward, z, reach))
                frame = _section([_arch(width + 2, height + 1.35, True)]).translate([0, -.12]) - profile
                additions.append(_place(frame.extrude(1.3), u, outward, [*(mid + outward * .62), z]))
            if body_edges:
                notes.append(f"Recessed {min(4, len(body_edges))} pointed iwans and framed their openings.")
        if rec.get("dome_drum_m"):
            drum = rec["dome_drum_m"] * scale
            for z in (eave - drum, eave - .45):
                additions.append(cs.offset(.42).extrude(.78).translate([0, 0, z - .22]))
        if facade and wall_height > 9:
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
                        depth = .5
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
        if "gothic" in keys and wall_height > 14 and top > maximum_top * .40:
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
