"""Printer profiles: what stone knows about the person's printer, and a read-only bridge to it.

One JSON per model in printers/ (the contract is in the track D notes): size, kinematics, enclosure,
the build plate and how its maker says to clean it, multi-material, camera and documented quirks.
Every fact carries its source. `stone printer` lists, sets and shows them; status and camera go
through Gantrel's `gantrel-printer` CLI, which is only ever asked to read: stone never starts,
resumes or cancels a print.
"""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
import subprocess
import tomllib
from functools import lru_cache
from pathlib import Path

from . import config

PRINTERS_DIR = Path(__file__).resolve().parent / "printers"
SETTINGS = config.REPO_ROOT / "recipes" / "lib" / "refs" / "printer_settings.json"
GANTREL = "gantrel-printer"
GANTREL_INSTALL = "uv tool install git+https://github.com/Students-of-Local/Gantrel"


@lru_cache(maxsize=1)
def load() -> dict[str, dict]:
    """Every profile by id, sorted by maker then name."""
    out = {}
    for f in sorted(PRINTERS_DIR.glob("*.json")):
        p = json.loads(f.read_text())
        out[p["id"]] = p
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["maker"], kv[1]["name"])))


@lru_cache(maxsize=1)
def _settings() -> dict[str, dict]:
    return {e["id"]: e for e in json.loads(SETTINGS.read_text())["entries"]}


def settings(p: dict, material: str) -> dict | None:
    """What this printer's slicer profile prints the plastic with (tools/orca_profiles.py), or None: nozzle, bed
    and chamber in C, max_flow mm3/s, diameter mm, its profile and url, and the fan in %: fan_long on layers longer than
    fan_min_layer_s, fan_max on ones shorter than fan_max_layer_s, from fan_min up to it between, and fan_over on
    bridges and on overhangs past the profile's threshold where that is more. chamber is the air the
    profile is written for: chamber_heated says whether the printer heats it or only its bed does. Heat the maker says the printer does not reach is
    cut to what it does, the chamber's to none on an open frame, and `cut` says so."""
    e = _settings().get(f"orca.{p['id']}.{material.upper()}")
    if not e:
        return None
    out = {**e["value"], "profile": e["cite"], "url": e["url"], "cut": []}
    out.setdefault("fan_long", out["fan_min"])
    out.setdefault("fan_over", out["fan_max"])
    out["chamber_heated"] = bool(out.get("chamber") and p.get("chamber_heater"))
    for k, top in (("nozzle", p.get("max_hotend_c")), ("bed", p.get("max_bed_c"))):
        if top and out.get(k, 0) > top:
            out["cut"].append(f"{e['cite']} wants the {k} at {out[k]:g} C; the {p['name']} reaches {top:g} C")
            out[k] = top
    if out.get("chamber") and not p.get("enclosed"):
        out["cut"].append(f"{e['cite']} wants {out.pop('chamber'):g} C air; the {p['name']} is an open frame")
    return out


def fan(s: dict, layer_s: float, over: bool = False) -> float:
    """Share of full speed a profile (settings) runs the fan at on layers that take layer_s; over: on lines over air."""
    if over:
        return max(fan(s, layer_s), s["fan_over"] / 100)
    if layer_s > s["fan_min_layer_s"]:
        return s["fan_long"] / 100
    a, b = s["fan_max_layer_s"], s["fan_min_layer_s"]
    short = 1.0 if b <= a else min(max((b - layer_s) / (b - a), 0.0), 1.0)
    return (s["fan_min"] + short * (s["fan_max"] - s["fan_min"])) / 100


def process(p: dict) -> dict | None:
    """This printer's slicer process: layer (mm) and widths, speeds, accels, shells, retract_mm, nozzle_volume_mm3 (where Orca gives it)."""
    e = _settings().get(f"orca.{p['id']}.process")
    return {**copy.deepcopy(e["value"]), "profile": e["cite"], "url": e["url"]} if e else None


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def short_name(p: dict) -> str:
    """The model name without the maker: "Bambu Lab X1 Carbon" is "X1 Carbon", "Original Prusa MK4S" is "MK4S"."""
    drop = {w.lower() for w in p["maker"].split()} | {"original"}
    return " ".join(w for w in p["name"].split() if w.lower() not in drop) or p["name"]


def get(pid: str | None) -> dict | None:
    """A profile by id, forgiving case and punctuation: creality_k2, creality-k2, "Creality K2", K2."""
    if not pid:
        return None
    lib = load()
    if pid in lib:
        return lib[pid]
    k = _key(pid)
    for p in lib.values():
        if k in (_key(p["id"]), _key(p["name"]), _key(short_name(p))):
            return p
    return None


def current(job: Path | None = None) -> dict | None:
    """The printer from stone.toml [printer] model (the job's, else the machine's), or None."""
    raw = config._toml(job).get("printer")
    model = raw.get("model") if isinstance(raw, dict) else None
    return get(str(model)) if model else None


