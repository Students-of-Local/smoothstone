"""Parts of a figure from its shape: grooves, the side a color edge slips to, the ledge check."""
import numpy as np
import pytest
import trimesh

from smoothstone import colors as C
from smoothstone import parts
from smoothstone.clean import cut_iso


def _dense(profile, step=0.05):
    """The (r, z) profile with points every `step` mm along each segment."""
    out = [profile[0]]
    for a, b in zip(profile[:-1], profile[1:]):
        a, b = np.asarray(a, float), np.asarray(b, float)
        n = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
        out += [a + (b - a) * k / n for k in range(1, n + 1)]
    return np.array(out)


def _arc(c, r, a0, a1, n=60):
    t = np.radians(np.linspace(a0, a1, n))
    return [(c[0] + r * np.cos(x), c[1] + r * np.sin(x)) for x in t]


def _lathe(profile, sections=120):
    m = trimesh.creation.revolve(_dense(profile), sections=sections)
    return C.load_stl_mesh(np.asarray(m.vertices, float), np.asarray(m.faces))


def _head(neck_r, neck_top, head_r):
    """Arc of a ball of radius head_r from where it meets a neck of radius neck_r up to the top."""
    cz = neck_top + np.sqrt(head_r ** 2 - neck_r ** 2)
    a0 = np.degrees(np.arctan2(neck_top - cz, neck_r))
    return _arc((0.0, cz), head_r, a0, 90.0)


def collar_figure():
    """A torso, a standing collar ring round the neck (top sloping out and down), a neck and a
    ball head: the groove is where the collar's top meets the neck, at z 12."""
    prof = [(0, 0), (6, 0), (6, 10), (4.2, 10), (4.2, 11.7), (3, 12), (3, 16)] + _head(3, 16, 5)[1:]
    return _lathe(prof)


def cuff_figure():
    """A hand (a cylinder of radius 2.5) coming out of a sleeve of radius 4 whose rim overhangs it
    by 1.5 mm: the groove is where the rim's underside meets the hand, at z 10."""
    return _lathe([(0, 0), (2.5, 0), (2.5, 10), (4, 10), (4, 16), (0, 16)])


def neck_figure():
    """A neck (radius 3) under a ball head of radius 5 that overhangs it: the groove at z 16."""
    return _lathe([(0, 0), (3, 0), (3, 16)] + _head(3, 16, 5)[1:])


def _line(name, z, r):
    return {"name": name, "z": z, "center": [0.0, 0.0], "rmax": r + parts.SNAP, "ring": 2 * np.pi * r}


def test_head_over_neck_slips_up():
    ln = parts.find_groove(neck_figure(), _line("neck", 16.0, 3.0))
    g = ln["groove"]
    assert g["used"], g
    assert g["side"] == 1, g  # onto the underside of the head, which faces down
    assert g["seen"]["up"] < g["seen"]["down"]
    assert 15.9 < min(ln["curve"]) and max(ln["curve"]) < 16.5


def test_cuff_over_wrist_slips_down():
    ln = parts.find_groove(cuff_figure(), _line("wrist", 10.0, 2.5))
    g = ln["groove"]
    assert g["used"], g
    assert g["side"] == -1, g  # onto the hand under the rim: up would show a lip on the sleeve
    assert g["seen"]["down"] < g["seen"]["up"]
    assert 9.5 < min(ln["curve"]) and max(ln["curve"]) < 10.0


def test_no_groove_keeps_the_plane():
    m = _lathe([(0, 0), (4, 0), (4, 20), (0, 20)])  # a plain cylinder: nothing concave to follow
    ln = parts.find_groove(m, _line("hem", 10.0, 4.0))
    assert ln["curve"] is None and not (ln["groove"] or {}).get("used")


def _paint(m, line):
    """Cut along the line; faces above it white (2), below black (1)."""
    V, F = cut_iso(m.vertices, m.faces, parts.field(line, m.vertices), 0.0, snap=0.02)
    lab = np.where(parts.side_of(C.load_stl_mesh(V, F), line) > 0, 2, 1)
    return V, F, lab


def test_ledge_check_fails_a_plane_cut_through_the_collar_and_passes_the_groove():
    m = collar_figure()
    plane = {**_line("neck", 11.0, 4.2), "curve": None}
    V, F, lab = _paint(m, plane)
    bad = C.ledge_faults(C.ledges(V, F, lab, [plane]))
    assert bad and bad[0]["name"] == "neck" and bad[0]["fil"] == 2, bad  # the collar's top is white

    groove = parts.find_groove(m, _line("neck", 12.5, 3.0))
    assert groove["groove"]["used"] and groove["groove"]["side"] == 1, groove["groove"]
    assert 11.95 < np.median(groove["curve"]) < 12.6
    V, F, lab = _paint(m, groove)
    found = C.ledges(V, F, lab, [groove])
    assert not C.ledge_faults(found), found
    # the edge itself is clean, and watertight
    t = trimesh.Trimesh(V, F, process=False)
    assert t.is_watertight
    worst, lines = C.color_edges(V, F, lab)
    assert worst < C.JAGGED


def test_a_sleeve_sloping_in_past_its_cuff_rim_is_not_a_ledge_of_the_hand():
    """Eval (DHH): the cuff's color edge ran in the groove under the sleeve's rim, yet the ledge
    check failed it (0.34 mm2 at 45 degrees): above the rim the arm bends toward the body, so the
    sleeve's own outside faces up there, and every up-facing sleeve face within 2 mm counted as
    the sleeve's color climbing onto a ledge. The rim's underside and lip stand between them and
    the edge; only faces the edge runs onto are a ledge. Here a hand (radius 2.5) under a sleeve
    rim that overhangs it by 1.5 mm at z 10, with a 0.5 mm upright lip, and the sleeve's outside
    sloping in at 45 degrees from z 10.5 to 12."""
    m = _lathe([(0, 0), (2.5, 0), (2.5, 10), (4, 10), (4, 10.5), (2.5, 12), (2.5, 16), (0, 16)])
    cuff = {**_line("wrist", 10.0, 2.5), "side": 1, "curve": None}
    V, F, lab = _paint(m, cuff)
    found = C.ledges(V, F, lab, [cuff])
    assert not C.ledge_faults(found), found


def test_a_neck_with_no_groove_ends_at_the_top_of_the_shoulders_slope():
    """Eval (Elon): the neck's line was a level plane (the groove search found none), and at the
    sides the shoulders slope on up past it to where the neck stands up, so the head's color lay
    on 1.64 mm2 of that up-facing slope next to the edge. With no groove, the line runs along the
    top of the slope, as a shoe's rim does. Here shoulders (radius 8, top at z 5) slope in at 45
    degrees and round off into an upright neck (radius 4) at z 8.4 to 9.8; the neck's level is
    halfway up the slope, at z 7."""
    prof = [(0, 0), (8, 0), (8, 5)] + _arc((6.0, 9.828), 2.0, 225, 180) + [(4, 13), (0, 13)]
    m = _lathe(prof)
    anat = {"top": 0.0, "height": 13.0, "center": 0.0, "hem": None, "neck": 7.0, "wrists": [], "ankles": []}
    neck = next(ln for ln in parts.find_lines(m, anat) if ln["name"] == "neck")
    assert not (neck.get("groove") or {}).get("used"), neck.get("groove")
    V, F, lab = _paint(m, neck)
    found = C.ledges(V, F, lab, [neck])
    assert not C.ledge_faults(found), found
    assert neck.get("rim") and 8.4 < float(np.median(neck["curve"])) < 9.9, neck


