"""The engineering grade (evals/engineering_grade.py) on a made-up product and a case built by hand:
the case that fits passes, and one case each fails fit, access, retention, strength and sources. Then
parts built by hand for the real specs (e04, e08, e09, e10) that a correct design passes and a wrong
one fails, one test for each fault the first review found (review-r1 F1 to F13)."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(name: str, file: str):
    s = importlib.util.spec_from_file_location(name, ROOT / "evals" / file)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


eg = _load("engineering_grade_t", "engineering_grade.py")
run = _load("run_eng", "run.py")

BODY = {"w": 40.0, "d": 30.0, "h": 20.0, "corner_r": 3.0}
PORT = {"name": "usb_c", "kind": "port", "face": "-y", "c": [20.0, 8.0], "size": [9.0, 3.2], "plug": [12.0, 6.5],
        "source": "https://example.com/drawing.pdf"}
SPEC = {"id": "x01_box_case", "request": "A case for the box.", "input": "text",
        "product": {"name": "a box", "sources": ["https://example.com/drawing.pdf"], "body": BODY, "features": [PORT],
                    "body_sources": {k: "https://example.com/drawing.pdf p1" for k in ("w", "d", "h", "corner_r")}},
        "expect": {"kind": "case", "material": "PLA", "fit": "slip", "retention": "snap", "safety": 2,
                   "covered": ["-z", "+x", "-x", "+y", "-y"], "open": ["+z"]}}
WALL = 2.0
URL = "https://example.com/drawing.pdf"


def _rounded(w, d, r, grow, h):
    import manifold3d as m3

    cs = m3.CrossSection.square([w - 2 * r, d - 2 * r]).translate([r, r]).offset(r + grow, m3.JoinType.Round,
                                                                                 circular_segments=96)
    return m3.Manifold.extrude(cs, h)


def _mesh(m) -> trimesh.Trimesh:
    m = m.to_mesh()
    return trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts), process=True)


def _box(lo, hi):
    import manifold3d as m3

    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return m3.Manifold.cube((hi - lo).tolist()).translate(lo.tolist())


def _cyl(x, y, z0, z1, r):
    import manifold3d as m3

    return m3.Manifold.cylinder(z1 - z0, r, r, 96).translate([x, y, z0])


ARM_ROOT_Z = 10.35  # the snap tongue in the +x wall: slots from the rim down to z 10.3
HOOK_TOP = 1.7  # the tongue runs this far past the rim, its catch from 0.3 to 1.7 mm over the product
SNAP = {"type": "snap", "y": 0.6, "t": 2.0, "L": 11.95 + HOOK_TOP, "w": 6.0,
        "at": [43.6, 17.3, ARM_ROOT_Z], "t_dir": [-1, 0, 0], "L_dir": [0, 0, 1]}


def build_case(clearance: float = 0.3, hole: bool = True, lid: bool = False,
               tongue: bool = True, hook: float = 0.6, hook_out: bool = False,
               bridge: float = 0.0) -> tuple[trimesh.Trimesh, np.ndarray]:
    """An open-top case around BODY: walls and floor WALL thick, `clearance` on every side and under
    it, the port's plug cut through the -y wall, and a snap tongue cut in the +x wall (two slots 0.8
    wide from the rim down 12 mm, 6 mm apart) that runs HOOK_TOP past the rim with a catch `hook` mm
    deep over the product's top edge (0 for none; on the tongue's outer face with hook_out). With
    `bridge`, the slots stop that far under the rim, so the wall above them ties the tongue's sides.
    Returns (mesh in part coordinates, frame)."""
    import manifold3d as m3

    w, d, h, r = BODY["w"], BODY["d"], BODY["h"], BODY["corner_r"]
    lift = WALL + clearance  # the product's bottom, from the bed
    outer = _rounded(w, d, r, clearance + WALL, lift + h)
    inner = _rounded(w, d, r, clearance, clearance + h + 1).translate([0, 0, WALL])
    case = outer - inner
    if hole:
        pw, ph = PORT["plug"]
        u, v = PORT["c"]
        cut = m3.Manifold.cube([pw, WALL + clearance + 2, ph]).translate([u - pw / 2, -(WALL + clearance + 1),
                                                                          lift + v - ph / 2])
        case = case - cut
    if tongue:
        top = lift + h
        for y0 in (d / 2 - 3.8, d / 2 + 3.0):
            case = case - _box([w + clearance - 0.3, y0, top - 12.0],
                               [w + clearance + WALL + 0.3, y0 + 0.8, top - bridge if bridge else top + 1])
        x0, x1, y0, y1 = w + clearance, w + clearance + WALL, d / 2 - 3.0, d / 2 + 3.0
        case = case + _box([x0, y0, top], [x1, y1, top + HOOK_TOP])
        if hook and hook_out:
            case = case + _box([x1 - 0.01, y0, top + 0.3], [x1 + hook, y1, top + HOOK_TOP])
        elif hook:
            case = case + _box([x0 - hook, y0, top + 0.3], [x0 + 0.01, y1, top + HOOK_TOP])
    if lid:  # a plate over the open top, 0.3 mm above the product
        case = case + _rounded(w, d, r, clearance + WALL, WALL).translate([0, 0, lift + h + 0.3])
        case = case + (outer - _rounded(w, d, r, clearance, lift + h + 2)).translate([0, 0, 0.5])
    move = clearance + WALL
    case = case.translate([move, move, 0])  # the case's outer corner near the origin
    mesh = _mesh(case)
    frame = np.eye(4)
    frame[:3, 3] = [move, move, lift]  # the product's min corner, clearance in from each wall
    return mesh, frame


def eng(frame, **over) -> dict:
    e = {"frame": frame.tolist(), "material": "PLA", "clearance": 0.3,
         "retention": dict(SNAP),
         "sources": {"w": URL, "d": URL, "h": URL, "corner_r": URL, "usb_c": URL + " p2"}}
    e.update(over)
    return e


def job_with(tmp_path: Path, mesh, e: dict | None) -> tuple[Path, Path]:
    job = tmp_path / "job"
    (job / "build").mkdir(parents=True)
    stl = job / "case.stl"
    mesh.export(stl)
    if e is not None:
        (job / "build" / "engineering.json").write_text(json.dumps(e))
    return job, stl


@pytest.fixture(scope="module")
def good():
    return build_case()


def test_samples_cover_every_mm2_twice():
    P, N, label = eg.sample_box(BODY)
    w, d, h, r = BODY["w"], BODY["d"], BODY["h"], BODY["corner_r"]
    area = 2 * (w * d - (4 - math.pi) * r * r) + (2 * (w + d) - 8 * r + 2 * math.pi * r) * h
    assert len(P) >= 2 * area
    assert np.allclose(np.linalg.norm(N, axis=1), 1)
    assert set(label) == set(eg.FACES)
    # a round shaft (corner_r half the width) still has four sides
    _, _, lab = eg.sample_box({"w": 6, "d": 6, "h": 15, "corner_r": 3})
    assert {"+x", "-x", "+y", "-y"} <= set(lab)


@pytest.mark.parametrize("face", eg.FACES)
def test_face_uv_is_seen_from_outside(face):
    p = eg.uv_point(face, 5.0, 7.0, BODY)
    assert np.allclose(eg.face_uv(face, p[None], BODY)[0], [5.0, 7.0])
    eu, ev = (np.array(a) for a in eg.face_axes(face))
    n = np.array(eg.NORMAL[face])
    # u to the viewer's right, v up, viewer outside looking in: u x v points back at the viewer
    assert np.allclose(np.cross(eu, ev), n)


def test_the_case_that_fits_passes(tmp_path, good):
    mesh, frame = good
    job, stl = job_with(tmp_path, mesh, eng(frame))
    res = eg.grade(job, SPEC, stl)
    assert res["why"] == [], res["why"]
    faces = res["measured"]["fit"]["faces"]
    for f in SPEC["expect"]["covered"]:
        assert faces[f]["median_gap"] == pytest.approx(0.3, abs=0.02)
    assert res["measured"]["access"]["usb_c"]["blocked_mm3"] < eg.BLOCKED_MM3
    assert res["measured"]["min_wall"] >= eg.MIN_WALL
    assert res["measured"]["printable"] is True


def test_no_engineering_json_fails(tmp_path, good):
    job, stl = job_with(tmp_path, good[0], None)
    assert eg.grade(job, SPEC, stl)["why"] == [eg.NO_FILE]


def test_too_tight_fails_fit(tmp_path):
    mesh, frame = build_case(clearance=-0.2)
    job, stl = job_with(tmp_path, mesh, eng(frame))
    why = eg.grade(job, SPEC, stl)["why"]
    assert any(w.startswith("fit: ") and "inside the part, 0.20 mm deep" in w for w in why), why


def test_blocked_port_fails_access(tmp_path):
    mesh, frame = build_case(hole=False)
    job, stl = job_with(tmp_path, mesh, eng(frame))
    why = eg.grade(job, SPEC, stl)["why"]
    assert [w for w in why if w.startswith("access: usb_c")], why
    assert not [w for w in why if w.startswith(("fit:", "covered:"))], why


def test_a_lid_on_the_open_face_fails_open(tmp_path):
    mesh, frame = build_case(lid=True)
    job, stl = job_with(tmp_path, mesh, eng(frame))
    why = eg.grade(job, SPEC, stl)["why"]
    assert [w for w in why if w.startswith("open: +z is 100% blocked")], why


def test_snap_strain_of_five_percent_fails_in_pla():
    e = {"material": "PLA", "retention": {"type": "snap", "y": 1.0, "t": 2.0, "L": math.sqrt(60)}}
    why = eg.check_retention(e, SPEC)
    assert why == ["retention: snap arm strain 5.0% (1.5 x 1 x 2 / 7.74597^2) is over 2% for PLA"]
    e["material"] = "TPU"  # 5% is fine in TPU, but the type still has to match
    assert eg.check_retention(e, {**SPEC, "expect": {**SPEC["expect"], "material": "TPU"}}) == []
    assert eg.check_retention({"material": "PLA", "retention": {"type": "none"}}, SPEC) == \
        ["retention: none (want snap)"]


def test_screw_holes_follow_the_tables():
    sp = {**SPEC, "expect": {**SPEC["expect"], "retention": "screw"}}
    ok = {"material": "PLA", "retention": {"type": "screw", "size": "M3", "method": "self_tap", "hole_d": 2.4}}
    assert eg.check_retention(ok, sp) == []
    ok["retention"].update(method="insert", hole_d=4.0)
    assert eg.check_retention(ok, sp) == []
    ok["retention"].update(hole_d=3.0)
    assert eg.check_retention(ok, sp) == ["retention: M3 insert hole 3.00 mm (want 4.00 +/- 0.15 mm)"]


def test_a_thin_arm_fails_strength():
    sp = {**SPEC, "expect": {**SPEC["expect"], "kind": "mount", "load_n": 20, "load_dir": "-z"}}
    weak = {"material": "PLA", "load": {"n": 20, "dir": "-z", "arm": 40, "b": 10, "h": 2, "across_layers": False}}
    why, m = eg.check_strength(weak, sp, 2)
    # 6 x 20 x 40 / (10 x 2^2) = 120 MPa against 50 / 2
    assert m["sigma_mpa"] == pytest.approx(120.0)
    assert why == ["strength: 120.0 MPa at the critical section (20 N x 40 mm on 10 x 2 mm), allowed 25.0 MPa "
                   "(PLA 50 MPa, safety 2)"]
    strong = {**weak, "load": {**weak["load"], "b": 20, "h": 8}}  # 6 x 800 / 1280 = 3.75 MPa
    assert eg.check_strength(strong, sp, 2)[0] == []
    across = {**weak, "load": {**weak["load"], "b": 20, "h": 4, "across_layers": True}}  # 15 MPa vs 12.5
    assert eg.check_strength(across, sp, 2)[0][0].endswith("x0.5 across layers, safety 2)")
    assert eg.check_strength({"material": "PLA"}, sp, 2)[0] == \
        ["strength: no load in engineering.json (the spec asks 20 N)"]


def test_a_missing_source_fails(tmp_path, good):
    mesh, frame = good
    e = eng(frame)
    del e["sources"]["h"]
    e["sources"]["usb_c"] = "from memory"
    assert eg.check_sources(e, SPEC) == ["sources: no source for h, usb_c (a URL the spec cites for it)"]
    e["sources"].update(h="photo with a bank card", usb_c="calipers")
    photo = {**SPEC, "input": "photo"}
    assert eg.check_sources(e, photo) == []


def test_sources_from_text_must_be_urls_the_spec_cites():
    """F13: "https://" alone, calipers, or a URL the spec never cites does not count for a text request."""
    e = {"sources": {"w": URL, "d": URL + " p2", "h": "https://", "corner_r": "calipers",
                     "usb_c": "https://example.org/made-up.pdf"}}
    assert eg.check_sources(e, SPEC) == ["sources: no source for h, corner_r, usb_c (a URL the spec cites for it)"]
    # from a photo, calipers and any real URL count, but "https://" with no host still does not
    assert eg.check_sources(e, {**SPEC, "input": "photo"}) == \
        ["sources: no source for h (a URL, calipers or a photo with a reference)"]


def test_a_scaled_frame_is_refused():
    M = np.eye(4)
    M[0, 0] = 1.01
    assert eg.read_frame(M.tolist())[0] is None
    assert eg.read_frame([[1, 0, 0, 0]])[0] is None
    assert eg.read_frame(np.eye(4).tolist())[0] is not None


def test_run_grades_a_product_spec_with_no_part(tmp_path):
    """grade_job on an engineering spec: no recipe is expected, and no part says why twice."""
    job = tmp_path / "job"
    job.mkdir()
    g = run.grade_job(job, SPEC, [])
    assert g["pass"] is False
    assert g["why"] == ["no finished part", eg.NO_FILE]


def test_every_engineering_spec_is_well_formed():
    """Each spec in evals/engineering: the schema of evals/README.md, a source for every number."""
    specs = sorted((ROOT / "evals" / "engineering").glob("*.json"))
    assert len(specs) == 10
    for p in specs:
        s = json.loads(p.read_text())
        assert s["id"] == p.stem and s["input"] in ("text", "model_number", "photo")
        prod, exp = s["product"], s["expect"]
        assert prod["sources"] and all(u.startswith("https://") for u in prod["sources"])
        assert all(prod["body"][k] >= 0 for k in ("w", "d", "h", "corner_r"))
        for f in prod.get("features", []):
            assert f["face"] in eg.FACES and len(f["c"]) == 2 and len(f["size"]) == 2, (p.name, f)
            assert f["kind"] in ("port", "button", "switch", "vent", "lens", "screen", "led", "slot", "hole")
            assert f.get("shape", "rect") in ("rect", "circle")
            assert f.get("source"), (p.name, f["name"])
            # F7: a port names the plug that must pass, or says why no plug size is published
            if f["kind"] in ("port", "button", "switch"):  # r2 F5: a button or switch names its fingertip
                assert f.get("plug") or f.get("plug_note"), (p.name, f["name"])
        if "profile" in prod["body"]:
            prof = prod["body"]["profile"]
            assert prof[0][0] == 0 and prof[-1][0] == 0 and max(z for _, z in prof) == prod["body"]["h"]
            assert max(r for r, _ in prof) == pytest.approx(prod["body"]["w"] / 2)
        assert exp["kind"] in ("case", "holder", "mount", "adapter", "replacement")
        assert (exp["material"], exp["fit"]) in eg.FIT
        assert exp["retention"] in ("friction", "snap", "screw", "none", "any")
        assert set(exp["covered"]) <= set(eg.FACES) and set(exp["open"]) <= set(eg.FACES)
        assert not set(exp["covered"]) & set(exp["open"])
        assert set(exp.get("face_gap", {})) <= set(exp["covered"]) | {exp.get("support")}
        assert exp.get("support", "-z") in eg.FACES and exp.get("support") not in exp["open"]
        assert set(exp.get("min_gap", {})) <= set(eg.FACES) and ("min_gap" in exp) == ("min_gap_note" in exp)
        if exp.get("attach"):
            att = exp["attach"]
            assert att["face"] in eg.FACES and att["screw"] in eg.CLEARANCE and att["min"] >= 1 and att["source"]
        assert bool(exp.get("attach")) == (p.stem in ("e05_appletv_wall_holder", "e07_mac_mini_mount")), p.name
        for ph in exp.get("part_holes", []):
            assert ph["axis"] in eg.FACES and ph["d"] > 0 and ph["pattern"] and ph["source"]
        # review r1 F5: a part hung from a wall or desk carries a load too
        assert ("load_n" in exp) == (exp["kind"] == "mount" or bool(exp.get("attach"))), p.name
        # review r1 F8: each number cites its own document, not only the product's list
        own = dict(prod.get("body_sources") or {})
        own.update({f["name"]: f.get("source", "") for f in prod.get("features", [])})
        need = ["w", "d", "h", "corner_r"] + (["profile"] if "profile" in prod["body"] else []) + \
            [f["name"] for f in prod.get("features", [])]
        if s["input"] != "photo":
            assert all(eg._cited(own.get(k, "")) for k in need), (p.name, [k for k in need if not eg._cited(own.get(k, ""))])
        if exp.get("load_dir"):  # F3: a load has a face to bear on
            assert exp.get("support", exp["load_dir"]) == exp["load_dir"], p.name
    e01 = json.loads((ROOT / "evals" / "engineering" / "e01_rpi5_case.json").read_text())
    usb = next(f for f in e01["product"]["features"] if f["name"] == "usb_c_power")
    assert usb["plug"] == [12.45, 6.6] and usb["depth"] == 14.0
    button = next(f for f in e01["product"]["features"] if f["name"] == "power_button")
    assert button["plug"] == [10.0, 10.0] and button["shape"] == "circle"
    e06 = json.loads((ROOT / "evals" / "engineering" / "e06_iphone_desk_holder.json").read_text())
    assert e06["product"]["features"][0]["depth"] == 14.0  # F6: Apple's note 2, outward 14.0 mm


# --- the first review's faults, each on a part built by hand -----------------------------------------

def spec(name: str) -> dict:
    return json.loads((ROOT / "evals" / "engineering" / f"{name}.json").read_text())


def fit_and(mesh, sp: dict, frame: np.ndarray, mat: str):
    why, fit = eg.check_fit(mesh, sp, frame, mat)
    return why, fit


def airtag_case(lip: str = "dome", hole_r: float = 13.4, gap: float = 0.15, wall: float = 1.6):
    """A case around the AirTag of e04, revolved: `gap` off the tag everywhere, `wall` thick, a lip over
    the dome's edge out of the Ø25.75 keepout ("dome": the lip follows the dome, "flat": a flat lip at
    the dome's peak height, "over": the lip runs in over the keepout to r 8)."""
    import manifold3d as m3

    body = spec("e04_airtag_case")["product"]["body"]
    cs = m3.CrossSection([[(float(r), float(z)) for r, z in body["profile"]]])
    half = m3.CrossSection.square([40.0, 40.0]).translate([0.0, -20.0])

    def rev(delta):
        return m3.Manifold.revolve(cs.offset(delta, m3.JoinType.Round, circular_segments=64) ^ half, 256)

    if lip == "flat":
        R = body["w"] / 2
        case = _cyl(0, 0, -gap - wall, body["h"] + gap + wall, R + gap + wall) - \
            _cyl(0, 0, -gap, body["h"] + gap, R + gap)
    else:
        case = rev(gap + wall) - rev(gap)
    case = case - _cyl(0, 0, 3.0, 20.0, 8.0 if lip == "over" else hole_r)
    frame = np.eye(4)
    frame[:3, 3] = [-body["w"] / 2, -body["d"] / 2, 0.0]
    return _mesh(case), frame


