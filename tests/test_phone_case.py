"""phone_case: every phone's case is built and measured against Apple's numbers in devices.json.

The cavity is sliced at the phone's mid-height and its width and height must equal the phone's
plus the clearance on each side. The camera opening must hold the plateau plus the margin. Every
build must pass stone's print checks, and slice must give a ring of the asked height."""
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from smoothstone import check, match, scad
from smoothstone import recipes as rc

REPO = Path(__file__).resolve().parent.parent
RDIR = REPO / "recipes" / "phone_case"
DOC = json.loads((RDIR / "devices.json").read_text())
PHONES = list(DOC["phones"])
CLEAR = {"rigid": 0.25, "tpu": 0.05}
_built: dict = {}

_spec = importlib.util.spec_from_file_location("phone_devices", REPO / "tools" / "phone_devices.py")
phone_devices = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(phone_devices)


def v(node):
    return node["v"]


def recipe():
    return rc.load("phone_case", REPO / "recipes")


def build(binary, tmp_root: Path, **params):
    """Build once per parameter set; returns (stl path, full params, mesh)."""
    key = tuple(sorted(params.items()))
    if key not in _built:
        r = recipe()
        full = {p.name: p.default for p in r.params} | params
        out = tmp_root / ("_".join(f"{k}-{val}" for k, val in key) or "defaults") / "part.stl"
        out.parent.mkdir(parents=True, exist_ok=True)
        run = scad.build_stl(binary, r, full, out)
        assert run.ok, run.error or run.log[-2000:]
        _built[key] = (out, full, check.load_off(out.with_suffix(".off")))
    return _built[key]


@pytest.fixture(scope="module")
def tmp_root(tmp_path_factory):
    return tmp_path_factory.mktemp("phone_case")


def crossings(mesh, z, axis, at):
    """Where the mid-height slice's outline crosses the line axis = at (sorted)."""
    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    other = 1 - axis
    out = []
    for seg in sec.vertices[np.concatenate([e.points[np.newaxis, i:i + 2] for e in sec.entities
                                            for i in range(len(e.points) - 1)])]:
        a, b = seg[0], seg[1]
        if (a[axis] - at) * (b[axis] - at) < 0:
            t = (at - a[axis]) / (b[axis] - a[axis])
            out.append(a[other] + t * (b[other] - a[other]))
    return sorted(out)


def cavity_extent(mesh, z, axis, at):
    """Inner wall to inner wall along the line axis = at: the two crossings nearest the center."""
    xs = crossings(mesh, z, axis, at)
    lo = max(x for x in xs if x < 0)
    hi = min(x for x in xs if x > 0)
    return hi - lo


@pytest.mark.parametrize("phone", PHONES)
@pytest.mark.parametrize("material", ["rigid", "tpu"])
def test_cavity_is_phone_plus_clearance(openscad, tmp_root, phone, material):
    d = DOC["phones"][phone]
    W, H, T = v(d["body"]["width"]), v(d["body"]["height"]), v(d["body"]["depth"])
    _, full, mesh = build(openscad, tmp_root, phone=phone, material=material)
    z = full["back"] + T / 2
    c = CLEAR[material]
    width = cavity_extent(mesh, z, 1, 0.0)        # across, at the middle of the phone
    height = cavity_extent(mesh, z, 0, 8.5)       # along, between the USB-C slot and the speaker slots
    print(f"{phone} {material}: cavity {width:.3f} x {height:.3f}, phone {W} x {H} + 2 x {c}")
    assert abs(width - (W + 2 * c)) <= 0.1
    assert abs(height - (H + 2 * c)) <= 0.1


def _rr_boundary(x0, x1, y0, y1, r, grow, n=24):
    """Points on a rounded rectangle grown by `grow` all round."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = []
    for cx, cy, a0 in [(x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270)]:
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((cx + (r + grow) * math.cos(a), cy + (r + grow) * math.sin(a)))
    pts = np.array(pts)
    edges = []
    for i in range(len(pts)):  # fill the straight sides too
        p, q = pts[i], pts[(i + 1) % len(pts)]
        edges += [p + (q - p) * t for t in np.linspace(0, 1, 12)]
    return np.array(edges)


def _inside(poly: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Even-odd point in polygon."""
    x, y = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        cross = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi)
        inside ^= cross
        j = i
    return inside


def plateau_points(phone, margin):
    """The plateau (or Apple's dimensioned area around it), every lens, flash, mic and sensor,
    each grown by the margin, in the case's frame."""
    d = DOC["phones"][phone]
    W, H = v(d["body"]["width"]), v(d["body"]["height"])
    cam = d["camera"]
    pts = []
    if "plateau" in cam:
        x0, x1 = v(cam["plateau"]["x"])
        y0, y1 = v(cam["plateau"]["y"])
        X0, X1, Y0, Y1 = W / 2 - x1, W / 2 - x0, H / 2 - y1, H / 2 - y0
        pts.append(_rr_boundary(X0, X1, Y0, Y1, v(cam["plateau"]["corner_r"]), margin))
    if "opening_bound" in cam:
        ob = cam["opening_bound"]
        r = v(ob["corner_r"]) or 0.0
        pts.append(_rr_boundary(-W / 2, W / 2, H / 2 - v(ob["y_bottom"]), H / 2 + 5, max(r, 1e-3), margin))
    for key in ("lenses", "flash", "mic", "sensor"):
        if key in cam:
            items = v(cam[key])
            for x, y, dd in (items if isinstance(items[0], list) else [items]):
                a = np.linspace(0, 2 * np.pi, 48, endpoint=False)
                rr = dd / 2 + margin
                pts.append(np.c_[W / 2 - x + rr * np.cos(a), H / 2 - y + rr * np.sin(a)])
    return np.vstack(pts)


