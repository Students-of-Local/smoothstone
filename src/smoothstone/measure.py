"""Real-world scale for a photo: find a ruler or tape measure, or use a card, a coin or a known length.

measure(path) returns mm_per_px, the main object's size in mm and a confidence. No ML: the ruler is
found from its tick marks, which make a strong periodic edge pattern along one direction.

1. Candidate directions: a histogram of gradient angles (tick edges all share one gradient direction).
2. For each direction, rotate so the ruler would lie along x, then cut the picture into short row
   bands and take the FFT of each band's intensity profile in windows. Ticks give one sharp peak.
3. The best run of periodic windows is the tick band. Its period is refined on the whole band with a
   harmonic sum, so hundreds of ticks average out the pixel grid.
4. Tick lengths, folded by 10 and 16, say which unit: mm rulers are longer every 5 and 10 ticks,
   inch rulers every 2, 4, 8 and 16 sixteenths.
5. The object is the largest foreground blob (background color model fitted on the picture) that is
   not the ruler, measured along its own principal axes.
"""

from __future__ import annotations

import math
import re
import warnings
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from .image import ImageProblem, _open

WORK_PX = 2000  # long side the picture is measured at
MIN_PERIOD = 2.5  # px; finer ticks than this cannot be resolved
BAND = 6  # rows per profile band
INCH = 25.4

REFS = {
    "card": {"size_mm": (85.60, 53.98), "text": "a bank card (85.60 x 53.98 mm)"},
    "coin-us-quarter": {"size_mm": (24.26, 24.26), "text": "a US quarter (24.26 mm across)"},
}
# image recipes and the parameter a measured object size fills in
SIZE_PARAMS = {"keychain": "size", "cookie_cutter": "size", "sign": "w", "relief": "width"}


class MeasureProblem(Exception):
    pass


def parse_known(text: str) -> float:
    """'120mm', '12 cm', '4.5in', '120' -> mm."""
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(mm|cm|m|in|inch|inches|\")?\s*", str(text).lower())
    if not m:
        raise MeasureProblem(f'cannot read "{text}" as a length; write it like 120mm')
    v = float(m.group(1))
    unit = m.group(2) or "mm"
    v *= {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": INCH, "inch": INCH, "inches": INCH, '"': INCH}[unit]
    if v <= 0:
        raise MeasureProblem("the known length must be more than 0")
    return v


# loading


def _load(path: Path) -> tuple[np.ndarray, float, tuple[int, int]]:
    im = _open(path)
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    im = im.convert("RGB")
    orig = im.size
    scale = 1.0
    if max(im.size) > WORK_PX:
        scale = WORK_PX / max(im.size)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    rgb = np.asarray(im, dtype=np.float64)
    return rgb, scale, orig


def _gray(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.299, 0.587, 0.114])


# ruler: directions


def _angle_candidates(gray: np.ndarray, k: int = 4) -> list[float]:
    g = ndimage.gaussian_filter(gray, 1.0)
    gx = ndimage.sobel(g, axis=1)
    gy = ndimage.sobel(g, axis=0)
    mag = np.hypot(gx, gy)
    thr = max(np.percentile(mag, 90), 1e-6)
    sel = mag > thr
    if sel.sum() < 50:
        return [0.0, 90.0]
    ang = np.degrees(np.arctan2(gy[sel], gx[sel])) % 180.0
    nb = 360
    hist, _ = np.histogram(ang, bins=nb, range=(0, 180), weights=mag[sel])
    hist = ndimage.gaussian_filter1d(hist.astype(float), 2, mode="wrap")
    peaks = []
    order = np.argsort(hist)[::-1]
    for i in order:
        if hist[i] < hist[order[0]] * 0.1 or len(peaks) >= k:
            break
        left, right = hist[(i - 1) % nb], hist[(i + 1) % nb]
        if hist[i] < left or hist[i] < right:
            continue
        den = left - 2 * hist[i] + right
        d = min(max(0.5 * (left - right) / den, -0.5), 0.5) if den < 0 else 0.0
        a = ((i + 0.5 + d) * 180.0 / nb) % 180.0
        if all(_adiff(a, p) > 5 for p in peaks):
            peaks.append(a)
    cands: list[float] = []
    for a in peaks + [(p + 90) % 180 for p in peaks]:
        if all(_adiff(a, c) > 3 for c in cands):
            cands.append(a)
    return cands or [0.0, 90.0]


def _adiff(a: float, b: float) -> float:
    d = abs(a - b) % 180
    return min(d, 180 - d)


