"""Crop the biggest face out of the photos, with its hair and a little of the shoulders.

python face.py <photo> [<photo> ...] <out.png>   (exit 0 wrote the crop and printed the photo it
came from, 3 found no face)
python face.py --skin <image> [<image> ...]       (prints a JSON list: each image's skin as an ITA
angle in degrees from its biggest face's cheeks, null where no face is found)
python face.py --box <image> [<image> ...]        (prints a JSON list: each image's biggest face as
[x, y, w, h] in pixels, null where no face is found)

The face that is biggest in pixels wins across all the photos: a found lead photo is often a whole
person on a stage, with a face a third the size of a close-up's.

Runs on the lift venv's python: opencv 4 has the Haar face finder, opencv 5 dropped it. The
style model keeps a likeness far better with this crop as its first picture: in a whole photo
the face is a few pixels of the render and comes out generic.
"""

import json
import math
import sys

import cv2
import numpy as np


def biggest(src: str):
    im = cv2.imread(src)
    if im is None or not hasattr(cv2, "CascadeClassifier"):
        return None
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    side = max(40, min(H, W) // 12)
    faces = sorted(c.detectMultiScale(g, 1.1, 6, minSize=(side, side)), key=lambda r: -r[2] * r[3])
    return (im, faces[0]) if len(faces) else None


def ita(im, face) -> float:
    """Individual typology angle of the cheeks: atan((L* - 50) / b*) in degrees. Over 55 is very
    light skin, under -30 dark; light and shadow move it less than raw brightness does."""
    x, y, w, h = face
    lab = cv2.cvtColor(im.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)
    cheeks = np.concatenate([lab[int(y + 0.55 * h):int(y + 0.72 * h), int(x + a * w):int(x + b * w)].reshape(-1, 3)
                             for a, b in ((0.2, 0.38), (0.62, 0.8))])
    L, B = float(np.median(cheeks[:, 0])), float(np.median(cheeks[:, 2]))
    return round(math.degrees(math.atan2(L - 50.0, B)), 1)


def main() -> int:
    if sys.argv[1:2] == ["--skin"]:
        out = []
        for src in sys.argv[2:]:
            got = biggest(src)
            out.append(ita(*got) if got else None)
        print(json.dumps(out))
        return 0
    if sys.argv[1:2] == ["--box"]:
        out = []
        for src in sys.argv[2:]:
            got = biggest(src)
            out.append([int(v) for v in got[1]] if got else None)
        print(json.dumps(out))
        return 0
    *srcs, out = sys.argv[1:]
    best = None
    for src in srcs:
        got = biggest(src)
        if got and (best is None or got[1][2] * got[1][3] > best[1][1][2] * best[1][1][3]):
            best = (src, got)
    if best is None:
        return 3
    src, (im, (x, y, w, h)) = best
    H, W = im.shape[:2]
    x0, y0 = max(0, int(x - 0.6 * w)), max(0, int(y - 0.8 * h))
    x1, y1 = min(W, int(x + 1.6 * w)), min(H, int(y + 1.7 * h))
    cv2.imwrite(out, im[y0:y1, x0:x1])
    print(src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