_HEAD = [(6.0, 12.0)] + _arc((0.0, 12.0), 6.0, 0.0, 90.0, 12)[1:]
# a step at the front: the neck's upright wall from z 7.5 to 9.5, then the head's underside
_FRONT = [(0, 0), (8, 0), (8, 5), (6, 7.5), (6, 9.5), (4, 10.5)] + _HEAD
# at the back one slope from z 5 on up into the head's underside at z 10.5, over 3 mm (GROOVE_BAND)
# above the neck's level, so no groove runs all round
_BACK = [(0, 0), (8, 0), (8, 5), (8 - 2 * 4.5 / 5.5, 7), (5, 8 + 2 / 3), (3.5, 10.5)] + _HEAD
_STEP = [(0, 0), (8, 0), (8, 5), (5.5, 7.5), (5.5, 8.1), (4, 10.5)] + _HEAD  # the back with a riser in it


def _by_angle(front, back, sections=120, step=0.1):
    """A shape turned round z whose (r, z) profile is `front` at the front (-y) and `back` over
    the back half (within 50 degrees of +y, eased over the next 12): the two profiles have the
    same points, blended. Each segment is cut the same number of times all round."""
    front, back = np.asarray(front, float), np.asarray(back, float)
    n = [max(1, int(np.ceil(max(np.linalg.norm(f1 - f0), np.linalg.norm(b1 - b0)) / step)))
         for f0, f1, b0, b1 in zip(front[:-1], front[1:], back[:-1], back[1:])]
    rings = []
    phi = np.linspace(0, 2 * np.pi, sections, endpoint=False)
    for a in phi:
        off = abs((np.degrees(a) - 90 + 180) % 360 - 180)
        w = float(np.clip((62 - off) / 12, 0, 1))
        w = w * w * (3 - 2 * w)
        prof = front * (1 - w) + back * w
        pts = [prof[0]]
        for k in range(len(prof) - 1):
            pts += [prof[k] + (prof[k + 1] - prof[k]) * j / n[k] for j in range(1, n[k] + 1)]
        rings.append(np.array(pts))
    P = np.stack(rings)  # sections x points x (r, z); the first and last points lie on the axis
    m = P.shape[1]
    V = [[0.0, 0.0, P[0, 0, 1]]]
    for i in range(1, m - 1):
        for j, a in enumerate(phi):
            V.append([P[j, i, 0] * np.cos(a), P[j, i, 0] * np.sin(a), P[j, i, 1]])
    V.append([0.0, 0.0, P[0, -1, 1]])
    top = len(V) - 1

    def vid(i, j):
        return 1 + (i - 1) * sections + j % sections

    F = []
    for j in range(sections):
        F.append([0, vid(1, j + 1), vid(1, j)])
        F.append([top, vid(m - 2, j), vid(m - 2, j + 1)])
        for i in range(1, m - 2):
            F.append([vid(i, j), vid(i, j + 1), vid(i + 1, j + 1)])
            F.append([vid(i, j), vid(i + 1, j + 1), vid(i + 1, j)])
    mesh = C.load_stl_mesh(np.array(V), np.array(F))
    if mesh.volume < 0:
        mesh = C.load_stl_mesh(np.array(V), np.array(F)[:, ::-1])
    return mesh


_NECK_ANAT = {"top": 0.0, "height": 18.0, "center": 0.0, "hem": None, "neck": 7.0, "wrists": [], "ankles": []}


def _back_bins():
    """The neck's 10 degree bins (first degree from -180) whose middle is within 50 degrees of +y."""
    return [b for b in range(-180, 180, 10) if abs((b + 5 - 90 + 180) % 360 - 180) < 50]


def test_a_neck_that_slopes_on_into_the_head_with_no_step_is_skipped_only_where_it_does():
    """Eval (Elon): behind the ears the shoulders' slope runs on up into the skull's underside
    with no step for the neck's line to sit on. The rim walk took the line up to the skull there
    and widened that rise, so in the bins beside it, where the neck does step, the edge rode up
    onto the slope over the step (0.40 mm2 at 135 degrees). Where the walk runs all the way to the
    head's overhang the line stays level and the ledge check skips that bin, and says so; where
    there is a step the check holds. Here the front steps (slope to z 7.5, an upright wall to
    z 9.5) and the back slopes from z 5 straight into the head's underside at z 10.5; the neck's
    level is z 7."""
    m = _by_angle(_FRONT, _BACK)
    assert m.is_watertight
    neck = next(ln for ln in parts.find_lines(m, _NECK_ANAT) if ln["name"] == "neck")
    V, F, lab = _paint(m, neck)
    found = C.ledges(V, F, lab, [neck])
    assert not C.ledge_faults(found), found
    back = _back_bins()
    assert set(back) <= set(neck.get("nostep") or []), (neck.get("nostep"), back)
    assert not set(neck.get("nostep") or []) & {b for b in range(-180, 180, 10) if (b + 5) % 360 > 200}

    # the same neck with a riser in the back slope: a step, so no bin is skipped there, and a
    # line kept level across the back (as it is where there is no step) rides onto the slope
    m = _by_angle(_FRONT, _STEP)
    neck = next(ln for ln in parts.find_lines(m, _NECK_ANAT) if ln["name"] == "neck")
    assert not set(neck.get("nostep") or []) & set(back), neck.get("nostep")
    deg = np.arange(-180, 180)
    cv = np.asarray(neck["curve"], float)
    cv[abs((deg + 0.5 - 90 + 180) % 360 - 180) < 50] = 7.0
    level = {**neck, "curve": [float(v) for v in cv]}
    V, F, lab = _paint(m, level)
    bad = C.ledge_faults(C.ledges(V, F, lab, [level]))
    assert bad and abs((bad[0]["angle"] - 90 + 180) % 360 - 180) < 60, bad


def test_a_ledge_above_a_wall_of_its_own_color_is_not_the_edge_climbing_onto_it():
    """r3 (Donovan, 2026-11-18, black shoes under blue pants): a wrinkle of the trousers 1 mm over
    the shoe faces up and is blue, with blue trouser wall between it and the shoe's edge. The ledge
    check failed it, so the shoes fell back to white. Only a ledge the edge runs onto is a fault."""
    m = _lathe([(0, 0), (4.6, 0), (4.6, 11.2), (4.0, 11.2), (4.0, 16), (0, 16)])
    ankle = {**_line("ankle", 10.0, 4.6), "curve": None}
    V, F, lab = _paint(m, ankle)
    found = C.ledges(V, F, lab, [ankle])
    assert not C.ledge_faults(found), found
    # the same shape at a collar is the collar's top painted the head's color: still a fault
    neck = {**ankle, "name": "neck"}
    assert C.ledge_faults(C.ledges(V, F, lab, [neck]))


def _zoned(m, z, below, above, parts_by_zone):
    """The mesh cut level at z, a zone per face by its side, regions per zone (nothing merged), the
    region list with a part each (the largest region of a zone takes parts_by_zone[zone], the
    rest "other", but every torso piece is the top, as name_parts makes it) and the region number
    per face."""
    V, F = cut_iso(m.vertices, m.faces, np.asarray(m.vertices)[:, 2] - z, 0.0, snap=0.02)
    cm = C.load_stl_mesh(V, F)
    zone = np.where(parts.side_of(cm, {"z": z, "curve": None}) > 0, above, below)
    region = C.regions(cm, np.zeros(len(cm.faces), int), min_share=0.0, zone=zone)
    info = C.describe(cm, region, [None] * (int(region.max()) + 1), None)
    seen = set()
    for d in info:  # largest first
        zr = int(np.bincount(zone[region == d["region"]]).argmax())
        d["part"] = "other" if zr in seen and zr != parts.TORSO else parts_by_zone[zr]
        seen.add(zr)
    num = np.zeros(int(region.max()) + 1, int)
    for d in info:
        num[d["region"]] = d["n"]
    return cm, num[region], info


def _n(info, part):
    return next(d["n"] for d in info if d["part"] == part)


def _all(info, part):
    return [d["n"] for d in info if d["part"] == part]


