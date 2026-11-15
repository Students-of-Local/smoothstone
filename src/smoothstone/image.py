"""Reference image -> silhouette.svg, height.png and info.json."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

WORK_PX = 600  # long side used for the silhouette mask
HEIGHT_PX = 300  # long side of height.png
SVG_WIDTH = 100.0  # svg width in mm (1 unit = 1 mm in OpenSCAD)

SILHOUETTE_RECIPES = ["keychain", "cookie_cutter", "sign"]
PHOTO_RECIPES = ["lithophane", "relief"]


class ImageProblem(Exception):
    pass


def _open(path: Path) -> Image.Image:
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:  # PIL raises many types on bad input
        raise ImageProblem(f"cannot read {path.name} as an image") from e
    return ImageOps.exif_transpose(im)


def _luminance(im: Image.Image) -> np.ndarray:
    """Grayscale 0..255 with transparency composited on white."""
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    return np.asarray(im.convert("L"), dtype=np.float64)


def _alpha(im: Image.Image) -> np.ndarray | None:
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        a = np.asarray(im.convert("RGBA"))[:, :, 3]
        if a.min() < 250:
            return a
    return None


def _border(a: np.ndarray) -> np.ndarray:
    return np.concatenate([a[0, :], a[-1, :], a[:, 0], a[:, -1]])


def subject_mask(im: Image.Image) -> tuple[np.ndarray, float, bool]:
    """Boolean mask (True = subject), Otsu separation 0..1, used_alpha."""
    from skimage.filters import threshold_otsu

    alpha = _alpha(im)
    if alpha is not None:
        mask = alpha > 127
        return mask, 1.0, True
    lum = _luminance(im)
    if lum.max() - lum.min() < 1:
        return np.zeros(lum.shape, bool), 0.0, False
    t = threshold_otsu(lum)
    dark = lum <= t
    # background is whatever most border pixels are
    if _border(dark).mean() > 0.5:
        mask = ~dark
    else:
        mask = dark
    # Otsu separation: between-class variance over total variance
    total = lum.var()
    w1 = dark.mean()
    w0 = 1 - w1
    eta = 0.0
    if total > 0 and 0 < w1 < 1:
        m1, m0 = lum[dark].mean(), lum[~dark].mean()
        eta = float(w0 * w1 * (m0 - m1) ** 2 / total)
    return mask, eta, False


def clean_mask(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage

    if not mask.any():
        return mask
    r = max(1, round(max(mask.shape) / 300))
    st = ndimage.generate_binary_structure(2, 1)
    st = ndimage.iterate_structure(st, r)
    m = ndimage.binary_opening(mask, structure=st)
    m = ndimage.binary_closing(m, structure=st, border_value=0)
    if not m.any():
        m = mask
    area = m.sum()
    lab, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= 0.01 * area
        m = keep[lab]
    # fill tiny holes (specks inside the subject), keep real ones
    holes = ~m
    hlab, hn = ndimage.label(holes)
    if hn:
        border_labels = set(np.unique(_border(hlab)).tolist())
        sizes = ndimage.sum(holes, hlab, range(1, hn + 1))
        for i, s in enumerate(sizes, start=1):
            if i not in border_labels and s < 0.01 * area:
                m[hlab == i] = True
    return m


def shape_stats(mask: np.ndarray) -> tuple[int, bool]:
    from scipy import ndimage

    _, n = ndimage.label(mask)
    holes = ~mask
    hlab, hn = ndimage.label(holes)
    border_labels = set(np.unique(_border(hlab)).tolist()) - {0}
    return int(n), bool(hn - len(border_labels) > 0)


def _svg_potrace(mask: np.ndarray, out: Path, width_mm: float, height_mm: float) -> bool:
    exe = shutil.which("potrace")
    if not exe:
        return False
    with tempfile.TemporaryDirectory() as td:
        pbm = Path(td) / "mask.pbm"
        svg = Path(td) / "mask.svg"
        # PIL mode "1": 0 = black. potrace traces black.
        Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert("1").save(pbm)
        try:
            subprocess.run(
                [exe, "-s", "--flat", "-t", "2", "-O", "0.4", "-M", "0", "-o", str(svg), str(pbm)],
                check=True, capture_output=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        text = svg.read_text()
    import re

    m = re.search(r"<svg\b[^>]*>", text)
    if not m:
        return False
    tag = m.group(0)
    tag = re.sub(r'\swidth="[^"]*"', f' width="{width_mm:.3f}mm"', tag)
    tag = re.sub(r'\sheight="[^"]*"', f' height="{height_mm:.3f}mm"', tag)
    tag = re.sub(r'\spreserveAspectRatio="[^"]*"', ' preserveAspectRatio="none"', tag)
    text = text[: m.start()] + tag + text[m.end():]
    out.write_text(text)
    return True


def _svg_contours(mask: np.ndarray, out: Path, width_mm: float, height_mm: float) -> None:
    from skimage.measure import approximate_polygon, find_contours

    h, w = mask.shape
    padded = np.pad(mask.astype(float), 1)
    sx = width_mm / w
    sy = height_mm / h
    parts = []
    for c in find_contours(padded, 0.5):
        c = approximate_polygon(c, tolerance=0.6)
        if len(c) < 4:
            continue
        pts = [(min(max(col - 0.5, 0), w) * sx, min(max(row - 0.5, 0), h) * sy) for row, col in c]
        d = "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in pts) + " Z"
        parts.append(d)
    path = " ".join(parts)
    out.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.3f}mm" '
        f'height="{height_mm:.3f}mm" viewBox="0 0 {width_mm:.3f} {height_mm:.3f}">\n'
        f'<path fill="#000000" fill-rule="evenodd" d="{path}"/>\n</svg>\n'
    )


def process(src: Path, out_dir: Path) -> dict:
    """Copy src into out_dir and write silhouette.svg, outline.svg, height.png, info.json."""
    src = Path(src)
    out_dir = Path(out_dir)
    if not src.is_file():
        raise ImageProblem(f"no file at {src}")
    out_dir.mkdir(parents=True, exist_ok=True)
    im = _open(src)
    dest = out_dir / ("source" + (src.suffix.lower() or ".png"))
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)

    # height map: grayscale, same orientation, long side at most 300 px
    lum_img = Image.fromarray(_luminance(im).clip(0, 255).astype(np.uint8), "L")
    # stretched to the full 0 to 255 range, so recipes can map black and white to exact heights
    from PIL import ImageOps

    hm = ImageOps.autocontrast(lum_img, cutoff=0.5)
    hm.thumbnail((HEIGHT_PX, HEIGHT_PX), Image.LANCZOS)
    hm.save(out_dir / "height.png")

    work = im.copy()
    work.thumbnail((WORK_PX, WORK_PX), Image.LANCZOS)
    mask, eta, used_alpha = subject_mask(work)
    mask = clean_mask(mask)
    fill = float(mask.mean())
    if not mask.any():
        raise ImageProblem("found no subject in the image (it is one flat color)")
    shapes, has_holes = shape_stats(mask)

    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    crop = mask[rows[0]: rows[-1] + 1, cols[0]: cols[-1] + 1]
    ch, cw = crop.shape
    width_mm = SVG_WIDTH
    height_mm = SVG_WIDTH * ch / cw
    svg = out_dir / "silhouette.svg"
    tracer = "potrace" if _svg_potrace(crop, svg, width_mm, height_mm) else "contours"
    if tracer == "contours":
        _svg_contours(crop, svg, width_mm, height_mm)
    # outline.svg: the same subject with every hole filled, for parts that follow only the
    # outer edge (cookie cutters, keychain backs)
    from scipy.ndimage import binary_fill_holes

    outline = out_dir / "outline.svg"
    filled = binary_fill_holes(crop)
    if not _svg_potrace(filled, outline, width_mm, height_mm):
        _svg_contours(filled, outline, width_mm, height_mm)

    kind = "silhouette" if (used_alpha or eta >= 0.75) and fill < 0.70 else "photo"
    info = {
        "source": str(dest),
        "width_px": im.width,
        "height_px": im.height,
        "image_aspect": round(im.width / im.height, 4),
        "aspect": round(cw / ch, 4),
        "fill": round(fill, 4),
        "shapes": shapes,
        "has_holes": has_holes,
        "contrast": round(eta, 3),
        "alpha": used_alpha,
        "kind": kind,
        "svg_size_mm": [round(width_mm, 3), round(height_mm, 3)],
        "tracer": tracer,
        "silhouette": str(svg),
        "outline": str(outline),
        "height": str(out_dir / "height.png"),
        "recipes": SILHOUETTE_RECIPES if kind == "silhouette" else PHOTO_RECIPES,
    }
    (out_dir / "info.json").write_text(json.dumps(info, indent=2) + "\n")
    return info
