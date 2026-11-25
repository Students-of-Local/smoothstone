"""Parts a reference pack supplies: docs/REFERENCE_PARTS.md.

Each is planned in metres from the pack's origin and built at the print's scale.
"""

from __future__ import annotations

import math

import numpy as np

from .landmark_refs import LandmarkProblem

MAX_PARTS = 400
THIN = 1.2  # mm, the narrowest body a print holds
LEAST = .8  # mm, the narrowest a part held at both ends may ask for
CUT = .6  # mm, the narrowest gap
ROOFS = ("flat", "pyramidal", "gabled", "hipped", "dome", "onion", "round", "skillion")
PLANS = ("rect", "circle", "ngon", "ring")
ANY = ("kind", "id", "source", "guess", "copies")
FIELDS = {"prism": (*PLANS, "at", "turn", "from", "to", "roof", "roof_rise", "top_scale", "top_shift", "least"),
          "lathe": ("at", "profile", "least"), "beam": ("path", "size", "round", "least"),
          "opening": ("at", "turn", "width", "depth", "from", "to", "arch", "arch_rise", "outline")}


def _need(ok, what):
    if not ok:
        raise ValueError(what)


def _number(value, name, above=None):
    _need(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
          f"{name} must be a number")
    _need(above is None or value > above, f"{name} must be more than {above}")
    return float(value)


def _vector(value, name, count=2):
    _need(isinstance(value, (list, tuple)) and len(value) == count, f"{name} must be a list of {count} numbers")
    return np.array([_number(v, name) for v in value])


def _points(value, name, count, least):
    _need(isinstance(value, list) and least <= len(value) <= 400, f"{name} must list {least} to 400 points")
    return np.array([_vector(v, name, count) for v in value])


def _turned(degrees):
    a = math.radians(degrees)  # clockwise
    return np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])


def _plan(part):
    import manifold3d as m3
    from .landmark import _section

    given = [k for k in PLANS if k in part]
    _need(len(given) == 1, "give one plan: rect, circle, ngon or ring")
    kind, value = given[0], part[given[0]]
    if kind == "rect":
        size = _vector(value, "rect")
        _need((size > 0).all(), "rect must be more than 0")
        cs = m3.CrossSection.square(size.tolist(), True)
    elif kind == "circle":
        cs = m3.CrossSection.circle(_number(value, "circle", 0), 64)
    elif kind == "ngon":
        sides, radius = _vector(value, "ngon")
        _need(sides == int(sides) and 3 <= sides <= 64 and radius > 0, "ngon must be [3 to 64 sides, radius]")
        cs = m3.CrossSection.circle(float(radius), int(sides)).rotate(90 + 180 / sides)  # a flat side to the front
    else:
        cs = _section([_points(value, "ring", 2, 3).tolist()])
    _need(not cs.is_empty() and cs.area() > 1e-6, f"{kind} encloses no area")
    return cs


def _span(part):
    lo, hi = _number(part.get("from", 0), "from"), _number(part.get("to"), "to")
    _need(hi > lo, "to must be above from")
    return lo, hi