def test_a_jacket_lip_boxed_in_under_the_hem_line_takes_the_jacket_color():
    """r3 (2026-11-18, Jensen in a black jacket over blue pants, rest white): the hem line ran in
    the slot under the jacket's lip at the back, so the lip's rim fell on the pants side, a region
    of its own that only the jacket touches. It took the rest color: a white stripe along the
    bottom of the jacket. A sliver boxed in by painted parts takes the color round it."""
    # pants (radius 4) up to the slot's top at 10; the jacket (5) above, its lip hanging to 9
    # round a slot 0.5 mm wide; the hem line at 9.6, inside the slot
    m = _lathe([(0, -40), (4, -40), (4, 10), (4.5, 10), (4.5, 9), (5, 9), (5, 100), (0, 100)])
    cm, num, info = _zoned(m, 9.6, parts.LEGS, parts.TORSO, {parts.LEGS: "pants", parts.TORSO: "top"})
    pants = _n(info, "pants")
    rim = [d["n"] for d in info if d["part"] == "other"]
    assert len(rim) == 1, info  # the fixture's decisive feature: the rim is a region of its own
    rim = rim[0]
    tops = _all(info, "top")
    fil = np.ones(len(info) + 1, int)  # rest=white
    fil[tops], fil[pants] = 2, 3  # top=black pants=blue
    named = set(tops) | {pants}
    got = C.boxed_slivers(cm, num, info, fil, named, 1)
    assert len(got) == 1 and got[0][0] == rim and got[0][1] in tops, (got, info)
    # a sliver the request names keeps its color; one beside the rest color is not boxed in
    assert C.boxed_slivers(cm, num, info, fil, named | {rim}, 1) == []
    loose = fil.copy()
    loose[tops] = 1
    assert C.boxed_slivers(cm, num, info, loose, {pants}, 1) == []
    # a strip the picture shows in the rest filament's own color is a detail (a white shirt
    # between black lapels under rest=white), never the garment's edge: it keeps the rest color
    white = (250.0, 250.0, 250.0)
    def shown(rgb):
        return [dict(d, rgb=list(rgb) if d["n"] == rim else [15.0, 15.0, 15.0]) for d in info]
    assert C.boxed_slivers(cm, num, shown(white), fil, named, 1, white) == []
    # a strip in any other color is the edge: dark like its host, or skin where the neck's
    # color bled onto a collar's top in the render (the Jensen job's regions 11 and 12)
    for rgb in ((30.0, 30.0, 30.0), (215.0, 167.0, 144.0)):
        assert [g[0] for g in C.boxed_slivers(cm, num, shown(rgb), fil, named, 1, white)] == [rim], rgb
    # with no rest color to compare, the shape alone decides
    assert [g[0] for g in C.boxed_slivers(cm, num, shown(white), fil, named, 1)] == [rim]
    # a lip 4 mm deep under the line is a piece of its own size, not a sliver: it stays rest
    m = _lathe([(0, -40), (4, -40), (4, 10), (4.5, 10), (4.5, 5), (5, 5), (5, 100), (0, 100)])
    cm, num, info = _zoned(m, 9.6, parts.LEGS, parts.TORSO, {parts.LEGS: "pants", parts.TORSO: "top"})
    fil = np.ones(len(info) + 1, int)
    fil[_all(info, "top")], fil[_n(info, "pants")] = 2, 3
    assert C.boxed_slivers(cm, num, info, fil, set(_all(info, "top")) | {_n(info, "pants")}, 1) == []


def test_a_lip_beside_pants_named_the_rest_color_still_takes_the_jacket_color():
    """Review of PR 25: with pants=white rest=white the pants are white by name, and a lip that
    touches them is still boxed in by painted parts, so it takes the jacket's color."""
    # pants (radius 4) up to 9, the jacket (5) from there; the picture shows the lip below the
    # line at 9.6 black like the jacket, so it is a region apart from the blue pants it touches
    m = _lathe([(0, -40), (4, -40), (4, 9), (5, 9), (5, 100), (0, 100)])
    V, F = cut_iso(m.vertices, m.faces, np.asarray(m.vertices)[:, 2] - 9.6, 0.0, snap=0.02)
    cm = C.load_stl_mesh(V, F)
    zone = np.where(parts.side_of(cm, {"z": 9.6, "curve": None}) > 0, parts.TORSO, parts.LEGS)
    c = cm.triangles_center
    labels = ((np.hypot(c[:, 0], c[:, 1]) > 4.2) & (c[:, 2] < 9.6)).astype(int)
    region = C.regions(cm, labels, min_share=0.0, zone=zone)
    info = C.describe(cm, region, [None] * (int(region.max()) + 1), None)
    seen = set()
    for d in info:
        zr = int(np.bincount(zone[region == d["region"]]).argmax())
        d["part"] = "other" if zr in seen and zr != parts.TORSO else {parts.LEGS: "pants", parts.TORSO: "top"}[zr]
        seen.add(zr)
    num = np.zeros(int(region.max()) + 1, int)
    for d in info:
        num[d["region"]] = d["n"]
    num = num[region]
    lip = [d["n"] for d in info if d["part"] == "other"]
    assert len(lip) == 1, info
    pants, tops = _n(info, "pants"), _all(info, "top")
    fil = np.ones(len(info) + 1, int)
    fil[tops] = 2  # top=black, pants=white and rest=white are filament 1
    got = C.boxed_slivers(cm, num, info, fil, set(tops) | {pants}, 1)
    assert len(got) == 1 and got[0][0] == lip[0] and got[0][1] in tops, (got, info)
    # unnamed, the white pants are the rest color round it, and the lip is no sliver
    assert C.boxed_slivers(cm, num, info, fil, set(tops), 1) == []


def test_a_collar_top_boxed_in_over_the_neck_line_is_the_jacket_not_a_ledge_of_the_head():
    """r3 (2026-11-18): stone colors failed "the neck color edge climbs onto a ledge: 0.69 mm2 of
    up-facing filament 1 faces seen next to it at 345 degrees". The jacket's collar stands round
    the neck with a gap, the neck line runs just over the gap's bottom, and the collar's top above
    that line was a region of its own in the head zone that only the jacket touches. Painted the
    rest color it is the head's color on the collar's top; boxed in, it takes the jacket's."""
    # torso (6) to 10, a collar (4 to 4.5) up to 12 round a gap 0.5 mm wide down to 11, the neck
    # (3.5) and a ball head; the neck line at 11.3, just over the gap's bottom
    prof = [(0, -100), (6, -100), (6, 10), (4.5, 10), (4.5, 12), (4, 12), (4, 11), (3.5, 11), (3.5, 16)]
    m = _lathe(prof + _head(3.5, 16, 5)[1:])
    cm, num, info = _zoned(m, 11.3, parts.TORSO, parts.HEAD, {parts.TORSO: "top", parts.HEAD: "face"})
    tops = _all(info, "top")
    collar = [d["n"] for d in info if d["part"] == "other"]
    assert len(collar) == 1, info
    fil = np.ones(len(info) + 1, int)  # rest=white: the face and anything unnamed
    fil[tops] = 2
    neck = {**_line("neck", 11.3, 3.5), "rmax": 4.5 + parts.SNAP, "curve": None}
    # painted rest, the collar's top is the head's color on a ledge: the fault the job showed
    assert C.ledge_faults(C.ledges(cm.vertices, cm.faces, fil[num], [neck]))
    got = C.boxed_slivers(cm, num, info, fil, set(tops), 1)
    assert len(got) == 1 and got[0][0] == collar[0] and got[0][1] in tops, (got, info)
    fil[collar[0]] = fil[got[0][1]]
    found = C.ledges(cm.vertices, cm.faces, fil[num], [neck])
    assert not C.ledge_faults(found), found


def test_mark_grooves_exempts_edges_in_a_groove_from_wobble():
    m = cuff_figure()
    ln = parts.find_groove(m, _line("wrist", 10.0, 2.5))
    V, F, lab = _paint(m, ln)
    _, lines = C.color_edges(V, F, lab)
    ring = max(lines, key=lambda x: x["length"])
    ring["wobble"] = C.WOBBLE * 2  # as wavy as a groove on a real hand can be
    assert C.edge_faults([ring])
    C.mark_grooves([ring], [ln])
    assert ring.get("groove") == "wrist"
    assert not C.edge_faults([ring])


