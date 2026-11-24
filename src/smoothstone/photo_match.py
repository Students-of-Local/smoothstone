"""Match a failure photo against the labeled gallery (failures/gallery) by image embedding.

Optional: it needs the vision extra (`uv sync --extra vision`: open_clip, MIT, and torch, BSD) and the
model weights in the Hugging Face cache (`uv run python -m smoothstone.photo_match --fetch`, about 600 MB,
once). Without either, stone doctor runs on the words and --looks and says the image match is off.
STONE_IMAGE_MATCH=off turns it off (the tests do). The gallery's embeddings are cached in
$XDG_CACHE_HOME/smoothstone, keyed by the model and labels.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

from . import config

MODEL, TAG = "ViT-B-32", "laion2b_s34b_b79k"  # open_clip's LAION-2B CLIP, MIT licensed weights
GALLERY = config.REPO_ROOT / "failures" / "gallery"


def _weights(download: bool = False) -> str:
    import open_clip
    from huggingface_hub import hf_hub_download

    repo = open_clip.get_pretrained_cfg(MODEL, TAG)["hf_hub"].strip("/")
    return hf_hub_download(repo, "open_clip_pytorch_model.bin", local_files_only=not download)


def available() -> tuple[bool, str]:
    """Whether the image match can run here, and why not."""
    if os.environ.get("STONE_IMAGE_MATCH", "").lower() in ("off", "0", "no"):
        return False, "STONE_IMAGE_MATCH=off"
    try:
        _weights()
    except ImportError:
        return False, "the vision extra is not installed (uv sync --extra vision)"
    except Exception:  # noqa: BLE001 - not in the Hugging Face cache, or the cache is unreadable
        return False, "the model is not downloaded (uv run python -m smoothstone.photo_match --fetch)"
    return True, ""


@lru_cache(maxsize=1)
def _model():
    import open_clip

    model, _, prep = open_clip.create_model_and_transforms(MODEL, pretrained=_weights())
    model.eval()
    return model, prep


def embed(paths: list[Path]):
    """Unit-length image embeddings, one row per path."""
    import torch
    from PIL import Image

    model, prep = _model()
    out = []
    with torch.no_grad():
        for i in range(0, len(paths), 16):
            batch = torch.stack([prep(Image.open(p).convert("RGB")) for p in paths[i:i + 16]])
            e = model.encode_image(batch)
            out.append(e / e.norm(dim=-1, keepdim=True))
    return torch.cat(out).numpy()


def labels() -> list[dict]:
    return [json.loads(ln) for ln in (GALLERY / "labels.jsonl").read_text().splitlines() if ln.strip()]


def group(file: str) -> str:
    """Frames of one print share a group (u1-facade-spaghetti-1, -2, -3): never neighbors of each other."""
    return re.sub(r"-\d+$", "", file.rsplit(".", 1)[0])


def gallery():
    """The gallery's labels and embeddings, cached on disk."""
    import numpy as np

    rows = labels()
    key = hashlib.sha1((MODEL + TAG + (GALLERY / "labels.jsonl").read_text()).encode()).hexdigest()[:12]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "smoothstone" / f"gallery-{key}.npy"
    if cache.exists():
        return rows, np.load(cache)
    emb = embed([GALLERY / r["file"] for r in rows])
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, emb)
    return rows, emb


def neighbors(photo: Path, n: int = 40, skip: set[str] = frozenset()) -> list[tuple[str, str, float]]:
    """The n most similar gallery photos as (file, failure, cosine), leaving out the files in skip and
    every frame of their prints."""
    rows, emb = gallery()
    sims = emb @ embed([photo])[0]
    groups = {group(f) for f in skip}
    order = sorted(range(len(rows)), key=lambda i: -sims[i])
    return [(rows[i]["file"], rows[i]["failure"], round(float(sims[i]), 4)) for i in order
            if group(rows[i]["file"]) not in groups][:n]


def votes(near: list[tuple[str, str, float]], k: int) -> dict[str, float]:
    """Each failure's share of the k nearest photos, weighted by similarity ("healthy" counts, for no id)."""
    top = near[:k]
    total = sum(s for _, _, s in top) or 1.0
    out: dict[str, float] = {}
    for _, fid, s in top:
        out[fid] = out.get(fid, 0.0) + s / total
    return {f: round(v, 4) for f, v in sorted(out.items(), key=lambda x: -x[1]) if f != "healthy"}


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        print(_weights(download=True))
    print(available())
