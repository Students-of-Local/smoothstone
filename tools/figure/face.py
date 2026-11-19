"""Crop the biggest face out of a photo, with its hair and a little of the shoulders.

python face.py <photo> <out.png>   (exit 0 wrote the crop, 3 found no face)

Runs on the lift venv's python: opencv 4 has the Haar face finder, opencv 5 dropped it. The
style model keeps a likeness far better with this crop as its first picture: in a whole photo
the face is a few pixels of the render and comes out generic.
"""

import sys

import cv2


def main() -> int:
    src, out = sys.argv[1], sys.argv[2]
    im = cv2.imread(src)
    if im is None:
        return 3
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    if not hasattr(cv2, "CascadeClassifier"):
        return 3
    c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    side = max(40, min(H, W) // 12)
    faces = sorted(c.detectMultiScale(g, 1.1, 6, minSize=(side, side)), key=lambda r: -r[2] * r[3])
    if not len(faces):
        return 3
    x, y, w, h = faces[0]
    x0, y0 = max(0, int(x - 0.6 * w)), max(0, int(y - 0.8 * h))
    x1, y1 = min(W, int(x + 1.6 * w)), min(H, int(y + 1.7 * h))
    cv2.imwrite(out, im[y0:y1, x0:x1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
