"""stone heat: will the part keep its shape where it lives, and will it warp on the bed.

Service temperatures, stiffness retention curves, HDT, Tg, CTE and shrink come from
recipes/lib/refs/materials.json. With a load, the part is solved at room temperature (stone
strength's model) and scaled to the softened stiffness and strength. Modeling choices are marked "assumption".
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import numpy as np

from . import printers
from . import refs as reftool
from . import strength

ROOM = 23.0  # C, the temperature the maker sheets test at (ISO 291 standard atmosphere 23/50)
CREEP_BAND = 20.0  # C below HDT where a lasting load creeps (assumption, refs <m>.creep)
SPARE = 5.0  # C below HDT that is still close with no load (assumption: the spot runs hotter some days)
CHAMBER = 40.0  # C, air in a closed printer without a heater (assumption)
WARP_MM = (0.6, 1.2)  # corner lift, mm: under the first is low, over the second high (assumption)
THIN = 0.05  # first-layer area over longest extent squared: under this the corners have little to hold (assumption)
WHERE = {"car": "service.car", "sun": "service.sun", "dishwasher": "service.dishwasher", "outdoor": "service.outdoor"}
WORDS = {"car": "a car dashboard in summer sun", "sun": "dark surfaces in summer sun", "dishwasher": "a dishwasher",
         "outdoor": "hot summer shade"}
HELP = {"where": "car, sun, dishwasher, outdoor, or a temperature like 70C", "material": "one of " + " ".join(reftool.STRENGTH),
        "enclosed": "yes or no", "bed": "the bed temperature in C"}
ASSUMPTIONS = [
    "No hot strength is sourced for printed parts: it falls with stiffness, or in a line from room temperature to nothing at "
    "the glass temperature, whichever is lower (nylon, which has crystals, with stiffness only).",
    "Between sourced points the stiffness ratio is linear in temperature and never rises (a DMA bump is not credited).",
    f"A lasting load creeps within {CREEP_BAND:g} C of the HDT at 0.45 MPa; a part with no load is close within {SPARE:g} C.",
    "Another plastic under the load keeps this part's stress; its deflection scales with stiffness.",
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


def strength_left(name: str, temp: float) -> float | None:
    """Share of room-temperature strength kept at temp (assumption, see ASSUMPTIONS); None where no curve is sourced."""
    r = retention(name, temp)
    if r is None or name == "PA":
        return r
    line = 1 - max(0.0, temp - ROOM) / (float(reftool.props(name)["tg"]["value"]) - ROOM)
    return max(0.0, min(r, line))


def softened(name: str, temp: float) -> strength.Props:
    b, r, k = strength.material(name), retention(name, temp), strength_left(name, temp)
    return strength.Props(name, b.e_xy * r, b.e_z * r, b.s_xy * k, b.s_z * k, b.exponent, b.ids)


def clamped_stress(name: str, alpha: float, t0: float, t1: float) -> float:
    """MPa in a bar held at both ends from t0 to t1: the integral of E(T) alpha dT (alpha in 1/K)."""
    e = reftool.props(name)["e_xy"]["value"]
    ts = np.linspace(t0, t1, 64)
    es = np.array([e * (1.0 if (r := retention(name, t)) is None else r) for t in ts])
    return float(np.sum((es[1:] + es[:-1]) / 2 * np.diff(ts)) * alpha)


def warp(name: str, mesh, enclosed: bool, bed: float | None) -> dict:
    """Corner lift risk of the worst first-layer piece: shrink x its longest extent, raised for a thin contact,
    a cold bed, an open printer for a material that wants an enclosure, and nylon's crystals."""
    p = reftool.props(name)
    sec = mesh.section(plane_origin=[0, 0, mesh.bounds[0][2] + 0.1], plane_normal=[0, 0, 1])
    pieces = _pieces([d[:, :2] for d in sec.discrete] if sec is not None else [])
    longest, area = max(pieces)
    out = {"longest_mm": round(longest, 1), "area_mm2": round(area, 1), "enclosed": enclosed, "bed_c": bed}
    if "shrink" not in p:
        return out | {"level": "low", "lift_mm": 0.0, "why": [f"{name} is soft and hardly lifts"], "fix": "none needed"}
    tg = float(p["tg"]["value"])
    share = (tg - CHAMBER) / (tg - 25) if enclosed else 1.0
    shrink = p["shrink"]["value"]
    best = (-1,)
    for longest, area in pieces:
        lift = shrink / 100 * longest * max(share, 0.0)
        level = 0 if lift < WARP_MM[0] else (1 if lift <= WARP_MM[1] else 2)
        thin = bool(longest) and area / longest ** 2 < THIN
        best = max(best, (level + thin, lift, longest, area, thin))
    level, lift, longest, area, thin = best
    out |= {"longest_mm": round(longest, 1), "area_mm2": round(area, 1)}
    why = [f"{lift:.2f} mm corner lift from {shrink:g}% shrink over {longest:.0f} mm"]
    if thin:
        why.append("a thin first layer for its length")
    bed_range = p.get("bed", {}).get("value")
    cold = bed is not None and isinstance(bed_range, list) and bed < bed_range[0]
    if cold:
        level, why = level + 1, why + [f"bed {bed:g} C, under the {bed_range[0]}-{bed_range[1]} C {name} wants"]
    enc = str(p.get("enclosure", {}).get("value", ""))
    if not enclosed and re.match(r"(needed|required)", enc):
        level, why = level + 1, why + [f"an open printer; {name} enclosure: {enc}"]
    if name == "PA":
        level, why = level + 1, why + ["nylon shrinks more as it crystallizes"]
    level = min(level, 2)
    fix = ["none needed", "add a 5 mm brim and round sharp corners on the bed",
           "brim and glue on the bed" + ("" if enclosed else ", and an enclosure")][level]
    if cold:
        fix = f"bed at {bed_range[0]}-{bed_range[1]} C" + ("" if level == 0 else f", and {fix}")
    return out | {"level": ["low", "medium", "high"][level], "lift_mm": round(lift, 2), "why": why, "fix": fix}