# SPEC3 A: the anatomy of a figure from its shape


GRAIN = 0.03


def block_figure(shoes=False, flare=False, cap=None, lock=None, ears=False):
    """A disc plinth (top at z 8), two leg boxes, a box torso, arms ending in two loose hand balls,
    a neck and a ball head: hem at the legs' top (28), wrists where the hands meet the arms (34),
    the neck between the torso and the head (48 to 52). shoes=True: each leg stands in a shoe
    (8 x 9, up to z 11) wider than the leg, as the Jensen sculpt's are. On the head (a finer ball
    then): cap, a function of the angle round the head giving the height the ridged hair comes
    down to (24 strands 0.15 mm high); lock, a function of the angle giving the height a smooth
    lock ends at, standing 1 mm proud of the skin with its underside sloping in over 3 mm
    (over the head's top where there is none); ears=True, a flat ear on each side, 105 degrees from the face (a disc 3.6 mm
    across, top at 56.8)."""
    def box(ext, at):
        b = trimesh.creation.box(ext)
        b.apply_translation(at)
        return b

    disc = trimesh.creation.cylinder(radius=20, height=8, sections=96)
    disc.apply_translation([0, 0, 4])
    legs = [box([6, 6, 20.5], [x, 0, 18.25]) for x in (-5, 5)]
    if shoes:
        legs += [box([8, 8.5 if flare else 9, 3.5], [x, 0.25 if flare else 1, 9.25]) for x in (-5, 5)]
    if flare:  # each trouser hem flares out over its shoe: 7.8 x 8.2 at the shoe's top to the leg at 12.4
        for x in (-5, 5):
            pts = [[x + sx * 3.9, 0.25 + sy * 4.1, 10.9] for sx in (-1, 1) for sy in (-1, 1)]
            pts += [[x + sx * 3.0, sy * 3.0, 12.4] for sx in (-1, 1) for sy in (-1, 1)]
            legs.append(trimesh.convex.convex_hull(np.array(pts)))
    torso = box([22, 12, 20], [0, 0, 38])
    arms = [box([5, 4, 12], [x, 0, 40]) for x in (-13.5, 13.5)]  # into the torso's side by 0.5
    hands = []
    for x in (-14.5, 14.5):  # 1 mm clear of the torso, so below the arm each hand is loose
        h = trimesh.creation.icosphere(subdivisions=4, radius=2.5)
        h.apply_translation([x, 0, 32.5])
        hands.append(h)
    neck = trimesh.creation.cylinder(radius=3, height=5, sections=64)
    neck.apply_translation([0, 0, 50])
    head = trimesh.creation.icosphere(subdivisions=5 if cap or lock else 4, radius=7)
    v = np.array(head.vertices)
    th, z = np.arctan2(v[:, 1], v[:, 0]), v[:, 2] + 58.5
    out = np.zeros(len(v))
    if cap is not None:
        out += 0.15 * np.clip((z - cap(th)) / 0.3, 0.0, 1.0) * np.sin(24 * th)
    if lock is not None:
        zb = lock(th)
        u = np.clip(np.nan_to_num((z - zb) / 3.0, nan=0.0), 0.0, 1.0)
        t = np.clip((65.0 - z) / 3.0, 0.0, 1.0)  # into the crown again at the top
        out += 1.0 * u * u * (3 - 2 * u) * t * t * (3 - 2 * t)
    if cap is not None or lock is not None:  # a sculpt's skin is never smooth: GRAIN mm of grain
        out += np.random.default_rng(7).normal(0.0, GRAIN, len(v))
    head = trimesh.Trimesh(v * ((7.0 + out) / 7.0)[:, None], head.faces)
    head.apply_translation([0, 0, 58.5])
    flaps = []
    if ears:
        for x in (-6.3, 6.3):
            e = trimesh.creation.cylinder(radius=1.8, height=1.0, sections=48)
            e.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
            e.apply_transform(trimesh.transformations.rotation_matrix(np.radians(15), [0, 0, 1]))
            e.apply_translation([x * np.cos(np.radians(15)), abs(x) * np.sin(np.radians(15)), 55.0])
            flaps.append(e)
    m = trimesh.boolean.union([disc, *legs, torso, *arms, *hands, neck, head, *flaps], engine="manifold")
    # fine faces, as a sculpted figure has, so lines and pieces are resolved
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=1.0)
    return C.load_stl_mesh(np.asarray(v, float), np.asarray(f))


def test_anatomy_of_a_block_figure():
    m = block_figure()
    a = parts.anatomy(m, 8.0)
    assert 28.0 <= a["hem"] <= 29.0, a["hem"]
    assert 48.0 <= a["neck"] <= 52.0, a["neck"]
    assert sorted(w["side"] for w in a["wrists"]) == [-1, 1]
    for w in a["wrists"]:
        assert 33.5 <= w["z"] <= 35.0, w
    assert abs(a["center"]) < 0.5
    names = {(ln["name"], ln.get("side")) for ln in a["lines"]}
    assert names == {("hem", None), ("neck", None), ("wrist", -1), ("wrist", 1)}


def _shorts_figure(belt, flap=False):
    """The block figure with its torso split at the hips. belt=False: shorts (18 x 10) from the
    legs up to 31.25 under a jacket (22 x 12) that overhangs them, so the jacket's hem is at 31.
    belt=True: a long coat (22 x 12) from the legs up, with a belt groove (21 x 11) at 30.5 to
    31.5: the coat's hem is at the legs. belt="low": the same coat with the belt groove at 28.75 to
    29.65, under 1 mm above the legs' split at 27.9. flap=True (with belt=False): the jacket's
    front hangs lower, a panel 16 mm wide down to 29.6 over the shorts' front, so its hem runs at
    29.6 across the front and 31 everywhere else."""
    def box(ext, at):
        b = trimesh.creation.box(ext)
        b.apply_translation(at)
        return b

    disc = trimesh.creation.cylinder(radius=20, height=8, sections=96)
    disc.apply_translation([0, 0, 4])
    legs = [box([6, 6, 20.5], [x, 0, 18.25]) for x in (-5, 5)]
    if belt == "low":
        body = [box([22, 12, 0.85], [0, 0, 28.325]), box([21, 11, 0.9], [0, 0, 29.2]),
                box([22, 12, 18.35], [0, 0, 38.825])]
    elif belt:
        body = [box([22, 12, 2.6], [0, 0, 29.2]), box([21, 11, 1.2], [0, 0, 31.0]),
                box([22, 12, 16.6], [0, 0, 39.7])]
    else:
        body = [box([18, 10, 3.5], [0, 0, 29.5]), box([22, 12, 17], [0, 0, 39.5])]
        if flap:  # x -8 to 8, y -6 to -4.5 (into the shorts' front at -5), z 29.6 up into the jacket
            body.append(box([16, 1.5, 1.6], [0, -5.25, 30.4]))
    arms = [box([5, 4, 12], [x, 0, 40]) for x in (-13.5, 13.5)]
    hands = []
    for x in (-14.5, 14.5):
        h = trimesh.creation.icosphere(subdivisions=4, radius=2.5)
        h.apply_translation([x, 0, 32.5])
        hands.append(h)
    neck = trimesh.creation.cylinder(radius=3, height=5, sections=64)
    neck.apply_translation([0, 0, 50])
    head = trimesh.creation.icosphere(subdivisions=4, radius=7)
    head.apply_translation([0, 0, 58.5])
    m = trimesh.boolean.union([disc, *legs, *body, *arms, *hands, neck, head], engine="manifold")
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=1.0)
    return C.load_stl_mesh(np.asarray(v, float), np.asarray(f))


def test_a_jacket_over_shorts_has_its_hem_at_its_own_edge():
    """r1 (judge, then a close look): the Jensen sculpt wears shorts under the jacket. The hem was
    put where the legs part, so "all white but the jacket" printed black shorts."""
    a = parts.anatomy(_shorts_figure(belt=False), 8.0)
    assert 30.5 <= a["hem"] <= 31.5, a["hem"]
    assert sorted(w["side"] for w in a["wrists"]) == [-1, 1]