def config_file() -> Path:
    return config.user_config_dir() / "stone.toml"


def set_model(pid: str) -> Path:
    """Write [printer] model = "<pid>" to the machine's stone.toml, keeping every other line."""
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    lines = f.read_text().splitlines() if f.is_file() else []
    keep, inside = [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[") and not s.startswith("[["):
            inside = s == "[printer]"
            if inside:
                continue
        if not inside:
            keep.append(ln)
    while keep and not keep[-1].strip():
        keep.pop()
    text = "\n".join(keep + ([""] if keep else []) + ["[printer]", f'model = "{pid}"']) + "\n"
    tomllib.loads(text)  # never leave a file stone cannot read
    f.write_text(text)
    return f


# what a person reads


def surface_line(p: dict) -> str:
    s = p["bed_surface"]
    return f"Plate: {s['type']}"


def clean_line(p: dict) -> str:
    s = p["bed_surface"]
    return f"Clean it (maker's steps): {s['clean']} ({s['source']})"


def filament_lines(p: dict) -> list[str]:
    """The plastics its slicer profile prints, and how much filament sits past where it can be pulled back from."""
    got = {k: settings(p, k) for k in (i.split(".")[2] for i in _settings() if i.startswith(f"orca.{p['id']}.")) if k != "process"}
    lines = ["Plastics in its slicer profiles (nozzle / bed C, most mm3/s): "
             + "; ".join(f"{k} {s['nozzle']:g} / {s['bed']:g}, {s['max_flow']:g}" for k, s in got.items())] if got else []
    kept = (process(p) or {}).get("nozzle_volume_mm3")
    if kept:
        lines.append(f"Cutter to nozzle tip: {kept / (math.pi * 1.75 ** 2 / 4):.0f} mm of filament ({kept:g} mm3), purged at each change of filament")
    if tube := p.get("bowden_mm"):
        lines.append(f"Feed: a {tube['value']:g} mm tube from the extruder to the hotend ({tube['source']})")
    return lines


def show_lines(p: dict) -> list[str]:
    x, y, z = p["build_volume_mm"]
    mm = p.get("multi_material") or "none"
    lines = [
        f"{p['name']} ({p['id']}): {p['kinematics']}, {p['firmware']} firmware, "
        f"{'enclosed' if p['enclosed'] else 'open frame'}"
        + (", heated chamber" if p.get("chamber_heater") else ""),
        f"Bed: {x:g} x {y:g} x {z:g} mm, nozzle {p['nozzle_mm']} mm"
        + (f", hotend up to {p['max_hotend_c']} C" if p.get("max_hotend_c") else "")
        + (f", bed up to {p['max_bed_c']} C" if p.get("max_bed_c") else ""),
        surface_line(p),
        clean_line(p),
        f"Leveling: {p.get('auto_level') or 'unknown'}. Multi-material: {mm}.",
    ]
    cam = p.get("camera") or {}
    if cam.get("where"):
        lines.append(f"Camera: {cam['where']}" + (", IR night view" if cam.get("ir_night") else "")
                     + (" (position is an assumption)" if cam.get("assumption") else ""))
    lines += filament_lines(p)
    for q in p.get("quirks", [])[:4]:
        lines.append(f"Known issue ({q['failure']}): {q['note']} ({q['source']})")
    return lines


# the printer itself, through Gantrel (read-only)


def gantrel() -> str | None:
    return shutil.which(GANTREL)


def _run(argv: list[str], timeout: float = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def paired(binary: str) -> list[dict]:
    code, text = _run([binary, "list", "--json"])
    try:
        rows = json.loads(text).get("printers", []) if code == 0 else []
    except (json.JSONDecodeError, AttributeError):
        rows = []
    return [r for r in rows if isinstance(r, dict) and r.get("name")]


def pick(rows: list[dict], p: dict | None, name: str | None = None) -> dict | None:
    """The paired printer to read: the one named, else the one whose model matches, else the only one."""
    if name:
        return next((r for r in rows if r["name"] == name), None)
    want = ((p or {}).get("connect") or {}).get("gantrel_model")
    hit = [r for r in rows if want and r.get("model") == want]
    if len(hit) == 1:
        return hit[0]
    return rows[0] if len(rows) == 1 else None


def live(p: dict | None) -> tuple[dict | None, str]:
    """The paired printer's own heat now, read once: name, state and, where it says, nozzle_c, nozzle_target_c, bed_c,
    bed_target_c and chamber_c. Or None and why not."""
    binary = gantrel()
    if binary is None:
        return None, f"{GANTREL} is not installed"
    row = pick(paired(binary), p)
    if row is None:
        return None, "no paired printer matches"
    code, text = _run([binary, "status", row["name"], "--json"])
    try:
        got = json.loads(text) if code == 0 else None
    except json.JSONDecodeError:
        got = None
    if not isinstance(got, dict):
        return None, f"{row['name']} did not answer"
    if got.get("state") not in ("printing", "paused"):
        return None, f"{row['name']} is not printing"
    ok = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 500  # noqa: E731
    return {"name": row["name"], "state": got["state"],
            **{k: float(got[k]) for k in ("nozzle_c", "nozzle_target_c", "bed_c", "bed_target_c", "chamber_c") if ok(got.get(k))}}, ""


def how_to_connect(p: dict | None) -> list[str]:
    c = (p or {}).get("connect") or {}
    kind = c.get("gantrel_type") or "<type>"
    model = f" --model {c['gantrel_model']}" if c.get("gantrel_model") else ""
    return [f"Install Gantrel's printer tool: {GANTREL_INSTALL}",
            f"Pair it: {GANTREL} discover, then {GANTREL} pair <name> --type {kind} --host <printer ip>{model}"]


def gantrel_text(text: str, limit: int = 12) -> list[str]:
    """Gantrel's own output without its NEXT line: stone ends with one NEXT of its own."""
    return [ln for ln in text.strip().splitlines() if ln.strip() and not ln.startswith("NEXT:")][:limit]


# stone printer [list | set <id> | show [id] | status | camera [--out f.jpg]]


def _back(job) -> str:
    """Where the person was before looking at the printer: the job's NEXT, else a new job."""
    from .cli import NEW_NEXT

    nxt = job.status().get("next") if job.exists() else None
    return nxt if nxt and nxt != "stone status" else NEW_NEXT


def cmd_printer(args, job):
    from .cli import Out

    out = Out(owns_next=False)
    action = (args.action or "list").lower()
    arg = args.id
    if action not in ("list", "set", "show", "status", "camera") and get(action):
        action, arg = "show", action  # stone printer creality_k2
    lib = load()
    have = current(job.root)
    if action == "list":
        out.add(f"{len(lib)} printers (stone printer show <id>):")
        for p in lib.values():
            x, y, z = p["build_volume_mm"]
            out.add(f"{p['id']}: {p['name']}, {x:g} x {y:g} x {z:g} mm" + (" (yours)" if have and have["id"] == p["id"] else ""))
        out.next = f"stone printer show {have['id']}" if have else \
            "ask the person: which printer do you have? Then: stone printer set <id>"
        return out
    if action == "set":
        p = get(arg)
        if p is None:
            out.fix(f"no printer {arg or '(none given)'}; ids: " + " ".join(lib))
            out.next = "stone printer"
            return out
        f = set_model(p["id"])
        out.add(f"Printer set: {p['name']} ({p['id']}) in {f}")
        out.next = f"stone printer show {p['id']}"
        out.result = f"printer {p['id']}"
        return out
    if action == "show":
        p = get(arg) if arg else have
        if p is None:
            out.fix(f"no printer {arg}" if arg else "no printer set yet")
            out.next = "stone printer"
            return out
        out.add(*show_lines(p))
        out.next = _back(job)
        return out
    # status and camera: read the real printer through Gantrel
    binary = gantrel()
    if binary is None:
        out.add(f"{GANTREL} is not installed, so stone cannot read the printer.", *how_to_connect(have))
        out.next = ("ask the person: install and pair the printer tool (lines above), or tell me what the "
                    "printer screen shows")
        return out
    rows = paired(binary)
    row = pick(rows, have, args.name)
    if row is None:
        out.add("No paired printer matches." if rows else "No printer is paired yet.", *how_to_connect(have)[1:])
        if len(rows) > 1:
            out.add("Paired: " + ", ".join(r["name"] for r in rows) + " (pick one with --name)")
        out.next = (f"stone printer {action} --name {rows[0]['name']}" if len(rows) > 1 else
                    "ask the person: pair the printer (line above), or tell me what the printer screen shows")
        return out
    if action == "status":
        code, text = _run([binary, "status", row["name"]])
        out.add(f"Printer {row['name']} ({row.get('model') or row.get('type')}):", *gantrel_text(text))
        out.next = "stone printer camera" if code == 0 else \
            "ask the person: the printer did not answer; is it on and on the network?"
        return out
    dest = Path(args.out or (job.root / "camera.jpg")).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, text = _run([binary, "camera", row["name"], "--out", str(dest)])
    if code != 0 or not dest.is_file():
        out.add(*gantrel_text(text, 4))
        out.fix(f"no camera frame from {row['name']}")
        out.next = "ask the person: the camera did not answer; describe what you see in the printer"
        return out
    out.add(f"Camera frame: {dest}", "Look at it. If the print looks fine, nothing needs fixing.")
    out.next = f'stone doctor "<what you see in the frame>" --image {dest}'
    out.result = "camera frame"
    return out
