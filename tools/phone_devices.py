"""Write recipes/phone_case/devices.scad and the dims in recipe.json from devices.json.

    uv run python tools/phone_devices.py          # write
    uv run python tools/phone_devices.py --check  # exit 1 if the written files are stale

devices.json keeps Apple's numbers as the drawings give them (mm from an edge, back-view
camera positions). This script moves them into the case's frame: origin at the phone's center,
+X toward the side button, +Y toward the top, z measured from the phone's back. The corner is
a Catmull-Rom curve through Apple's Detail A points.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "recipes" / "phone_case"
SRC = DIR / "devices.json"
SCAD = DIR / "devices.scad"
RECIPE = DIR / "recipe.json"
ORDER = ["iphone_17", "iphone_17_pro", "iphone_17_pro_max", "iphone_air"]
STEPS = 10  # curve points per Detail A segment


def v(node):
    return node["v"]


def catmull_rom(pts: list[list[float]], steps: int) -> list[tuple[float, float]]:
    """Centripetal-free uniform Catmull-Rom through pts, with the straight sides as end tangents."""
    p = [(pts[0][0], pts[0][1] + 6.0)] + [tuple(q) for q in pts] + [(pts[-1][0] + 6.0, pts[-1][1])]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                       + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3)
                for k in (0, 1)))
    out.append(tuple(pts[-1]))
    return out


def convex_hull(pts):
    """Counterclockwise convex hull (monotone chain)."""
    pts = sorted(set(pts))
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def outline(W: float, H: float, corner: list[list[float]]) -> list[tuple[float, float]]:
    """The plan outline, counterclockwise, centered on the origin. The spline overshoots the
    straight sides by up to 0.035 mm next to the tangent points; clamping to the sides and taking
    the convex hull keeps the outline inside W x H and convex, so hull() in the recipe is exact."""
    c = [(max(a, 0.0), max(b, 0.0)) for a, b in catmull_rom(corner, STEPS)]
    def quad(sx, sy, pts):
        return [(round(sx * (W / 2 - a), 4), round(sy * (H / 2 - b), 4)) for a, b in pts]
    return convex_hull(quad(1, 1, c) + quad(-1, 1, c) + quad(-1, -1, c) + quad(1, -1, c))


def diagonal_radius(corner) -> float:
    c = catmull_rom(corner, 200)
    a, b = min(c, key=lambda q: abs(q[0] - q[1]))
    return (a + b) / 2 / (1 - math.cos(math.radians(45)))


def phone_rows(d: dict) -> dict:
    W, H, T = v(d["body"]["width"]), v(d["body"]["height"]), v(d["body"]["depth"])
    corner = v(d["corner"]["points"])
    front, back = v(d["edge"]["front"]), v(d["edge"]["back"])
    # The lip may start turning inward this far above mid-thickness and still clear the front edge
    # at 45 degrees: the highest point of z - x on the front profile, plus 0.15.
    lip_z = max(z - x for x, z in front) + 0.15
    # The floor-to-wall chamfer may be this big and stay clear of the back edge.
    floor_f = min(1.0, min(x + (z + T / 2) for x, z in back) - 0.1)
    b = d["buttons"]
    def zc(node):
        return v(node["z_from_back"])
    buttons = []
    for name in ("action", "volume_up", "volume_down", "side"):
        n = b[name]
        buttons.append([-1 if n["side"] == "left" else 1, round(H / 2 - v(n["center_from_top"]), 3),
                        v(n["length"]), v(n["width"]), zc(n), v(n["protrusion"])])
    cc, ck = b["camera_control"], d["camera_control_keepout"]
    camera_control = [round(H / 2 - v(cc["center_from_top"]), 3), v(cc["length"]), v(cc["width"]), zc(cc),
                      v(ck["length"]), v(ck["half_height"]), v(ck["corner_r"]),
                      round(math.tan(math.radians(v(ck["flare_deg"]))), 4)]
    u = d["usb_c"]
    # Where the drawing does not say which face a height is from (iPhone Air), cover both readings.
    zu = zc(u)
    either = "either face" in u["z_from_back"].get("how", "")
    amb = round(abs(T - 2 * zu) / 2, 3) if either else 0
    zmid = round(T / 2, 3) if either else zu
    usb = [round(v(u["center_x"]) - W / 2, 3), zmid, amb, v(u["keepout_width"]), v(u["keepout_height"]), v(u["keepout_r"])]
    sm = d["speaker_mic"]
    ports = [[round(a - W / 2, 3), round(e - W / 2, 3)] for a, e in v(sm["groups"])]
    rc = d["receiver"]
    receiver = [v(rc["from_top"])[0], v(rc["from_top"])[1], v(rc["length"])]
    cam = d["camera"]
    rects, circles = [], []
    if "opening_bound" in cam:  # full-width plateau: the dimensioned area that holds it
        ob = cam["opening_bound"]
        r = v(ob["corner_r"]) or 0.01
        rects.append([-W / 2, W / 2, round(H / 2 - v(ob["y_bottom"]), 3), round(H / 2 + 25, 3), r])
    if "plateau" in cam:
        pl = cam["plateau"]
        x0, x1 = v(pl["x"])
        y0, y1 = v(pl["y"])
        rects.append([round(W / 2 - x1, 3), round(W / 2 - x0, 3), round(H / 2 - y1, 3), round(H / 2 - y0, 3), v(pl["corner_r"])])
    for key in ("lenses", "flash", "mic", "sensor"):
        if key not in cam:
            continue
        items = v(cam[key])
        for x, y, dd in (items if isinstance(items[0], list) else [items]):
            circles.append([round(W / 2 - x, 3), round(H / 2 - y, 3), dd])
    return {
        "W": W, "H": H, "T": T,
        "OUTLINE": outline(W, H, corner),
        "LIP_Z": round(lip_z, 3), "FLOOR_F": round(floor_f, 3),
        "ACTIVE_IN": v(d["display"]["housing_to_active_area"]), "FLAT_IN": v(d["display"]["housing_to_flat"]),
        "BUTTONS": buttons, "CAMERA_CONTROL": camera_control,
        "USB": usb, "PORT_D": v(sm["hole_d"]), "PORT_Z": zmid, "PORT_AMB": amb, "PORTS": ports,
        "RECEIVER": receiver, "CAM_RECTS": rects, "CAM_CIRCLES": circles,
        "CAM_PLATEAU_H": v(cam["plateau_height"]),
    }


def fmt(x) -> str:
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(fmt(i) for i in x) + "]"
    if isinstance(x, str):
        return json.dumps(x)
    if isinstance(x, float):
        return repr(round(x, 4)).rstrip("0").rstrip(".") if "." in repr(round(x, 4)) else repr(x)
    return str(x)


def scad_text(doc: dict) -> str:
    rows = {k: phone_rows(doc["phones"][k]) for k in ORDER}
    lines = ["// GENERATED by tools/phone_devices.py from devices.json. Do not edit by hand.",
             "// Frame: origin at the phone's center, +X toward the side button, +Y toward the top,",
             "// heights (z) from the phone's back. Lengths in mm.",
             f"PHONES = {fmt([[k, doc['phones'][k]['name']] for k in ORDER])};", ""]
    keys = list(next(iter(rows.values())))
    for key in keys:
        expr = " : ".join(f'phone == "{k}" ? {fmt(rows[k][key])}' for k in ORDER[:-1])
        lines.append(f"DEV_{key} = {expr} : {fmt(rows[ORDER[-1]][key])};")
    for k in ORDER:
        r = diagonal_radius(v(doc["phones"][k]["corner"]["points"]))
        lines.append(f"// {k}: radius of the circle through the corner's 45 degree point = {r:.2f}")
    return "\n".join(lines) + "\n"


def dims(doc: dict) -> dict:
    def pick(field):
        parts = [f"{v(doc['phones'][k]['body'][field])} if phone == '{k}' else" for k in ORDER[:-1]]
        return "(" + " ".join(parts) + f" {v(doc['phones'][ORDER[-1]]['body'][field])})"
    c = "(0.05 if material == 'tpu' else 0.25)"
    pad = "(0.3 if buttons == 'cover' else 0)"
    return {
        "x": f"{pick('width')} + 2 * ({c} + wall) + {pad}",
        "y": f"{pick('height')} + 2 * ({c} + wall)",
        "z": f"min(slice, back + {pick('depth')} + lip) if slice > 0 else back + {pick('depth')} + lip",
    }


def main() -> int:
    doc = json.loads(SRC.read_text())
    scad = scad_text(doc)
    recipe = json.loads(RECIPE.read_text()) if RECIPE.exists() else None
    want_dims = dims(doc)
    if "--check" in sys.argv:
        stale = []
        if not SCAD.exists() or SCAD.read_text() != scad:
            stale.append(str(SCAD.relative_to(ROOT)))
        if recipe is None or recipe.get("dims") != want_dims:
            stale.append(str(RECIPE.relative_to(ROOT)) + " dims")
        if stale:
            print("stale: " + ", ".join(stale) + ". Run: uv run python tools/phone_devices.py")
            return 1
        print("devices.scad and recipe dims match devices.json")
        return 0
    SCAD.write_text(scad)
    if recipe is not None:
        recipe["dims"] = want_dims
        RECIPE.write_text(json.dumps(recipe, indent=1) + "\n")
    print(f"wrote {SCAD.relative_to(ROOT)}" + (" and recipe dims" if recipe else ""))
    for k in ORDER:
        print(f"  {k}: corner radius at 45 degrees {diagonal_radius(v(doc['phones'][k]['corner']['points'])):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