def _prism(part):
    cs, (lo, hi) = _plan(part), _span(part)
    roof, rise = part.get("roof", "flat"), _number(part.get("roof_rise", 0), "roof_rise")
    _need(roof in ROOFS, "roof must be one of " + ", ".join(ROOFS))
    _need(0 <= rise <= hi - lo, "roof_rise must be from 0 to the part's height")
    _need((roof == "flat") == (rise == 0), "a roof needs roof_rise, and a flat roof has none")
    scale = _number(part.get("top_scale", 1), "top_scale", 0)
    shift = _vector(part.get("top_shift", [0, 0]), "top_shift")
    _need(rise == 0 or part.get("least", THIN) == THIN, "a roof keeps its 1.6 mm tip, so a part with one takes no least")

    def build(floor, notes):
        from .landmark import _roof

        body, eave, foot = _wide(cs, floor), hi - rise, min(lo, hi - floor)  # thick enough, and the top stays
        x0, y0, x1, y1 = body.bounds()
        mid = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
        run = eave - foot
        solids, top = [], body
        if run > 1e-6:
            least = min(1., floor / max(1e-9, min(x1 - x0, y1 - y0)))  # the top prints too
            s = max(scale, least) if scale < 1 else scale
            walls = body.translate((-mid).tolist()).extrude(run, scale_top=[s, s])
            shear = np.array([[1, 0, shift[0] / run, mid[0]], [0, 1, shift[1] / run, mid[1]], [0, 0, 1, foot]])
            solids.append(walls.transform(shear.tolist()))
            top = body.translate((-mid).tolist()).scale([s, s]).translate((mid + shift).tolist())
        if rise:
            over = min(.02, rise / 4)
            mm = THIN / floor if floor else 1.  # roofs are lofted in print millimetres
            loft = _roof(top.scale([mm, mm]), {"roof_shape": roof, "tags": {"roof:direction": "0"} if roof == "skillion" else {}},
                         (eave - over) * mm, (rise + over) * mm, notes)
            solids.append(loft.scale([1 / mm] * 3))
        return solids
    return build, lo, hi, rise, roof


def _wide(cs, floor):
    """The plan, widened where a print would lose it."""
    import manifold3d as m3

    out = []
    for c in cs.decompose():
        if floor and c.offset(-floor / 2).is_empty():
            lo, hi = 0., floor
            for _ in range(12):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if c.offset(mid).offset(-floor / 2).is_empty() else (lo, mid)
            c = c.offset(hi)
        out.append(c)
    return m3.CrossSection.batch_boolean(out, m3.OpType.Add)


def _lathe(part):
    import manifold3d as m3

    profile = _points(part.get("profile"), "profile", 2, 2)
    z, r = profile.T
    _need((np.diff(z) > 0).all(), "profile must rise")
    _need((r >= 0).all() and r.max() > 0, "profile needs a radius above 0, and none below")

    def build(floor, notes):
        wide = np.maximum(r, floor / 2)
        foot = min(z[0], z[-1] - floor)
        ring = [[0, foot], [wide[0], foot], *np.c_[wide, z][int(foot == z[0]):].tolist(), [0, z[-1]]]
        return [m3.CrossSection([ring]).revolve(64)]
    return build, z[0], z[-1], 0, "flat"


def _beam(part):
    path = _points(part.get("path"), "path", 3, 2)
    size = part.get("size")
    each = isinstance(size, list) and bool(size) and isinstance(size[0], list)
    sizes = _points(size, "size", 2, 2) if each else np.tile(_vector(size, "size"), (len(path), 1))
    _need(len(sizes) == len(path), "size needs one [width, height], or one for each point of path")
    _need((sizes > 0).all(), "size must be more than 0")
    round_ = part.get("round", False)
    _need(isinstance(round_, bool), "round must be true or false")
    steps = np.diff(path, axis=0)
    runs = np.linalg.norm(steps, axis=1)
    _need((runs > 1e-6).all(), "path repeats a point")
    corners = ([(math.cos(a), math.sin(a)) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)] if round_
               else [(a, b) for a in (-1, 1) for b in (-1, 1)])

    def build(floor, notes):
        import manifold3d as m3

        half = np.maximum(sizes, floor) / 2
        frames = []
        for step, run in zip(steps, runs):
            along = step / run
            side = np.array([along[1], -along[0], 0.])
            width = np.linalg.norm(side)
            side = side / width if width > 1e-6 else np.array([1., 0, 0])
            frames.append((side, np.cross(side, along)))

        def end(frame, at):
            (side, up), (w, h) = frame, half[at]
            return [path[at] + side * a * w + up * b * h for a, b in corners]
        solids = []
        for i, frame in enumerate(frames):
            solids.append(m3.Manifold.hull_points(np.array(end(frame, i) + end(frame, i + 1))))
            if i:  # the elbow
                solids.append(m3.Manifold.hull_points(np.array(end(frames[i - 1], i) + end(frame, i))))
        return [s for s in solids if not s.is_empty()]
    return build, 0, 0, 0, "flat"  # its heights are its solid's


