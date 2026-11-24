"""stone doctor share and the shared cases: every case in failures/community validates, the scrub, the share
flow against a fake gh (nothing reaches GitHub), and the prior shift the shared cases cause."""

import json
import re
import shutil
import subprocess
from pathlib import Path
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


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.chdir(w)
    monkeypatch.setenv("STONE_JOB", str(w / "stone-job"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"subprocess {a}")))
    monkeypatch.setattr(printers, "gantrel", lambda: None)
    monkeypatch.setattr(share.time, "sleep", lambda s: None)
    return w


def stone(*argv):
    text, code = cli.run(list(argv))
    lines = text.splitlines()
    assert len(lines) <= cli.MAX_LINES and sum(ln.startswith("NEXT:") for ln in lines) == 1, text
    assert "Traceback" not in text and "\u2014" not in text and "\u2013" not in text, text
    return text, code, lines[-1][len("NEXT: "):]


class FakeGh:
    """gh as the tests see it: every call is recorded, none reaches GitHub."""

    def __init__(self, login="somefan", fail=(), open_pr=""):
        self.calls, self.login, self.fail, self.open_pr = [], login, fail, open_pr

    def __call__(self, args, timeout=60):
        self.calls.append(args)
        if any(f in " ".join(args) for f in self.fail):
            return 1, "failed"
        if args[:2] == ["api", "user"]:
            return 0, self.login
        if "git/ref/heads/main" in args[1]:
            return 0, "abc123"
        if args[:2] == ["pr", "create"]:
            return 0, "https://github.com/baney75/smoothstone/pull/999"
        if args[:2] == ["pr", "list"]:
            return 0, self.open_pr
        return 0, ""


def _fixed_case(work):
    stone("doctor", "--image", str(PHOTO), "--printer", "creality_k2")
    stone("doctor", OWNER["said"], "--material", "PLA", "--printer", "creality_k2")
    stone("doctor", "try", "plate_contaminated")
    return stone("doctor", "fixed", "washed the plate with dish soap and water, ask jo@example.com")


def test_fixed_ask_share_dry_then_send(work, monkeypatch):
    gh = FakeGh()
    monkeypatch.setattr(share, "_gh", gh)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    text, code, nxt = _fixed_case(work)
    assert nxt == share.ASK and "MIT license" in nxt and "stone doctor share no" in nxt

    text, code, nxt = stone("doctor", "share")
    assert gh.calls == [] and nxt == share.SEND_ASK  # nothing leaves without --send
    assert "Nothing is sent yet" in text and share.LICENSE_LINE in text and "Removed first: 1 email" in text
    bundle = next((work / "stone-job" / "doctor").glob("*/share"))
    d = json.loads((bundle / "case.json").read_text())
    assert (d["failure"], d["cause"], d["printer"], d["material"]) == ("bed_adhesion", "plate_contaminated", "creality_k2", "PLA")
    assert "[email]" in d["fixed_by"] and share.leaks(json.dumps(d)) == []
    with Image.open(bundle / "photo.jpg") as im:
        assert max(im.size) == share.PX and not im.getexif()

    text, code, nxt = stone("doctor", "share", "--send")
    assert "Sent: https://github.com/baney75/smoothstone/pull/999" in text and nxt == doctor.DONE
    puts = [c[3] for c in gh.calls if c[:3] == ["api", "-X", "PUT"]]
    assert puts == [f"repos/somefan/smoothstone/contents/failures/community/{d['id']}/{n}" for n in ("case.json", "photo.jpg")]
    assert ["repo", "fork", "baney75/smoothstone", "--clone=false"] in gh.calls
    pr = next(c for c in gh.calls if c[:2] == ["pr", "create"])
    assert pr[pr.index("--title") + 1] == "Fixed: bed_adhesion on creality_k2"
    assert pr[pr.index("--head") + 1] == f"somefan:fix/{d['id']}" and not (bundle / ".put.json").exists()
    text, code, nxt = stone("doctor", "share", "--send")
    assert "Already shared" in text and len([c for c in gh.calls if c[:2] == ["pr", "create"]]) == 1
    text, code, nxt = stone("doctor", "share", "no")  # a decline after the send does not claim it stayed home
    assert "Already shared" in text and "Not shared" not in text


def test_dry_run_next_asks_the_person(work, monkeypatch):
    gh = FakeGh()
    monkeypatch.setattr(share, "_gh", gh)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    _fixed_case(work)
    text, code, nxt = stone("doctor", "share")
    assert nxt.startswith("ask the person:") and "show them the photo" in nxt and "send exactly this?" in nxt
    assert nxt.endswith("yes: stone doctor share --send. no: stone doctor share no") and gh.calls == []


def test_decline_after_preview_blocks_send(work, monkeypatch):
    gh = FakeGh()
    monkeypatch.setattr(share, "_gh", gh)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    _fixed_case(work)
    stone("doctor", "share")
    text, code, nxt = stone("doctor", "share", "no")
    assert "Not shared" in text and not list((work / "stone-job" / "doctor").glob("*/share"))
    text, code, nxt = stone("doctor", "share", "--send")
    assert not any(c[:3] == ["api", "-X", "PUT"] or c[:2] == ["pr", "create"] for c in gh.calls), gh.calls
    assert code == 1 and "Nothing was sent" in text and nxt == "stone doctor share"