def test_a_jacket_hem_lower_at_the_front_follows_its_groove_all_the_way_round():
    """r3 (2026-11-18, Jensen in a black jacket over blue pants): stone colors failed "color
    boundary is jagged: filament 3/4 at z 38 mm is 1.11 times its smoothed length". The jacket's
    hem crease runs at 36.6 across the front and up to 38.5 at the back, with a slot under the
    lip there. hem_fold found that crease (0.142 per mm) but passed on only its median, 37.75;
    the hem's own groove search looked 1 mm each side of that, lost the front, found no groove
    and cut a level plane through the slot in small jagged loops. The search must reach the
    whole crease hem_fold found, so the hem follows it, and the front panel stays the jacket."""
    m = _shorts_figure(belt=False, flap=True)
    a = parts.anatomy(m, 8.0)
    assert a.get("hem_fold") and 30.5 <= a["hem"] <= 31.5, a["hem"]
    hem = next(ln for ln in a["lines"] if ln["name"] == "hem")
    assert (hem["groove"] or {}).get("used"), hem["groove"]
    cv = np.asarray(hem["curve"])
    front = cv[np.argmin(np.abs(parts._BINS + np.pi / 2))]  # -90 degrees: the -y side, the panel
    back = cv[np.argmin(np.abs(parts._BINS - np.pi / 2))]
    assert front < 30.0 and back > 30.5, (front, back)
    # painted by zone, the panel is the jacket's, not the shorts'
    V, F = parts.cut(m.vertices, m.faces, a)
    cm = C.load_stl_mesh(V, F)
    c = cm.triangles_center
    base = (c[:, 2] < 8.0) | (cm.vertices[cm.faces][:, :, 2].max(1) <= 8.01)
    zone, _ = parts.zones(cm, a, base)
    panel = (c[:, 1] < -5.9) & (np.abs(c[:, 0]) < 6.0) & (c[:, 2] > 29.8) & (c[:, 2] < 30.8)
    assert panel.sum() > 10
    torso = cm.area_faces[panel & (zone == parts.TORSO)].sum() / cm.area_faces[panel].sum()
    assert torso > 0.95, torso


def test_a_belt_on_a_long_coat_is_not_its_hem():
    a = parts.anatomy(_shorts_figure(belt=True), 8.0)
    assert 28.0 <= a["hem"] <= 29.0, a["hem"]


def test_a_belt_just_above_the_legs_is_not_its_hem():
    # 1 mm under the groove the section is between the legs: one leg is no measure of the coat
    a = parts.anatomy(_shorts_figure(belt="low"), 8.0)
    assert not a.get("hem_fold"), a["hem"]


def test_the_hem_groove_search_runs_only_where_the_body_steps_out(monkeypatch):
    # the block figure's jacket hangs straight from its hem at the legs (28) until the arms join
    # it at 34: a figure with no fold pays for a groove search only near a real step
    m = block_figure()
    a = parts.anatomy(m, 8.0)
    assert a["hem"] is not None and not a.get("hem_fold")
    calls = []
    real = parts.crease_loop

    def counted(*args, **kw):
        calls.append(float(args[2]) + 1.0)
        return real(*args, **kw)

    monkeypatch.setattr(parts, "crease_loop", counted)
    lo = a["hem"]
    assert parts.hem_fold(m, lo, lo + parts.HEM_FOLD * (a["height"] - 8.0)) is None
    assert calls and all(abs(z - 34.0) <= 2.5 for z in calls), calls


def test_part_names_of_a_block_figure():
    m = block_figure()
    a = parts.anatomy(m, 8.0)
    V, F = parts.cut(m.vertices, m.faces, a)
    m = C.load_stl_mesh(V, F)
    zc = m.triangles_center[:, 2]
    base = (zc < 8.0) | (m.vertices[m.faces][:, :, 2].max(1) <= 8.01)
    zone, hand = parts.zones(m, a, base)
    assert (hand >= 0).sum() > 0 and set(np.unique(hand[hand >= 0])) == {0, 1}
    # one region per zone, each hand its own
    region = zone.copy()
    region[hand == 1] = len(parts.ZONES)
    _, region = np.unique(region, return_inverse=True)
    region = region.reshape(-1)
    R = int(region.max()) + 1
    base_region = int(region[base][0])
    palette = {parts.LEGS: [30, 30, 90], parts.TORSO: [20, 20, 20], parts.HANDS: [225, 180, 150],
               parts.HEAD: [225, 180, 150]}
    rgb = [None] * R
    for r in range(R):
        if r != base_region:
            z = int(np.bincount(zone[region == r]).argmax())
            rgb[r] = palette[z]
    info = C.describe(m, region, rgb, base_region)
    parts.name_parts(m, region, info, zone, a, look="a man in a black jacket and jeans")
    got = sorted(d["part"] for d in info)
    assert got == sorted(["base", "jeans", "jacket", "hands", "hands", "face"]), got


def test_a_shoe_wider_than_its_leg_gets_its_own_line_and_zone():
    """f3 (Donovan, 2026-11-18): "Make his pants blue too!", then black shoes. The sculpt's shoes
    and pants were one color region, so the blue pants ran down over the shoes. Each leg needs a
    line at its shoe's top and a shoes zone under it, on that leg alone."""
    m = block_figure(shoes=True)
    a = parts.anatomy(m, 8.0)
    assert sorted(x["side"] for x in a["ankles"]) == [-1, 1], a["ankles"]
    for x in a["ankles"]:
        assert 10.8 <= x["z"] <= 11.3, x
    assert {(ln["name"], ln.get("side")) for ln in a["lines"] if ln["name"] == "ankle"} == {("ankle", -1), ("ankle", 1)}
    V, F = parts.cut(m.vertices, m.faces, a)
    cm = C.load_stl_mesh(V, F)
    assert cm.is_watertight and abs(cm.volume - m.volume) < 1e-3 * m.volume
    c = cm.triangles_center
    base = (c[:, 2] < 8.0) | (cm.vertices[cm.faces][:, :, 2].max(1) <= 8.01)
    zone, _ = parts.zones(cm, a, base)
    shoe = zone == parts.SHOES
    assert c[shoe, 2].max() <= 11.3 and c[shoe, 2].min() >= 8.0
    assert (c[shoe, 0] < 0).any() and (c[shoe, 0] > 0).any()  # both feet
    low = ~base & (c[:, 2] < 10.8) & (np.abs(c[:, 0]) < 10)
    assert (zone[low] == parts.SHOES).all()  # nothing of the pants left on a shoe
    region = zone.copy()
    _, region = np.unique(region, return_inverse=True)
    region = region.reshape(-1)
    base_region = int(region[base][0])
    palette = {parts.LEGS: [40, 80, 200], parts.TORSO: [20, 20, 20], parts.HANDS: [225, 180, 150],
               parts.HEAD: [225, 180, 150], parts.SHOES: [20, 20, 20]}
    rgb = [None if r == base_region else palette[int(np.bincount(zone[region == r]).argmax())]
           for r in range(int(region.max()) + 1)]
    info = C.describe(cm, region, rgb, base_region)
    parts.name_parts(cm, region, info, zone, a, look="a man in a black jacket, blue pants and black shoes")
    assert "shoes" in {d["part"] for d in info}, [d["part"] for d in info]