def _head(arch, w, rise):
    """The points of an arch's head over half its width, from the right springing to the left, and its rise."""
    least, usual = {"round": (0, w), "pointed": (w, w * math.sqrt(3)), "triangle": (0, w)}[arch]
    rise = usual if rise is None else rise
    _need(rise >= least, "a pointed arch rises at least half its width")
    if arch == "triangle":
        return [[w, 0], [0, rise], [-w, 0]], rise
    if arch == "round":
        return [[w * math.cos(a), rise * math.sin(a)] for a in np.linspace(0, math.pi, 25)], rise
    off = (rise ** 2 - w ** 2) / (2 * w)  # each side is an arc about a centre this far past the middle
    arc = [[(w + off) * math.cos(a) - off, (w + off) * math.sin(a)] for a in np.linspace(0, math.atan2(rise, off), 13)]
    return arc + [[-x, z] for x, z in arc[-2::-1]], rise


def _opening(part):
    import manifold3d as m3
    from .landmark import _section

    depth = _number(part.get("depth"), "depth", 0)
    if "outline" in part:
        extra = {"width", "from", "to", "arch", "arch_rise"} & set(part)
        _need(not extra, f"an outline takes no {', '.join(sorted(extra))}")
        ring = _points(part["outline"], "outline", 2, 3)
        lo, hi = ring[:, 1].min(), ring[:, 1].max()
    else:
        half = _number(part.get("width"), "width", 0) / 2
        lo, hi = _span(part)
        arch = part.get("arch", False)
        _need(isinstance(arch, bool) or arch in ("round", "pointed", "triangle"),
              "arch must be true, false, round, pointed or triangle")
        _need(arch or "arch_rise" not in part, "arch_rise needs an arch")
        top, rise = [[half, 0], [-half, 0]], 0
        if arch:
            top, rise = _head("round" if arch is True else arch, half,
                              _number(part["arch_rise"], "arch_rise", 0) if "arch_rise" in part else None)
        _need(hi - lo >= rise - 1e-9, f"the arch rises {rise:g} m, more than to - from")
        ring = np.array([[-half, lo], [half, lo]] + [[x, hi - rise + z] for x, z in top])
    cs = _section([ring.tolist()])
    _need(not cs.is_empty() and cs.area() > 1e-6, "an opening encloses no area")

    def build(floor, notes):
        deep = max(depth, floor)
        # x stays x, the profile's y is up, its depth is y
        return [cs.extrude(deep).transform([[1, 0, 0, 0], [0, 0, -1, deep / 2], [0, 1, 0, 0]])]
    return build, lo, hi, 0, "flat"


def _narrowest(part):
    """An opening's width: an outline's is that of the widest circle it holds."""
    from .landmark import _section

    if "outline" not in part:
        return part["width"]
    cs = _section([part["outline"]])
    lo, hi = 0., math.sqrt(cs.area())
    for _ in range(20):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if cs.offset(-mid).is_empty() else (mid, hi)
    return 2 * lo


KINDS = {"prism": _prism, "lathe": _lathe, "beam": _beam, "opening": _opening}


def _copies(spec):
    """Planar transforms, 2 x 3, one for each copy."""
    if spec is None:
        return [np.eye(2, 3)]
    _need(isinstance(spec, dict), "copies must be an object")
    keys = set(spec)
    if keys == {"mirror"}:
        signs = {"x": [(1, 1), (-1, 1)], "y": [(1, 1), (1, -1)], "xy": [(1, 1), (-1, 1), (1, -1), (-1, -1)]}
        _need(spec["mirror"] in signs, 'mirror must be "x", "y" or "xy"')
        return [np.array([[a, 0, 0], [0, b, 0]], float) for a, b in signs[spec["mirror"]]]
    _need(keys in ({"around", "count"}, {"row", "count"}), "copies is around and count, row and count, or mirror")
    count = _number(spec["count"], "count")
    _need(count == int(count) and 1 <= count <= MAX_PARTS, f"count must be 1 to {MAX_PARTS}")
    if "row" in spec:
        step = _vector(spec["row"], "row")
        return [np.c_[np.eye(2), step * k] for k in range(int(count))]
    centre = _vector(spec["around"], "around")
    turns = [_turned(360 * k / count) for k in range(int(count))]
    return [np.c_[R, centre - R @ centre] for R in turns]


