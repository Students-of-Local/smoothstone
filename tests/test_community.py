"""stone doctor share and the shared cases: every case in failures/community validates, the scrub, the share
flow (stone prints a link and runs nothing), and the prior shift the shared cases cause."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from smoothstone import cli, doctor, printers, share

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "community"
CASES = sorted(p.parent for root in (doctor.COMMUNITY, FIXTURES) for p in root.glob("*/case.json"))
KEYS = {"schema", "id", "failure", "cause", "printer", "material", "said", "fixed_by", "answers", "photo",
        "stone_version", "date", "license"}
OWNER = json.loads((REPO / "evals" / "doctor" / "r_k2_detached_plate.json").read_text())
PHOTO = FIXTURES / "2026-11-24-creality_k2-bed_adhesion-8cb14e6" / "photo.jpg"


@pytest.mark.parametrize("case_dir", CASES, ids=[c.name for c in CASES])
def test_every_shared_case_validates(case_dir):
    validate(case_dir)


def validate(case_dir):
    d = json.loads((case_dir / "case.json").read_text())
    assert set(d) == KEYS and d["schema"] == 1 and d["license"] == "MIT"
    f = doctor.failure(d["failure"])
    assert f and d["cause"] in {c["id"] for c in f["causes"]}, (d["failure"], d["cause"])
    assert d["printer"] in printers.load()
    assert d["id"] == case_dir.name and re.fullmatch(rf"\d{{4}}-\d\d-\d\d-{d['printer']}-{d['failure']}-[0-9a-f]{{7}}", d["id"])
    assert d["said"].strip() and d["fixed_by"].strip()
    text = json.dumps(d, ensure_ascii=False)
    assert share.leaks(text) == [] and "\u2014" not in text and "\u2013" not in text
    files = {p.name for p in case_dir.iterdir()}
    assert files == {"case.json"} | ({"photo.jpg"} if d["photo"] else set())
    if d["photo"]:
        with Image.open(case_dir / "photo.jpg") as im:
            assert im.format == "JPEG" and max(im.size) <= share.PX and not im.getexif()  # no EXIF, so no GPS


def test_scrub_removes_private_details():
    said = ("my printer Shopy at 192.168.1.50 (aa:bb:cc:dd:ee:ff) on k2.local, photo in /Users/jo/prints/a.jpg or "
            r"C:\Users\jo\a.jpg or ~/prints, mail jo@example.com, serial SN: K2X9981 and id ABC123DEF456, "
            "stream rtsp://10.0.0.2/live")
    text, gone = share.scrub(said, ["Shopy"])
    for leak in ("Shopy", "192.168", "aa:bb", "k2.local", "/Users", "Users\\jo", "~/prints", "jo@", "K2X9981",
                 "ABC123DEF456", "rtsp"):
        assert leak not in text, (leak, text)
    assert set(gone) == {"link", "email", "path", "address", "host", "serial", "name"} and share.leaks(text) == []
    keep = "washed the PLA/PETG plate with dish soap and water at 60 C, Creality K2, creality_k2, 0.4 mm"
    assert share.scrub(keep, ["Shopy"]) == (keep, [])


SPACED = ("/Volumes/Shop Drive/Jane Doe/failed.stl", r"C:\Users\Jane Doe\Desktop\part.3mf",
          "~/Shop Drive/Jane Doe/failed.stl", "/Users/Jane Doe/Shop Drive")


@pytest.mark.parametrize("path", SPACED)
def test_a_path_with_spaces_goes_whole(path):
    for said in (f"the file {path} failed again", f"open \"{path}\" in the slicer", f"saved to {path}"):
        text, gone = share.scrub(said, [])
        for word in ("Jane", "Doe", "Shop", "Drive", "Users", "Desktop"):
            assert word not in text, (word, text)
        assert "[path]" in text and "path" in gone and share.leaks(text) == [], text
        assert any(found.startswith(path) for found in share.leaks(said)), (path, share.leaks(said))
    if "." in path:  # a last segment with an extension ends the path, so the words after it stay
        assert share.scrub(f"the file {path} failed again", [])[0] == "the file [path] failed again"
    assert share.scrub(f"open \"{path}\" in the slicer", [])[0] == "open \"[path]\" in the slicer"


def test_slashes_in_prose_stay():
    keep = "PLA/PETG plate, a 50/50 mix, and/or 0.2/0.4 mm at 1/2 speed"
    assert share.scrub(keep, []) == (keep, []) and share.leaks(keep) == []


def test_scrub_and_leaks_catch_every_ipv6_form():
    for addr in ("fd00::1234", "::1", "fe80::1", "2001:db8::8a2e:370:7334", "fd00::", "2001:db8:0:0:0:0:2:1", "10.0.0.2"):
        text, gone = share.scrub(f"the printer at {addr} dropped", [])
        assert text == "the printer at [address] dropped" and gone == ["address"], (addr, text)
        assert share.leaks(f"at {addr}"), addr
    assert share.scrub("camera at fd00::1234. Then fe80:1:2:3::5 too", [])[0] == "camera at [address]. Then [address] too"
    keep = "paused at 12:30 and again 1:05:22 in, ratio 3:2"
    assert share.scrub(keep, []) == (keep, []) and share.leaks(keep) == []


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.chdir(w)
    monkeypatch.setenv("STONE_JOB", str(w / "stone-job"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"subprocess {a}")))
    monkeypatch.setattr(printers, "gantrel", lambda: None)
    return w


def stone(*argv):
    text, code = cli.run(list(argv))
    lines = text.splitlines()
    assert len(lines) <= cli.MAX_LINES and sum(ln.startswith("NEXT:") for ln in lines) == 1, text
    assert "Traceback" not in text and "\u2014" not in text and "\u2013" not in text, text
    return text, code, lines[-1][len("NEXT: "):]


def _fixed_case(work):
    stone("doctor", "--image", str(PHOTO), "--printer", "creality_k2")
    stone("doctor", OWNER["said"], "--material", "PLA", "--printer", "creality_k2")
    stone("doctor", "try", "plate_contaminated")
    return stone("doctor", "fixed", "washed the plate with dish soap and water, ask jo@example.com")


def _bundle(work):
    return next((work / "stone-job" / "doctor").glob("*/share"))


def test_fixed_ask_share_link_then_done(work):
    text, code, nxt = _fixed_case(work)
    assert nxt == share.ASK and "MIT license" in nxt and "stone doctor share no" in nxt

    text, code, nxt = stone("doctor", "share")  # the work fixture fails any subprocess: stone runs nothing
    assert code == 0 and nxt == share.LINK_ASK and "stone sends nothing" in text
    assert share.LICENSE_LINE in text and "Removed first: 1 email" in text
    bundle = _bundle(work)
    d = json.loads((bundle / "case.json").read_text())
    assert (d["failure"], d["cause"], d["printer"], d["material"]) == ("bed_adhesion", "plate_contaminated", "creality_k2", "PLA")
    assert "[email]" in d["fixed_by"] and share.leaks(json.dumps(d)) == []
    assert {f.name for f in bundle.iterdir()} == {"case.json", "photo.jpg"} and f"Photo: {bundle / 'photo.jpg'}" in text
    with Image.open(bundle / "photo.jpg") as im:
        assert max(im.size) == share.PX and not im.getexif()
    url = next(ln for ln in text.splitlines() if ln.startswith("https://"))
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://github.com/baney75/smoothstone/issues/new?") and q["template"] == "print-fix.yml"
    assert (q["failure"], q["cause"], q["printer"]) == ("bed_adhesion", "plate_contaminated", "creality_k2")
    assert q["title"] == "Fixed: bed_adhesion on creality_k2" and q["fixed_by"] == d["fixed_by"]
    fields = re.findall(r"^\s+id: (\w+)$", (REPO / ".github" / "ISSUE_TEMPLATE" / "print-fix.yml").read_text(), re.M)
    assert set(q) - {"template", "title"} <= set(fields)

    text, code, nxt = stone("doctor", "share", "done")
    assert code == 0 and nxt == doctor.DONE
    assert share.last_fixed(SimpleNamespace(root=work / "stone-job"))["share"]["state"] == "linked"
    text, code, nxt = stone("doctor", "share")
    assert "Already shared" in text and "https://" not in text and nxt == doctor.DONE
    text, code, nxt = stone("doctor", "share", "no")  # a decline after the person submitted it does not claim it stayed home
    assert "Already shared" in text and "Not shared" not in text and _bundle(work).is_dir()


def test_dry_run_next_asks_the_person():
    nxt = share.LINK_ASK
    assert nxt.startswith("ask the person:") and "show them the photo" in nxt and "stone sends nothing" in nxt
    assert nxt.endswith("yes: stone doctor share done. no: stone doctor share no")


def test_decline_after_preview(work):
    _fixed_case(work)
    stone("doctor", "share")
    text, code, nxt = stone("doctor", "share", "no")
    assert "Not shared" in text and nxt == doctor.DONE and not list((work / "stone-job" / "doctor").glob("*/share"))
    assert share.last_fixed(SimpleNamespace(root=work / "stone-job"))["share"] == {"state": "declined"}
    text, code, nxt = stone("doctor", "share", "done")  # done after a decline records nothing
    assert code == 1 and nxt == "stone doctor share"
    assert share.last_fixed(SimpleNamespace(root=work / "stone-job"))["share"] == {"state": "declined"}


def test_done_before_any_preview_records_nothing(work):
    _fixed_case(work)
    text, code, nxt = stone("doctor", "share", "done")
    assert code == 1 and nxt == "stone doctor share" and "share" not in share.last_fixed(SimpleNamespace(root=work / "stone-job"))


def test_every_typed_field_is_scrubbed(work):
    stone("doctor", "--image", str(PHOTO), "--printer", "creality_k2")
    stone("doctor", "the print came off the plate; camera at fd00::1234", "--material", "jo@example.com",
          "--printer", "creality_k2")
    stone("doctor", "try", "plate_contaminated")
    stone("doctor", "fixed", "washed the plate")
    text, code, nxt = stone("doctor", "share")
    d = json.loads(next((work / "stone-job" / "doctor").glob("*/share/case.json")).read_text())
    assert d["material"] == "[email]" and "[address]" in d["said"], d
    raw = json.dumps(d)
    assert "fd00" not in raw and "@" not in raw and share.leaks(raw) == [] and "fd00" not in text
    assert share.leaks(raw.replace("[address]", "fd00::1234")) and share.leaks(raw.replace("[email]", "JO@EXAMPLE.COM"))


def test_a_detail_the_scrub_missed_gives_no_link(work, monkeypatch):
    scrub = share.scrub
    stone("doctor", "--image", str(PHOTO), "--printer", "creality_k2")
    stone("doctor", "the print came off; camera at fd00::1234", "--material", "jo@example.com", "--printer", "creality_k2")
    stone("doctor", "try", "plate_contaminated")
    stone("doctor", "fixed", "washed the plate")
    monkeypatch.setattr(share, "scrub", lambda text, names=(): (text, []))  # a scrub that misses everything
    text, code, nxt = stone("doctor", "share")
    assert code == 1 and "still holds" in text and "https://" not in text and nxt == doctor.DONE, text
    assert "fd00" not in text and "jo@" not in text
    monkeypatch.setattr(share, "scrub", scrub)
    text, code, nxt = stone("doctor", "share", "done")  # the held case cannot be marked shared
    assert code == 1 and nxt == "stone doctor share"


def test_spaced_paths_in_the_words_and_material_never_reach_the_bundle(work):
    stone("doctor", "--image", str(PHOTO), "--printer", "creality_k2")
    stone("doctor", "the print from /Volumes/Shop Drive/Jane Doe/failed.stl came off the plate",
          "--material", r"C:\Users\Jane Doe\Desktop\part.3mf", "--printer", "creality_k2")
    stone("doctor", "try", "plate_contaminated")
    stone("doctor", "fixed", "washed the plate, file in ~/Shop Drive/Jane Doe/failed.stl")
    text, code, nxt = stone("doctor", "share")
    d = json.loads(next((work / "stone-job" / "doctor").glob("*/share/case.json")).read_text())
    raw = json.dumps(d)
    for word in ("Jane", "Doe", "Shop", "Drive"):
        assert word not in raw and word not in text, (word, raw)
    assert d["material"] == "[path]" and "[path]" in d["said"] and "[path]" in d["fixed_by"], d
    assert share.leaks(raw) == []


def test_dashes_in_the_words_pass_the_community_check(work, tmp_path):
    _fixed_case(work)
    job = SimpleNamespace(root=work / "stone-job")
    case = share.last_fixed(job)
    case["said"] = "the print came off \u2014 twice \u2014 on the 1\u20132 mm part"
    case["outcome"]["what_worked"] = "washed the plate\u2014then dried it"
    bundle, d, gone = share.build(job, case)
    assert d["said"] == "the print came off, twice, on the 1-2 mm part" and d["fixed_by"] == "washed the plate, then dried it"
    dest = tmp_path / d["id"]
    dest.mkdir()
    for name in ("case.json", "photo.jpg"):
        shutil.copy(bundle / name, dest / name)
    validate(dest)


def test_no_declines_and_nothing_to_share(work):
    text, code, nxt = stone("doctor", "share")
    assert code == 1 and "no fixed doctor case" in text
    _fixed_case(work)
    text, code, nxt = stone("doctor", "share", "no")
    assert "Not shared" in text and nxt == doctor.DONE
    assert not list((work / "stone-job" / "doctor").glob("*/share"))


def test_a_case_without_a_printer_asks_for_one(work):
    stone("doctor", "the print came off the bed")
    stone("doctor", "fixed", "cleaned the plate")
    text, code, nxt = stone("doctor", "share")
    assert code == 1 and "stone doctor share --printer" in nxt
    text, code, nxt = stone("doctor", "share", "--printer", "bambu_p1s")
    assert "Printer: bambu_p1s" in text and "Photo: none" in text and nxt == share.LINK_ASK


# learning from shared cases


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setattr(doctor, "COMMUNITY", FIXTURES)
    doctor.community.cache_clear()
    yield
    doctor.community.cache_clear()


def test_community_prior_shift(work, shared, monkeypatch):
    said, k2 = "the print came off the bed", printers.get("creality_k2")
    monkeypatch.setattr(doctor, "COMMUNITY", work / "none")
    doctor.community.cache_clear()
    before = doctor.diagnose(said, k2)["causes"]
    # 3 fixture cases on the K2: plate_contaminated 2, first_layer_too_high 1; 5 causes: K (n + 1) / (M + K)
    f = doctor.failure("bed_adhesion")
    monkeypatch.setattr(doctor, "COMMUNITY", FIXTURES)
    doctor.community.cache_clear()
    mult = doctor.community_mult(f, "creality_k2")
    assert mult["plate_contaminated"] == pytest.approx(5 * 3 / 8) and mult["cold_room"] == pytest.approx(5 / 8)
    after = doctor.diagnose(said, k2)["causes"]
    assert after["plate_contaminated"] > before["plate_contaminated"] and after["cold_room"] < before["cold_room"]
    ratio = lambda p: p["plate_contaminated"] / p["cold_room"]
    assert ratio(after) / ratio(before) == pytest.approx(3.0)  # 1.875 / 0.625
    assert doctor.community_mult(f, "bambu_p1s") == {}  # another printer: no shift
    print(f"plate_contaminated on the K2: {before['plate_contaminated']:.0%} before, {after['plate_contaminated']:.0%} after")

    text, code, nxt = stone("doctor", said, "--printer", "creality_k2")
    assert "On Creality K2, 2 of 3 shared bed_adhesion cases were fixed by plate_contaminated" in text
    assert doctor.examples("bed_adhesion", "creality_k2")[0] == str(PHOTO)


def test_the_cap(shared, monkeypatch, tmp_path):
    for i in range(40):
        (tmp_path / f"c{i}").mkdir()
        (tmp_path / f"c{i}" / "case.json").write_text(json.dumps({"printer": "creality_k2", "failure": "bed_adhesion",
                                                                     "cause": "plate_contaminated"}))
    monkeypatch.setattr(doctor, "COMMUNITY", tmp_path)
    doctor.community.cache_clear()
    mult = doctor.community_mult(doctor.failure("bed_adhesion"), "creality_k2")
    assert mult["plate_contaminated"] == doctor.CAP and mult["cold_room"] == pytest.approx(1 / doctor.CAP)