def test_a_trouser_hem_flaring_over_the_shoe_stays_the_trousers_color():
    """r3, the blind judge on the first black-shoes run: "black band painted on the bottom of the
    pant legs above the shoes; the blue stops short of the hem". The hem's flare was the steepest
    step, so the shoe line sat on top of it. The line is the crease where the hem meets the shoe."""
    m = block_figure(shoes=True, flare=True)
    a = parts.anatomy(m, 8.0)
    ankles = [ln for ln in a["lines"] if ln["name"] == "ankle"]
    assert len(ankles) == 2
    V, F = parts.cut(m.vertices, m.faces, a)
    cm = C.load_stl_mesh(V, F)
    c = cm.triangles_center
    base = (c[:, 2] < 8.0) | (cm.vertices[cm.faces][:, :, 2].max(1) <= 8.01)
    zone, _ = parts.zones(cm, a, base)
    shoe = zone == parts.SHOES
    assert shoe.any() and c[shoe, 2].max() <= 11.4, c[shoe, 2].max()  # not up the flare (11 to 12.4)
    flare = ~base & (c[:, 2] > 11.4) & (c[:, 2] < 12.3) & (np.abs(c[:, 0]) < 10)
    assert (zone[flare] == parts.LEGS).all()


def test_straight_legs_have_no_shoe_line():
    assert parts.anatomy(block_figure(), 8.0)["ankles"] == []


# SPEC3 E2: odd regions (the square notch on the back of the neck)


def _tube():
    t = trimesh.creation.cylinder(radius=10, height=30, sections=128)
    t.apply_translation([0, 0, 15])
    v, f = trimesh.remesh.subdivide_to_size(t.vertices, t.faces, max_edge=0.6)
    return C.load_stl_mesh(np.asarray(v, float), np.asarray(f))


def _merge(m, patch):
    region = np.where(patch, 1, 0)
    band = (m.triangles_center[:, 2] > 20) & (m.triangles_center[:, 2] < 23)
    band &= np.abs(m.face_normals[:, 2]) < 0.5
    region[band] = 2
    zone = np.full(len(region), parts.TORSO)
    return parts.merge_odd(m, region, region.copy(), zone, keep={0}, x0=0.0)


def test_a_one_sided_square_notch_merges_into_its_neighbor():
    m = _tube()
    c = m.triangles_center
    patch = (c[:, 0] > 5) & (np.abs(c[:, 1]) < 3) & (c[:, 2] > 10) & (c[:, 2] < 16)
    region, merged = _merge(m, patch)
    assert [(r, into) for r, into, _ in merged] == [(1, 0)], merged
    assert "one-sided" in merged[0][2]
    assert not (region == 1).any() and (region == 2).any()  # the smooth band stays


def test_a_symmetric_patch_with_square_corners_merges_too():
    m = _tube()
    c = m.triangles_center
    patch = (c[:, 1] < -5) & (np.abs(c[:, 0]) < 3) & (c[:, 2] > 10) & (c[:, 2] < 16)
    region, merged = _merge(m, patch)
    assert [(r, into) for r, into, _ in merged] == [(1, 0)], merged
    assert "corner" in merged[0][2]
    assert (region == 2).any()


def test_a_smooth_band_all_round_stays():
    m = _tube()
    region, merged = _merge(m, np.zeros(len(m.faces), bool))
    assert merged == [] and (region == 2).any()


def test_ledges_do_not_depend_on_the_vertex_order():
    """Review sol-F1: ledges() must index its own mesh's vertices, so shuffling the input
    vertices (faces remapped to match) gives the same result."""
    m = collar_figure()
    plane = {**_line("neck", 11.0, 4.2), "curve": None}
    V, F, lab = _paint(m, plane)
    perm = np.random.default_rng(3).permutation(len(V))
    inv = np.empty_like(perm)
    inv[perm] = np.arange(len(perm))
    V2, F2 = np.asarray(V)[perm], inv[np.asarray(F)]
    a, b = C.ledges(V, F, lab, [plane]), C.ledges(V2, F2, lab, [plane])
    assert a[0]["faces"] > 0, a
    assert [(x["area"], x["angle"], x["fil"], x["faces"]) for x in a] == \
        [(x["area"], x["angle"], x["fil"], x["faces"]) for x in b], (a, b)


def test_a_jacket_in_three_palette_regions_is_all_jacket():
    """Review sol-F2: a jacket split into the chest and two sleeves of another palette color
    is one garment; jacket=black reaches all three regions."""
    from smoothstone import cli

    m = block_figure()
    a = parts.anatomy(m, 8.0)
    V, F = parts.cut(m.vertices, m.faces, a)
    m = C.load_stl_mesh(V, F)
    c = m.triangles_center
    base = (c[:, 2] < 8.0) | (m.vertices[m.faces][:, :, 2].max(1) <= 8.01)
    zone, hand = parts.zones(m, a, base)
    region = zone.copy()
    region[hand == 1] = len(parts.ZONES)
    torso = zone == parts.TORSO
    region[torso & (c[:, 0] < -11)] = len(parts.ZONES) + 1  # left sleeve
    region[torso & (c[:, 0] > 11)] = len(parts.ZONES) + 2  # right sleeve
    _, region = np.unique(region, return_inverse=True)
    region = region.reshape(-1)
    R = int(region.max()) + 1
    base_region = int(region[base][0])
    sleeves = {int(region[torso & (c[:, 0] < -11)][0]), int(region[torso & (c[:, 0] > 11)][0])}
    palette = {parts.LEGS: [30, 30, 90], parts.TORSO: [20, 20, 20], parts.HANDS: [225, 180, 150],
               parts.HEAD: [225, 180, 150]}
    rgb = [None] * R
    for r in range(R):
        if r != base_region:
            rgb[r] = [70, 70, 75] if r in sleeves else palette[int(np.bincount(zone[region == r]).argmax())]
    info = C.describe(m, region, rgb, base_region)
    parts.name_parts(m, region, info, zone, a, look="a man in a black jacket and jeans")
    jacket = sorted(d["region"] for d in info if d["part"] == "jacket")
    assert len(jacket) == 3 and sleeves <= set(jacket), [(d["region"], d["part"]) for d in info]
    black = sorted(r for n in cli._part_regions(info, "jacket") for r in [next(d["region"] for d in info if d["n"] == n)])
    assert black == jacket


def test_a_cuff_cut_masked_to_the_hand_still_cuts_every_face_it_crosses():
    """Eval r1: the cuff line cuts only round the hand, so parts.cut sets the field to +1 on every
    other vertex. cut_iso took its snap distance from the slope along each vertex's edges, and the
    jump to +1 at the rim of the hand made that slope steep: vertices up to 0.15 mm off the line
    counted as on it, faces across the line stayed whole, and the jacket's color ran onto the hand
    in a 0.2 mm tab. The snap must come from the true field, so every face inside the zone that
    the line crosses is cut."""
    m = trimesh.creation.cylinder(radius=3.0, height=10.0, sections=96)
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=0.3)
    V, F = np.asarray(v, float), np.asarray(f, np.int64)

    def true(X):  # a tilted, wavy cuff line
        return X[:, 2] - 0.4 * np.sin(np.arctan2(X[:, 1], X[:, 0]))

    inside = V[:, 0] > 0.0  # the hand's faces and their ring: one half of the tube
    V2, F2 = parts.cut_masked(V, F, true(V), inside)
    d = true(V2)[F2]
    zone = (V2[F2][:, :, 0] > 0.0).all(1)  # every face whose corners are all inside, the rim's too
    across = zone & (d.min(1) < -0.03) & (d.max(1) > 0.03)
    assert not across.any(), f"{int(across.sum())} faces cross the cuff line uncut"



def thumb_figure():
    """The block figure with each hand a capsule (radius 1.6, z 26.9 to 35.1) hanging 1.5 mm clear
    of the torso's side under a sleeve (5 x 5) that overhangs it, its cuff groove at z 34, and a
    thumb (1 x 1 mm) bridging the gap to the hip at z 31.5 to 32.5: the hand is loose only under
    the thumb, so its wrist level is 31.4, under the cuff."""
    def box(ext, at):
        b = trimesh.creation.box(ext)
        b.apply_translation(at)
        return b

    disc = trimesh.creation.cylinder(radius=20, height=8, sections=96)
    disc.apply_translation([0, 0, 4])
    legs = [box([6, 6, 20.5], [x, 0, 18.25]) for x in (-5, 5)]
    torso = box([22, 12, 20], [0, 0, 38])
    arms = [box([5, 5, 12], [x, 0, 40]) for x in (-13.5, 13.5)]
    hands = []
    for s in (-1, 1):
        h = trimesh.creation.capsule(height=7.0, radius=1.6, count=[48, 48])
        h.apply_translation([s * 14.1, 0, 31.0])
        hands += [h, box([2.1, 1.0, 1.0], [s * 11.95, 0, 32.0])]
    neck = trimesh.creation.cylinder(radius=3, height=5, sections=64)
    neck.apply_translation([0, 0, 50])
    head = trimesh.creation.icosphere(subdivisions=4, radius=7)
    head.apply_translation([0, 0, 58.5])
    m = trimesh.boolean.union([disc, *legs, torso, *arms, *hands, neck, head], engine="manifold")
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=1.0)
    return C.load_stl_mesh(np.asarray(v, float), np.asarray(f))


