"""Paths, tool discovery and settings from env and stone.toml."""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from functools import lru_cache
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
# src/smoothstone -> src -> repo
REPO_ROOT = PKG_DIR.parent.parent

FALLBACK_OPENSCAD = Path("/home/baney75/lfm3-3d-skill/vendor/openscad/AppRun")
DEFAULT_BED = (256.0, 256.0, 256.0)
TIERS = ("S", "M", "L")


def recipes_dir() -> Path:
    env = os.environ.get("STONE_RECIPES")
    return Path(env).resolve() if env else REPO_ROOT / "recipes"


def vendor_dir() -> Path:
    return REPO_ROOT / "vendor"


def skill_dir() -> Path:
    return REPO_ROOT / "skill"


def job_dir(arg: str | None = None) -> Path:
    raw = arg or os.environ.get("STONE_JOB") or "stone-job"
    return Path(raw).expanduser().resolve()


def find_openscad() -> str | None:
    env = os.environ.get("STONE_OPENSCAD")
    if env:
        return env if Path(env).exists() or shutil.which(env) else None
    found = shutil.which("openscad")
    if found:
        return found
    if FALLBACK_OPENSCAD.exists():
        return str(FALLBACK_OPENSCAD)
    return None


@lru_cache(maxsize=8)
def openscad_has_manifold(binary: str) -> bool:
    try:
        out = subprocess.run(
            [binary, "--help"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    text = (out.stdout or "") + (out.stderr or "")
    return "--backend" in text and "manifold" in text.lower()


def openscad_env() -> dict[str, str]:
    env = dict(os.environ)
    paths = [str(vendor_dir()), str(recipes_dir())]
    old = env.get("OPENSCADPATH")
    if old:
        paths.append(old)
    env["OPENSCADPATH"] = os.pathsep.join(paths)
    return env


def _toml(job: Path | None) -> dict:
    for base in (Path.cwd(), job):
        if base is None:
            continue
        f = base / "stone.toml"
        if f.is_file():
            try:
                return tomllib.loads(f.read_text())
            except (tomllib.TOMLDecodeError, OSError):
                return {}
    return {}


def tier(job: Path | None = None) -> str:
    raw = os.environ.get("STONE_TIER") or _toml(job).get("tier") or "S"
    raw = str(raw).strip().upper()
    return raw if raw in TIERS else "S"


def bed(job: Path | None = None) -> tuple[float, float, float]:
    raw = _toml(job).get("bed")
    try:
        x, y, z = (float(v) for v in raw)
        return (x, y, z)
    except (TypeError, ValueError):
        return DEFAULT_BED


def tier_rules(t: str, limit: int = 6) -> list[str]:
    f = skill_dir() / "tiers" / f"{t}.md"
    if not f.is_file():
        return []
    rules: list[str] = []
    inside = False
    for line in f.read_text().splitlines():
        s = line.strip()
        if s.startswith("#"):
            inside = s.lstrip("#").strip().lower() == "rules" and s.startswith("## ")
            continue
        if inside and (s.startswith("- ") or s.startswith("* ")):
            rules.append("- " + s[2:].strip())
        elif inside and s[:1].isdigit() and ". " in s[:4]:
            rules.append("- " + s.split(". ", 1)[1].strip())
        if len(rules) >= limit:
            break
    return rules
