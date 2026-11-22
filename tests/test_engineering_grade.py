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
        "product": {"name": "a box", "sources": ["https://example.com/drawing.pdf"], "body": BODY, "features": [PORT]},
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
SNAP = {"type": "snap", "y": 0.6, "t": 2.0, "L": 11.95, "w": 6.0,
        "at": [43.6, 17.3, ARM_ROOT_Z], "t_dir": [1, 0, 0], "L_dir": [0, 0, 1]}


def build_case(clearance: float = 0.3, hole: bool = True, lid: bool = False,
               tongue: bool = True) -> tuple[trimesh.Trimesh, np.ndarray]:
    """An open-top case around BODY: walls and floor WALL thick, `clearance` on every side and under
    it, the port's plug cut through the -y wall, and a snap tongue cut in the +x wall (two slots 0.8
    wide from the rim down 12 mm, 6 mm apart). Returns (mesh in part coordinates, frame)."""
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
            case = case - _box([w + clearance - 0.3, y0, top - 12.0], [w + clearance + WALL + 0.3, y0 + 0.8, top + 1])
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
    assert eg.check_sources(e, SPEC) == ["sources: no source for h, usb_c (a URL the spec cites)"]
    e["sources"].update(h="photo with a bank card", usb_c="calipers")
    photo = {**SPEC, "input": "photo"}
    assert eg.check_sources(e, photo) == []


def test_sources_from_text_must_be_urls_the_spec_cites():
    """F13: "https://" alone, calipers, or a URL the spec never cites does not count for a text request."""
    e = {"sources": {"w": URL, "d": URL + " p2", "h": "https://", "corner_r": "calipers",
                     "usb_c": "https://example.org/made-up.pdf"}}
    assert eg.check_sources(e, SPEC) == ["sources: no source for h, corner_r, usb_c (a URL the spec cites)"]
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
            if f["kind"] == "port":
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
        for ph in exp.get("part_holes", []):
            assert ph["axis"] in eg.FACES and ph["d"] > 0 and ph["pattern"] and ph["source"]
        assert ("load_n" in exp) == (exp["kind"] == "mount"), p.name
        if exp.get("load_dir"):  # F3: a load has a face to bear on
            assert exp.get("support", exp["load_dir"]) == exp["load_dir"], p.name
    e01 = json.loads((ROOT / "evals" / "engineering" / "e01_rpi5_case.json").read_text())
    usb = next(f for f in e01["product"]["features"] if f["name"] == "usb_c_power")
    assert usb["plug"] == [12.45, 6.6] and usb["depth"] == 14.0
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
    # a plate far under the board, holes and all, gives the board nothing to bear on
    mesh, e = pi4_plate(standoffs=False)
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
    assert eg.check_retention_mesh(mesh, eng(frame)) == \
        ["retention: the snap arm is not free at its sides: the part is 30.2 mm wide halfway along it (w says 6)"]
    mesh, frame = build_case()
    assert eg.check_retention_mesh(mesh, eng(frame)) == []
    thin = eng(frame, retention={**SNAP, "t": 1.5})
    assert eg.check_retention_mesh(mesh, thin) == \
        ["retention: the snap arm is 2.00 mm thick at its root in the part (t says 1.5)"]
    long = eng(frame, retention={**SNAP, "L": 20.0})
    assert eg.check_retention_mesh(mesh, long)[0].startswith("retention: the snap arm runs 11.95 mm from its root")
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


def pi5_case(post_top: float = 1.45):
    """A PLA case for e01's Pi 5 on four Ø6 standoffs up to the PCB underside (frame z 1.45, above
    the microSD socket that sets the body's -z), floor 2 mm under the body, walls 0.3 off the sides,
    top open."""
    sp = spec("e01_rpi5_case")
    w, d, h = (sp["product"]["body"][k] for k in ("w", "d", "h"))
    case = _box([-2.3, -2.3, -4.0], [w + 2.3, d + 2.3, h]) - _box([-0.3, -0.3, -2.0], [w + 0.3, d + 0.3, h + 1])
    for x in (12.0, w - 12.0):
        for y in (8.0, d - 8.0):
            case = case + _cyl(x, y, -2.5, post_top, 3.0)
    return sp, _mesh(case)


def test_pi5_case_on_standoffs_passes():
    """Review round 2 F1: e01 covered -z at a slip gap under the microSD socket, so standoffs that
    reach the PCB 1.45 mm above it read as inside the product and a normal Pi case failed."""
    sp, mesh = pi5_case()
    why, fit = eg.check_fit(mesh, sp, np.eye(4), "PLA")
    assert not [w for w in why if w.startswith("fit: ") and "inside the part" in w], why
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
