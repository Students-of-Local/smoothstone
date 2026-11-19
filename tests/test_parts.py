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


def block_figure(shoes=False, flare=False):
    """A disc plinth (top at z 8), two leg boxes, a box torso, arms ending in two loose hand balls,
    a neck and a ball head: hem at the legs' top (28), wrists where the hands meet the arms (34),
    the neck between the torso and the head (48 to 52). shoes=True: each leg stands in a shoe
    (8 x 9, up to z 11) wider than the leg, as the Jensen sculpt's are."""
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
    head = trimesh.creation.icosphere(subdivisions=4, radius=7)
    head.apply_translation([0, 0, 58.5])
    m = trimesh.boolean.union([disc, *legs, torso, *arms, *hands, neck, head], engine="manifold")
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


def _shorts_figure(belt):
    """The block figure with its torso split at the hips. belt=False: shorts (18 x 10) from the
    legs up to 31.25 under a jacket (22 x 12) that overhangs them, so the jacket's hem is at 31.
    belt=True: a long coat (22 x 12) from the legs up, with a belt groove (21 x 11) at 30.5 to
    31.5: the coat's hem is at the legs. belt="low": the same coat with the belt groove at 28.75 to
    29.65, under 1 mm above the legs' split at 27.9."""
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
