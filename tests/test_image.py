import json
import math
import subprocess
import xml.etree.ElementTree as ET

import pytest
import trimesh
from PIL import Image, ImageDraw

from smoothstone import config, image


def star_points(cx, cy, r_out, r_in):
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = math.pi / 2 + i * math.pi / 5
        pts.append((cx + r * math.cos(a), cy - r * math.sin(a)))
    return pts


@pytest.fixture
def star_png(tmp_path):
    im = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(im)
    d.polygon(star_points(200, 160, 130, 55), fill="black")
    d.ellipse((185, 145, 215, 175), fill="white")  # a hole in the middle
    d.point((5, 5), fill="black")  # a speck to drop
    f = tmp_path / "star.png"
    im.save(f)
    return f


@pytest.fixture
def transparent_png(tmp_path):
    # same color everywhere; only alpha marks the subject
    im = Image.new("RGBA", (300, 300), (40, 40, 40, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((50, 50, 250, 250), fill=(40, 40, 40, 255))
    d.ellipse((120, 120, 180, 180), fill=(40, 40, 40, 0))
    f = tmp_path / "ring.png"
    im.save(f)
    return f


def svg_ok(path):
    root = ET.parse(path).getroot()
    assert root.tag.endswith("svg")
    assert root.get("width") == "100.000mm"
    paths = [el for el in root.iter() if el.tag.endswith("path")]
    assert paths and all(p.get("d") for p in paths)


def extrude_with_openscad(binary, svg, tmp_path):
    scad = tmp_path / "x.scad"
    stl = tmp_path / "x.stl"
    scad.write_text(f'linear_extrude(3) import("{svg.as_posix()}");\n')
    cmd = [binary]
    if config.openscad_has_manifold(binary):
        cmd.append("--backend=manifold")
    r = subprocess.run(cmd + ["-o", str(stl), str(scad)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return trimesh.load(str(stl), force="mesh")


@pytest.mark.parametrize("tracer", ["potrace", "contours"])
def test_star_silhouette(star_png, tmp_path, monkeypatch, tracer):
    if tracer == "potrace" and not image.shutil.which("potrace"):
        pytest.skip("no potrace")
    if tracer == "contours":
        monkeypatch.setattr(image.shutil, "which", lambda name: None)
    out = tmp_path / "img"
    info = image.process(star_png, out)
    assert info["tracer"] == tracer
    assert info["kind"] == "silhouette"
    assert info["shapes"] == 1  # speck dropped
    assert info["has_holes"] is True
    assert 0.9 < info["aspect"] < 1.2
    assert 0.1 < info["fill"] < 0.5
    svg_ok(out / "silhouette.svg")
    saved = json.loads((out / "info.json").read_text())
    assert saved["aspect"] == info["aspect"]
    h = Image.open(out / "height.png")
    assert h.mode == "L" and max(h.size) == 300 and h.size[0] > h.size[1]
    assert (out / "source.png").is_file()


@pytest.mark.parametrize("tracer", ["potrace", "contours"])
def test_star_svg_imports_in_openscad(star_png, tmp_path, monkeypatch, openscad, tracer):
    if tracer == "potrace" and not image.shutil.which("potrace"):
        pytest.skip("no potrace")
    if tracer == "contours":
        monkeypatch.setattr(image.shutil, "which", lambda name: None)
    image.process(star_png, tmp_path / "img")
    mesh = extrude_with_openscad(openscad, tmp_path / "img" / "silhouette.svg", tmp_path)
    assert mesh.is_watertight
    ext = mesh.extents
    assert ext[0] == pytest.approx(100, abs=1.0)
    assert ext[2] == pytest.approx(3, abs=0.01)
    assert mesh.euler_number == 0  # one body with one hole
    # star tip points up (+y): the top 10% of the part is narrow
    v = mesh.vertices
    top = v[v[:, 1] > mesh.bounds[1][1] - 0.1 * ext[1]]
    assert top[:, 0].max() - top[:, 0].min() < 0.25 * ext[0]


def test_transparent_png(transparent_png, tmp_path, openscad):
    out = tmp_path / "img"
    info = image.process(transparent_png, out)
    assert info["alpha"] is True
    assert info["kind"] == "silhouette"
    assert info["shapes"] == 1 and info["has_holes"] is True
    assert info["aspect"] == pytest.approx(1.0, abs=0.02)
    svg_ok(out / "silhouette.svg")
    mesh = extrude_with_openscad(openscad, out / "silhouette.svg", tmp_path)
    assert mesh.is_watertight
    assert mesh.euler_number == 0


def test_photo_like(tmp_path):
    import numpy as np

    x = np.linspace(0, 255, 320)
    arr = np.add.outer(np.linspace(0, 120, 240), x / 2).clip(0, 255).astype("uint8")
    f = tmp_path / "grad.jpg"
    Image.fromarray(arr, "L").convert("RGB").save(f)
    info = image.process(f, tmp_path / "img")
    assert info["kind"] == "photo"
    assert "lithophane" in info["recipes"]


def test_not_an_image(tmp_path):
    f = tmp_path / "x.png"
    f.write_text("hello")
    with pytest.raises(image.ImageProblem):
        image.process(f, tmp_path / "img")
