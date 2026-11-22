"""The engineering grade (evals/engineering_grade.py) on a made-up product and a case built by hand:
the case that fits passes, and one case each fails fit, access, retention, strength and sources."""

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


def build_case(clearance: float = 0.3, hole: bool = True, lid: bool = False) -> tuple[trimesh.Trimesh, np.ndarray]:
    """An open-top case around BODY: walls and floor WALL thick, `clearance` on every side and under
    it, the port's plug cut through the -y wall. Returns (mesh in part coordinates, frame)."""
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
    if lid:  # a plate over the open top, 0.3 mm above the product
        case = case + _rounded(w, d, r, clearance + WALL, WALL).translate([0, 0, lift + h + 0.3])
        case = case + (outer - _rounded(w, d, r, clearance, lift + h + 2)).translate([0, 0, 0.5])
    move = clearance + WALL
    case = case.translate([move, move, 0])  # the case's outer corner near the origin
    m = case.to_mesh()
    mesh = trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts), process=True)
    frame = np.eye(4)
    frame[:3, 3] = [move, move, lift]  # the product's min corner, clearance in from each wall
    return mesh, frame


def eng(frame, **over) -> dict:
    e = {"frame": frame.tolist(), "material": "PLA", "clearance": 0.3,
         "retention": {"type": "snap", "y": 0.6, "t": 1.5, "L": 12.0},
         "sources": {"w": URL, "d": URL, "h": URL, "corner_r": URL, "usb_c": "calipers"}}
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
    assert eg.check_sources(e, SPEC) == ["sources: no source for h, usb_c"]
    e["sources"].update(h="photo with a bank card", usb_c="calipers")
    assert eg.check_sources(e, SPEC) == []


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
            assert f["kind"] in ("port", "button", "switch", "vent", "lens", "screen", "led", "slot")
            assert f.get("source"), (p.name, f["name"])
        assert exp["kind"] in ("case", "holder", "mount", "adapter", "replacement")
        assert (exp["material"], exp["fit"]) in eg.FIT
        assert exp["retention"] in ("friction", "snap", "screw", "none", "any")
        assert set(exp["covered"]) <= set(eg.FACES) and set(exp["open"]) <= set(eg.FACES)
        assert not set(exp["covered"]) & set(exp["open"])
        assert ("load_n" in exp) == (exp["kind"] == "mount"), p.name