def _pieces(loops: list[np.ndarray], h: float = 0.2) -> list[tuple[float, float]]:
    """(longest extent mm, area mm2) of each separate piece inside closed loops, even-odd (a loop inside a loop
    is a hole), on an h mm raster."""
    if not loops:
        return [(0.0, 0.0)]
    from scipy.spatial import ConvexHull, QhullError
    from skimage.draw import polygon
    from skimage.measure import label

    lo = np.vstack(loops).min(0) - h
    n = np.ceil((np.vstack(loops).max(0) - lo) / h).astype(int) + 2
    inside = np.zeros(n, dtype=bool)
    for lp in loops:
        rr, cc = polygon((lp[:, 0] - lo[0]) / h, (lp[:, 1] - lo[1]) / h, shape=inside.shape)
        mask = np.zeros_like(inside)
        mask[rr, cc] = True
        inside ^= mask
    lab, out = label(inside, return_num=True, connectivity=2)[0], []
    for k in range(1, int(lab.max()) + 1):
        pts = np.argwhere(lab == k) * h
        try:
            hull = pts[ConvexHull(pts).vertices]
        except (QhullError, ValueError):
            hull = np.array([pts.min(0), pts.max(0)])
        out.append((float(np.linalg.norm(hull[:, None] - hull[None], axis=2).max()) + h, len(pts) * h * h))
    return out or [(0.0, 0.0)]


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
            bad.append(f"{it}: {HELP[k]}")
    if where is None and not any(b.startswith("where") for b in bad):
        bad.append(f"where: say where it lives: {HELP['where']}")
    named = next((r for r in rest if r.lower().endswith(".stl")), None)
    extra = [r for r in rest if r != named]
    if extra:
        told = any(e.partition("=")[0].lower() in strength.HELP for e in extra)  # else a typo, not a load
        bad += [b for b in strength.parse(extra)[2] if told or not b.startswith("load:")]
    need = dict.fromkeys(k for k in (re.match(r"\w*", b)[0].lower() for b in bad) if k in HELP | strength.HELP)

    def again(*ask: str, words: list[str] = (), file: str | None = named) -> str:
        """This command with these words left for whoever fills them in; every other known word stays as typed."""
        known = [i for i in [*items, *words] if "=" in i and i.partition("=")[0].lower() in {*HELP, *strength.HELP} - {*ask}]
        kept = ([shlex.quote(file) if file == named else file] if file else []) + [shlex.quote(i) for i in known]
        return " ".join(["stone heat", *kept, *(f"{k}=<{(HELP | strength.HELP)[k]}>" for k in ask)])

    if bad:
        out.fix("; ".join(bad))
        q = "where does the part live?" if "where" in need else f"what is right for {', '.join(need)}?" if need else ""
        out.next = (f"ask the person: {q} Then: " if q else "") + again(*need)
        return
    temp, words, ref = where
    f = Path(named).expanduser().resolve() if named else job.build_dir / "part.stl"
    if not f.is_file():
        out.fix(f"no file at {f}" if named else "no built part yet; build first or name an STL file")
        out.next = f"ask the person: where is the STL? Then: {again(file='<the STL file>')}" if named else "stone build"
        return
    own = job.exists() and f.resolve() == (job.build_dir / "part.stl").resolve()  # the job's part, not another file
    pick = reftool.strength_material(plan_material) if own else ""
    if own and plan_material and not pick and not mat:
        out.fix(f"no heat data for {plan_material}, the job's filament")
        out.next = f"ask the person: which of these is closest to {plan_material}? Then: {again('material')}"
        return
    bd = job.build_dir if own else f.parent
    prev = read_json(bd / "strength.json") or {}
    prev = prev.get("inputs", {}) if prev.get("file") == str(f) else {}  # the last load on this very part
    name = mat or pick or (prev.get("material") if not extra else "") or "PLA"
    p = reftool.props(name)
    mesh = trimesh.load(f, force="mesh")
    hdt, tg = (float(p[k]["value"]) if k in p else None for k in ("hdt_045", "tg"))
    soft, test = (hdt, "HDT at 0.45 MPa") if hdt is not None else (float(p["vicat"]["value"]), "Vicat")
    keep = retention(name, temp), strength_left(name, temp)
    case_words = extra or [f"{k}={v}" for k, v in prev.get("words", {}).items()]
    band = CREEP_BAND if case_words else SPARE
    margin = soft - temp
    flag = "too hot" if margin <= 0 else ("close" if margin < band else "fine")
    why = (f"past the {soft:g} C where {name} softens" if margin <= 0 else
           f"within {band:g} C of the {soft:g} C where {name} softens" if margin < band else "")
    lines = [f"{words[0].upper() + words[1:]}: {temp:g} C. {name} softens at {soft:g} C ({test})"
             + (f", glass at {tg:g} C: " if tg is not None else ": ")
             + (f"{-margin:g} C past it, it will soften and bend." if margin <= 0 else f"{margin:g} C to spare.")]
    if keep[0] is not None:
        said = [f"{k:.0%}" if k >= 0.01 else "under 1%" for k in keep]
        lines.append(f"At {temp:g} C {name} keeps about {said[0]} of its stiffness; stone counts on {said[1]} of its strength.")
    found, src = printer_enclosed(job)
    if enclosed is None:
        enclosed, src = (found, src) if found is not None else (False, "assumed open; say enclosed=yes")
    else:
        src = "enclosed= given"
    res = st = load = None
    cure = plain = _cure(name, temp)  # a plastic that takes the heat
    redo = weak = ""  # a load that has to be told another way; a part too weak even cold
    if case_words:
        case, given = strength.parse(case_words)[0], [] if extra else [w for w in case_words if not w.startswith("material=")]
        problem = ""
        if not mesh.is_watertight:
            problem, redo = f"{f.name} is not a closed shape", f"is there a closed STL of it? Then: {again(words=given, file='<the STL file>')}"
        elif keep[0] is None:
            problem, redo = f"no softening curve for {name}", f"which plastic instead? Then: {again('material', words=given)}"
        if not problem:
            st, res = strength.solve(mesh, case, strength.material(name), case.voxels)  # at room temperature; the rest scales
            if res and res.thin and not case.voxels:
                st, res = strength.solve(mesh, case, strength.material(name), strength.REFINE)
            problem = st.problem if res is None else ""
        if res is None:
            flag = "close" if flag == "fine" else flag
            why = why or f"the load could not be checked ({problem})"
            cure = None
            if st is not None:
                redo = (f"what holds the part still ({strength.HELP['fixed']}), and where does the load go? "
                        f"Then: {again('at', 'fixed', words=given)}")
            lines.append(f"Load not checked: {problem}.")
        else:
            cold, (sf, mode) = abs(res.deflection), _moved(res, name, name, temp)
            hot, room = cold / max(keep[0], 1e-9), _moved(res, name, name, ROOM)[0]
            how = ("it will bend too far" if mode == "sag" else "it will fail") if sf < 1 else (
                "not sure, part of it is too thin for this model" if res.thin else
                ("it bends close to its limit" if mode == "sag" else "little margin") if sf < strength.FINE else "fine")
            cap = max(1.0, 0.1 * st.lever)  # past a tenth of the lever a linear model only says "a lot"
            last = "" if extra else " (the load from the last stone strength)"
            lines.append(f"Load {case.load:g} N{last}: deflection {cold:.2f} mm at room temperature -> "
                         + (f"{hot:.2f} mm" if hot <= cap else f"more than {cap:.0f} mm") + f" at {temp:g} C (limit {res.limit:.1f} mm), "
                         + f"safety factor {room:.1f} -> " + (f"{sf:.1f}" if sf >= 0.1 else "under 0.1") + f", {how}.")
            load = {"words": case_words, "deflection_room_mm": round(cold, 3), "deflection_hot_mm": round(hot, 3),
                    "safety_factor_room": room, "safety_factor_hot": sf, "fails_by": mode}
            cure = None if res.thin else _cure(name, temp, res)
            if res.thin or sf < strength.FINE:
                if margin > 0:
                    if room < strength.FINE:
                        weak = f", {room:.1f} even at room temperature"
                    flag = ("too weak" if room < 1 else "too hot") if sf < 1 else "close"
                    why = (f"the {case.load:g} N load leaves a safety factor of {sf:.1f} there{weak} ({strength.FINE:g} is fine)"
                           if sf < strength.FINE else f"part of it is too thin for this model to judge the {case.load:g} N load")
            if flag != "fine" and cure:
                lines.append(f"{cure} there: safety factor {_moved(res, name, cure, temp)[0]:.1f}, fine.")
        if 0 < margin < CREEP_BAND:
            lines.append(f"Creep: within {CREEP_BAND:g} C of its {test.split()[0]} a load held for days slowly bends it (rule of thumb).")
    alpha = float(p["cte"]["value"]) * 1e-6
    longest = float(np.max(mesh.bounds[1] - mesh.bounds[0]))
    grow = alpha * (temp - ROOM) * longest
    clamp, k = None if keep[1] is None else abs(clamped_stress(name, alpha, ROOM, temp)), keep[1]  # no curve, no stress
    held = "" if k is None else (f"; held tight at both ends it {'pushes' if grow >= 0 else 'pulls'} with {clamp:.1f} MPa" + (
        f", {clamp / (float(p['tensile_xy']['value']) * k):.0%} of its strength there" if k >= 0.1 else "; this soft it bends instead"))
    lines.append(f"Expansion: it {'grows' if grow >= 0 else 'shrinks'} {abs(grow):.2f} mm over its {longest:.0f} mm{held}.")
    risk = warp(name, mesh, enclosed, bed)
    lines.append(f"Warp risk on the bed: {risk['level']} ({'; '.join(risk['why'])}). Fix: {risk['fix']}.")
    write_json(bd / "heat.json", {
        "file": str(f), "where": words, "temp_c": temp, "temp_ref": ref, "material": name, "softens_c": soft, "softens_test": test,
        "tg_c": tg, "verdict": flag, "retention": keep[0], "strength_left": keep[1], "growth_mm": round(grow, 3),
        "clamped_stress_mpa": clamp and round(clamp, 2), "cure": cure, "load": load,
        "warp_risk": risk | {"enclosed_from": src}, "assumptions": ASSUMPTIONS})
    out.add(f"Part: {f.name}, {name}.", *lines)
    out.result = f"heat: {flag} at {temp:g} C in {name}"
    nxt = (job.status().get("next") or "stone status") if own else "none, the part takes the heat"
    if flag != "fine":
        if cure:
            new = warp(cure, mesh, enclosed, None)
            ask = f"print it in {cure}?" + (f" It is likely to warp: {new['fix']}." if new["level"] == "high" else "")
        elif margin <= 0:  # no shape of this plastic holds there
            ask = "a cooler spot" + (f", or a part in {plain} strong enough for the load (not checked)" if plain else "") + "?"
        else:
            ask = redo or ("a stiffer part, or less load?" if weak else "a cooler spot, or a stiffer part?" if case_words else "a cooler spot?")
        out.next = f"ask the person: {words} reaches {temp:g} C, {why}; {ask}"
    elif risk["level"] == "high":
        out.next = f"ask the person: it is likely to warp on the bed ({risk['why'][0]}); can you print it with {risk['fix']}? If so: {nxt}"
    else:
        out.next = nxt