def test_airtag_case_that_follows_apples_dome_passes_fit_and_access():
    """F1 and F10: a snug case whose lip curls over the dome's edge and leaves the round Ø25.75 keepout
    open. Graded against a square keepout and a 7.98 mm cylinder, this case failed (the lip sat inside
    the cylinder and inside the square's corners)."""
    sp = spec("e04_airtag_case")
    mesh, frame = airtag_case()
    why, fit = eg.check_fit(mesh, sp, frame, "PETG")
    assert why == [], why
    assert fit["faces"]["+z"]["median_gap"] == pytest.approx(0.15, abs=0.03)
    aw, acc = eg.check_access(mesh, sp, frame, fit)
    assert aw == [], aw
    assert acc["speaker_keepout"]["blocked_mm3"] < eg.BLOCKED_MM3


def test_airtag_keepout_is_round():
    """F1: the keepout's path is a Ø25.75 cylinder, not a 25.75 mm square."""
    sp = spec("e04_airtag_case")
    f = sp["product"]["features"][0]
    path = eg.plug_path(f, sp["product"]["body"], np.eye(4), 5.0)
    sag = eg.top_sag(sp["product"]["body"], 25.75 / 2)
    assert 0.8 < sag < 1.0  # Detail A: the top is 7.03 to 7.20 mm high at r 12.9
    assert path.volume() == pytest.approx(math.pi * (25.75 / 2) ** 2 * (5.0 - 0.05 + sag), rel=0.01)


