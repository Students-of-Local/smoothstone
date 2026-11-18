"""Run OpenSCAD: recipe + params -> STL, STL -> preview PNG."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config
from .recipes import Recipe, scad_literal

BUILD_TIMEOUT = 300
PREVIEW_TIMEOUT = 120


@dataclass
class ScadRun:
    ok: bool
    returncode: int | None
    log: str
    error: str = ""  # first meaningful error line
    timed_out: bool = False


def d_flags(recipe: Recipe, params: dict) -> list[str]:
    out = []
    for name, v in params.items():
        p = recipe.param(name)
        if p is None:
            continue
        out += ["-D", f"{name}={scad_literal(p, v)}"]
    return out


def _base_cmd(binary: str) -> list[str]:
    cmd = [binary]
    if config.openscad_has_manifold(binary):
        cmd.append("--backend=manifold")
    return cmd


_ERR_RE = re.compile(r"^\s*(ERROR|Error|error):?\s*(.*)$")


def first_error(log: str) -> str:
    lines = [ln.strip() for ln in log.splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("ERROR:") or ln.startswith("ERROR "):
            return _shorten(ln)
    for ln in lines:
        if "Assertion" in ln and "failed" in ln:
            return _shorten(ln)
    for ln in lines:
        if _ERR_RE.match(ln) or "Parser error" in ln:
            return _shorten(ln)
    for ln in lines:
        low = ln.lower()
        if "top level object is empty" in low or "no top level geometry" in low:
            return _shorten(ln)
    return ""


def _shorten(line: str, n: int = 160) -> str:
    line = re.sub(r"in file [^,]*/", "in file ", line)
    return line if len(line) <= n else line[: n - 3] + "..."


def build_stl(binary: str, recipe: Recipe, params: dict, out_stl: Path) -> ScadRun:
    """Build the recipe to <out_stl>.off (OpenSCAD's exact mesh) and <out_stl>: that mesh rebuilt as a
    float32 2-manifold (clean.for_slicer), the file that is checked and shipped. Written straight
    from the OFF, float32 rounding can merge distinct vertices and leave non-manifold edges that a
    slicer reports even though the float64 mesh was closed."""
    out_off = out_stl.with_suffix(".off")
    cmd = _base_cmd(binary) + ["-o", str(out_off)] + d_flags(recipe, params) + [str(recipe.scad)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
            env=config.openscad_env(),
            cwd=str(recipe.path),
        )
    except subprocess.TimeoutExpired as e:
        log = "$ " + " ".join(cmd) + "\n" + _txt(e.stdout) + _txt(e.stderr)
        return ScadRun(False, None, log, f"OpenSCAD ran over {BUILD_TIMEOUT} s", True)
    except OSError as e:
        return ScadRun(False, None, f"$ {' '.join(cmd)}\n{e}", f"cannot run OpenSCAD: {e}")
    log = "$ " + " ".join(cmd) + "\n" + (proc.stdout or "") + (proc.stderr or "")
    err = first_error(log)
    if proc.returncode == 0 and out_off.is_file() and out_off.stat().st_size > 0:
        try:
            from .check import load_off
            from .clean import for_slicer

            for_slicer(load_off(out_off)).export(str(out_stl))
        except Exception as e:  # a broken OFF means a broken build; report it, do not crash
            log += f"\nOFF to STL failed: {type(e).__name__}: {e}"
            out_stl.unlink(missing_ok=True)
    ok = proc.returncode == 0 and out_stl.is_file() and out_stl.stat().st_size > 0 and not (
        err.startswith("ERROR") or "Assertion" in err
    )
    if not ok and not err:
        err = f"OpenSCAD exit code {proc.returncode}, no STL written"
    return ScadRun(ok, proc.returncode, log, err)


def _txt(b) -> str:
    if b is None:
        return ""
    return b.decode(errors="replace") if isinstance(b, bytes) else b


def render_preview(binary: str, stl: Path, png: Path) -> ScadRun:
    view = png.with_suffix(".scad")
    view.write_text(f'color("#d9a066") import("{stl.resolve().as_posix()}");\n')
    cmd = _base_cmd(binary) + [
        "--render",
        "--imgsize=900,900",
        "--camera=0,0,0,55,0,25,0",
        "--viewall",
        "--autocenter",
        "--colorscheme=Tomorrow Night",
        "-o",
        str(png),
        str(view),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=PREVIEW_TIMEOUT, env=config.openscad_env()
        )
    except subprocess.TimeoutExpired:
        return ScadRun(False, None, "$ " + " ".join(cmd) + "\npreview timed out", "preview timed out", True)
    except OSError as e:
        return ScadRun(False, None, str(e), str(e))
    log = "$ " + " ".join(cmd) + "\n" + (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and png.is_file() and png.stat().st_size > 0
    return ScadRun(ok, proc.returncode, log, "" if ok else first_error(log) or "no image written")
