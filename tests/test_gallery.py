"""The failure photo gallery: every photo labeled with a taxonomy id, licensed for an MIT repo, small and clean."""

import importlib.util
import json

from PIL import Image

from test_cli import REPO

GALLERY = REPO / "failures" / "gallery"
spec = importlib.util.spec_from_file_location("gallery_credits", REPO / "tools" / "gallery_credits.py")
credits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credits)
LABELS = credits.load()
IDS = credits.failure_ids()
GPS_IFD = 0x8825


def test_taxonomy_is_the_program_list():
    ids = json.loads(credits.TAXONOMY.read_text())["ids"]
    assert len(ids) == 29 and "bed_adhesion" in ids and "other" in ids
    assert all(k == k.lower() and " " not in k for k in ids)


def test_every_label_is_complete_and_allowed():
    files = set()
    for l in LABELS:
        where = l["file"]
        assert where not in files, f"{where}: listed twice"
        files.add(where)
        assert (GALLERY / where).is_file(), f"{where}: no such file"
        assert l["failure"] in IDS or l["failure"] == credits.HEALTHY, f"{where}: {l['failure']}"
        assert where.split("/")[0] == l["failure"], f"{where}: folder is not its failure id"
        assert set(l["also"]) <= IDS and l["failure"] not in l["also"], f"{where}: also {l['also']}"
        assert l["license"] in credits.LICENSES, f"{where}: license {l['license']}"
        assert l["author"].strip(), f"{where}: no author"
        assert l["note"].strip(), f"{where}: no note saying what is visible"
        assert l["source"].strip(), f"{where}: no source"
        if not l["synthetic"] and l["license"] != "MIT":
            assert l["url"] and l["url"].startswith("https://"), f"{where}: no url"
        assert isinstance(l["synthetic"], bool)
        for k in ("printer", "material"):
            assert l[k] is None or (isinstance(l[k], str) and l[k].strip()), f"{where}: {k}"


def test_no_photo_without_a_label():
    on_disk = {p.relative_to(GALLERY).as_posix() for p in GALLERY.rglob("*.jpg")}
    assert on_disk == {l["file"] for l in LABELS}


def test_photos_are_small_and_carry_no_metadata():
    total = 0
    for l in LABELS:
        p = GALLERY / l["file"]
        total += p.stat().st_size
        with Image.open(p) as im:
            assert im.format == "JPEG", l["file"]
            assert max(im.size) <= 768, f"{l['file']}: {im.size}"
            exif = im.getexif()
            assert GPS_IFD not in exif and not exif.get_ifd(GPS_IFD), f"{l['file']}: GPS in EXIF"
            assert len(exif) == 0, f"{l['file']}: EXIF left in"
    assert total < 25 * 1024 * 1024, f"gallery is {total / 1e6:.1f} MB"


def test_credits_match_labels():
    assert credits.CREDITS.read_text() == credits.render(LABELS), "run uv run python tools/gallery_credits.py"


def test_gallery_has_no_em_or_en_dashes():
    for p in (credits.LABELS, credits.CREDITS, GALLERY / "README.md"):
        text = p.read_text()
        assert "\u2014" not in text and "\u2013" not in text, p.name


def test_gallery_floor():
    """A floor, not a target: raise it when photos are added, never lower it without a LOG.md line."""
    real = [l for l in LABELS if not l["synthetic"] and l["failure"] != credits.HEALTHY]
    healthy = [l for l in LABELS if l["failure"] == credits.HEALTHY]
    assert len(real) >= FLOOR_REAL_FAILURES
    assert len({l["failure"] for l in real}) >= FLOOR_FAILURE_IDS
    assert len(healthy) >= 30
    assert any(l["printer"] == "creality_k2" and l["failure"] == "bed_adhesion" for l in LABELS)


FLOOR_REAL_FAILURES = 151
FLOOR_FAILURE_IDS = 25