def test_airtag_case_over_the_keepout_or_loose_on_the_dome_fails():
    sp = spec("e04_airtag_case")
    mesh, frame = airtag_case(lip="over")
    why, fit = eg.check_fit(mesh, sp, frame, "PETG")
    aw, _ = eg.check_access(mesh, sp, frame, fit)
    assert [w for w in aw if w.startswith("access: speaker_keepout")], aw
    # F10: a flat lip at the dome's peak never touches the curved dome: loose, not snug
    mesh, frame = airtag_case(lip="flat")
    why, _ = eg.check_fit(mesh, sp, frame, "PETG")
    assert [w for w in why if w.startswith(("fit: +z gap", "covered: +z"))], why


def pi4_plate(pi_holes: bool = True, vesa: bool = True, vesa_shift: float = 0.0, standoffs: bool = True):
    """A PETG plate 5 mm under the Pi 4 of e08 (product frame = part frame): 3 mm thick, Ø6 standoffs
    up to the board at its four holes with Ø1.875 pilots (M2.5 self-tapping in PETG), and the VESA 75
    pattern as four Ø4.5 holes through the plate around the board's middle."""
    cx, cy = 42.5, 28.0
    plate = _box([cx - 47.5, cy - 47.5, -8.0], [cx + 47.5, cy + 47.5, -5.0])
    for x in (3.5, 61.5):
        for y in (3.5, 52.5):
            if standoffs:
                plate = plate + _cyl(x, y, -5.5, 0.0, 3.0)
            if pi_holes:
                plate = plate - _cyl(x, y, -9.0, 1.0, 1.875 / 2)
    if vesa:
        for sx in (-37.5, 37.5):
            for sy in (-37.5, 37.5):
                plate = plate - _cyl(cx + sx + vesa_shift, cy + sy, -9.0, -4.0, 4.5 / 2)
    e = {"retention": {"type": "screw", "size": "M2.5", "method": "self_tap", "hole_d": 1.875},
         "part_holes": {"vesa_75": {"c": [cx, cy, -8.0], "u": [1, 0, 0]}}}
    return _mesh(plate), e


def test_vesa_adapter_with_lined_up_holes_passes():
    """F2: e08's holes are checked: the board's four holes have a pilot under them with the plate
    around it, and the VESA 75 pattern is four clear holes through the plate."""
    sp = spec("e08_rpi4_vesa_adapter")
    mesh, e = pi4_plate()
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    why, out = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert why == [], why
    assert len(out["vesa_75"]) == 4 and all(r["bore_mm3"] < eg.BLOCKED_MM3 for r in out["vesa_75"])


def test_vesa_adapter_flat_plate_with_no_holes_fails():
    """F2: a flat plate with no holes passed every check before; now each missing hole is a line."""
    sp = spec("e08_rpi4_vesa_adapter")
    mesh, e = pi4_plate(pi_holes=False, vesa=False)
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    why, _ = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert len([w for w in why if w.startswith("holes: mount_hole_") and "no hole in the part" in w]) == 4, why
    assert [w for w in why if w.startswith("holes: vesa_75: 4 of 4 holes are not clear")], why
    # holes 1 mm off the declared pattern do not line up either
    mesh, e = pi4_plate(vesa_shift=1.0)
    why, _ = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert [w for w in why if w.startswith("holes: vesa_75:")], why
    # a plate far under the board, holes and all, gives a self-tapping screw nothing to bear on (a
    # through hole is found wherever the plate is: test_pi4_plate_on_bought_standoffs_passes)
    mesh, e = pi4_plate(standoffs=False)
    assert e["retention"]["method"] == "self_tap"
    why, _ = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert len([w for w in why if "nothing to bear on" in w]) == 4, why
    del e["part_holes"]
    why, _ = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert "holes: engineering.json does not place vesa_75 (part_holes.vesa_75 c and u)" in why


def test_a_feature_on_an_open_face_is_checked_too():
    """F2: access ran only for features on covered faces; a bar right in front of a port on an open
    face passed, since the open check leaves the port's own area out."""
    sp = {**SPEC, "expect": {**SPEC["expect"], "covered": ["-z"], "open": ["-y", "+z"]}}
    mesh, frame = build_case()
    floor = _box([0, 0, 0], [46, 36, 2.0])
    bar = _box([2.3 + 14, 2.3 - 9, 2.3 + 5], [2.3 + 26, 2.3 - 6, 2.3 + 11])
    mesh = _mesh(floor + bar)
    why, fit = eg.check_fit(mesh, sp, frame, "PLA")
    assert not [w for w in why if w.startswith("open:")], why
    aw, acc = eg.check_access(mesh, sp, frame, fit)
    assert [w for w in aw if w.startswith("access: usb_c")], aw
    assert acc["usb_c"]["path_mm"] == eg.OPEN_REACH


def tray(lips: str):
    """Side walls around BODY at 0.3 mm and, under it, nothing ("none"), one lip along -x ("one"), or
    lips along both sides ("both"), 8 mm wide, 0.3 mm under the product."""
    w, d, h = BODY["w"], BODY["d"], BODY["h"]
    walls = _box([-2.3, -2.3, -2.3], [w + 2.3, d + 2.3, h]) - _box([-0.3, -0.3, -3.0], [w + 0.3, d + 0.3, h + 1])
    if lips in ("one", "both"):
        walls = walls + _box([-2.3, -2.3, -2.3], [8.0, d + 2.3, -0.3])
    if lips == "both":
        walls = walls + _box([w - 8.0, -2.3, -2.3], [w + 2.3, d + 2.3, -0.3])
    return _mesh(walls)


