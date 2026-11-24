"""stone heat: will the part keep its shape where it lives, and will it warp on the bed.

Service temperatures, stiffness retention curves, HDT, Tg, CTE and shrink come from
recipes/lib/refs/materials.json. With a load, the part is solved again (stone strength's model) at the
softened stiffness and strength. Modeling choices are marked "assumption".
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from . import printers
from . import refs as reftool
from . import strength

ROOM = 23.0  # C, the temperature the maker sheets test at (ISO 291 standard atmosphere 23/50)
CREEP_BAND = 20.0  # C below HDT where a lasting load creeps (assumption, refs <m>.creep)
CHAMBER = 40.0  # C, air in a closed printer without a heater (assumption)
WARP_MM = (0.6, 1.2)  # corner lift, mm: under the first is low, over the second high (assumption)
THIN = 0.05  # first-layer area over longest extent squared: under this the corners have little to hold (assumption)
WHERE = {"car": "service.car", "sun": "service.sun", "dishwasher": "service.dishwasher", "outdoor": "service.outdoor"}
WORDS = {"car": "a car dashboard in summer sun", "sun": "dark surfaces in summer sun", "dishwasher": "a dishwasher",
         "outdoor": "hot summer shade"}
ASSUMPTIONS = [
    "Strength falls with temperature in the same ratio as stiffness (no sourced hot strength for printed parts).",
    "Between sourced points the stiffness ratio is linear in temperature and never rises (a DMA bump is not credited).",
    f"A lasting load creeps within {CREEP_BAND:g} C of the HDT at 0.45 MPa.",
    f"Corner lift = shrink x longest first-layer extent; low under {WARP_MM[0]} mm, high over {WARP_MM[1]} mm; a closed "
    f"printer holds the air near {CHAMBER:g} C.",
]


def service(word: str) -> tuple[float, str, str | None]:
    """(C, words, ref id) for car sun dishwasher outdoor, or a number like 70C."""
    w = word.strip().lower()
    if w in WHERE:
        e = reftool.get(WHERE[w])
        return float(e["value"]), WORDS[w], e["id"]
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*c?", w)
    if not m:
        raise ValueError(word)
    return float(m.group(1)), "the spot it lives in", None


def curve(name: str) -> list[tuple[float, float]] | None:
    """Stiffness ratio to room temperature against C, running minimum (a rise in a DMA curve is not credited)."""
    p = reftool.props(name)
    e = p.get("modulus_vs_temp")
    if not e:
        return None
    pts = sorted((float(t), float(r)) for t, r in e["value"])
    low = np.minimum.accumulate([r for _, r in pts])
    return [(t, float(r)) for (t, _), r in zip(pts, low)]


def retention(name: str, temp: float) -> float | None:
    """Share of room-temperature stiffness kept at temp; None where no curve is sourced."""
    c = curve(name)
    if c is None:
        return None
    ts, rs = zip(*c)
    return float(np.interp(temp, ts, rs))


def clamped_stress(name: str, alpha: float, t0: float, t1: float) -> float:
    """MPa in a bar held at both ends from t0 to t1: the integral of E(T) alpha dT (alpha in 1/K)."""
    e = reftool.props(name)["e_xy"]["value"]
    ts = np.linspace(t0, t1, 64)
    es = np.array([e * (retention(name, t) or 1.0) for t in ts])
    return float(np.sum((es[1:] + es[:-1]) / 2 * np.diff(ts)) * alpha)


def warp(name: str, mesh, enclosed: bool, bed: float | None) -> dict:
    """Corner lift risk from the first layer: shrink x its longest extent, raised for a thin contact,
    a cold bed, an open printer for a material that wants an enclosure, and nylon's crystals."""
    p = reftool.props(name)
    lo = mesh.bounds[0][2]
    sec = mesh.section(plane_origin=[0, 0, lo + 0.1], plane_normal=[0, 0, 1])
    loops = [d[:, :2] for d in sec.discrete] if sec is not None else []
    pts = np.vstack(loops) if loops else np.zeros((1, 2))
    area = _area(loops)
    from scipy.spatial import ConvexHull, QhullError

    try:
        hull = pts[ConvexHull(pts).vertices]
    except (QhullError, ValueError):
        hull = pts
    longest = float(max(np.linalg.norm(hull[:, None] - hull[None], axis=2).max(), 0.0))
    out = {"longest_mm": round(longest, 1), "area_mm2": round(area, 1), "enclosed": enclosed, "bed_c": bed}
    if "shrink" not in p:
        return out | {"level": "low", "lift_mm": 0.0, "why": [f"{name} is soft and hardly lifts"], "fix": "none needed"}
    tg = float(p["tg"]["value"])
    share = (tg - CHAMBER) / (tg - 25) if enclosed else 1.0
    lift = p["shrink"]["value"] / 100 * longest * max(share, 0.0)
    level = 0 if lift < WARP_MM[0] else (1 if lift <= WARP_MM[1] else 2)
    why = [f"{lift:.2f} mm corner lift from {p['shrink']['value']:g}% shrink over {longest:.0f} mm"]
    if longest and area / longest ** 2 < THIN:
        level, why = level + 1, why + ["a thin first layer for its length"]
    bed_range = p.get("bed", {}).get("value")
    if bed is not None and isinstance(bed_range, list) and bed < bed_range[0]:
        level, why = level + 1, why + [f"bed {bed:g} C, under the {bed_range[0]}-{bed_range[1]} C {name} wants"]
    enc = str(p.get("enclosure", {}).get("value", ""))
    if not enclosed and re.match(r"(needed|required)", enc):
        level, why = level + 1, why + [f"an open printer; {name} enclosure: {enc}"]
    if name == "PA":
        level, why = level + 1, why + ["nylon shrinks more as it crystallizes"]
    level = min(level, 2)
    fix = ["none needed", "add a 5 mm brim and round sharp corners on the bed",
           "brim, glue on the bed and an enclosure, or PETG or PLA, which shrink less"][level]
    return out | {"level": ["low", "medium", "high"][level], "lift_mm": round(lift, 2), "why": why, "fix": fix}


