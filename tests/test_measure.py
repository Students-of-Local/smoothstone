"""stone measure: scale from a ruler in a photo. Synthetic pictures are drawn here at a known px/mm."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from smoothstone import measure as ms

from test_cli import stone

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "measure"
SS = 4  # supersampling while drawing

def ruler_image(px_mm: float, unit: str = "mm", length_mm: float = 200, width_mm: float = 30) -> Image.Image:
    """A yellow ruler with dark ticks along its top edge, drawn flat at px_mm, RGBA."""
    k = px_mm * SS
    w, h = round(length_mm * k), round(width_mm * k)
    im = Image.new("RGBA", (w, h), (246, 214, 92, 255))
    d = ImageDraw.Draw(im)
    tw = 0.22 * k  # tick line width
    if unit == "mm":
        step = 1.0
        n = int((length_mm - 10) / step) + 1
        for i in range(n):
            x = (5 + i * step) * k
            ln = 7.0 if i % 10 == 0 else 5.0 if i % 5 == 0 else 3.2
            d.rectangle([x - tw / 2, 0, x + tw / 2, ln * k], fill=(25, 25, 25, 255))
            if i % 10 == 0:
                d.text((x - 3 * k / 2, 9 * k), str(i // 10), fill=(25, 25, 25, 255), font_size=int(5 * k))
    else:
        step = 25.4 / 16
        n = int((length_mm - 10) / step) + 1
        for i in range(n):
            x = (5 + i * step) * k
            ln = 9.0 if i % 16 == 0 else 7.0 if i % 8 == 0 else 5.5 if i % 4 == 0 else 4.0 if i % 2 == 0 else 2.6
            d.rectangle([x - tw / 2, 0, x + tw / 2, ln * k], fill=(25, 25, 25, 255))
            if i % 16 == 0:
                d.text((x - 1.5 * k, 11 * k), str(i // 16), fill=(25, 25, 25, 255), font_size=int(6 * k))
    return im

def scene(path: Path, px_mm: float, angle: float, unit: str = "mm", obj_mm=(60.0, 35.0), obj_angle=25.0,
          ruler: bool = True, ref: str | None = None, seed: int = 0) -> None:
    """Light paper, a ruler rotated by angle, a dark rounded block of obj_mm; blur and noise."""
    k = px_mm * SS
    cw, ch = 260, 210  # canvas in mm
    canvas = Image.new("RGBA", (round(cw * k), round(ch * k)), (226, 223, 216, 255))
    if ruler:
        r = ruler_image(px_mm, unit).rotate(angle, resample=Image.BICUBIC, expand=True)
        cx, cy = (45, 105) if abs(angle) > 60 else (130, 55)
        canvas.alpha_composite(r, (round(cx * k - r.width / 2), round(cy * k - r.height / 2)))
    if ref == "card":
        card = Image.new("RGBA", (round(85.6 * k), round(53.98 * k)), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=3 * k,
                                                fill=(40, 90, 170, 255))
        card = card.rotate(-8, resample=Image.BICUBIC, expand=True)
        canvas.alpha_composite(card, (round(20 * k), round(20 * k)))
    if ref == "coin-us-quarter":
        d = ImageDraw.Draw(canvas)
        r_ = 24.26 / 2 * k
        d.ellipse([60 * k - r_, 50 * k - r_, 60 * k + r_, 50 * k + r_], fill=(150, 150, 155, 255))
    ow, oh = obj_mm
    blk = Image.new("RGBA", (round(ow * k), round(oh * k)), (0, 0, 0, 0))
    ImageDraw.Draw(blk).rounded_rectangle([0, 0, blk.width - 1, blk.height - 1], radius=2 * k,
                                           fill=(52, 50, 62, 255))
    blk = blk.rotate(obj_angle, resample=Image.BICUBIC, expand=True)
    ox, oy = (165, 105) if (ruler and abs(angle) > 60) else (150, 145)
    canvas.alpha_composite(blk, (round(ox * k - blk.width / 2), round(oy * k - blk.height / 2)))
    small = canvas.convert("RGB").resize((round(cw * px_mm), round(ch * px_mm)), Image.BOX)
    small = small.filter(ImageFilter.GaussianBlur(0.7))
    a = np.asarray(small, dtype=float)
    # mild light falloff and sensor noise
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    a = a * (1.0 - 0.06 * (xx / a.shape[1]) - 0.04 * (yy / a.shape[0]))[..., None]
    a = a + np.random.default_rng(seed).normal(0, 3.0, a.shape)
    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(path)

def err(a, b):
    return abs(a - b) / b

@pytest.mark.parametrize("angle,px_mm", [(0, 5.0), (17, 4.5), (90, 6.0)])
def test_mm_ruler_at_any_angle(tmp_path, angle, px_mm):
    f = tmp_path / f"r{angle}.png"
    scene(f, px_mm, angle, seed=angle)
    r = ms.measure(f)
    assert r["method"] == "ruler" and r["unit"] == "mm", r
    assert err(r["mm_per_px"], 1 / px_mm) < 0.02, r
    assert err(r["object"]["long_mm"], 60) < 0.03, r
    assert err(r["object"]["short_mm"], 35) < 0.03, r
    assert r["confidence"] >= 0.6, r

def test_inch_ruler(tmp_path):
    f = tmp_path / "inch.png"
    scene(f, 5.0, 8, unit="inch", obj_mm=(50.8, 30.0), seed=3)
    r = ms.measure(f)
    assert r["method"] == "ruler" and r["unit"] == "inch" and r["ruler"]["tick"] == "1/16 in", r
    assert err(r["mm_per_px"], 1 / 5.0) < 0.02, r
    assert err(r["object"]["long_mm"], 50.8) < 0.03, r

def test_no_ruler_falls_back(tmp_path):
    f = tmp_path / "plain.png"
    scene(f, 5.0, 0, ruler=False, seed=4)
    r = ms.measure(f)
    assert r["method"] == "none" and r["mm_per_px"] is None
    assert "No ruler" in r["assumed"]
    assert r["object"] and err(r["object"]["long_px"], 300) < 0.03
    r = ms.measure(f, known_mm=ms.parse_known("120mm"))
    assert r["method"] == "known" and err(r["object"]["long_mm"], 120) < 1e-6
    assert err(r["object"]["short_mm"], 70) < 0.03, r

@pytest.mark.parametrize("ref", ["card", "coin-us-quarter"])
def test_reference_object(tmp_path, ref):
    f = tmp_path / f"{ref}.png"
    scene(f, 5.0, 0, ruler=False, ref=ref, seed=5)
    r = ms.measure(f, ref=ref)
    assert r["method"] == ref, r
    assert err(r["mm_per_px"], 0.2) < 0.03, r
    assert err(r["object"]["long_mm"], 60) < 0.04, r

def test_parse_known():
    assert ms.parse_known("120mm") == 120
    assert ms.parse_known("12 cm") == 120
    assert abs(ms.parse_known("2in") - 50.8) < 1e-9
    with pytest.raises(ms.MeasureProblem):
        ms.parse_known("big")

def test_blender_photo():
    """A Blender render: perspective camera tilted 14 deg, soft light, JPEG. Ground truth in truth.json."""
    truth = json.loads((FIXTURES / "truth.json").read_text())
    r = ms.measure(FIXTURES / truth["image"])
    assert r["method"] == "ruler" and r["unit"] == "mm" and r["ruler"]["ticks"] > 150, r
    # the method: scale beside the object and the object at that scale
    assert err(r["mm_per_px"], truth["ruler_mm_per_px_beside_object"]) < 0.02, r
    ideal = truth["object_mm_at_ruler_scale"]
    assert err(r["object"]["long_mm"], ideal[0]) < 0.03 and err(r["object"]["short_mm"], ideal[1]) < 0.03, r
    # the real size: perspective adds most of this, and stone says the photo is at an angle
    real = truth["object_mm"]
    assert err(r["object"]["long_mm"], real[0]) < truth["max_error"], r
    assert err(r["object"]["short_mm"], real[1]) < truth["max_error"], r
    assert any("angle" in n for n in r["notes"]), r

def test_cli_measure_feeds_recipe_size(jobenv, tmp_path, recipes_root):
    f = tmp_path / "photo.png"
    scene(f, 5.0, 0, seed=7)
    text, code, nxt = stone("measure", str(f))
    assert code == 0 and "Object:" in text and "No job" in text
    assert nxt.startswith('stone new "<what to make>" --image')
    stone("new", "a keychain of this block", "--image", str(f))
    text, code, nxt = stone("measure", str(f))
    assert code == 0 and "60." in text and "Saved" in text, text
    saved = json.loads((jobenv / "stone-job" / "measure.json").read_text())
    assert saved["method"] == "ruler"
    # a picture recipe with a size param takes the measured long side
    d = recipes_root / "keychain"
    d.mkdir()
    (d / "recipe.scad").write_text('image = "";\ncube(10);\n')
    (d / "recipe.json").write_text(json.dumps({
        "name": "keychain", "title": "Keychain", "summary": "A charm.", "tags": ["keychain"],
        "tier": "S", "params": [
            {"name": "image", "type": "image", "default": "", "image_kind": "silhouette"},
            {"name": "size", "type": "number", "default": 50, "min": 20, "max": 150, "unit": "mm"}],
    }))
    text, code, nxt = stone("show", "keychain")
    line = next(ln for ln in text.splitlines() if ln.startswith("From the picture:"))
    v = float(line.split("size=")[1].split()[0])
    assert abs(v - 60) < 1.8, text
    text, code, nxt = stone("set", "keychain")
    assert f"size = {line.split('size=')[1].split()[0]} mm" in text, text
    # a size the model sets wins
    text, code, nxt = stone("set", "keychain", "size=40")
    assert "size = 40 mm" in text
    text, code, nxt = stone("status")
    assert "Measured:" in text

def test_cli_measure_no_ruler_says_what_to_add(jobenv, tmp_path):
    f = tmp_path / "plain.png"
    scene(f, 5.0, 0, ruler=False, seed=8)
    stone("new", "a cookie cutter of this", "--image", str(f))
    text, code, nxt = stone("measure", str(f))
    assert code == 1 and "No ruler" in text
    assert nxt == f"stone measure {f} --known <long side>mm"
    text, code, nxt = stone("measure", str(f), "--known", "120mm")
    assert code == 0 and "120" in text
    text, code, nxt = stone("measure", str(f), "--known", "big")
    assert code == 1 and "FIX:" in text


@pytest.mark.parametrize("measure_first", [True, False])
def test_outline_leaves_the_ruler_out(jobenv, tmp_path, measure_first):
    """The same photo for stone measure and stone image traces the object, not the ruler too."""
    f = tmp_path / "photo.png"
    scene(f, 5.0, 0, obj_angle=0, seed=3)  # a 60 x 35 mm block, square to the frame
    stone("new", "a keychain of this block")
    if measure_first:
        stone("measure", str(f))
        text, code, nxt = stone("image", str(f))
        assert "cropped to the measured object" in text, text
    else:
        stone("image", str(f))
        text, code, nxt = stone("measure", str(f))
        assert "without the ruler" in text, text
    info = json.loads((jobenv / "stone-job" / "image" / "info.json").read_text())
    assert abs(info["aspect"] - 60 / 35) < 0.12, info