@pytest.mark.parametrize("lips,ok", [("none", False), ("one", False), ("both", True)])
def test_a_load_needs_the_part_under_it(lips, ok):
    """F3: a mount with load_dir -z and -z not covered: walls alone, or one lip, let the product drop
    or tip; lips on both sides hold it."""
    sp = {**SPEC, "expect": {**SPEC["expect"], "kind": "mount", "load_n": 20, "load_dir": "-z",
                             "covered": ["+x", "-x"], "open": ["+z"]}}
    sp["product"] = {**SPEC["product"], "features": []}
    _, fit = eg.check_fit(tray(lips), sp, np.eye(4), "PLA")
    why, out = eg.check_support(sp, fit)
    assert (why == []) == ok, (why, out)
    if not ok:
        assert why[0].startswith("support: the part bears on -z in ")


def uno_case():
    """A PLA case for the UNO R4 Minima of e10 on four Ø6 standoffs 2 mm tall, so the through-hole
    leads under the board clear the floor; walls 0.3 off +x, +y and -y; -x and the top open."""
    sp = spec("e10_model_number_case")
    w, d, h = (sp["product"]["body"][k] for k in ("w", "d", "h"))
    case = _box([-2.3, -2.3, -4.0], [w + 2.3, d + 2.3, h]) - _box([-0.3, -0.3, -2.0], [w + 0.3, d + 0.3, h + 1])
    case = case - _box([-5.0, -0.3, -2.0], [0.5, d + 0.3, h + 1])  # the -x end left open
    for x in (5.0, w - 5.0):
        for y in (5.0, d - 5.0):
            case = case + _cyl(x, y, -2.5, 0.0, 3.0)
    return sp, _mesh(case)


def test_uno_case_on_standoffs_passes():
    """F11: -z was covered at a slip gap at the bare PCB's underside, so a case on standoffs that clears
    the board's leads failed with a 2 mm -z gap. Now -z must only bear the board."""
    sp, mesh = uno_case()
    why, fit = eg.check_fit(mesh, sp, np.eye(4), "PLA")
    assert why == [], why
    sw, out = eg.check_support(sp, fit)
    assert sw == [], (sw, out)
    assert "-z" not in sp["expect"]["covered"] and sp["expect"]["support"] == "-z"


def knob(extra: float):
    """A PLA knob for e09's 6.0 mm shaft: bore Ø6.0 (press), `extra` mm deeper than the 7 mm knurl."""
    body = _cyl(0, 0, 0.0, 7.0 + extra + 3.0, 8.0) - _cyl(0, 0, -1.0, 7.0 + extra, 3.0)
    frame = np.eye(4)
    frame[:3, 3] = [-3.0, -3.0, 0.0]
    return _mesh(body), frame


def test_knob_bore_deeper_than_the_shaft_passes():
    """F12: the press band applied to the shaft's tip too, so a knob whose bore is 0.5 mm deeper than
    the shaft failed with "+z gap 0.50". The tip has its own band now."""
    sp = spec("e09_pot_knob")
    mesh, frame = knob(0.5)
    why, fit = eg.check_fit(mesh, sp, frame, "PLA")
    assert why == [], why
    assert fit["faces"]["+z"]["median_gap"] == pytest.approx(0.5, abs=0.02)
    # a bore 1.5 mm deeper no longer grips the knurl's end: out of the tip's band
    mesh, frame = knob(1.5)
    why, _ = eg.check_fit(mesh, sp, frame, "PLA")
    assert [w for w in why if w.startswith(("fit: +z", "covered: +z"))], why


def test_the_snap_arm_must_be_in_the_part(tmp_path):
    """F4: a snap arm declared in engineering.json but not cut in the part, or thicker or shorter than
    declared, fails."""
    mesh, frame = build_case(tongue=False)
    why = eg.check_retention_mesh(mesh, eng(frame))
    assert "retention: the snap arm is not free at its sides: the part is 30.2 mm wide 5% along it (w says 6)" in why
    mesh, frame = build_case()
    assert eg.check_retention_mesh(mesh, eng(frame)) == []
    thin = eng(frame, retention={**SNAP, "t": 1.5})
    assert eg.check_retention_mesh(mesh, thin) == \
        ["retention: the snap arm is 2.00 mm thick at its root in the part (t says 1.5)"]
    long = eng(frame, retention={**SNAP, "L": 20.0})
    assert eg.check_retention_mesh(mesh, long)[0].startswith("retention: the snap arm runs 13.65 mm from its root")
    nowhere = eng(frame, retention={**SNAP, "at": [0, 0, 50]})
    assert eg.check_retention_mesh(mesh, nowhere)[0].endswith("is not inside the part")
    # and in the whole grade: no arm, no pass
    job, stl = job_with(tmp_path, build_case(tongue=False)[0], eng(frame))
    assert [w for w in eg.grade(job, SPEC, stl)["why"] if w.startswith("retention: the snap arm")]


def block_with_hole(hole: float | None):
    b = _box([0, 0, 0], [20, 20, 10])
    if hole:
        b = b - _cyl(10, 10, 4.0, 11.0, hole / 2)
    return _mesh(b)


def test_screw_holes_must_be_in_the_part():
    """F4: a screw passed on hole_d alone; now each declared hole is probed in the mesh."""
    ret = {"type": "screw", "size": "M3", "method": "self_tap", "hole_d": 2.4,
           "holes": [{"at": [10, 10, 10], "axis": [0, 0, -1]}]}
    assert eg.check_retention_mesh(block_with_hole(2.4), {"retention": ret}) == []
    why = eg.check_retention_mesh(block_with_hole(None), {"retention": ret})
    assert why and why[0].startswith("retention: screw hole 0 is not in the part")
    off = {**ret, "holes": [{"at": [14, 10, 10], "axis": [0, 0, -1]}]}
    assert eg.check_retention_mesh(block_with_hole(2.4), {"retention": off})
    assert eg.check_retention_mesh(block_with_hole(2.4), {"retention": {**ret, "holes": []}}) == \
        ["retention: the screw holes are not placed in the part (holes: [{at, axis}])"]


def test_the_critical_section_is_measured():
    """F4: strength took b and h on trust; the section is measured in the part, and the smaller counts."""
    sp = {**SPEC, "expect": {**SPEC["expect"], "kind": "mount", "load_n": 20, "load_dir": "-z"}}
    beam = _mesh(_box([0, 0, 0], [20, 60, 8]))
    load = {"n": 20, "dir": "-z", "arm": 40, "b": 20, "h": 8, "across_layers": False,
            "section": {"at": [10, 5, 4], "b_dir": [1, 0, 0], "h_dir": [0, 0, 1]}}
    why, m = eg.check_strength({"material": "PLA", "load": load}, sp, 2, beam)
    assert why == [] and m["section_mm"] == [20.0, 8.0]
    big = {**load, "h": 30}
    why, m = eg.check_strength({"material": "PLA", "load": big}, sp, 2, beam)
    assert why == ["strength: the critical section is 20.00 x 8.00 mm in the part (b x h says 20 x 30)"]
    no_sec = {k: v for k, v in load.items() if k != "section"}
    why, _ = eg.check_strength({"material": "PLA", "load": no_sec}, sp, 2, beam)
    assert why == ["strength: the critical section is not placed in the part (section at, b_dir, h_dir)"]


@pytest.mark.parametrize("ret,line", [
    ({"type": "snap", "y": 0.6, "t": 1.5, "L": 0}, "retention: the snap has L 0 (it must be a number above 0)"),
    ({"type": "snap", "y": 0.6, "t": "x", "L": 9}, "retention: the snap has t 'x', not a number"),
    ({"type": "screw", "size": "M3", "method": "insert", "hole_d": float("nan")},
     "retention: the screw has hole_d nan (it must be a number above 0)"),
])
def test_bad_retention_inputs_fail_with_a_line(ret, line):
    """F5: an L of 0 raised ZeroDivisionError and stopped the eval run."""
    sp = {**SPEC, "expect": {**SPEC["expect"], "retention": ret["type"]}}
    assert eg.check_retention({"material": "PLA", "retention": ret}, sp) == [line]


@pytest.mark.parametrize("k,v", [("h", 0), ("b", 0), ("arm", -40), ("n", float("inf"))])
def test_bad_load_inputs_fail_with_a_line(k, v):
    """F5: h or b of 0 raised ZeroDivisionError; a negative arm made the stress negative and passed."""
    sp = {**SPEC, "expect": {**SPEC["expect"], "kind": "mount", "load_n": 20, "load_dir": "-z"}}
    load = {"n": 20, "dir": "-z", "arm": 40, "b": 20, "h": 8, k: v}
    why, _ = eg.check_strength({"material": "PLA", "load": load}, sp, 2)
    assert why == [f"strength: the load has {k} {v:g} (it must be a number above 0)"]


def test_a_feature_depth_reaches_past_the_wall():
    """F6: Apple's USB-C keepout reaches 14 mm out; a shelf 6 to 9 mm in front of the port, outside
    the old wall plus 3 mm path, now blocks it."""
    mesh, frame = build_case()
    shelf = _box([2.3 + 14, 2.3 - 9, 2.3 + 5], [2.3 + 26, 2.3 - 6, 2.3 + 11])
    both = _mesh(eg._to_manifold(mesh) + shelf)
    _, fit = eg.check_fit(both, SPEC, frame, "PLA")
    assert eg.check_access(both, SPEC, frame, fit)[0] == []
    deep = {**SPEC, "product": {**SPEC["product"], "features": [{**PORT, "depth": 14.0}]}}
    aw, acc = eg.check_access(both, deep, frame, fit)
    assert acc["usb_c"]["path_mm"] == 14.0 and aw and aw[0].startswith("access: usb_c")