def test_a_hand_whose_thumb_touches_the_hip_under_its_cuff_ends_between_them():
    """Eval (Elon): a white band ran across the hips at the hem. The thumb's tip touches the hip
    there, so the hand is loose only under that touch and its wrist level is the touch, under the
    cuff. Every face from that level up to the cuff within HAND_REACH of the hand's axis counted as
    the hand, the hip's side and front too, so a strip of hip took the hand's color. The hand must
    end on the line halfway between it and the hip, and still reach its cuff."""
    m = thumb_figure()
    a = parts.anatomy(m, 8.0)
    wrists = [ln for ln in parts.all_lines(a) if ln["name"] == "wrist"]
    assert len(wrists) == 2 and all(ln["curve"] is not None for ln in wrists), wrists
    for w in a["wrists"]:
        assert 31.0 <= w["z"] <= 31.6, w  # the touch, not the cuff
    V, F = parts.cut(m.vertices, m.faces, a)
    m = C.load_stl_mesh(V, F)
    c = m.triangles_center
    for w in a["wrists"]:
        h = parts.hand_faces(m, a, w)
        hip = float(m.area_faces[h & (np.abs(c[:, 0]) < 11.05)].sum())
        assert hip < 0.5, f"side {w['side']}: {hip:.1f} mm2 of hip in the hand"
        assert np.abs(c[h, 0]).min() > 11.5, "the hand runs more than halfway along the thumb"
        assert c[h, 2].max() > 33.5, "the hand stops short of its cuff"


def test_the_side_of_a_flat_rim_groove_does_not_ride_on_rounding():
    """CI on x86 failed test_cuff_over_wrist_slips_down while ARM passed: the sleeve rim's flat
    underside lies exactly on the groove's level, so the sign of its distance to the groove fit
    (about 1e-16 mm) was rounding noise, and the rim landed in the up strip on one CPU and the down
    strip on another. Groove points 1e-9 mm above or below the rim give either sign on any CPU;
    the side and the seen areas must not change."""
    m = cuff_figure()
    V = np.asarray(m.vertices)
    ring = V[(np.abs(V[:, 2] - 10.0) < 1e-9) & (np.abs(np.hypot(V[:, 0], V[:, 1]) - 2.5) < 1e-6)]
    got = set()
    for eps in (0.0, 1e-9, -1e-9):
        side, seen = parts.choose_side(m, ring + [0.0, 0.0, eps], (0.0, 0.0))
        got.add((side, seen[1][0], seen[-1][0]))
    assert len(got) == 1 and next(iter(got))[0] == -1, got


def _shoe_figure(kind):
    """block_figure with other shoes: "seam", a plain shoe (8 x 9, top at 11) with a sole seam 0.75
    deep and 0.5 tall whose middle is 1.5 mm under its top; "low", a plain shoe only 2 mm tall;
    "sloped", a shoe whose top rises from 10.4 at the heel to 11.6 at the toe."""
    def box(ext, at):
        b = trimesh.creation.box(ext)
        b.apply_translation(at)
        return b

    disc = trimesh.creation.cylinder(radius=20, height=8, sections=96)
    disc.apply_translation([0, 0, 4])
    legs = [box([6, 6, 20.5], [x, 0, 18.25]) for x in (-5, 5)]
    for x in (-5, 5):
        if kind == "seam":
            legs += [box([8, 9, 1.25], [x, 1, 8.625]), box([6.5, 7.5, 0.5], [x, 1, 9.5]), box([8, 9, 1.25], [x, 1, 10.375])]
        elif kind == "low":
            legs += [box([8, 9, 2.0], [x, 1, 9.0])]
        else:
            pts = [[x + sx * 4, y, z] for sx in (-1, 1) for y, z in ((-3.5, 8), (5.5, 8), (-3.5, 10.4), (5.5, 11.6))]
            legs.append(trimesh.convex.convex_hull(np.array(pts)))
    torso = box([22, 12, 20], [0, 0, 38])
    arms = [box([5, 4, 12], [x, 0, 40]) for x in (-13.5, 13.5)]
    hands = []
    for x in (-14.5, 14.5):
        h = trimesh.creation.icosphere(subdivisions=4, radius=2.5)
        h.apply_translation([x, 0, 32.5])
        hands.append(h)
    neck = trimesh.creation.cylinder(radius=3, height=5, sections=64)
    neck.apply_translation([0, 0, 50])
    head = trimesh.creation.icosphere(subdivisions=4, radius=7)
    head.apply_translation([0, 0, 58.5])
    m = trimesh.boolean.union([disc, *legs, torso, *arms, *hands, neck, head], engine="manifold")
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=1.0)
    return C.load_stl_mesh(np.asarray(v, float), np.asarray(f))


@pytest.mark.parametrize("kind,top", [("seam", 11.0), ("low", 10.0)])
def test_a_sole_seam_or_a_low_shoe_keeps_the_shoe_line_at_the_shoes_top(kind, top):
    """Review of #14: the crease search under the step must not settle on a sole seam, or on the
    plinth's corner under a low shoe, and leave the shoe's upper the pants' color."""
    m = _shoe_figure(kind)
    a = parts.anatomy(m, 8.0)
    for ln in [x for x in a["lines"] if x["name"] == "ankle"]:
        assert ln["curve"] is not None and abs(np.median(ln["curve"]) - top) < 0.3, (ln["z"], ln["curve"][:3])
    V, F = parts.cut(m.vertices, m.faces, a)
    cm = C.load_stl_mesh(V, F)
    c = cm.triangles_center
    base = (c[:, 2] < 8.0) | (cm.vertices[cm.faces][:, :, 2].max(1) <= 8.01)
    zone, _ = parts.zones(cm, a, base)
    upper = ~base & (c[:, 2] > top - 1.2) & (c[:, 2] < top - 0.1) & (np.abs(np.abs(c[:, 0]) - 5) < 4.5)
    assert upper.any() and (zone[upper] == parts.SHOES).all()


def test_a_shoe_rim_line_is_its_own_course_and_its_edge_follows_the_shape(monkeypatch):
    """Review of #14: with no groove at a sloped shoe's top, the line follows the rim. It must not
    keep the groove dict of the search it rejected, and a color edge along the rim follows the
    shape, so the wobble limit for flat cuts does not apply to it."""
    real = parts.find_groove

    def no_ankle_groove(mesh, ln, only=None):
        if ln["name"] == "ankle":
            return {**ln, "curve": None, "groove": {"cost": 0.1, "length": 30.0, "used": True}}
        return real(mesh, ln, only)

    monkeypatch.setattr(parts, "find_groove", no_ankle_groove)
    m = _shoe_figure("sloped")
    a = parts.anatomy(m, 8.0)
    rims = [x for x in a["lines"] if x["name"] == "ankle"]
    assert len(rims) == 2
    for ln in rims:
        assert ln.get("rim") and ln["groove"] is None, ln.get("groove")
        cv = np.asarray(ln["curve"])
        assert cv.max() - cv.min() > 0.2  # it rises toward the toe
        # a color edge laid along the rim, just inside the shoe's outline
        th = np.radians(np.arange(-180, 180, 5))
        cx, cy = ln["center"]
        r = max(ln["rmax"] - 1.5, 1.0)
        pts = np.c_[cx + r * np.cos(th), cy + r * np.sin(th), cv[np.arange(-180, 180, 5) + 180]]
        edge = [{"pts": pts, "wobble": 1.0, "ratio": 1.0}]
        C.mark_grooves(edge, a["lines"])
        assert edge[0].get("groove") == "ankle"
        assert C.edge_faults(edge) == []