def _rotate(img: np.ndarray, theta: float):
    """Rotate so direction theta (deg, x right, y down) runs along +x. Returns out, M, offset.

    A point (row', col') in the output came from M @ (row', col') + offset in the input."""
    t = math.radians(theta)
    c, s = math.cos(t), math.sin(t)
    h, w = img.shape
    wo = int(math.ceil(abs(w * c) + abs(h * s)))
    ho = int(math.ceil(abs(w * s) + abs(h * c)))
    cin = np.array([(h - 1) / 2, (w - 1) / 2])
    cout = np.array([(ho - 1) / 2, (wo - 1) / 2])
    m = np.array([[c, s], [-s, c]])
    off = cin - m @ cout
    out = ndimage.affine_transform(img, m, offset=off, output_shape=(ho, wo), order=1,
                                   cval=np.nan, prefilter=False)
    return out, m, off


# ruler: periodic windows


def _scan(rot: np.ndarray):
    """Score every (row band, x window) for one sharp periodic peak. Returns a list of dicts."""
    ho, wo = rot.shape
    win = 512 if wo >= 1024 else max(128, 2 ** int(math.floor(math.log2(max(wo, 2)))) // 2)
    if wo < win:
        return [], win
    step = win // 2
    nb = ho // BAND
    rows = rot[: nb * BAND].reshape(nb, BAND, wo)
    valid = ~np.isnan(rows).any(axis=1)
    with np.errstate(invalid="ignore"):
        prof = np.nanmean(np.where(np.isnan(rows), np.nan, rows), axis=1) if nb else np.zeros((0, wo))
    starts = list(range(0, wo - win + 1, step))
    if starts[-1] + win < wo:
        starts.append(wo - win)
    segs = np.stack([prof[:, x0: x0 + win] for x0 in starts], axis=1)  # nb, nw, win
    vfrac = np.stack([valid[:, x0: x0 + win].mean(axis=1) for x0 in starts], axis=1)
    mean = np.nanmean(np.where(np.isfinite(segs), segs, np.nan), axis=2, keepdims=True) if segs.size else segs
    segs = np.where(np.isfinite(segs), segs, mean)
    segs = np.nan_to_num(segs - mean)
    segs = segs * np.hanning(win)
    pw = np.abs(np.fft.rfft(segs, axis=2)) ** 2
    pmax = win / 10  # at least 10 ticks per window
    kmin = max(3, int(math.ceil(win / pmax)))
    kmax = min(pw.shape[2] - 2, int(win / MIN_PERIOD))
    band = pw[:, :, kmin: kmax + 1]
    total = band.sum(axis=2) + 1e-12
    kk = band.argmax(axis=2) + kmin
    out = []
    amp = np.sqrt(total) / win
    for bi in range(nb):
        for wi in range(len(starts)):
            if vfrac[bi, wi] < 0.8 or amp[bi, wi] < 0.05:
                continue
            k = int(kk[bi, wi])
            if k <= kmin + 1 or k >= kmax - 1:
                continue  # a peak at the edge of the band is a slope or noise, not ticks
            p = pw[bi, wi]
            peak = p[k - 2: k + 3].sum()
            score = float(peak / total[bi, wi])
            if score < 0.18:
                continue
            a, b, cc = math.log(p[k - 1] + 1e-12), math.log(p[k] + 1e-12), math.log(p[k + 1] + 1e-12)
            den = a - 2 * b + cc
            d = min(max(0.5 * (a - cc) / den, -0.5), 0.5) if den < 0 else 0.0
            out.append({"bi": bi, "wi": wi, "x0": starts[wi], "score": score, "period": win / (k + d)})
    return out, win


def _regions(hits: list[dict]) -> list[dict]:
    """Group windows with the same period that touch each other."""
    if not hits:
        return []
    grid: dict[tuple[int, int], list[int]] = {}
    for i, h in enumerate(hits):
        grid.setdefault((h["bi"], h["wi"]), []).append(i)
    regions = []
    used = [False] * len(hits)
    for i in range(len(hits)):
        if used[i]:
            continue
        # flood fill over neighbouring windows with a period within 4%
        stack, comp = [i], []
        used[i] = True
        while stack:
            j = stack.pop()
            hj = hits[j]
            comp.append(hj)
            for db in (-1, 0, 1):
                for dw in (-1, 0, 1):
                    for k in grid.get((hj["bi"] + db, hj["wi"] + dw), ()):
                        if not used[k] and abs(math.log(hits[k]["period"] / hj["period"])) < 0.04:
                            used[k] = True
                            stack.append(k)
        per_w: dict[int, float] = {}
        for c in comp:
            per_w[c["x0"]] = max(per_w.get(c["x0"], 0.0), c["score"])
        regions.append({
            "hits": comp,
            "key": float(sum(per_w.values())),  # best band per window: a level ruler scores highest
            "period": float(np.median([c["period"] for c in comp])),
            "score_sum": float(sum(c["score"] for c in comp)),
            "score": float(np.mean([c["score"] for c in comp])),
            "bi": (min(c["bi"] for c in comp), max(c["bi"] for c in comp)),
            "x": (min(c["x0"] for c in comp), max(c["x0"] for c in comp)),
        })
    return regions


def _pick_region(regions: list[dict], win: int) -> dict | None:
    if not regions:
        return None
    ok = [r for r in regions if (r["x"][1] - r["x"][0] + win) / r["period"] >= 15]
    if not ok:
        return None
    best = max(ok, key=lambda r: r["key"])
    # rows with only the long ticks repeat every 5 or 10 mm: prefer the fine ticks of the same ruler
    for r in sorted(ok, key=lambda r: r["period"]):
        if r is best or r["key"] < 0.25 * best["key"]:
            continue
        ratio = best["period"] / r["period"]
        near = r["x"][0] <= best["x"][1] + win and best["x"][0] <= r["x"][1] + win
        if near and any(abs(ratio - m) / m < 0.05 for m in (2, 4, 5, 8, 10, 16)):
            return r
    return best


# ruler: refine on the found band


def _harmonic_power(p: np.ndarray, xs: np.ndarray, f: float) -> float:
    return float(sum(abs(np.sum(p * np.exp(-2j * math.pi * h * f * xs))) ** 2 for h in (1, 2, 3)))


def _refine_period(p: np.ndarray, xs: np.ndarray, period: float) -> float:
    f0 = 1.0 / period
    grid = np.linspace(f0 * 0.97, f0 * 1.03, 241)
    vals = np.array([_harmonic_power(p, xs, f) for f in grid])
    i = int(vals.argmax())
    for _ in range(2):  # zoom in twice around the best frequency
        lo = grid[max(i - 1, 0)]
        hi = grid[min(i + 1, len(grid) - 1)]
        grid = np.linspace(lo, hi, 41)
        vals = np.array([_harmonic_power(p, xs, f) for f in grid])
        i = int(vals.argmax())
    return 1.0 / grid[i]


def _fold(lengths: np.ndarray, m: int):
    n = len(lengths)
    if n < 2 * m + 2:
        return -1.0, None
    idx = np.arange(n) % m
    cnt = np.bincount(idx, minlength=m)
    means = np.bincount(idx, lengths, minlength=m) / np.maximum(cnt, 1)
    tot = float(((lengths - lengths.mean()) ** 2).sum())
    if tot <= 1e-9:
        return 0.0, means
    r2 = float((cnt * (means - lengths.mean()) ** 2).sum()) / tot
    return 1 - (1 - r2) * (n - 1) / (n - m), means


def _ruler_on(rot: np.ndarray, region: dict, win: int) -> dict | None:
    ho, wo = rot.shape
    r0 = region["bi"][0] * BAND
    r1 = (region["bi"][1] + 1) * BAND
    xa = max(0, region["x"][0] - win // 2)
    xb = min(wo, region["x"][1] + win + win // 2)
    with np.errstate(invalid="ignore"):
        prof = np.nanmean(rot[r0:r1, xa:xb], axis=0)
    xs = np.arange(xa, xb, dtype=float)
    good = np.isfinite(prof)
    if good.sum() < 20:
        return None
    period = region["period"]
    # where along x the ticks actually are: local amplitude of the tick frequency
    pz = np.where(good, prof - np.nanmean(prof), 0.0)
    f = 1.0 / period
    demod = pz * np.exp(-2j * math.pi * f * xs)
    span = max(3, int(round(4 * period)))
    amp = np.abs(ndimage.uniform_filter1d(demod.real, span) + 1j * ndimage.uniform_filter1d(demod.imag, span))
    core = (xs >= region["x"][0]) & (xs < region["x"][1] + win)
    ref = np.median(amp[core]) if core.any() else amp.max()
    on = amp > 0.35 * ref
    lab, n = ndimage.label(on)
    if n == 0:
        return None
    sizes = ndimage.sum(on, lab, range(1, n + 1))
    keep = lab == (int(np.argmax(sizes)) + 1)
    xi = np.where(keep)[0]
    x_lo, x_hi = xs[xi[0]], xs[xi[-1]]
    sel = keep & good
    p = pz[sel]
    pxs = xs[sel]
    p = p - p.mean()
    period = _refine_period(p, pxs, period)
    f = 1.0 / period

    # follow the tick phase along the ruler: a photo taken at an angle stretches one end
    demod = np.where(sel, pz, 0.0) * np.exp(-2j * math.pi * f * xs)
    span = max(5, int(round(8 * period)))
    zf = ndimage.uniform_filter1d(demod.real, span) + 1j * ndimage.uniform_filter1d(demod.imag, span)
    xk_all = xs[keep]
    psi = 2 * math.pi * f * xk_all + np.unwrap(np.angle(zf[keep]))
    xm, xsd = xk_all.mean(), max(xk_all.std(), 1.0)
    deg = 3 if len(xk_all) > 40 * period else 1
    coef = np.polyfit((xk_all - xm) / xsd, psi, deg, w=np.abs(zf[keep]) + 1e-9)
    grid = np.linspace(x_lo, x_hi, max(200, int(x_hi - x_lo) + 1))
    psi_g = np.polyval(coef, (grid - xm) / xsd)
    dpsi = np.gradient(psi_g, grid)
    if np.any(dpsi <= 0):
        return None
    local = 2 * math.pi / dpsi  # tick spacing in px along the ruler

    # tick phase and polarity from the profile folded on the tracked phase
    nbins = 24
    ph = (np.interp(pxs, grid, psi_g) / (2 * math.pi)) % 1.0
    bi = np.minimum((ph * nbins).astype(int), nbins - 1)
    folded = np.bincount(bi, p, minlength=nbins) / np.maximum(np.bincount(bi, minlength=nbins), 1)
    med = np.median(folded)
    dark = (med - folded.min()) >= (folded.max() - med)
    sign = 1.0 if dark else -1.0
    j = int(np.argmin(folded) if dark else np.argmax(folded))
    a, b, c = sign * folded[(j - 1) % nbins], sign * folded[j], sign * folded[(j + 1) % nbins]
    den = a - 2 * b + c
    d = min(max(0.5 * (a - c) / den, -0.5), 0.5) if den > 0 else 0.0
    phase = ((j + 0.5 + d) / nbins) % 1.0
    turns = psi_g / (2 * math.pi) - phase
    k0, k1 = int(math.ceil(turns[0])), int(math.floor(turns[-1]))
    if k1 - k0 + 1 < 15:
        return None
    xk = np.interp(np.arange(k0, k1 + 1), turns, grid)
    pk = np.interp(xk, grid, local)
    period = float((grid[-1] - grid[0]) / (turns[-1] - turns[0]))  # mean spacing over the ruler

    # tick lengths: contrast of each tick against the paper beside it, row by row
    yc = 0.5 * (r0 + r1)
    reach = 18 * period
    ys = np.arange(max(0.0, yc - reach), min(ho - 1.0, yc + reach) + 1, 1.0)
    sm = np.where(np.isfinite(rot), rot, np.nanmean(rot[r0:r1]))
    sm = ndimage.gaussian_filter(sm, (1.0, 0.0))
    yy, xx = np.meshgrid(ys, xk, indexing="ij")
    on_t = ndimage.map_coordinates(sm, [yy, xx], order=1, mode="nearest")
    half = np.broadcast_to(pk / 2, xx.shape)
    side = 0.5 * (ndimage.map_coordinates(sm, [yy, xx - half], order=1, mode="nearest")
                  + ndimage.map_coordinates(sm, [yy, xx + half], order=1, mode="nearest"))
    con = sign * (side - on_t)  # rows x ticks
    rowmed = np.median(con, axis=1)
    yrow = int(np.argmax(rowmed))
    ref = rowmed[yrow]
    if ref <= 0:
        return None
    thr = 0.4 * ref
    above = con > thr
    lengths = np.zeros(len(xk))
    top = np.zeros(len(xk))
    bot = np.zeros(len(xk))
    for t in range(len(xk)):
        if not above[yrow, t]:
            top[t] = bot[t] = yrow
            continue
        u = yrow
        while u - 1 >= 0 and above[u - 1, t]:
            u -= 1
        v = yrow
        while v + 1 < len(ys) and above[v + 1, t]:
            v += 1
        top[t], bot[t] = u, v
        lengths[t] = v - u + 1
    present = lengths > 0

    r10, m10 = _fold(lengths, 10)
    r16, m16 = _fold(lengths, 16)
    r8, _ = _fold(lengths, 8)
    notes = []
    if max(r10, r16) < 0.3:
        unit, tick_mm, label = "mm", 1.0, "1 mm"
        notes.append("Tick pattern unclear; assumed the finest ticks are 1 mm apart.")
        struct = 0.3
    elif r10 >= r16:
        unit, tick_mm, label = "mm", 1.0, "1 mm"
        struct = r10
    else:
        struct = r16
        # 1/8 in ticks: the inch mark and the mark 8 ticks on (the next inch) are the same length
        j = int(np.argmax(m16))
        twin = m16[(j + 8) % 16] >= 0.92 * m16[j]
        if r8 >= r16 - 0.05 and twin:
            unit, tick_mm, label = "inch", INCH / 8, "1/8 in"
        else:
            unit, tick_mm, label = "inch", INCH / 16, "1/16 in"

    # which side is the ruler edge: every tick starts there, so the run ends line up
    tops = top[present]
    bots = bot[present]
    edge_top = np.std(tops) <= np.std(bots)
    y_edge = ys[0] + (np.median(tops) if edge_top else np.median(bots))
    long_px = float(lengths.max())
    return {
        "period": period, "tick_mm": tick_mm, "unit": unit, "label": label,
        "ticks": int(present.sum()), "struct": float(struct), "notes": notes,
        "x": (float(x_lo), float(x_hi)), "rows": (float(r0), float(r1)),
        "y_edge": float(y_edge), "edge_top": bool(edge_top), "long_tick_px": long_px,
        "tick_rows": (float(ys[0] + np.min(tops)), float(ys[0] + np.max(bots))) if present.any() else (r0, r1),
        "r10": float(r10), "r16": float(r16),
        "grid": grid, "local": local,
        "spread": float((local.max() - local.min()) / local.mean()),
    }


def _ruler_zone(rot: np.ndarray, ru: dict) -> tuple[float, float]:
    """Rows (in the rotated frame) the ruler body covers: from the tick edge to the far edge."""
    ho, wo = rot.shape
    px_mm = ru["period"] / ru["tick_mm"]
    xa, xb = int(ru["x"][0]), int(ru["x"][1]) + 1
    g = np.abs(np.diff(np.where(np.isfinite(rot[:, xa:xb]), rot[:, xa:xb], np.nan), axis=0))
    with np.errstate(invalid="ignore"):
        rowstrength = np.nanmedian(g, axis=1)
    rowstrength = np.nan_to_num(rowstrength)
    y0 = ru["y_edge"]
    d = 1 if ru["edge_top"] else -1
    lo = y0 + d * (ru["long_tick_px"] + 2 * px_mm)
    hi = y0 + d * 55 * px_mm
    a, b = sorted((int(lo), int(hi)))
    a, b = max(a, 0), min(b, len(rowstrength) - 1)
    far = y0 + d * 32 * px_mm
    if b > a:
        seg = rowstrength[a: b + 1]
        base = np.median(rowstrength[max(0, a - 50): b + 50]) + 1e-6
        i = int(np.argmax(seg))
        if seg[i] > 4 * base and seg[i] > 2.0:
            far = a + i + 0.5
    near = y0 - d * 1.5 * px_mm
    return tuple(sorted((near, far + d * 1.0 * px_mm)))


def _drift(region: dict, win: int) -> float:
    """Angle error (deg) from how the tick band climbs or drops across the x windows."""
    by_w: dict[int, list] = {}
    for h in region["hits"]:
        by_w.setdefault(h["x0"], []).append(h)
    if len(by_w) < 2:
        return 0.0
    xs, ys, ws = [], [], []
    for x0, hs in by_w.items():
        sc = np.array([h["score"] for h in hs])
        bi = np.array([h["bi"] for h in hs], dtype=float)
        xs.append(x0 + win / 2)
        ys.append((bi * sc).sum() / sc.sum() * BAND + BAND / 2)
        ws.append(sc.sum())
    slope = np.polyfit(xs, ys, 1, w=np.sqrt(ws))[0]
    return math.degrees(math.atan(slope))


def _best_region(gray: np.ndarray, theta: float):
    rot, m, off = _rotate(gray, theta)
    hits, win = _scan(rot)
    region = _pick_region(_regions(hits), win)
    return rot, m, off, region, win


def find_ruler(gray: np.ndarray) -> dict | None:
    best = None
    for theta in _angle_candidates(gray):
        rot, m, off, region, win = _best_region(gray, theta)
        if region is None:
            continue
        key = region["key"]
        if best is None or key > best[0]:
            best = (key, theta, rot, m, off, region, win)
    if best is None:
        return None
    _, theta, rot, m, off, region, win = best
    # the histogram angle can be a degree or two off: follow the band's drift until it runs level
    for _ in range(3):
        d = _drift(region, win)
        if abs(d) < 0.05:
            break
        got = _best_region(gray, theta + d)
        if got[3] is None or got[3]["key"] < 0.9 * region["key"]:
            break
        theta += d
        rot, m, off, region, win = got
    ru = _ruler_on(rot, region, win)
    if ru is None:
        return None
    ru["angle"] = theta % 180
    ru["score"] = region["score"]
    ru["zone_rows"] = _ruler_zone(rot, ru)
    ru["_frame"] = (rot.shape, m, off)
    return ru


def _frame_mask(shape, frame, rows: tuple[float, float], xs: tuple[float, float]) -> np.ndarray:
    """Mask in the picture of a rectangle given in the rotated frame."""
    (ho, wo), m, off = frame
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    pts = np.stack([yy.ravel() - off[0], xx.ravel() - off[1]])
    inv = np.linalg.inv(m)
    q = inv @ pts
    ry, rx = q[0].reshape(h, w), q[1].reshape(h, w)
    return (ry >= rows[0]) & (ry <= rows[1]) & (rx >= xs[0]) & (rx <= xs[1])


# object


def _otsu(v: np.ndarray) -> float:
    from skimage.filters import threshold_otsu

    return float(threshold_otsu(v))


def _two_level(d: np.ndarray) -> float:
    """Otsu, then a second Otsu below it when a fainter thing (a gray coin, a pale card) sits there."""
    t1 = _otsu(d)
    low = d[d < t1]
    if low.size < 100:
        return t1
    med = float(np.median(low))
    sigma = 1.4826 * float(np.median(np.abs(low - med))) + 1e-6
    t2 = _otsu(low)
    mid = ((d > t2) & (d < t1)).mean()
    if t2 > med + 8 * sigma and mid > 0.002:
        return t2
    return t1


def _foreground(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pixels that differ from a smooth background model (quadratic in x and y per channel)."""
    h, w, _ = rgb.shape
    sm = ndimage.gaussian_filter(rgb, (1.0, 1.0, 0))
    border = np.concatenate([sm[0], sm[-1], sm[:, 0], sm[:, -1]])
    bg = np.median(border, axis=0)
    d = np.linalg.norm(sm - bg, axis=2)
    if np.percentile(d, 99.5) < 12:  # one flat color: nothing stands out
        return np.zeros((h, w), bool), d
    fg = d > _otsu(d)
    # fit the paper on a coarse grid, away from anything that is not paper
    st = 4
    ys, xs = np.arange(0, h, st), np.arange(0, w, st)
    yn, xn = np.meshgrid(ys / max(h - 1, 1) - 0.5, xs / max(w - 1, 1) - 0.5, indexing="ij")
    small = sm[::st, ::st].reshape(-1, 3)
    basis_s = np.stack([np.ones_like(xn), xn, yn, xn * xn, yn * yn, xn * yn], axis=-1).reshape(-1, 6)
    yf = np.linspace(-0.5, 0.5, h)[:, None]
    xf = np.linspace(-0.5, 0.5, w)[None, :]
    for _ in range(2):
        keep = ~ndimage.binary_dilation(fg[::st, ::st], iterations=max(1, round(max(h, w) / 800)))
        idx = np.flatnonzero(keep)
        if len(idx) < 100:
            break
        model = np.empty_like(sm)
        for ch in range(3):
            c, *_ = np.linalg.lstsq(basis_s[idx], small[idx, ch], rcond=None)
            model[..., ch] = c[0] + c[1] * xf + c[2] * yf + c[3] * xf * xf + c[4] * yf * yf + c[5] * xf * yf
        d = np.linalg.norm(sm - model, axis=2)
        fg = d > _two_level(d)
    r = max(1, round(max(h, w) / 600))
    se = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 1), r)
    fg = ndimage.binary_opening(fg, structure=se)
    return fg, d


def _half_contrast(mask: np.ndarray, d: np.ndarray, exclude: np.ndarray | None = None) -> np.ndarray:
    """Redraw a blob's edge where it is halfway between its own core and the paper around it."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    pad = 10
    y0, y1 = max(rows[0] - pad, 0), min(rows[-1] + pad + 1, mask.shape[0])
    x0, x1 = max(cols[0] - pad, 0), min(cols[-1] + pad + 1, mask.shape[1])
    m, dd = mask[y0:y1, x0:x1], d[y0:y1, x0:x1]
    core = ndimage.binary_erosion(m, iterations=3)
    near = ndimage.binary_dilation(m, iterations=3)
    ring = ndimage.binary_dilation(m, iterations=7) & ~near
    if core.sum() < 20 or ring.sum() < 20:
        return mask
    t = 0.5 * (np.median(dd[core]) + np.median(dd[ring]))
    new = (dd > t) & near
    if exclude is not None:
        new &= ~exclude[y0:y1, x0:x1]
    lab, n = ndimage.label(new)
    if n == 0:
        return mask
    sizes = ndimage.sum(new, lab, range(1, n + 1))
    out = np.zeros_like(mask)
    out[y0:y1, x0:x1] = ndimage.binary_fill_holes(lab == (int(np.argmax(sizes)) + 1))
    return out


def _shape(mask: np.ndarray) -> dict:
    ys, xs = np.nonzero(mask)
    pts = np.stack([xs, ys], axis=1).astype(float)
    c = pts.mean(axis=0)
    cov = np.cov((pts - c).T)
    ev, evec = np.linalg.eigh(cov)
    major = evec[:, 1]
    minor = evec[:, 0]
    pa = (pts - c) @ major
    pb = (pts - c) @ minor
    long_px = float(pa.max() - pa.min() + 1)
    short_px = float(pb.max() - pb.min() + 1)
    angle = math.degrees(math.atan2(major[1], major[0])) % 180
    area = float(len(pts))
    return {
        "long_px": long_px, "short_px": short_px, "angle_deg": round(angle, 1), "area_px": area,
        "fill": area / (long_px * short_px),
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
        "center": c,
    }


def _components(fg: np.ndarray, min_frac: float = 0.0005):
    lab, n = ndimage.label(fg)
    if n == 0:
        return lab, []
    sizes = ndimage.sum(fg, lab, range(1, n + 1))
    order = [i + 1 for i in np.argsort(sizes)[::-1] if sizes[i] >= min_frac * fg.size]
    return lab, order


def _object_mask(fg: np.ndarray, lab: np.ndarray, ids: list[int], tick_zone=None, ruler_zone=None,
                 trim: int = 3):
    """The largest blob that is not the ruler. A blob joined to the ruler keeps only its part off the ruler."""
    best, best_area = None, 0
    se = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 1), trim)
    for i in ids:
        comp = lab == i
        if tick_zone is not None and (comp & tick_zone).any():
            comp = ndimage.binary_opening(comp & ~ruler_zone, structure=se)  # thin ruler leftovers go
            l2, n2 = ndimage.label(comp)
            if n2 == 0:
                continue
            sizes = ndimage.sum(comp, l2, range(1, n2 + 1))
            comp = l2 == (int(np.argmax(sizes)) + 1)
        area = int(comp.sum())
        if area > best_area and area >= 0.0005 * comp.size:
            best, best_area = comp, area
    return ndimage.binary_fill_holes(best) if best is not None else None


def _ref_score(sh: dict, ref: str) -> float:
    aspect = sh["long_px"] / max(sh["short_px"], 1)
    if ref == "card":
        want = 85.60 / 53.98
        return abs(aspect - want) / want + abs(sh["fill"] - 0.98)
    return abs(aspect - 1.0) + abs(sh["fill"] - math.pi / 4) * 2


# main entry


def measure(path, ref: str | None = None, known_mm: float | None = None) -> dict:
    """Find a ruler (or use ref / known_mm) and measure the main object. Sizes in mm."""
    path = Path(path)
    if not path.is_file():
        raise ImageProblem(f"no file at {path}")
    if ref is not None and ref not in REFS:
        raise MeasureProblem(f'unknown reference "{ref}"; use {" or ".join(REFS)}')
    rgb, scale, (ow, oh) = _load(path)
    gray = _gray(rgb)
    notes: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # empty slices in the rotated corners
        ru = find_ruler(gray)
    if ru is not None and ru["notes"] and (ref or known_mm):
        ru = None  # the periodic pattern is unsure; the user's reference is better
    fg, dist = _foreground(rgb)
    lab, ids = _components(fg)
    result = {
        "source": str(path), "width_px": ow, "height_px": oh,
        "method": "none", "unit": None, "mm_per_px": None, "confidence": 0.0,
        "object": None, "ruler": None, "assumed": "", "notes": notes,
    }
    mm_per_work = None
    obj = None
    zone = None
    if ru is not None:
        mm_per_work = ru["tick_mm"] / ru["period"]
        px_mm = 1.0 / mm_per_work
        tick_zone = _frame_mask(gray.shape, ru["_frame"], ru["tick_rows"], ru["x"])
        tick_zone = ndimage.binary_dilation(tick_zone, iterations=2)
        ruler_zone = _frame_mask(gray.shape, ru["_frame"], ru["zone_rows"],
                                 (ru["x"][0] - 3 * px_mm, ru["x"][1] + 3 * px_mm))
        obj = _object_mask(fg, lab, ids, tick_zone, ruler_zone, trim=max(2, round(px_mm)))
        zone = ruler_zone
        if obj is not None and obj.any():
            # read the tick spacing beside the object: in a photo taken at an angle it changes along the ruler
            (_, m, off) = ru["_frame"]
            cy, cx = ndimage.center_of_mass(obj)
            col = (np.linalg.inv(m) @ (np.array([cy, cx]) - off))[1]
            mm_per_work = ru["tick_mm"] / float(np.interp(col, ru["grid"], ru["local"]))
        notes.extend(ru["notes"])
        period_q = min(ru["score"] / 0.4, 1.0)
        struct_q = min(max(ru["struct"], 0) / 0.7, 1.0)
        count_q = min(ru["ticks"] / 40, 1.0)
        conf = (0.35 * period_q + 0.4 * struct_q + 0.25 * count_q) * max(0.5, 1 - 2 * max(ru["spread"] - 0.02, 0))
        if ru["notes"]:  # no 5 and 10 or inch pattern: maybe a grille or stripes, not a ruler
            conf *= 0.5
            notes.append("If there is no ruler in the photo, use --known <long side>mm.")
        if ru["spread"] > 0.03:
            notes.append(f"Tick spacing changes {ru['spread'] * 100:.0f}% along the ruler, so the photo is at an "
                         "angle. Sizes can be off; a photo from straight above is best.")
        if ref or known_mm:
            notes.append("Found a ruler, so the --ref or --known value was not used.")
        result.update(method="ruler", unit=ru["unit"], confidence=round(conf, 2))
        result["ruler"] = {
            "angle_deg": round(ru["angle"], 1), "tick": ru["label"], "ticks": ru["ticks"],
            "tick_px": round(ru["period"] / scale, 3),
        }
        result["assumed"] = f"Scale from a {'mm' if ru['unit'] == 'mm' else 'inch'} ruler, ticks {ru['label']} apart."
    elif ref is not None:
        shapes = [(i, _shape(lab == i)) for i in ids[:4]]
        if len(shapes) < 2:
            result["assumed"] = f"No ruler found, and could not find both {REFS[ref]['text']} and an object."
            return _finish(result, None, None, scale)
        ri, rsh = min(shapes, key=lambda s: _ref_score(s[1], ref))
        rsh = _shape(_half_contrast(ndimage.binary_fill_holes(lab == ri), dist))
        a, b = REFS[ref]["size_mm"]
        mm_per_work = 0.5 * (a / rsh["long_px"] + b / rsh["short_px"])
        obj = _object_mask(fg, lab, [i for i, _ in shapes if i != ri])
        q = max(0.0, 1.0 - 3 * _ref_score(rsh, ref))
        result.update(method=ref, confidence=round(0.6 * q, 2))
        result["assumed"] = f"No ruler found. Assumed the {'card' if ref == 'card' else 'round blob'} is {REFS[ref]['text']}."
    elif known_mm is not None:
        obj = _object_mask(fg, lab, ids)
        if obj is not None:
            obj = _half_contrast(obj, dist)
            mm_per_work = known_mm / _shape(obj)["long_px"]
            result.update(method="known", confidence=0.5)
        result["assumed"] = f"No ruler found. Assumed the object's long side is {known_mm:g} mm."
    else:
        obj = _object_mask(fg, lab, ids)
        result["assumed"] = "No ruler found, so there is no scale."
    if obj is not None:
        obj = _half_contrast(obj, dist, zone)
    return _finish(result, obj, mm_per_work, scale)


def _finish(result: dict, obj, mm_per_work, scale: float) -> dict:
    if mm_per_work is not None:
        result["mm_per_px"] = round(mm_per_work * scale, 6)
    if obj is not None and obj.any():
        sh = _shape(obj)
        o = {
            "long_px": round(sh["long_px"] / scale, 1),
            "short_px": round(sh["short_px"] / scale, 1),
            "angle_deg": sh["angle_deg"],
            "bbox_px": [round(v / scale) for v in sh["bbox"]],
        }
        if mm_per_work is not None:
            bw = (sh["bbox"][2] - sh["bbox"][0]) * mm_per_work
            bh = (sh["bbox"][3] - sh["bbox"][1]) * mm_per_work
            o.update(long_mm=round(sh["long_px"] * mm_per_work, 2),
                     short_mm=round(sh["short_px"] * mm_per_work, 2),
                     bbox_mm=[round(bw, 2), round(bh, 2)])
        result["object"] = o
    elif mm_per_work is not None:
        result["notes"].append("Found no object apart from the reference.")
    return result