def test_an_open_mesh_is_not_read_as_clear(tmp_path):
    """F9: manifold3d turns an open mesh into an empty solid, which read every path as clear."""
    box = trimesh.creation.box([10, 10, 10])
    box.update_faces(np.arange(len(box.faces)) != 0)
    part, why = eg.closed_part(box)
    assert part is None and why.startswith("access: the part is not a closed solid")
    _, fit = eg.check_fit(box, SPEC, np.eye(4), "PLA")
    assert eg.check_access(box, SPEC, np.eye(4), fit)[0] == [why]


def test_run_still_wants_the_recipe_of_a_non_engineering_spec(tmp_path):
    """F8: a spec with no product and no recipe (a typo) raises, as before the engineering suite."""
    job = tmp_path / "job"
    job.mkdir()
    with pytest.raises(KeyError):
        run.grade_job(job, {"id": "t0_typo", "request": "a box", "expect": {"recipe_typo": "box"}}, [])


PI5_HOLES = [(3.95, 5.13), (61.95, 5.13), (3.95, 54.13), (61.95, 54.13)]  # e01's frame: board + 0.45, + 1.63


def pi5_case(post_top: float = 1.45, floor_top: float = -2.0):
    """A PLA case for e01's Pi 5 on four Ø6 standoffs at its mounting holes, up to the PCB underside
    (frame z 1.45, above the microSD socket that sets the body's -z), floor top at `floor_top` (2 mm
    under the body), walls 0.3 off the sides, top open."""
    sp = spec("e01_rpi5_case")
    w, d, h = (sp["product"]["body"][k] for k in ("w", "d", "h"))
    case = _box([-2.3, -2.3, -4.0], [w + 2.3, d + 2.3, h]) - _box([-0.3, -0.3, -2.0], [w + 0.3, d + 0.3, h + 1])
    if floor_top > -2.0:  # a floor flat across the underside, stopping 0.01 mm inside the side faces
        case = case + _box([0.01, 0.01, -2.01], [w - 0.01, d - 0.01, floor_top])
    for x, y in PI5_HOLES:
        case = case + _cyl(x, y, -2.5, post_top, 3.0)
    return sp, _mesh(case)


def test_pi5_case_on_standoffs_passes():
    """Review round 2 F1: e01 covered -z at a slip gap under the microSD socket, so standoffs that
    reach the PCB 1.45 mm above it read as inside the product and a normal Pi case failed."""
    sp, mesh = pi5_case()
    why, fit = eg.check_fit(mesh, sp, np.eye(4), "PLA")
    assert why == [], why
    sw, out = eg.check_support(sp, fit)
    assert sw == [], (sw, out)
    old = {**sp, "expect": {**sp["expect"], "covered": sp["expect"]["covered"] + ["-z"], "face_gap": {}}}
    why_old, _ = eg.check_fit(mesh, old, np.eye(4), "PLA")
    assert any("inside the part" in w for w in why_old), why_old


def test_pi5_standoffs_into_the_board_fail():
    """Standoffs 1 mm past the PCB underside push into the board."""
    sp, mesh = pi5_case(post_top=2.45)
    why, _ = eg.check_fit(mesh, sp, np.eye(4), "PLA")
    assert any("inside the part" in w for w in why), why


# --- the second review's faults (review-r2), each on a part built by hand ----------------------------

def test_snap_catch_is_measured():
    """r2 F3: the undercut y was never measured. A catch 0.6 deep declared as 0.2 read 1.7% strain where
    the real one is over 2%, and a tongue with no catch at all passed: it holds nothing."""
    mesh, frame = build_case()
    assert eg._hook(mesh, np.array(SNAP["at"], float), np.array([-1.0, 0, 0]), np.array([0, 0, 1.0]),
                    SNAP["L"]) == pytest.approx(0.6, abs=0.02)
    small = eng(frame, retention={**SNAP, "y": 0.2})
    assert eg.check_retention_mesh(mesh, small) == \
        ["retention: the snap arm's catch stands out 0.60 mm in the part (y says 0.2)"]
    bare, frame = build_case(hook=0)
    why = eg.check_retention_mesh(bare, eng(frame, retention={**SNAP, "y": 0.2}))
    assert why == ["retention: the snap arm has no catch: it stands out 0.00 mm toward the product past its root "
                   "face in its outer half (y says 0.2)"], why


def test_snap_root_must_be_where_the_arm_joins_the_part():
    """r2 F4: `at` moved 6 mm down into the solid wall under the slots with L 6 mm longer passed every
    check (the sides were probed only halfway along) and read a lower strain. Declared up in the free
    tongue, the root has the tongue, not the wall, behind it."""
    mesh, frame = build_case()
    sunk = eng(frame, retention={**SNAP, "at": [43.6, 17.3, ARM_ROOT_Z - 6.0], "L": SNAP["L"] + 6.0})
    why = eg.check_retention_mesh(mesh, sunk)
    assert "retention: the snap arm is not free at its sides: the part is 30.2 mm wide 5% along it (w says 6)" in why
    high = eg.check_retention_mesh(mesh, eng(frame, retention={**SNAP, "at": [43.6, 17.3, ARM_ROOT_Z + 4.0],
                                                                "L": SNAP["L"] - 4.0}))
    assert [w for w in high if w.startswith("retention: the snap arm's root is not where it joins the part: 0.5 mm "
                                            "behind it the part is 6.0 mm wide")], high


def mount_spec():
    return {**SPEC, "product": {**SPEC["product"], "features": []},
            "expect": {**SPEC["expect"], "kind": "mount", "load_n": 20, "load_dir": "-z", "support": "-z",
                       "covered": ["+x", "-x"], "open": ["+z"]}}


def test_the_arm_is_measured_from_where_the_product_bears():
    """r2 F2: engineering.json could declare arm 1 at a thick spot, or turn h_dir along the part's
    longest side, and strength passed a part that would snap. Now the arm is what the section carries
    of the load, h_dir must lie along the load, and the layers come from the beam's axis."""
    sp, mesh, _ = mac_mount(FLANGE_HOLES, flange=15.0)
    sp = {**sp, "expect": {k: v for k, v in sp["expect"].items() if k != "attach"}}
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    sec = {"at": [0.0, 63.5, -1.8], "b_dir": [0, 1, 0], "h_dir": [0, 0, 1]}  # the root of the -x lip
    load = {"n": 20, "dir": "-z", "arm": 1, "b": 20, "h": 3, "across_layers": False, "section": sec}
    why, m = eg.check_strength({"material": "PETG", "load": load}, sp, 2, mesh, np.eye(4), fit)
    assert m["arm_mm"] == pytest.approx(3.75, abs=0.4), m
    assert [w for w in why if w.startswith("strength: the arm is ") and "where the product bears (arm says 1)" in w], why
    # h_dir along the lip's 127 mm depth, not the load, is refused
    side = {**load, "arm": 3.75, "h": 20, "b": 3, "section": {**sec, "b_dir": [0, 0, 1], "h_dir": [0, 1, 0]}}
    why, _ = eg.check_strength({"material": "PETG", "load": side}, sp, 2, mesh, np.eye(4), fit)
    assert "strength: the section's h_dir is not along the load (-z): bending under it is across h" in why
    # a part printed on its side: the load runs along the bed, the beam's axis up z, so across the layers
    R = np.array([[0, 0, -1, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]], float)  # product -z to part +x
    beam = _mesh(_box([-8, 0, 0], [0, 20, 60]))
    R[:3, 3] = [-24.0, -5.0, 25.0]  # the product's middle (part z 45) 40 mm up the beam from the section
    lo = {"n": 20, "dir": "-z", "arm": 40, "b": 20, "h": 8, "across_layers": False,
          "section": {"at": [-4, 10, 5], "b_dir": [0, 1, 0], "h_dir": [1, 0, 0]}}
    tip = mount_spec()
    why, m = eg.check_strength({"material": "PLA", "load": lo}, {**tip, "expect": {**tip["expect"], "support": None}},
                               2, beam, R, None)
    assert m["across_layers"] is True and m["allowed_mpa"] == 12.5 and m["arm_mm"] == pytest.approx(40, abs=0.5), m


FLANGE_HOLES = [(-10.5, 30.0), (-10.5, 97.0), (137.5, 30.0), (137.5, 97.0)]  # on 15 mm flanges, off the Mac


