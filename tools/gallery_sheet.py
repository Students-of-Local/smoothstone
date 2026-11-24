"""Contact sheets of the failure gallery, one per failure id, for a person checking the labels.

uv run python tools/gallery_sheet.py [ID ...] [--out DIR]

Writes DIR/<id>.jpg (default /tmp/gallery-sheets); not committed.
"""
import argparse
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gallery_credits import GALLERY, load  # noqa: E402

TILE, COLS, TEXT_H = 320, 4, 64


def sheet(rows, out):
    n = len(rows)
    grid = Image.new("RGB", (COLS * TILE, ((n + COLS - 1) // COLS) * (TILE + TEXT_H)), "white")
    d = ImageDraw.Draw(grid)
    for i, l in enumerate(rows):
        x, y = (i % COLS) * TILE, (i // COLS) * (TILE + TEXT_H)
        im = Image.open(GALLERY / l["file"]).convert("RGB")
        im.thumbnail((TILE, TILE))
        grid.paste(im, (x + (TILE - im.width) // 2, y + (TILE - im.height) // 2))
        head = f"{Path(l['file']).stem} [{l.get('printer') or '?'}]"
        lines = [head] + textwrap.wrap(l["note"], 52)[:3]
        d.multiline_text((x + 4, y + TILE + 2), "\n".join(lines), fill="black")
    grid.save(out, quality=85)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ids", nargs="*")
    p.add_argument("--out", type=Path, default=Path("/tmp/gallery-sheets"))
    a = p.parse_args()
    labels = load()
    ids = a.ids or sorted({l["failure"] for l in labels})
    a.out.mkdir(parents=True, exist_ok=True)
    for fid in ids:
        rows = [l for l in labels if l["failure"] == fid]
        if not rows:
            print(f"{fid}: no photos")
            continue
        sheet(rows, a.out / f"{fid}.jpg")
        print(f"{fid}: {len(rows)} photos -> {a.out / (fid + '.jpg')}")


if __name__ == "__main__":
    main()
