"""The stress picture for stone strength: three views through the part, red where it is nearest to breaking."""

from __future__ import annotations

from pathlib import Path

import numpy as np

VIEWS = ((2, "from above"), (1, "from the front"), (0, "from the right"))
SIDE = 300  # px, about the longest side of each view


def picture(st, res, path: Path) -> None:
    """Each pixel is the highest stress over strength along that line of sight (blue low, red at or past breaking).
    A black ring marks the worst spot."""
    from PIL import Image, ImageDraw

    full = np.zeros(st.grid.shape)
    full[st.grid.solid] = np.minimum(res.ratio, 1.0)
    cell = st.grid.cells()[int(np.argmax(res.ratio))]
    scale = max(1, SIDE // max(full.shape))
    panels = []
    for axis, title in VIEWS:
        img, seen = full.max(axis=axis), st.grid.solid.any(axis=axis)
        x, y = (i for i in range(3) if i != axis)
        rgb = np.stack([img, 1 - np.abs(2 * img - 1), 1 - img], -1)
        rgb = np.where(seen[..., None], rgb / rgb.max(-1, keepdims=True), 1.0)
        pic = Image.fromarray((np.flipud(rgb.transpose(1, 0, 2)) * 255).astype(np.uint8))
        pic = pic.resize((pic.width * scale, pic.height * scale), Image.NEAREST)
        panels.append((title, pic, (cell[x] + 0.5) * scale, (img.shape[1] - cell[y] - 0.5) * scale))
    out = Image.new("RGB", (sum(max(p[1].width, 90) + 30 for p in panels), max(p[1].height for p in panels) + 50), "white")
    draw, left = ImageDraw.Draw(out), 15
    for title, pic, px, py in panels:
        draw.text((left, 8), title, fill=(90, 90, 90))
        out.paste(pic, (left, 30))
        draw.ellipse((left + px - 9, py + 21, left + px + 9, py + 39), outline=(0, 0, 0), width=3)
        left += max(pic.width, 90) + 30
    out.save(path)