def mac_mount(holes: list[tuple[float, float]] | None = None, top: float = 3.0, flange: float = 0.0,
              recess: str | None = None):
    """A PETG tray for e07's Mac mini, product frame = part frame: 3 mm walls at 0.3 mm on +x and -x,
    a `top` mm top 0.3 mm over the Mac, lips 15 mm wide under each side, open front and back, the top
    run out `flange` mm past each side wall, and M4 holes (Ø4.5) through the top at `holes` (x, y),
    with an Ø8.8 counterbore 3.4 deep ("cbore") or a 90 degree Ø8.8 countersink ("csink") on the
    inside."""
    import manifold3d as m3

    sp = spec("e07_mac_mini_mount")
    w, d, h = (sp["product"]["body"][k] for k in ("w", "d", "h"))
    roof = h + 0.3 + top
    tray_ = _box([-3.3, 0, -3.3], [w + 3.3, d, roof]) - _box([-0.3, -1, -0.3], [w + 0.3, d + 1, h + 0.3])
    tray_ = tray_ - _box([15.0, -1, -4.0], [w - 15.0, d + 1, -0.2])
    if flange:
        tray_ = tray_ + _box([-3.3 - flange, 0, h + 0.3], [w + 3.3 + flange, d, roof])
    for x, y in holes or []:
        tray_ = tray_ - _cyl(x, y, h - 1.0, roof + 2.0, 4.5 / 2)
        if recess == "cbore":
            tray_ = tray_ - _cyl(x, y, h - 1.0, h + 0.3 + 3.4, 8.8 / 2)
        elif recess == "csink":
            cone = m3.Manifold.cylinder(2.15 + 0.01, 4.4 + 0.01, 2.25 - 0.0, 96).translate([x, y, h + 0.3 - 0.01])
            tray_ = tray_ - cone
    e = {"material": "PETG", "attach": {"holes": [{"at": [x, y, roof]} for x, y in holes or []]}}
    return sp, _mesh(tray_), e


def test_mac_mount_must_screw_to_the_desk():
    """r2 F6: e07's tray that sat on the floor, wrapped the Mac and had no way onto the desk passed. Now
    it needs two M4 clearance holes through its +z side."""
    sp, mesh, e = mac_mount(FLANGE_HOLES, flange=15.0)
    why, out, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    assert why == [] and len(good) == 4, (why, out)
    sp0, bare, e0 = mac_mount([], flange=15.0)
    why, _, _ = eg.attach_holes(bare, sp0, e0, np.eye(4))
    assert why == ["attach: 0 good screw holes on the +z side for M4 (need 2, ISO 273 4.3 to 4.8 mm, through its wall), "
                   "so it cannot be screwed to the desk"]
    # a hole listed twice, a mouth inside the part, and a hole the part does not have, are not counted
    e2 = {"attach": {"holes": [{"at": [-10.5, 30.0, 53.3]}, {"at": [-10.4, 30.0, 53.3]}, {"at": [-10.5, 60.0, 51.0]},
                               {"at": [-10.5, 75.0, 53.3]}]}}
    why, out, good = eg.attach_holes(mesh, sp, e2, np.eye(4))
    assert len(good) == 1 and len(why) == 4, why


def test_attach_screw_heads_need_room():
    """Review r1 second-F6: Ø4.5 holes through a 3 mm top 0.3 mm over the Mac passed attach, but a pan
    head (Ø8.2 x 3.1) under that top lands in the 0.3 mm gap: the Mac cannot slide in, or it bears on
    the heads. Holes on flanges off the Mac, or holes over it with a counterbore or a countersink that
    holds the head, pass."""
    over = [(30.0, 30.0), (97.0, 97.0)]
    sp, mesh, e = mac_mount(over)
    why, out, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    assert len(good) == 0 and len([w for w in why if "has no room for its screw head" in w]) == 2, (why, out)
    sp, mesh, e = mac_mount(over, top=6.5, recess="cbore")
    why, out, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    assert why == [] and {r["head"] for r in out["holes"]} == {"pan"}, (why, out)
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    assert not [w for w in eg.check_fit(mesh, sp, np.eye(4), "PETG")[0] if "inside the part" in w]
    sp, mesh, e = mac_mount(over, recess="csink")
    why, out, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    assert why == [] and {r["head"] for r in out["holes"]} == {"flat"}, (why, out)
    # a counterbore too shallow for the pan head still leaves it in the gap
    sp, mesh, e = mac_mount(over, top=3.6, recess="cbore")
    why, _, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    assert len(good) == 0, why


def test_attach_holes_must_spread_across_the_part():
    """Review r1 second-F9: e07 asks two holes so the mount cannot turn about one, but two holes 6 mm
    apart counted as two."""
    sp, mesh, e = mac_mount([(-10.5, 30.0), (-10.5, 36.0)], flange=15.0)
    why, out, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    assert len(good) == 2 and why == [f"attach: the good screw holes are 6.0 mm apart at most (need 40.9, 25% of the "
                                      f"part's 164 mm across its +z side), so it can turn about them"], (why, out)


def test_a_two_sided_cradle_loads_each_lip_with_its_own_side():
    """Review r1 first-F1: on e07's cradle, lips 15 mm wide under both sides of the Mac and screws on
    flanges off it, the section at one lip's root took the mean distance of every bearing point on
    both lips (63.5 mm) and the full 20 N, so two correct 20 x 3 mm PETG straps read 42 MPa and failed.
    The lip carries its own half of the load, 7.5 mm out on average: 6 x 20 x 3.75 / (20 x 3^2) =
    2.5 MPa."""
    sp, mesh, e = mac_mount(FLANGE_HOLES, flange=15.0)
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    _, _, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    sec = {"at": [0.0, 63.5, -1.8], "b_dir": [0, 1, 0], "h_dir": [0, 0, 1]}
    load = {"n": 20, "dir": "-z", "arm": 3.75, "b": 20, "h": 3, "across_layers": False, "section": sec}
    why, m = eg.check_strength({"material": "PETG", "load": load}, sp, 2, mesh, np.eye(4), fit, good)
    assert why == [] and m["arm_mm"] == pytest.approx(3.75, abs=0.4) and m["sigma_mpa"] == pytest.approx(2.5, abs=0.1), \
        (why, m)
    # the far lip's root, mirrored, reads the same; the section between the near screws and the
    # flange's tip carries nothing and is not the critical one
    far = {**load, "section": {**sec, "at": [127.0, 63.5, -1.8], "b_dir": [0, -1, 0]}}
    why, m = eg.check_strength({"material": "PETG", "load": far}, sp, 2, mesh, np.eye(4), fit, good)
    assert why == [] and m["arm_mm"] == pytest.approx(3.75, abs=0.4), (why, m)
    tip = {**load, "section": {"at": [-15.0, 63.5, 51.8], "b_dir": [0, 1, 0], "h_dir": [0, 0, 1]}}
    why, m = eg.check_strength({"material": "PETG", "load": tip}, sp, 2, mesh, np.eye(4), fit, good)
    assert [w for w in why if w.startswith("strength: the critical section carries none of the load")], (why, m)
    # at the flange's root, inside the near screws, the -x lip's half crosses it on its way to them
    root = {**load, "arm": 7.0, "section": {"at": [-6.0, 63.5, 51.8], "b_dir": [0, 1, 0], "h_dir": [0, 0, 1]}}
    why, m = eg.check_strength({"material": "PETG", "load": root}, sp, 2, mesh, np.eye(4), fit, good)
    assert why == [] and m["arm_mm"] == pytest.approx(6.75, abs=0.4), (why, m)


def test_wall_and_desk_holders_name_their_attachment():
    """r2 F6: e05 and e07 say which side screws to the wall or desk, with an ISO 273 screw."""
    for name, face in (("e05_appletv_wall_holder", "-x"), ("e07_mac_mini_mount", "+z")):
        att = spec(name)["expect"]["attach"]
        assert att["face"] == face and att["screw"] in eg.CLEARANCE and att["min"] >= 2 and "ISO 273" in att["source"]


def test_pi4_plate_with_through_holes_passes():
    """r2 F7: a Pi 4 plate with M2.5 clearance holes for bolts and nuts, or bought standoffs, failed
    "screw method 'through' (self_tap or insert)". Through holes follow ISO 273 now."""
    sp = spec("e08_rpi4_vesa_adapter")
    ok = {"material": "PETG", "retention": {"type": "screw", "size": "M2.5", "method": "through", "hole_d": 2.9}}
    assert eg.check_retention(ok, sp) == []
    ok["retention"]["hole_d"] = 2.3
    assert eg.check_retention(ok, sp) == ["retention: M2.5 through hole 2.30 mm (want the ISO 273 clearance hole, "
                                          "2.7 to 3.1 mm, +/- 0.15 mm)"]
    import manifold3d as m3

    mesh, e = pi4_plate(pi_holes=False)
    plate = eg._to_manifold(mesh)
    holes = []
    for x in (3.5, 61.5):
        for y in (3.5, 52.5):
            plate = plate - _cyl(x, y, -9.0, 1.0, 2.9 / 2)
            holes.append({"at": [x, y, -8.0], "axis": [0, 0, 1]})
    mesh = _mesh(plate)
    e["retention"] = {"type": "screw", "size": "M2.5", "method": "through", "hole_d": 2.9, "holes": holes}
    assert eg.check_retention_mesh(mesh, e) == []
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    assert eg.check_holes(mesh, sp, e, np.eye(4), fit)[0] == []
    # a blind 2.9 hole that stops in the standoff is no through hole
    blind = _mesh(eg._to_manifold(pi4_plate(pi_holes=False)[0]) - _cyl(3.5, 3.5, -9.0, -2.0, 2.9 / 2))
    e["retention"]["holes"] = holes[:1]
    assert eg.check_retention_mesh(blind, e)[0].startswith("retention: screw hole 0 is not in the part")
    assert m3  # manifold3d is what the plate is cut with