def _moved(res, name: str, alt: str, temp: float) -> tuple[float, str]:
    """(safety factor, what gives first) of a part solved in name at room temperature, in alt at temp: the same
    stress, that plastic's strength and stiffness there (what stone strength's material advice does)."""
    a, b = softened(alt, temp), strength.material(name)
    s, e = res.stress, min(a.e_xy / b.e_xy, a.e_z / b.e_z)
    factors = {"along": a.s_xy / max(s["peak_mpa"], 1e-9), "layers": a.s_z / max(s["across_layers_mpa"], 1e-9),
               "sag": res.limit * e / max(abs(res.deflection), 1e-12), "buckle": res.buckle * e}
    mode = min(factors, key=factors.get)
    return strength.shown(factors[mode]), mode


def _cure(name: str, temp: float, res=None) -> str | None:
    """The plastic that clears temp by the creep band with the least to spare (the easiest of them to print) and,
    with a solved load, holds it there; None when none does."""
    ok = []
    for m in ("PETG", "ASA", "ABS", "PC", "PETG-CF"):
        spare = float(reftool.props(m)["hdt_045"]["value"]) - temp
        if m != name and spare >= CREEP_BAND and (res is None or _moved(res, name, m, temp)[0] >= strength.FINE):
            ok.append((spare, m))
    return min(ok)[1] if ok else None