def _hair_true(th):
    """The fixture's hairline round the head's axis: high at the front (-y), low at the back, and
    lower again over the ears (+-x)."""
    return 59.5 - 1.5 * np.sin(th) - 0.6 * np.cos(2 * th)


def _hair_picture(c):
    """The fake picture's colors at points c on the block figure: brown hair above _hair_true with
    the bleed a picture has under it (an ear blotch on each side joined to the hair by a thin
    streak, and a loose blotch on the forehead), skin on the rest of the head and the hands, a
    black jacket and blue jeans."""
    th = np.arctan2(c[:, 1], c[:, 0])
    z = c[:, 2]
    zl = _hair_true(th)
    out = np.where((z < 28.0)[:, None], [[40, 50, 120]], [[25, 25, 28]]).astype(float)
    skin = (z > 50.0) | ((np.abs(c[:, 0]) > 12.0) & (z < 36.0))
    out[skin] = [225, 180, 150]
    head = z > 50.0
    hair = head & (z > zl)
    for t in (0.0, np.pi):  # the ear blotches and their streaks
        d = np.abs(np.angle(np.exp(1j * (th - t))))
        zc = _hair_true(np.array([t]))[0] - 3.0
        hair |= head & (np.hypot(d * 7.0, z - zc) < 1.5)
        hair |= head & (d * 7.0 < 0.5) & (z > zc) & (z <= zl)
    d = np.abs(np.angle(np.exp(1j * (th + np.pi / 2))))
    hair |= head & (np.hypot(d * 7.0, z - (_hair_true(np.array([-np.pi / 2]))[0] - 2.5)) < 1.0)
    out[hair] = [95, 60, 30]
    return out, hair, head & (z < zl - 0.6) & hair


def test_the_hair_ends_on_a_smooth_line_fitted_to_the_picture_and_leaves_its_blotches(monkeypatch, tmp_path):
    """Eval (Elon, DHH): the hair's edge came straight from the picture, so it was ragged (wobble
    0.40 and 0.43 mm, over 0.15) and every blotch the picture left on the ears and the face that
    touched the hair was painted brown. The hair must end on one smooth line round the head,
    fitted to the picture's edge with the blotches and streaks under it left out, and nothing under
    that line is hair."""
    from smoothstone import paint

    m = block_figure()
    top_z, H = 65.5, 65.5 - 8.0

    def fake(sub, front, back, atlas):
        # undo the scaling to unit height: the figure's top vertex is the head's top at (0, 0, 65.5)
        V = np.asarray(sub.vertices, float)
        t = V[V[:, 2].argmax()]
        c = (sub.triangles_center - t) * H + np.array([0.0, 0.0, top_z])
        return _hair_picture(c)[0]

    monkeypatch.setattr(paint, "face_colors", fake)
    (tmp_path / "front.png").write_bytes(b"picture")
    res = C.find_regions(m, "figure", {"base": "round", "name": ""}, tmp_path / "front.png", None,
                         tmp_path / "atlas.png")
    mesh, num, info = res["mesh"], res["num"], res["regions"]
    hair_n = [d["n"] for d in info if d["part"] == "hair"]
    assert len(hair_n) == 1, [(d["n"], d["part"]) for d in info]
    hair = num == hair_n[0]
    c = mesh.triangles_center
    _, _, blotch = _hair_picture(c)
    assert blotch.any()
    assert not (hair & blotch).any(), f"{int((hair & blotch).sum())} blotch faces are hair"
    # the hair's edge: corners shared by hair and other head faces lie on the true line
    head = c[:, 2] > 50.0
    adj = mesh.face_adjacency
    cross = (hair[adj[:, 0]] != hair[adj[:, 1]]) & head[adj[:, 0]] & head[adj[:, 1]]
    P = mesh.vertices[np.unique(mesh.face_adjacency_edges[cross])]
    off = np.abs(P[:, 2] - _hair_true(np.arctan2(P[:, 1], P[:, 0])))
    phi = np.degrees(np.abs(np.angle(np.exp(1j * (np.arctan2(P[:, 1], P[:, 0]) + np.pi / 2)))))
    # the picture sets the line only at the face (Donovan: the photo sets forehead and temples);
    # round the rest it goes over the ears and down to the nape
    face = phi < parts.HAIR_FRONT
    assert face.any()
    assert off[face].max() < 0.4, f"the hair's edge strays {off[face].max():.2f} mm from the picture's line at the face"


def test_the_hair_is_level_across_the_back_and_drops_to_it_just_behind_the_ears(monkeypatch, tmp_path):
    """Eval (Elon, DHH, 8 angles): the hairline held over the ears until 5 degrees past them, then
    blended down to the nape over 30 more, and the fit smoothed that into a V: on DHH it sat 2.6 mm
    over the nape at the back's middle and left a bare white wedge behind each ear. Across the back
    the hair must come down level to just over where the head meets the neck."""
    from smoothstone import paint

    m = block_figure(ears=True)
    top_z, H = 65.5, 65.5 - 8.0

    def fake(sub, front, back, atlas):
        V = np.asarray(sub.vertices, float)
        t = V[V[:, 2].argmax()]
        c = (sub.triangles_center - t) * H + np.array([0.0, 0.0, top_z])
        out = np.where((c[:, 2] < 28.0)[:, None], [[40, 50, 120]], [[25, 25, 28]]).astype(float)
        out[(c[:, 2] > 50.0) | ((np.abs(c[:, 0]) > 12.0) & (c[:, 2] < 36.0))] = [225, 180, 150]
        th = np.arctan2(c[:, 1], c[:, 0])  # the picture's hair: over the brows at the front, low behind
        zl = 58.5 + 2.0 * np.clip(-np.sin(th), 0, None) - 4.5 * np.clip(np.sin(th), 0, None)
        out[(c[:, 2] > 50.0) & (c[:, 2] > zl)] = [95, 60, 30]
        return out

    monkeypatch.setattr(paint, "face_colors", fake)
    (tmp_path / "front.png").write_bytes(b"picture")
    res = C.find_regions(m, "figure", {"base": "round", "name": ""}, tmp_path / "front.png", None,
                         tmp_path / "atlas.png")
    mesh, num, info = res["mesh"], res["num"], res["regions"]
    hair_n = [d["n"] for d in info if d["part"] == "hair"]
    assert len(hair_n) == 1, [(d["n"], d["part"]) for d in info]
    hair = num == hair_n[0]
    c = mesh.triangles_center
    head = c[:, 2] > 52.0
    adj = mesh.face_adjacency
    cross = (hair[adj[:, 0]] != hair[adj[:, 1]]) & head[adj[:, 0]] & head[adj[:, 1]]
    P = mesh.vertices[np.unique(mesh.face_adjacency_edges[cross])]
    phi = np.degrees(np.abs(np.angle(np.exp(1j * (np.arctan2(P[:, 1], P[:, 0]) + np.pi / 2)))))
    # the ball head (radius 7 at z 58.5) meets the neck (radius 3) at 58.5 - sqrt(40): the nape
    level = 58.5 - np.sqrt(40.0) + parts.HAIR_BACK
    back = P[phi >= 170, 2]
    assert len(back), "no hair edge at the back"
    assert np.median(back) < level + 0.8, f"the hair's edge at the back is {np.median(back) - level:.2f} mm over the nape's level"
    # the ears stay out of the hair
    ears = head & (np.abs(c[:, 0]) > 6.6) & (np.abs(c[:, 2] - 55.0) < 1.6)
    assert ears.any() and not (hair & ears).any(), f"{int((hair & ears).sum())} ear faces are hair"