def _area(loops: list[np.ndarray], h: float = 0.2) -> float:
    """mm2 inside closed loops, even-odd (a loop inside a loop is a hole), on an h mm raster."""
    if not loops:
        return 0.0
    from skimage.draw import polygon

    lo = np.vstack(loops).min(0) - h
    n = np.ceil((np.vstack(loops).max(0) - lo) / h).astype(int) + 2
    inside = np.zeros(n, dtype=bool)
    for lp in loops:
        rr, cc = polygon((lp[:, 0] - lo[0]) / h, (lp[:, 1] - lo[1]) / h, shape=inside.shape)
        mask = np.zeros_like(inside)
        mask[rr, cc] = True
        inside ^= mask
    return float(inside.sum() * h * h)


def printer_enclosed(job) -> tuple[bool | None, str]:
    """`enclosed` from the printer profile stone.toml names (stone printer), for the job or the machine."""
    p = printers.current(job.root if job.exists() else None)
    if not p or "enclosed" not in p:
        return None, ""
    return bool(p["enclosed"]), f"printer profile {p.get('name', p.get('id', ''))}"


def report(job, items: list[str], out, plan_material: str = "") -> None:
    """stone heat where=car [load=...]: fill `out` (a cli.Out) with the verdict lines and one NEXT."""
    import trimesh

    from .job import read_json, write_json

    usage = "stone heat where=car"
    where, mat, enclosed, bed, rest, bad = None, "", None, None, [], []
    for it in items:
        k, _, v = it.partition("=")
        k = k.lower()
        try:
            if k == "where":
                where = service(v)
            elif k == "material":
                mat = reftool.strength_material(v) or ""
                if not mat:
                    raise ValueError
            elif k == "enclosed":
                enclosed = {"yes": True, "true": True, "no": False, "false": False}[v.lower()]
            elif k == "bed":
                bed = float(v.lower().rstrip("c"))
            else:
                rest.append(it)
        except (ValueError, KeyError):
            bad.append(f"{it}: " + {"where": "car, sun, dishwasher, outdoor, or a temperature like 70C",
                                    "material": "one of " + " ".join(reftool.STRENGTH),
                                    "enclosed": "yes or no", "bed": "the bed temperature in C"}.get(k, "not understood"))
    if where is None and not bad:
        bad.append("where: say where it lives: car, sun, dishwasher, outdoor, or a temperature like 70C")
    loaded = any(r.lower().startswith(("load=", "force=", "weight=")) for r in rest)
    bd = job.build_dir
    prev = read_json(bd / "strength.json") or {} if job.exists() else {}
    extra = [r for r in rest if not r.lower().endswith(".stl")]
    if not loaded and extra and not bad:
        bad.append(f"{' '.join(extra)}: load words need load=, like load=20N")
    if loaded:
        bad += strength.parse(extra)[2]
    if bad:
        out.fix("; ".join(bad))
        out.next = usage
        return
    temp, words, ref = where
    f = next((Path(r).expanduser().resolve() for r in rest if r.lower().endswith(".stl")), bd / "part.stl")
    if not f.is_file():
        out.fix("no built part yet; build first or name an STL file")
        out.next = "stone build"
        return
    name = mat or (prev.get("inputs", {}).get("material") if not loaded else "") or plan_material or "PLA"
    p = reftool.props(name)
    mesh = trimesh.load(f, force="mesh")
    hdt, tg = (float(p[k]["value"]) if k in p else None for k in ("hdt_045", "tg"))
    r = retention(name, temp)
    lines, flag, why, alt_ok = [], "fine", "", True
    if hdt is not None:
        margin = hdt - temp
        flag = "too hot" if margin <= 0 else ("close" if margin < CREEP_BAND else "fine")
        why = (f"past the {hdt:g} C where {name} softens" if margin <= 0 else
               f"within {CREEP_BAND:g} C of the {hdt:g} C where {name} softens" if margin < CREEP_BAND else "")
        lines.append(f"{words[0].upper() + words[1:]}: {temp:g} C. {name} softens at {hdt:g} C (HDT at 0.45 MPa), glass at {tg:g} C: "
                     + (f"{-margin:g} C past it, it will soften and bend." if margin <= 0 else f"{margin:g} C to spare."))
    else:
        v = p.get("vicat", {}).get("value")
        lines.append(f"{words[0].upper() + words[1:]}: {temp:g} C. {name} has no HDT; it softens toward {v} C (Vicat).")
    if r is not None:
        kept = f"{r:.0%}" if r >= 0.01 else "under 1%"
        lines.append(f"At {temp:g} C {name} keeps {'about ' if r >= 0.01 else ''}{kept} of its stiffness and strength.")
    # load: solve at the softened stiffness and strength; room numbers scale back (linear, force loads)
    case_words = rest if loaded else [f"{k}={v}" for k, v in prev.get("inputs", {}).get("words", {}).items()]
    hot = None
    if case_words and r:
        case, _, cbad = strength.parse([w for w in case_words if not w.lower().endswith(".stl")])
        if not cbad:
            base = strength.material(name)
            props = strength.Props(name, base.e_xy * r, base.e_z * r, base.s_xy * r, base.s_z * r, base.exponent, base.ids)
            st, hot = strength.solve(mesh, case, props, case.voxels)
        if hot is None:
            flag, why = "close" if flag == "fine" else flag, why or "the load could not be checked"
            lines.append(f"Load not checked: {'; '.join(cbad) or st.problem}.")
        else:
            cold = abs(hot.deflection) * r
            sf = strength.shown(hot.sf)
            sag = "it will sag" if sf < 1 else ("not sure, the loaded spot is too thin for this model" if hot.thin else
                                                "little margin" if sf < strength.FINE else "fine")
            alt, alt_ok = _better(name, temp, cold, base.e_xy, hot.limit)
            cap = max(1.0, 0.1 * st.lever)  # past a tenth of the lever a linear model only says "a lot"
            hot_d = f"{abs(hot.deflection):.2f} mm" if abs(hot.deflection) <= cap else f"more than {cap:.0f} mm"
            src = "" if loaded else " (the load from the last stone strength)"
            lines.append(f"Load {case.load:.0f} N{src}: deflection {cold:.2f} mm at room temperature -> {hot_d} at "
                         f"{temp:g} C, safety factor {sf:.1f}, {sag}.".replace("factor 0.0,", "factor under 0.1,") + (f" {alt}" if alt else ""))
            if hot.thin or sf < strength.FINE:
                flag = "too hot" if sf < 1 else ("close" if flag == "fine" else flag)
                if hdt is None or temp < hdt:
                    why = (f"the {case.load:.0f} N load leaves a safety factor of {sf:.1f} there (2 is fine)" if sf < strength.FINE else
                           f"the spot under the {case.load:.0f} N load is too thin for this model to judge")
    if hdt is not None and hdt - CREEP_BAND <= temp < hdt:
        lines.append(f"Creep: within {CREEP_BAND:g} C of its HDT a load held for days slowly bends it (rule of thumb).")
    alpha = float(p["cte"]["value"]) * 1e-6
    longest = float(np.max(mesh.bounds[1] - mesh.bounds[0]))
    grow = alpha * (temp - ROOM) * longest
    clamp = clamped_stress(name, alpha, ROOM, temp) if temp > ROOM else 0.0
    hot_s = float(p["tensile_xy"]["value"]) * (r if r is not None else 1.0)
    share = f", {clamp / hot_s:.0%} of its hot strength" if (r is None or r >= 0.1) else "; this soft it bends instead"
    lines.append(f"Expansion: it grows {grow:.2f} mm over its {longest:.0f} mm; held tight at both ends it pushes with "
                 f"{clamp:.1f} MPa{share}.")
    found, src = printer_enclosed(job)
    if enclosed is None:
        enclosed, src = (found, src) if found is not None else (False, "assumed open; say enclosed=yes")
    else:
        src = "enclosed= given"
    risk = warp(name, mesh, enclosed, bed)
    lines.append(f"Warp risk on the bed: {risk['level']} ({'; '.join(risk.get('why', []))}). Fix: {risk['fix']}.")
    write_json(bd / "heat.json" if job.exists() else f.parent / "heat.json", {
        "file": str(f), "where": words, "temp_c": temp, "temp_ref": ref, "material": name, "hdt_045_c": hdt, "tg_c": tg,
        "verdict": flag, "retention": r, "growth_mm": round(grow, 3), "clamped_stress_mpa": round(clamp, 2),
        "load": None if hot is None else {"words": case_words, "deflection_room_mm": round(abs(hot.deflection) * r, 3),
                                          "deflection_hot_mm": round(abs(hot.deflection), 3), "safety_factor_hot": round(hot.sf, 2)},
        "warp_risk": risk | {"enclosed_from": src}, "assumptions": ASSUMPTIONS})
    out.add(f"Part: {f.name}, {name}.", *lines)
    out.result = f"heat: {flag} at {temp:g} C in {name}"
    nxt = (job.status().get("next") or "stone status") if job.exists() else "none, the part takes the heat"
    alt = _best(temp)
    if flag == "fine":
        out.next = nxt
    else:
        out.next = (f"ask the person: {words} reaches {temp:g} C, {why}; "
                    + (f"print it in {alt}?" if alt and alt != name and alt_ok else "a cooler spot, or a stiffer part?"))


def _best(temp: float) -> str | None:
    """The material that clears temp by the creep band with the least to spare (the easiest of them to print),
    else the one that softens last."""
    ok = [(float(reftool.props(m)["hdt_045"]["value"]) - temp, m) for m in ("PETG", "ASA", "ABS", "PC", "PETG-CF")]
    ok = [(d, m) for d, m in ok if d >= CREEP_BAND]
    return min(ok)[1] if ok else (max((float(reftool.props(m)["hdt_045"]["value"]), m) for m in ("ASA", "PC"))[1])


def _better(name: str, temp: float, cold: float, e_room: float, limit: float) -> tuple[str, bool]:
    """A line for the material _best picks: its hot deflection, scaled by stiffness, and whether it is in the limit."""
    alt = _best(temp)
    r = retention(alt, temp) if alt and alt != name else None
    if not r:
        return "", True
    d = cold * e_room / (reftool.props(alt)["e_xy"]["value"] * r)
    return f"{alt}: {d:.2f} mm, {'fine' if d <= limit else 'too much as well'}.", d <= limit