def _place(solids, flat, scale=1.):
    """Planned metres to east, north and up, at a scale."""
    M = np.eye(3, 4)
    M[:2, :2], M[:2, 3] = flat[:, :2], flat[:, 2]
    return [s.transform((M * scale).tolist()) for s in solids]


def _world(lat, lon, axis, refs):
    shift = np.array([(lon - refs["longitude"]) * 111320 * math.cos(math.radians(refs["latitude"])),
                      (lat - refs["latitude"]) * 111320])
    return np.c_[_turned(axis), shift]


def plinth(pack, refs):
    """The base the pack asks for, in local east and north metres, or None for one that follows the plan."""
    fact = pack.get("parts", {})
    if "plinth" not in fact:
        return None
    try:
        spec = fact["plinth"]
        _need(isinstance(spec, dict), "it must be an object")
        unknown = set(spec) - {*PLANS, "at", "turn", "source", "guess"}
        _need(not unknown, f"it has no field {', '.join(sorted(unknown))}")
        guess, source = spec.get("guess"), spec.get("source", fact["source"])
        _need(guess is None or isinstance(guess, str) and guess.strip(), "guess must say how it was chosen")
        _need(isinstance(source, str) and source.startswith(("http://", "https://")), "source must be a URL")
        cs = _plan(spec)
        here = np.c_[_turned(_number(spec.get("turn", 0), "turn")), _vector(spec.get("at", [0, 0]), "at")]
        lat, lon = _vector(fact["origin"], "origin")
        world = _world(lat, lon, _number(fact.get("axis", 0), "axis"), refs)
        return cs.transform(here.tolist()).transform(world.tolist())
    except ValueError as exc:
        raise LandmarkProblem(f"Reference plinth: {exc}. See docs/REFERENCE_PARTS.md.") from exc


