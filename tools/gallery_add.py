"""Add one photo to the failure gallery: resize, strip metadata, append its label, refresh CREDITS.md.

uv run python tools/gallery_add.py PHOTO --failure stringing --slug benchy-hairs \\
    --license "CC BY 2.0" --author "Jane Doe" --url https://www.flickr.com/photos/... \\
    --title "Stringy benchy" --source "Flickr" --note "fine hairs span the gap between the two towers" \\
    [--also warping ...] [--printer prusa_mk4s] [--material PLA] [--synthetic]

Look at the photo before you label it: keep it only when the failure is plain to see.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gallery_credits import CREDITS, GALLERY, HEALTHY, LABELS, LICENSES, failure_ids, load, render  # noqa: E402

MAX_SIDE = 768
QUALITY = 85


def shrink(src, dst):
    """Upright, RGB, at most MAX_SIDE px, JPEG q85, no EXIF/ICC/XMP (PIL writes none unless asked)."""
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    clean = Image.new("RGB", im.size)
    clean.paste(im)
    dst.parent.mkdir(parents=True, exist_ok=True)
    clean.save(dst, "JPEG", quality=QUALITY, optimize=True)


def add(src, label, write_credits=True):
    failure = label["failure"]
    if failure != HEALTHY and failure not in failure_ids():
        raise SystemExit(f"{failure}: not a taxonomy id (src/smoothstone/failures/taxonomy.json)")
    for a in label.get("also", []):
        if a not in failure_ids():
            raise SystemExit(f"also {a}: not a taxonomy id")
    if label["license"] not in LICENSES:
        raise SystemExit(f"{label['license']}: not on the allowlist {sorted(LICENSES)}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", label["slug"]):
        raise SystemExit("slug: lowercase words joined by -")
    rel = f"{failure}/{label.pop('slug')}.jpg"
    dst = GALLERY / rel
    if dst.exists():
        raise SystemExit(f"{rel} already exists")
    shrink(src, dst)
    row = {"file": rel, "failure": failure, "also": label.get("also", []), "printer": label.get("printer"),
           "material": label.get("material"), "title": label.get("title"), "source": label["source"],
           "license": label["license"], "author": label["author"], "url": label.get("url"),
           "note": label["note"], "synthetic": bool(label.get("synthetic", False))}
    with LABELS.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if write_credits:
        CREDITS.write_text(render(load()))
    return rel


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("photo", type=Path)
    for k in ("failure", "slug", "license", "author", "source", "note"):
        p.add_argument(f"--{k}", required=True)
    for k in ("url", "title", "printer", "material"):
        p.add_argument(f"--{k}")
    p.add_argument("--also", nargs="*", default=[])
    p.add_argument("--synthetic", action="store_true")
    a = vars(p.parse_args())
    rel = add(a.pop("photo"), a)
    print(f"added failures/gallery/{rel}")


if __name__ == "__main__":
    main()
