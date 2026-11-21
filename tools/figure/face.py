"""Crop the biggest face out of the photos, with its hair and a little of the shoulders.

python face.py <photo> [<photo> ...] <out.png>   (exit 0 wrote the crop and printed the photo it
came from, 3 found no face)

The face that is biggest in pixels wins across all the photos: a found lead photo is often a whole
person on a stage, with a face a third the size of a close-up's.

Runs on the lift venv's python: opencv 4 has the Haar face finder, opencv 5 dropped it. The
style model keeps a likeness far better with this crop as its first picture: in a whole photo
the face is a few pixels of the render and comes out generic.
"""

import sys

import cv2


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


def main() -> int:
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