def read(pack, refs):
    """The pack's parts: (records, sections, openings). A record's `_build(scale, notes)` gives its solids."""
    import manifold3d as m3
    from .landmark import _fact

    fact = pack.get("parts")
    if fact is None:
        return [], [], []
    records, sections, openings, seen = [], [], [], set()
    try:
        unknown = set(fact) - {"source", "origin", "axis", "replace", "plinth", "value"}
        _need(not unknown, f"unknown field {', '.join(sorted(unknown))}")
        _need(fact.get("replace", "none") in ("none", "all") or isinstance(fact["replace"], list),
              'replace must be "none", "all" or a list of OSM ids')
        lat, lon = _vector(fact.get("origin"), "origin")
        _need(isinstance(fact.get("replace", ""), str) or all(type(i) is int for i in fact["replace"]), "replace lists OSM ids as integers")
        _need(math.dist((lat, lon), (refs["latitude"], refs["longitude"])) < .05,
              "origin must be [lat, lon] within 5 km of the landmark")
        axis = _number(fact.get("axis", 0), "axis")
        _need(isinstance(fact["value"], list) and fact["value"], "value must list the parts")
    except ValueError as exc:
        raise LandmarkProblem(f"Reference parts: {exc}. See docs/REFERENCE_PARTS.md.") from exc
    world = _world(lat, lon, axis, refs)
    for i, part in enumerate(fact["value"]):
        try:
            _need(isinstance(part, dict) and part.get("kind") in KINDS, "kind must be one of " + ", ".join(KINDS))
            kind = part["kind"]
            unknown = set(part) - {*ANY, *FIELDS[kind]}
            _need(not unknown, f"{kind} has no field {', '.join(sorted(unknown))}")
            guess, source = part.get("guess"), part.get("source", fact["source"])
            _need(guess is None or isinstance(guess, str) and guess.strip(), "guess must say how it was chosen")
            _need(isinstance(source, str) and source.startswith(("http://", "https://")), "source must be a URL")
            least = _number(part.get("least", THIN), "least")
            _need(LEAST <= least <= THIN, f"least must be {LEAST} to {THIN} mm")
            build, lo, hi, rise, roof = KINDS[kind](part)
            here = np.eye(2, 3)
            here[:, 2] = _vector(part.get("at", [0, 0]), "at")
            here[:, :2] = _turned(_number(part.get("turn", 0), "turn"))
            copies = _copies(part.get("copies"))
            width = _narrowest(part) if kind == "opening" else 0
            _need(len(records) + len(openings) + len(copies) <= MAX_PARTS, f"more than {MAX_PARTS} parts")
            outline = m3.Manifold.batch_boolean(build(0, []), m3.OpType.Add)
            if kind == "beam":
                lo, hi = outline.bounding_box()[2::3]
            for k, copy in enumerate(copies):
                flat = world @ np.r_[copy, [[0, 0, 1]]] @ np.r_[here, [[0, 0, 1]]]

                record = {}

                def make(scale, notes, flat=flat, build=build, plain=outline, record=record, least=least,
                         slim=np.min(part["size"]) if kind == "beam" else math.inf):
                    solids = build(least / scale, notes)
                    grown = m3.Manifold.batch_boolean(solids, m3.OpType.Add)
                    # a beam's thin end may widen inside the box of its thick one
                    if (np.abs(np.subtract(grown.bounding_box(), plain.bounding_box())).max() * scale > .01
                            or slim * scale < least - .01):
                        record["print_modifications"] = [f"Widened to {least:g} mm."]
                    return _place(solids, flat, scale)
                def hole(scale, floor=0., flat=flat, build=build):
                    return _place(build(floor, []), flat, scale)[0].translate([0, 0, 2]).trim_by_plane([0, 0, 1], 2.02)
                if kind == "opening":
                    openings.append((hole, width, source, guess))
                    continue
                name = f"{part.get('id', f'part-{i}')}" + (f"-{k + 1}" if len(copies) > 1 else "")
                _need(name not in seen, f"id {name} is used twice")
                seen.add(name)
                section = _place([outline], flat)[0].project()
                record.update({
                    "id": name, "type": "reference", "height": _fact(hi, source, guess is not None, guess),
                    "min_height": _fact(lo, source, guess is not None, guess),
                    "roof_height": _fact(rise, source, guess is not None, guess), "roof_shape": roof,
                    "spire": roof in ("pyramidal", "onion") and rise > math.sqrt(section.area()), "source": source,
                    "tags": {}, "footprint": [ring.tolist() for ring in section.to_polygons()], "_build": make})
                records.append(record)
                sections.append(section)
        except ValueError as exc:
            raise LandmarkProblem(f"Reference parts[{i}]: {exc}. See docs/REFERENCE_PARTS.md.") from exc
    if not records:
        raise LandmarkProblem("Reference parts: an opening needs a part to open. See docs/REFERENCE_PARTS.md.")
    return records, sections, openings


def cut(man, openings, scale, notes):
    """Cut the pack's openings, down to the base."""
    for hole, width, _, guess in openings:
        if guess:
            notes.append(f"Guessed an opening: {guess}.")
        if width * scale < CUT:
            notes.append(f"Omitted detail below the print floor: an opening {width:g} m wide.")
            continue
        solid = hole(scale)
        if (solid - man).volume() < 1e-6 * solid.volume():  # the wall was widened past it: a pocket no light gets through
            solid = hole(scale, 1.1 * THIN / scale)
        man = man - solid
    return man


def lean(man, fact, notes):
    """Tip everything above the base by the sourced angle."""
    try:
        degrees, way = _vector(fact["value"], "lean")
        _need(0 < degrees <= 15, "lean must be up to 15 degrees")
    except ValueError as exc:
        raise LandmarkProblem(f"Reference lean: {exc}. See docs/REFERENCE_PARTS.md.") from exc
    run = math.tan(math.radians(degrees))
    step = np.array([math.sin(math.radians(way)), math.cos(math.radians(way))]) * run
    notes.append(f"Leaned {degrees:g} degrees toward bearing {way:g}, above a level base.")

    def tip(v):
        z = max(0., v[2] - 2)
        return [v[0] + step[0] * z, v[1] + step[1] * z, v[2]]
    return man.warp(tip)
