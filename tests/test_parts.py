"""Parts of a figure from its shape: grooves, the side a color edge slips to, the ledge check."""
import numpy as np
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


def block_figure():
    """A disc plinth (top at z 8), two leg boxes, a box torso, arms ending in two loose hand balls,
    a neck and a ball head: hem at the legs' top (28), wrists where the hands meet the arms (34),
    the neck between the torso and the head (48 to 52)."""
    def box(ext, at):
        b = trimesh.creation.box(ext)
        b.apply_translation(at)
        return b

    disc = trimesh.creation.cylinder(radius=20, height=8, sections=96)
    disc.apply_translation([0, 0, 4])
    legs = [box([6, 6, 20.5], [x, 0, 18.25]) for x in (-5, 5)]
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
