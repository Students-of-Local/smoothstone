"""Is a photo of one person, and the same person as another photo?

OpenCV's YuNet finds the faces and SFace turns a face into 128 numbers; two faces of the same
person point the same way (cosine similarity). Both models are from opencv_zoo (Apache 2.0, CPU,
39 MB together) and are downloaded once into the cache, checked against their SHA-256.

stone find uses this to keep only photos of the one person meant: a group shot, a face too small
to style from or a face that is someone else's never makes a figure.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MODELS = {
    "detect": ("face_detection_yunet_2023mar.onnx",
               "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
               "face_detection_yunet"),
    "embed": ("face_recognition_sface_2021dec.onnx",
              "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
              "face_recognition_sface"),
}
MIRRORS = ("https://huggingface.co/opencv/{repo}/resolve/main/{name}",
           "https://github.com/opencv/opencv_zoo/raw/main/models/{repo}/{name}")
AGENT = "smoothstone/0.3 (https://github.com/Students-of-Local/smoothstone; stone find)"

# SFace's own cosine bar (opencv_zoo), checked on Commons photos of seven people (LOG.md, 2026-11-20):
# one person's main photo against another's photos 0.26 at most, against their own mostly 0.39 to
# 0.95; C215's stencil of Michael Jordan 0.32.
SAME = 0.363
DOMINANT = 2.0  # the biggest face has at least this times the area of the next
MIN_FACE = 80  # px: the shorter side of the face box in the photo as found (1280 px wide at most)
SCORE = 0.7  # YuNet's own confidence that a box is a face
WORK_PX = 1280  # photos are looked at no bigger than this on the long side


class Unavailable(Exception):
    """The face models cannot be had (offline, a bad download, no opencv): find works as before."""


@dataclass
class Look:
    """What one photo shows: how many faces, whether one leads, and that face's embedding."""
    faces: int = 0
    one: bool = False  # exactly one dominant face, big enough to style from
    why: str = ""  # why not: "no face", "small", "group"
    embedding: list[float] | None = field(default=None, repr=False)


def judge(boxes: list[tuple[float, float]]) -> tuple[bool, str]:
    """(ok, why not) for the faces' (width, height) in a photo: one face that leads by DOMINANT
    in area over the next, and MIN_FACE or more on its shorter side."""
    if not boxes:
        return False, "no face"
    areas = sorted((w * h for w, h in boxes), reverse=True)
    big = max(boxes, key=lambda b: b[0] * b[1])
    if len(areas) > 1 and areas[0] < DOMINANT * areas[1]:
        return False, "group"
    if min(big) < MIN_FACE:
        return False, "small"
    return True, ""


def cosine(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a, dtype=float).ravel(), np.asarray(b, dtype=float).ravel()
    n = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / n) if n else 0.0


def agree(embeddings: list[list[float]], same: float = SAME) -> list[int]:
    """The indexes of the largest group of faces that are one person, with no anchor to go by.

    Each face gathers every face within `same` of it; the biggest gathering wins, and a tie goes to
    the one that holds the earliest (best ranked) face. With nobody agreeing that is the first face
    alone: a photo nothing else confirms is not mixed with others."""
    best: list[int] = []
    for i, e in enumerate(embeddings):
        group = [j for j, f in enumerate(embeddings) if j == i or cosine(e, f) >= same]
        if len(group) > len(best) or (len(group) == len(best) and group and min(group) < min(best)):
            best = group
    return sorted(best)


def cache_dir() -> Path:
    env = os.environ.get("STONE_FACE_MODELS")
    return Path(env).expanduser() if env else Path.home() / ".cache" / "stone-style" / "models" / "opencv-face"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model(kind: str, timeout: float = 60) -> Path:
    """The model file, downloaded on first use and checked against its SHA-256."""
    name, digest, repo = MODELS[kind]
    path = cache_dir() / name
    if path.exists() and _sha(path) == digest:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(name + ".part")
    last = "no mirror answered"
    for url in MIRRORS:
        try:
            req = urllib.request.Request(url.format(repo=repo, name=name), headers={"User-Agent": AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r, part.open("wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            if _sha(part) == digest:
                part.replace(path)
                return path
            last = "a download did not match its SHA-256"
        except Exception as e:  # offline, a timeout, an http error: try the next mirror
            last = f"cannot download it ({type(e).__name__})"
    part.unlink(missing_ok=True)
    raise Unavailable(f"the face model {name}: {last}")


class Checker:
    """YuNet and SFace, loaded once for a find."""

    def __init__(self):
        try:
            import cv2
        except ImportError as e:
            raise Unavailable("opencv is not installed") from e
        self.cv2 = cv2
        try:  # opencv 5 warns on stderr that its new graph engine takes no target; stone's lines stay clean
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        try:
            self.det = cv2.FaceDetectorYN.create(str(model("detect")), "", (320, 320), SCORE, 0.3, 50)
            self.rec = cv2.FaceRecognizerSF.create(str(model("embed")), "")
        except Unavailable:
            raise
        except Exception as e:  # an opencv that cannot read the models
            raise Unavailable(f"opencv cannot load the face models ({type(e).__name__})") from e

    def look(self, raw: bytes) -> Look:
        import numpy as np
        cv2 = self.cv2
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            return Look(why="no face")
        h, w = im.shape[:2]
        k = min(1.0, WORK_PX / max(h, w))
        if k < 1.0:
            im = cv2.resize(im, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
            h, w = im.shape[:2]
        rows, scale = self._detect(im), 1.0
        if not rows:  # a face that fills the frame is bigger than YuNet looks for: give it a border
            pad = max(h, w) // 2
            im = cv2.copyMakeBorder(im, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(127, 127, 127))
            scale = min(1.0, WORK_PX / max(im.shape[:2]))
            if scale < 1.0:
                im = cv2.resize(im, (round(im.shape[1] * scale), round(im.shape[0] * scale)),
                                interpolation=cv2.INTER_AREA)
            rows = self._detect(im)
        ok, why = judge([(float(r[2]) / scale, float(r[3]) / scale) for r in rows])
        out = Look(faces=len(rows), one=ok, why=why)
        if ok:
            top = max(rows, key=lambda r: r[2] * r[3])
            feat = self.rec.feature(self.rec.alignCrop(im, top))
            out.embedding = [float(x) for x in feat.ravel()]
        return out

    def _detect(self, im) -> list:
        self.det.setInputSize((im.shape[1], im.shape[0]))
        _, rows = self.det.detect(im)
        return [] if rows is None else list(rows)


def checker() -> Checker:
    """The face checker, or Unavailable with the reason. STONE_FACES=0 turns it off."""
    if os.environ.get("STONE_FACES") == "0":
        raise Unavailable("STONE_FACES=0 turned it off")
    return Checker()
