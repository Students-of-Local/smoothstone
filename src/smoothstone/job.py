"""The job folder: every bit of state lives here so a model can lose its context."""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
from pathlib import Path


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


class Job:
    def __init__(self, root: Path):
        self.root = Path(root)

    # paths
    @property
    def brief_file(self) -> Path:
        return self.root / "brief.md"

    @property
    def plan_file(self) -> Path:
        return self.root / "plan.json"

    @property
    def status_file(self) -> Path:
        return self.root / "status.json"

    @property
    def log_file(self) -> Path:
        return self.root / "log.txt"

    @property
    def image_dir(self) -> Path:
        return self.root / "image"

    @property
    def build_dir(self) -> Path:
        return self.root / "build"

    @property
    def measure_file(self) -> Path:
        return self.root / "measure.json"

    def measured(self) -> dict | None:
        """The last stone measure result with a scale and an object, if any."""
        m = read_json(self.measure_file)
        if isinstance(m, dict) and m.get("mm_per_px") and (m.get("object") or {}).get("long_mm"):
            return m
        return None

    def exists(self) -> bool:
        return self.brief_file.is_file() or self.status_file.is_file()

    # create
    def create(self, request: str, force: bool = False) -> Path | None:
        """Make the job. Returns where an old job was moved, if any."""
        moved = None
        if self.root.exists() and any(self.root.iterdir()):
            if not force:
                raise FileExistsError(str(self.root))
            n = 1
            while True:
                cand = self.root.with_name(f"{self.root.name}.old-{n}")
                if not cand.exists():
                    break
                n += 1
            shutil.move(str(self.root), str(cand))
            moved = cand
        self.root.mkdir(parents=True, exist_ok=True)
        self.brief_file.write_text(f"# Request\n\n{request.strip()}\n")
        self.save_status(
            {
                "stage": "new",
                "last_command": "",
                "last_result": "job created",
                "next": "stone recipes",
                "builds": 0,
                "failed_builds": 0,
                "passed": False,
            }
        )
        self.log(f"new job: {request.strip()}")
        return moved

    # brief
    def request(self) -> str:
        try:
            text = self.brief_file.read_text()
        except OSError:
            return ""
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        return " ".join(ln.strip() for ln in lines)

    # plan
    def plan(self) -> dict | None:
        p = read_json(self.plan_file)
        if isinstance(p, dict) and p.get("recipe"):
            p.setdefault("params", {})
            return p
        return None

    def save_plan(self, recipe: str, params: dict) -> None:
        write_json(self.plan_file, {"recipe": recipe, "params": params})

    # status
    def status(self) -> dict:
        s = read_json(self.status_file, {}) or {}
        s.setdefault("stage", "new")
        s.setdefault("builds", 0)
        s.setdefault("failed_builds", 0)
        s.setdefault("passed", False)
        return s

    def save_status(self, s: dict) -> None:
        write_json(self.status_file, s)

    def update(self, **kw) -> dict:
        s = self.status()
        s.update(kw)
        self.save_status(s)
        return s

    # log
    def log(self, text: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a") as f:
                f.write(f"[{_now()}] {text.rstrip()}\n")
        except OSError:
            pass

    def image_paths(self) -> dict[str, Path]:
        out = {}
        svg = self.image_dir / "silhouette.svg"
        png = self.image_dir / "height.png"
        if svg.is_file():
            out["silhouette"] = svg
        if (self.image_dir / "outline.svg").is_file():
            out["outline"] = self.image_dir / "outline.svg"
        if png.is_file():
            out["height"] = png
        latest = self.image_dir / "figure" / "latest.txt"
        if latest.is_file():
            fig = Path(latest.read_text().strip())
            if fig.is_file():
                out["figure"] = fig
        return out

    def photos(self) -> list[Path]:
        """Photos for a figure: found ones first, then the picture given with stone image."""
        found = sorted((self.image_dir / "found").glob("photo_*"))
        given = sorted(self.image_dir.glob("source.*"))
        return given + found if given else found