def test_power_button_needs_a_fingertip():
    """r2 F5: e01's power button had only its 2 mm body, so a 2.1 mm hole no finger fits through passed
    access. Its plug is a Ø10 bare fingertip (MIL-STD-1472F Figure 12)."""
    sp, mesh = pi5_case()
    y, z = 57.63 - 37.6, 4.49
    small = _mesh(eg._to_manifold(mesh) - _box([-3.0, y - 1.05, z - 1.05], [0.5, y + 1.05, z + 1.05]))
    _, fit = eg.check_fit(small, sp, np.eye(4), "PLA")
    aw, _ = eg.check_access(small, sp, np.eye(4), fit)
    assert [w for w in aw if w.startswith("access: power_button")], aw
    big = _mesh(eg._to_manifold(mesh) - eg._cylinder(np.array([-3.0, y, z]), np.array([1.0, 0, 0]), 3.5, 5.3))
    _, fit = eg.check_fit(big, sp, np.eye(4), "PLA")
    aw, _ = eg.check_access(big, sp, np.eye(4), fit)
    assert not [w for w in aw if w.startswith("access: power_button")], aw


def test_pi4_plate_flat_under_the_board_fails():
    """r2 F8: a plate flat against the Pi 4's underside passed, though the board's through-hole leads
    stand out under it. Outside the holes' Ø6 pads the plate must stay 2.5 mm clear."""
    sp = spec("e08_rpi4_vesa_adapter")
    mesh, _ = pi4_plate()
    why, _ = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    assert not [w for w in why if w.startswith("clear:")], why
    flat = _box([-5.0, -19.5, -3.0], [90.0, 75.5, 0.0])
    for x in (3.5, 61.5):
        for y in (3.5, 52.5):
            flat = flat - _cyl(x, y, -4.0, 1.0, 1.875 / 2)
    why, _ = eg.check_fit(_mesh(flat), sp, np.eye(4), "PETG")
    assert [w for w in why if w.startswith("clear: ") and "of -z have the part 0.00 mm away" in w], why


def test_sources_are_tied_to_their_number():
    """r2 F9 and review r1 second-F8: any URL the spec cited counted for any number (Apple's iPhone
    drawing for the Pi 5's width, VESA's standard for the Pi 4's), and a profiled body's profile
    needed no source. A number's source is a URL its own body or feature source cites."""
    e01 = spec("e01_rpi5_case")
    drawing = "https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf"
    step = e01["product"]["sources"][1]
    iphone = "https://developer.apple.com/download/files/accessories/dimensional-drawings/iphone-17-pro.pdf"
    src = {k: drawing for k in ["w", "d", "corner_r"] + [f["name"] for f in e01["product"]["features"]]}
    src.update(h=step, microsd_slot=step)
    assert eg.check_sources({"sources": src}, e01) == []
    # review r2 first-F2: the STEP is where w's 88.5 and usb_c_power's v and size come from
    assert eg.check_sources({"sources": {**src, "w": step, "usb_c_power": step}}, e01) == []
    src["usb_c_power"] = iphone  # its own source cites Apple's USB-C keepout
    assert eg.check_sources({"sources": src}, e01) == []
    src["w"] = iphone
    assert eg.check_sources({"sources": src}, e01) == ["sources: no source for w (a URL the spec cites for it)"]
    src.update(w=drawing, h=drawing)  # the drawing gives no height; the STEP does
    assert eg.check_sources({"sources": src}, e01) == ["sources: no source for h (a URL the spec cites for it)"]
    e08 = spec("e08_rpi4_vesa_adapter")
    pi4 = "https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-mechanical-drawing.pdf"
    src = {k: pi4 for k in ["w", "d", "h", "corner_r"] + [f["name"] for f in e08["product"]["features"]]}
    assert eg.check_sources({"sources": src}, e08) == []
    src["w"] = "https://vesa.org/mounting-standard/"  # in product.sources, but VESA gives no Pi width
    assert eg.check_sources({"sources": src}, e08) == ["sources: no source for w (a URL the spec cites for it)"]
    e04 = spec("e04_airtag_case")
    tag = "https://developer.apple.com/download/files/accessories/dimensional-drawings/airtag.pdf"
    src = {k: tag for k in ("w", "d", "h", "corner_r", "speaker_keepout")}
    assert eg.check_sources({"sources": src}, e04) == ["sources: no source for profile (a URL the spec cites for it)"]
    src["profile"] = tag
    assert eg.check_sources({"sources": src}, e04) == []


# --- review round 1 of PR 64 (review-r1), each on a part built by hand ------------------------------

def test_snap_catch_must_face_the_product():
    """Review r1 second-F7: the catch was read on either face of the arm, so the tongue's 0.6 mm block
    moved to its outer face, hooking nothing, passed as "catch 0.60"."""
    mesh, frame = build_case(hook_out=True)
    why = eg.check_retention_mesh(mesh, eng(frame), spec=SPEC)
    assert why == ["retention: the snap arm has no catch: it stands out 0.00 mm toward the product past its root "
                   "face in its outer half (y says 0.6)"], why
    # the product's side is found from the frame, whichever way t_dir is declared
    mesh, frame = build_case()
    assert eg.check_retention_mesh(mesh, eng(frame, retention={**SNAP, "t_dir": [1, 0, 0]}), spec=SPEC) == []
    out, frame = build_case(hook_out=True)
    assert eg.check_retention_mesh(out, eng(frame, retention={**SNAP, "t_dir": [1, 0, 0]}), spec=SPEC)


def test_snap_arm_length_is_measured_both_ways():
    """Review r1 first-F2: the README says L within 0.2 mm, but a declared L shorter than the arm in the
    mesh passed, and the sides were probed only that far. Slots stopping 4 mm under the rim leave a
    bridge that fixes the arm at both ends: declared at the slots' length, L fails; declared at the
    full length, the sides are probed into the bridge and fail."""
    mesh, frame = build_case(bridge=4.0)
    short = eng(frame, retention={**SNAP, "L": 8.0})
    why = eg.check_retention_mesh(mesh, short, spec=SPEC)
    assert "retention: the snap arm runs 13.65 mm from its root in the part (L says 8)" in why, why
    full = eg.check_retention_mesh(mesh, eng(frame), spec=SPEC)
    assert [w for w in full if w.startswith("retention: the snap arm is not free at its sides")], full
    assert eg.check_retention_mesh(build_case()[0], eng(frame), spec=SPEC) == []


def test_through_hole_is_probed_through_its_wall_only():
    """Review r1 first-F3: a through hole was probed the part's whole diagonal, so a closed Pi plate
    with a cover over the board read "screw hole 0 is not in the part" through the cover."""
    mesh, e = pi4_plate(pi_holes=False)
    plate = eg._to_manifold(mesh)
    holes = []
    for x in (3.5, 61.5):
        for y in (3.5, 52.5):
            plate = plate - _cyl(x, y, -9.0, 1.0, 2.9 / 2)
            holes.append({"at": [x, y, -8.0], "axis": [0, 0, 1]})
    cover = _box([-5.0, -19.5, 20.0], [90.0, 75.5, 22.0]) + _box([-5.0, -19.5, -5.0], [-3.0, 75.5, 20.0])
    e["retention"] = {"type": "screw", "size": "M2.5", "method": "through", "hole_d": 2.9, "holes": holes}
    assert eg.check_retention_mesh(_mesh(plate + cover), e) == []
    blind = _mesh(eg._to_manifold(pi4_plate(pi_holes=False)[0]) - _cyl(3.5, 3.5, -9.0, -2.0, 2.9 / 2) + cover)
    e["retention"]["holes"] = holes[:1]
    assert eg.check_retention_mesh(blind, e)[0].startswith("retention: screw hole 0 is not in the part")


def test_wall_holder_carries_its_load():
    """Review r1 first-F5: e05 screws to the wall and cantilevers its floor out from it, but the schema
    allowed load_n only on a mount, so the strength check never ran on it."""
    e05 = spec("e05_appletv_wall_holder")
    assert e05["expect"]["load_n"] >= 10 and e05["expect"]["load_dir"] == "-z"
    why, _ = eg.check_strength({"material": "PLA"}, e05, 2)
    assert why == ["strength: no load in engineering.json (the spec asks 10 N)"]


# --- review round 2 of PR 64 (review-r2), each on a part built by hand ------------------------------

def mac_strap(t: float, wide: float):
    """e07's cradle on flange screws with its -x lip cut to a strap `t` thick and `wide` wide, under
    the Mac's middle (y 63.5), out 15 mm from the -x wall."""
    sp, mesh, e = mac_mount(FLANGE_HOLES, flange=15.0)
    m = eg._to_manifold(mesh) - _box([-0.3, -1, -4.0], [15.5, 63.5 - wide / 2, 0.0]) - \
        _box([-0.3, 63.5 + wide / 2, -4.0], [15.5, 128, 0.0]) - _box([-0.3, 60, -4.0], [15.5, 67, -0.3 - t])
    return sp, _mesh(m), e