@pytest.mark.parametrize("phone", PHONES)
def test_camera_opening_holds_plateau_plus_margin(openscad, tmp_root, phone):
    d = DOC["phones"][phone]
    W, H = v(d["body"]["width"]), v(d["body"]["height"])
    _, full, mesh = build(openscad, tmp_root, phone=phone, material="rigid")
    m = full["camera_margin"]
    pts = plateau_points(phone, m - 0.05)
    # The opening stops at the cavity wall, so only points inside the cavity count.
    phone_outline = np.array(phone_devices.outline(W, H, v(d["corner"]["points"])))
    pts = pts[_inside(phone_outline * (1 - 0.1 / W), pts)]
    assert len(pts) > 100
    probe = np.c_[pts, np.full(len(pts), full["back"] / 2)]  # in the back plate
    solid = mesh.contains(probe)
    assert not solid.any(), f"{solid.sum()} plateau points are covered, first at {probe[solid][0]}"


@pytest.mark.parametrize("phone", PHONES)
def test_case_passes_stone_checks(openscad, tmp_root, phone):
    stl, full, _ = build(openscad, tmp_root, phone=phone, material="rigid")
    results = check.check_stl(stl, recipe(), full)
    assert check.passed(results), [r for r in results if not r.ok]
    byname = {r.name: r for r in results}
    assert byname["bodies"].ok and byname["watertight"].ok and byname["resting"].ok


@pytest.mark.parametrize("params", [
    {"phone": "iphone_17_pro", "text": "DONOVAN"},
    {"phone": "iphone_17_pro_max", "material": "tpu", "buttons": "cover"},
    {"phone": "iphone_air", "buttons": "cover"},
    {"phone": "iphone_17", "buttons": "cover"},
])
def test_options_pass_stone_checks(openscad, tmp_root, params):
    stl, full, _ = build(openscad, tmp_root, **params)
    results = check.check_stl(stl, recipe(), full)
    assert check.passed(results), [r for r in results if not r.ok]


@pytest.mark.parametrize("phone,ring", [("iphone_17_pro", 10), ("iphone_air", 4)])
def test_slice_gives_a_ring_of_that_height(openscad, tmp_root, phone, ring):
    stl, full, mesh = build(openscad, tmp_root, phone=phone, slice=ring)
    lo, hi = mesh.bounds
    assert abs(lo[2]) < 1e-6 and abs((hi[2] - lo[2]) - ring) < 0.01
    assert len(mesh.split(only_watertight=False)) == 1
    # a ring: nothing at the middle of the back
    assert not mesh.contains([[0, -20, 0.5]])[0]
    assert check.passed(check.check_stl(stl, recipe(), full))


def test_generated_files_match_devices_json():
    out = subprocess.run([sys.executable, str(REPO / "tools" / "phone_devices.py"), "--check"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_every_number_has_a_source():
    def walk(node, path):
        if isinstance(node, dict):
            if "v" in node:
                assert node.get("src"), path
                assert node["src"] == "not in drawing" or node["src"].split(" p")[0] in {
                    "iphone-17.pdf", "iphone-17-pro.pdf", "iphone-17-pro-max.pdf", "iphone-air.pdf"}, path
                if node["v"] is None:
                    assert node["src"] == "not in drawing" or node.get("how"), path
                return
            for k, val in node.items():
                walk(val, f"{path}.{k}")
    walk(DOC["phones"], "phones")


@pytest.mark.parametrize("request_text,want", [
    ("A case for my iPhone 17 Pro Max", {"phone": "iphone_17_pro_max"}),
    ("17 pro case", {"phone": "iphone_17_pro"}),
    ("a case for the iphone air", {"phone": "iphone_air"}),
    ("TPU case for my iPhone 17", {"phone": "iphone_17", "material": "tpu"}),
    ("A case for my iPhone 17 Pro with DONOVAN on the back", {"phone": "iphone_17_pro", "text": "DONOVAN"}),
])
def test_requests_set_the_phone(request_text, want):
    got, left = match.suggest_full(recipe(), request_text)
    assert {k: got.get(k) for k in want} == want, got
    assert left == [], left  # "17" in the model name is not left over as a size


def test_my_name_asks_for_the_name():
    got, left = match.suggest_full(recipe(), "A case for my iPhone 17 Pro with my name on the back")
    assert got.get("phone") == "iphone_17_pro" and "text" not in got
    assert any("my name" in x for x in left)


def test_request_ranks_the_phone_case_first():
    """At tier S too, the default for a new job: a hidden recipe would send the model to box."""
    ranked = rc.rank(rc.visible(rc.load_all(REPO / "recipes"), "S"), "A case for my iPhone 17 Pro")
    assert ranked[0][1].name == "phone_case"
