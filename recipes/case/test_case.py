"""Self-check for the `case` recipe: build it with OpenSCAD and run smoothstone's print checks.

Run:  uv run python recipes/case/test_case.py
Fails loudly if the case stops being one watertight body, sits on the bed, keeps its
walls, or comes out the size asked for. Needs OpenSCAD; nothing is written outside a temp dir.
Also checks the snap cover: it builds as one part, its rim fits the opening at the default
clearance, and each hook's catch sits inside the wall it catches on.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from smoothstone import config, recipes, scad  # noqa: E402
from smoothstone.check import check_stl, passed  # noqa: E402


def build(params: dict, td: str, name: str = "case"):
    binary = config.find_openscad()
    assert binary, "OpenSCAD not found (put it on PATH or set STONE_OPENSCAD)"
    r = recipes._load_one(HERE)
    assert r is not None, "could not load recipe"
    stl = Path(td) / f"{name}.stl"
    res = scad.build_stl(binary, r, r.merged(params), stl)
    assert res.ok, f"{name}: build failed: {res.error}\n{res.log[-800:]}"
    return stl, r, r.merged(params)


def run(params: dict, label: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        stl, r, merged = build(params, td, label)
        results = check_stl(stl, recipe=r, params=merged)
        bad = [x for x in results if not x.ok]
        for x in results:
            print(f"{label:8s} {x.name:12s} {'PASS' if x.ok else 'FIX '} {x.detail}")
        return not bad


def snap_fit() -> bool:
    """The cover is one part and it actually latches: seated it is clear of the body, it presses on
    without dragging, and it will not come off unless each catch climbs its ramp. Runs the checks on
    the assembled pair."""
    import numpy as np
    import trimesh

    with tempfile.TemporaryDirectory() as td:
        cstl, r, m = build({"part": "cover"}, td, "cover")
        bstl, _, _ = build({"part": "body"}, td, "body")
        cover, body = trimesh.load(cstl), trimesh.load(bstl)
        nb = len(cover.split(only_watertight=False))
        print(f"cover    bodies       {'PASS' if nb == 1 else 'FIX '} {nb} bodies (need 1)")
        ok = nb == 1

        w, d, h, wall, clr, ct = m["w"], m["d"], m["h"], m["wall"], m["clr"], m["cover_t"]
        hook_w = m.get("hook_w", 6)
        ext = cover.extents
        fits = abs(ext[0] - w) <= 0.6 and abs(ext[1] - d) <= 0.6
        print(f"cover    fits         {'PASS' if fits else 'FIX '} {ext[0]:.1f} x {ext[1]:.1f} mm (plate {w:.1f} x {d:.1f})")
        reaches = abs(ext[2] - h) <= 0.6
        print(f"cover    hooks        {'PASS' if reaches else 'FIX '} {ext[2]:.1f} mm tall (hooks reach h = {h:.1f} mm)")
        ok = ok and fits and reaches

        # assembled the way tools/case_still.py places it: flipped about X, plate on the front rim
        T = np.eye(4); T[1, 1] = -1; T[2, 2] = -1; T[2, 3] = h + ct
        cov = cover.copy(); cov.apply_transform(T)
        inner_w = w - 2 * wall
        hook_y = (d - 2 * wall) / 2 - clr - 6 / 2 - 1.5

        def vol(lift):
            c = cov.copy(); c.apply_translation([0, 0, lift])
            i = body.intersection(c)
            return 0.0 if i.is_empty else float(i.volume)

        # (d) seated: no interference at rest
        seat = vol(0.0)
        print(f"snap     seated       {'PASS' if seat < 0.5 else 'FIX '} {seat:.2f} mm3 body/cover overlap (need < 0.5)")
        ok = ok and seat < 0.5

        # the catch holds: lifting the cover off the rim wedges the catch into the solid wall above it,
        # and the resistance grows with the lift, as a catch climbing its ledge does
        pull = [vol(l) for l in (0.5, 1.0, 1.5)]
        grows = pull[0] > 0.1 and pull[0] < pull[1] < pull[2]
        print(f"snap     holds        {'PASS' if grows else 'FIX '} overlap {pull[0]:.2f} -> {pull[1]:.2f} -> "
              f"{pull[2]:.2f} mm3 as the cover is lifted 0.5/1.0/1.5 mm off (need to grow from > 0.1)")
        ok = ok and grows

        # (a) solid wall directly above each catch's flat face, within 0.5 mm
        v = cov.vertices
        for y in (-hook_y, hook_y):
            near = v[(np.abs(v[:, 1] - y) < 3.01) & (v[:, 0] < -inner_w / 2) & (v[:, 2] < h - 0.01)]
            xmin = float(near[:, 0].min())
            zc = near[near[:, 0] <= xmin + 1e-3][:, 2]
            hits = []
            for x in np.linspace(xmin + 0.05, -inner_w / 2 - 0.05, 6):
                locs, _, _ = body.ray.intersects_location(
                    np.array([[x, y, zc.max() + 0.01]]), np.array([[0, 0, 1.0]]))
                hits.append(min((float(l[2]) for l in locs), default=None))
            ledge = bool(hits) and all(q is not None for q in hits) and min(hits) - zc.max() <= 0.5
            print(f"snap     ledge        {'PASS' if ledge else 'FIX '} y={y:+.2f}: ledge at z "
                  f"{min(hits) if ledge else hits} over catch top {zc.max():.2f} (need solid, within 0.5 mm)")
            ok = ok and ledge

        # (b) each arm is a free cantilever: in the printed part there is a slot either side of it,
        # and the arm itself stands clear of the body
        za = 0.5 * h
        for y in (-hook_y, hook_y):
            on = [x for x in np.arange(-w / 2, -inner_w / 2 + 0.1, 0.1)
                  if len(cover.ray.intersects_location(np.array([[x, y, za]]), np.array([[0, 0, 1.0]]))[0])]
            slots = [s for s in (y - hook_w / 2 - 0.25, y + hook_w / 2 + 0.25)
                     if not len(cover.ray.intersects_location(
                         np.array([[-(inner_w - 2 * clr) / 2 - wall / 2, s, za]]),
                         np.array([[0, 0, 1.0]]))[0])]
            free = bool(on) and len(slots) == 2
            print(f"snap     arm gap      {'PASS' if free else 'FIX '} y={y:+.2f}: arm "
                  f"{min(on) if on else 0:.2f}..{max(on) if on else 0:.2f} at z {za:.2f}, "
                  f"{len(slots)}/2 slots either side")
            ok = ok and free

        # (c) no ray through the back plate at the pocket
        back = []
        for y in (-hook_y, hook_y):
            locs, _, _ = body.ray.intersects_location(
                np.array([[-inner_w / 2 - 0.5, y, -1.0]]), np.array([[0, 0, 1.0]]))
            back.append(len(locs) > 0)
        print(f"snap     back         {'PASS' if all(back) else 'FIX '} back plate solid under both pockets")

        # (e) the pockets stop at the wall's inner face, so the screw posts beside them stay whole: a ray
        # down the post's outer side, 0.5 mm in, enters at its top and leaves at the back, nothing between
        post = True
        if m["post_d"] > 0:
            px = -(inner_w / 2 - 1.0)  # posts sit 0.5 mm off the wall
            py = (d - 2 * wall) / 2 - m["post_d"] / 2 - 0.5
            post = all(len(body.ray.intersects_location(np.array([[px, y, h + 1]]), np.array([[0, 0, -1.0]]))[0]) == 2
                       for y in (-py, py))
        print(f"snap     posts        {'PASS' if post else 'FIX '} screw posts beside the pockets are whole")
        return ok and all(back) and post


if __name__ == "__main__":
    good = run({}, "default")
    bare = run({"win_w": 0, "win_h": 0, "port_w": 0, "post_d": 0, "close": "none"}, "bare")
    small = run({"w": 60, "d": 40, "h": 30, "win_w": 30, "win_z": 2, "win_h": 10, "port_h": 6}, "small")
    snap = snap_fit()
    allpass = good and bare and small and snap
    print(f"\nALL PASS: {allpass}")
    sys.exit(0 if allpass else 1)