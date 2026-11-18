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