def test_send_refuses_a_bundle_changed_after_preview(work, monkeypatch):
    gh = FakeGh()
    monkeypatch.setattr(share, "_gh", gh)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    _fixed_case(work)
    stone("doctor", "share")
    bundle = next((work / "stone-job" / "doctor").glob("*/share"))
    d = json.loads((bundle / "case.json").read_text())
    (bundle / "case.json").write_text(json.dumps(d | {"said": "not what the person saw"}))
    text, code, nxt = stone("doctor", "share", "--send")
    assert gh.calls == [] and code == 1 and "Nothing was sent" in text and nxt == "stone doctor share"
    stone("doctor", "share")
    text, code, nxt = stone("doctor", "share", "--send")
    assert "Sent: " in text


def _kinds(gh, *kinds):
    return [c for c in gh.calls if any(c[:len(k)] == k for k in kinds)]


def test_partial_upload_says_what_is_public_and_resumes(work, monkeypatch):
    gh = FakeGh(fail=("photo.jpg",))
    monkeypatch.setattr(share, "_gh", gh)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    _fixed_case(work)
    stone("doctor", "share")
    d = json.loads(next((work / "stone-job" / "doctor").glob("*/share/case.json")).read_text())
    text, code, nxt = stone("doctor", "share", "--send")
    tree = f"https://github.com/somefan/smoothstone/tree/fix/{d['id']}/failures/community/{d['id']}"
    assert "Nothing was sent" not in text and "Public on GitHub now: case.json" in text and tree in text, text
    assert "photo.jpg" not in text.split("Public on GitHub now:")[1].splitlines()[0]
    assert nxt.startswith("ask the person:") and "stone doctor share --send" in nxt
    gh.fail = ()
    text, code, nxt = stone("doctor", "share", "--send")
    assert "Sent: https://github.com/baney75/smoothstone/pull/999" in text and nxt == doctor.DONE
    assert len(_kinds(gh, ["api", "-X", "POST", "repos/somefan/smoothstone/git/refs"])) == 1  # the branch made once
    puts = [c[3].rsplit("/", 1)[1] for c in _kinds(gh, ["api", "-X", "PUT"])]
    assert puts == ["case.json", "photo.jpg", "photo.jpg"]  # case.json is not sent twice


def test_retry_finds_the_open_pull_request(work, monkeypatch):
    gh = FakeGh(fail=("pr create",))
    monkeypatch.setattr(share, "_gh", gh)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    _fixed_case(work)
    stone("doctor", "share")
    text, code, nxt = stone("doctor", "share", "--send")
    assert "Public on GitHub now: case.json, photo.jpg" in text and "gh could not open the pull request" in text
    gh.fail, gh.open_pr = (), "https://github.com/baney75/smoothstone/pull/998"
    text, code, nxt = stone("doctor", "share", "--send")
    assert "Sent: https://github.com/baney75/smoothstone/pull/998" in text
    assert len(_kinds(gh, ["pr", "create"])) == 1 and len(_kinds(gh, ["api", "-X", "PUT"])) == 2


def test_decline_after_a_partial_upload_names_what_stays_public(work, monkeypatch):
    monkeypatch.setattr(share, "_gh", FakeGh(fail=("photo.jpg",)))
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    _fixed_case(work)
    stone("doctor", "share")
    stone("doctor", "share", "--send")
    text, code, nxt = stone("doctor", "share", "no")
    assert "stays on this machine" not in text and "Still public on GitHub: case.json" in text


def test_owner_skips_the_fork(work, monkeypatch):
    gh = FakeGh(login="baney75")
    monkeypatch.setattr(share, "_gh", gh)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/fake/gh")
    _fixed_case(work)
    stone("doctor", "share")
    stone("doctor", "share", "--send")
    assert not any(c[:2] == ["repo", "fork"] for c in gh.calls)
    assert any(c[3].startswith("repos/baney75/smoothstone/contents/") for c in gh.calls if c[:3] == ["api", "-X", "PUT"])


@pytest.mark.parametrize("which,fail,why", [(None, (), "gh is not installed"),
                                            ("/fake/gh", ("auth",), "gh is not signed in"),
                                            ("/fake/gh", ("contents",), "gh could not upload case.json")])
def test_no_gh_gives_an_issue_link(work, monkeypatch, which, fail, why):
    monkeypatch.setattr(share, "_gh", FakeGh(fail=fail))
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: which)
    _fixed_case(work)
    stone("doctor", "share")
    text, code, nxt = stone("doctor", "share", "--send")
    assert f"Nothing was sent: {why}" in text and nxt.startswith("ask the person: open the link above, attach ")
    url = next(ln for ln in text.splitlines() if ln.startswith("https://"))
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://github.com/baney75/smoothstone/issues/new?") and q["template"] == "print-fix.yml"
    assert (q["failure"], q["cause"], q["printer"]) == ("bed_adhesion", "plate_contaminated", "creality_k2")
    fields = re.findall(r"^\s+id: (\w+)$", (REPO / ".github" / "ISSUE_TEMPLATE" / "print-fix.yml").read_text(), re.M)
    assert set(q) - {"template", "title"} <= set(fields)


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
    assert "Printer: bambu_p1s" in text and nxt == share.SEND_ASK


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