def test_the_weakest_cut_on_the_load_path_is_graded():
    """Review r2 first-F1: on e07's cradle with its -x lip cut to a 1.2 x 5 mm strap, a section
    declared in the thick -x wall (h 50) passed strength, though the strap's root carries half the
    Mac (the far lip the other half) 7.5 mm out: about 60 MPa against 23.5 allowed. The load is now
    shared by statics, not by bearing area, and every cut from the declared section out to the
    bearing points and on to the screws is graded on its own cut face."""
    sp, mesh, e = mac_strap(1.2, 5.0)
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    assert eg.check_support(sp, fit)[0] == []
    _, _, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    sec = {"at": [-1.8, 63.5, -1.8], "b_dir": [0, 1, 0], "h_dir": [0, 0, 1]}
    load = {"n": 20, "dir": "-z", "arm": 10, "b": 5, "h": 50, "across_layers": False, "section": sec}
    why, m = eg.check_strength({"material": "PETG", "load": load}, sp, 2, mesh, np.eye(4), fit, good)
    weak = [w for w in why if w.startswith("strength: ") and "at the weakest cut on the load path" in w]
    assert weak and "on a cut 5 x 1.2 mm" in weak[0], (why, m)
    assert m["weakest"]["sigma_mpa"] > 50, m  # about 10 N at 7 mm on 5 x 1.2^2 / 6
    # a strap 20 x 3 carries it: 10 N x 7.5 mm on 20 x 3^2 / 6 is 2.5 MPa
    sp, mesh, e = mac_strap(3.0, 20.0)
    _, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    _, _, good = eg.attach_holes(mesh, sp, e, np.eye(4))
    ok = {**load, "b": 20, "h": 3, "section": {**sec, "at": [0.0, 63.5, -1.8]}}
    why, m = eg.check_strength({"material": "PETG", "load": ok}, sp, 2, mesh, np.eye(4), fit, good)
    assert why == [] and 2.0 < m["weakest"]["sigma_mpa"] < 3.5, (why, m)


def test_the_load_is_shared_by_statics():
    """Review r2 first-F1: two bearing groups at x 0 (3 points) and x 10 (30), the load's line at x 5: each takes half,
    whatever its area; the line at x 7.5 puts three quarters on the group at 10."""
    pts = np.array([[0, y, 0] for y in (13.5, 14.5, 15.5)] + [[10, y, 0] for y in range(30)], float)
    z = np.array([0, 0, -1.0])
    w = eg._statics(pts, np.array([5.0, 14.5, 9.0]), z)
    assert w[:3].sum() == pytest.approx(0.5, abs=1e-6) and w.sum() == pytest.approx(1.0)
    w = eg._statics(pts, np.array([7.5, 14.5, 9.0]), z)
    assert w[3:].sum() == pytest.approx(0.75, abs=1e-6)


def test_pi5_flat_floor_under_the_board_fails():
    """Review r2 second-F6: a Pi 5 case whose floor runs flat across the underside 1.45 mm up into the
    body's box, flush with the PCB, passed support and fit, though it fills the microSD socket's and
    the leads' room. e01 now has the four mounting holes with their Ø6 pads, and outside them the
    part stays 1.05 mm under the body (2.5 mm under the PCB); standoffs on the pads still pass."""
    sp, mesh = pi5_case(floor_top=1.45)
    why, fit = eg.check_fit(mesh, sp, np.eye(4), "PLA")
    assert [w for w in why if w.startswith("clear: ") and "of -z have the part" in w], why
    assert eg.check_support(sp, fit)[0] == []  # it bears; it is the clearance that fails
    sp, mesh = pi5_case()
    why, fit = eg.check_fit(mesh, sp, np.eye(4), "PLA")
    assert why == [] and eg.check_support(sp, fit)[0] == [], why
    # the pads are where the standoffs bear: support counts them
    assert all(q >= eg.SUPPORT_MM2 for q in eg.check_support(sp, fit)[1]["quarters_mm2"])
    # a snap case is not graded as a screw seat on the product's holes; its standoffs need no bore
    assert eg.check_holes(mesh, sp, {"retention": {"type": "snap"}}, np.eye(4), fit)[0] == []


def bought_standoff_plate(holes: bool = True, window: bool = False):
    """e08's plate for bought M2.5 brass standoffs: a flat 3 mm PETG plate 5 mm under the Pi 4 (z -8 to
    -5), no printed standoffs, Ø2.9 clearance holes through it under the board's four holes, the VESA
    75 holes, and with `window` a cutout under the front left hole."""
    mesh, e = pi4_plate(pi_holes=False, standoffs=False)
    plate = eg._to_manifold(mesh)
    at = []
    for x in (3.5, 61.5):
        for y in (3.5, 52.5):
            if holes:
                plate = plate - _cyl(x, y, -9.0, 1.0, 2.9 / 2)
            at.append({"at": [x, y, -8.0], "axis": [0, 0, 1]})
    if window:
        plate = plate - _box([-2.0, -2.0, -9.0], [9.0, 9.0, -4.0])
    e["retention"] = {"type": "screw", "size": "M2.5", "method": "through", "hole_d": 2.9, "holes": at}
    return _mesh(plate), e


def test_pi4_plate_on_bought_standoffs_passes():
    """Review r2 second-F4: a flat plate on bought M2.5 standoffs with Ø2.9 clearance holes, the
    commonest Pi mount, failed check_holes four times ("nothing to bear on"), since the seat was looked
    for only 1.45 mm under the board. A through hole is now found along its axis wherever the part
    is: clear through that wall, with the part around it there."""
    sp = spec("e08_rpi4_vesa_adapter")
    mesh, e = bought_standoff_plate()
    why, fit = eg.check_fit(mesh, sp, np.eye(4), "PETG")
    assert why == [], why
    hw, out = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert hw == [], (hw, out)
    assert out["mount_hole_front_left"]["from_mm"] == pytest.approx(4.95, abs=0.05)
    assert out["mount_hole_front_left"]["wall_mm"] == pytest.approx(3.0, abs=0.05)
    assert eg.check_retention_mesh(mesh, e) == []
    assert eg.check_retention(e | {"material": "PETG"}, sp) == []
    # the plate without the holes: the bore now reaches the plate, 5 mm down
    mesh, e = bought_standoff_plate(holes=False)
    hw, _ = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert len([w for w in hw if "has no hole in the part" in w and "clear through the part's wall" in w]) == 4, hw
    # no plate under a hole: nothing for its standoff to stand on
    mesh, e = bought_standoff_plate(window=True)
    hw, _ = eg.check_holes(mesh, sp, e, np.eye(4), fit)
    assert hw == ["holes: mount_hole_front_left has nothing to bear on: no part under it along its axis"], hw


def test_a_through_bolt_in_a_thin_wall_passes():
    """Review r2 second-F5: an M3 bolt through a sound 2.5 mm wall failed "no part around it (42% of a
    1.2 mm ring 6.0 mm deep)": the ring was probed 2 x d deep, past the wall. It is probed through
    the wall the bolt passes now."""
    for size, d, t in (("M3", 3.4, 2.5), ("M2.5", 2.9, 2.0)):
        block = _mesh(_box([0, 0, 0], [20, 20, t]) - _cyl(10, 10, -1.0, t + 1.0, d / 2))
        ret = {"type": "screw", "size": size, "method": "through", "hole_d": d,
               "holes": [{"at": [10, 10, t], "axis": [0, 0, -1]}]}
        assert eg.check_retention_mesh(block, {"retention": ret}) == [], (size, t)
    # a wall with no hole is still no through hole
    solid = _mesh(_box([0, 0, 0], [20, 20, 2.0]))
    ret = {"type": "screw", "size": "M2.5", "method": "through", "hole_d": 2.9,
           "holes": [{"at": [10, 10, 2.0], "axis": [0, 0, -1]}]}
    assert eg.check_retention_mesh(solid, {"retention": ret})[0].startswith("retention: screw hole 0 is not in the part")


def test_a_screw_hole_mouth_is_on_the_part():
    """Review r2 second-F7: a through hole declared 1 mm under a solid plate, in the air, read the
    1 mm of air as its wall: the bore was empty, and the plate had no hole. The mouth must lie on the
    part's surface."""
    plate = _mesh(_box([0, 0, 0], [20, 20, 3.0]) + _cyl(10, 10, 3.0, 9.0, 3.0))
    ret = {"type": "screw", "size": "M2.5", "method": "through", "hole_d": 2.9,
           "holes": [{"at": [10, 10, -1.0], "axis": [0, 0, 1]}]}
    assert eg.check_retention_mesh(plate, {"retention": ret}) == [
        "retention: screw hole 0's mouth [10.0, 10.0, -1.0] is not on the part's surface (beside it the part "
        "must start there along its axis)"]
