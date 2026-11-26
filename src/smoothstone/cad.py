"""stone export: the job's part as an editable solid in SolidCraft (open-source parametric CAD).

SolidCraft's headless CLI turns the checked STL into a solid body (mesh.convert), writes it as STEP
for any CAD program and saves a SolidCraft design (.sc). stone then reads the file back with
`solidcraft-cli eval` and says it is ready only when every body is closed and the volume matches the STL.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .job import read_json, write_json

RELEASES = "https://github.com/tangency-labs/solidcraft/releases"
FALLBACKS = ("/opt/SolidCraft/solidcraft-cli", "/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli")
TIMEOUT = 300  # seconds for one run or eval; a 2600-triangle hook takes about 2
MAX_DIFF = 0.5  # percent: a converted solid holds the STL's volume to 0.001%, so more is a lost or open face


def find_cli() -> str | None:
    """STONE_SOLIDCRAFT, then solidcraft-cli on PATH, then where the installers put it."""
    env = os.environ.get("STONE_SOLIDCRAFT")
    if env:
        return env if Path(env).is_file() else shutil.which(env)
    found = shutil.which("solidcraft-cli")
    if found:
        return found
    return next((p for p in FALLBACKS if Path(p).is_file()), None)


def version() -> str | None:
    """`solidcraft-cli --version`, or None when it is not installed or does not answer."""
    exe = find_cli()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or r.stderr.strip()).splitlines()[0] if r.returncode == 0 else None


def parts(job) -> list[tuple[Path, str]]:
    """The job's built parts as (STL, name): a recipe build's part, or every part of a fitted model."""
    data = read_json(job.build_dir / "model" / "parts.json") or {}
    files = [Path(p["file"]) for p in data.get("parts") or [] if p.get("file")]
    if files and all(f.is_file() for f in files):
        return [(f, f.stem) for f in files]
    stl = job.build_dir / "part.stl"
    if not stl.is_file():
        return []
    plan = job.plan() or {}
    return [(stl, plan.get("recipe") or "part")]


class Failed(Exception):
    pass


def _call(cmd: list[str], log: Path) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        with log.open("a") as f:
            f.write(f"$ {' '.join(cmd)}\ntimed out after {TIMEOUT} s\n")
        raise Failed(f"SolidCraft timed out after {TIMEOUT} s") from None
    with log.open("a") as f:
        f.write(f"$ {' '.join(cmd)}\nexit {r.returncode}\n{r.stdout}{r.stderr}\n")
    if r.returncode != 0:
        first = next((ln.strip() for ln in (r.stderr or r.stdout).splitlines() if ln.strip()), f"exit {r.returncode}")
        raise Failed(f"SolidCraft failed: {first[:160]} (log: {log})")
    return r.stdout


def export_one(exe: str, job, stl: Path, name: str, fmt: str) -> dict:
    """Convert one STL; returns the files written and what eval read back. Raises Failed."""
    import trimesh

    step, design = job.root / f"{name}.step", job.root / f"{name}.sc"
    cmds = [{"command": "file.insert_mesh", "params": {"path": str(stl.resolve())}},
            {"command": "mesh.convert", "params": {"body": stl.stem}}]
    if fmt in ("step", "both"):
        cmds.append({"command": "file.export_step", "params": {"path": str(step)}})
    script = job.build_dir / f"solidcraft_{name}.json"
    write_json(script, {"commands": cmds})
    log = job.build_dir / "solidcraft.log"
    run = [exe, "run", str(script), "--results"] + (["--save", str(design)] if fmt in ("sc", "both") else [])
    _call(run, log)
    target = step if fmt in ("step", "both") else design
    if not target.is_file():
        raise Failed(f"SolidCraft wrote no {target.name} (log: {log})")
    try:
        ev = json.loads(_call([exe, "eval", str(target)], log))
        bodies, vol = ev["bodies"], float(ev["total"]["volume_mm3"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise Failed(f"could not read SolidCraft's eval of {target.name} (log: {log})") from None
    if not bodies or not all(b.get("closed") for b in bodies):
        raise Failed(f"the solid in {target.name} is not closed, so CAD cannot use it as a body")
    v0 = float(trimesh.load(stl, force="mesh").volume)
    diff = abs(vol - v0) / v0 * 100 if v0 else 100.0
    if diff > MAX_DIFF:
        raise Failed(f"{'STEP' if target == step else 'design'} volume differs from the STL by {diff:.1f}%")
    return {"step": step if fmt in ("step", "both") else None, "sc": design if fmt in ("sc", "both") else None,
            "faces": sum(int(b.get("faces") or 0) for b in bodies), "volume": vol, "diff": diff}


def cmd(args, job, out):
    fmt = args.format
    found = parts(job)
    if not found:
        out.fix("build the part first")
        out.next = "stone build"
        return out
    exe = find_cli()
    if not exe:
        out.fix(f"SolidCraft is not installed (optional); get it at {RELEASES}")
        out.next = "stone status"
        return out
    job.build_dir.mkdir(parents=True, exist_ok=True)
    (job.build_dir / "solidcraft.log").write_text("")
    for stl, name in found:
        try:
            r = export_one(exe, job, stl, name, fmt)
        except Failed as e:
            out.fix(str(e))
            out.next = "stone status"
            out.result = "export failed"
            return out
        if r["step"]:
            out.add(f"STEP: {r['step']} ({r['faces']} faces, {r['volume']:.0f} mm3, within {r['diff']:.3f}% of the STL)")
        if r["sc"]:
            out.add(f"SolidCraft design: {r['sc']}" + ("" if r["step"] else
                                                       f" ({r['faces']} faces, within {r['diff']:.3f}% of the STL)"))
    out.next = "open it in SolidCraft"
    out.result = f"exported {len(found)} part{'s' if len(found) > 1 else ''} for CAD"
    return out
