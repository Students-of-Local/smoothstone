import importlib.util
import json
import urllib.parse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
spec = importlib.util.spec_from_file_location("judge_likeness", ROOT / "evals" / "judge_likeness.py")
jl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jl)
sys.modules["judge_likeness"] = jl
spec = importlib.util.spec_from_file_location("run_evals", ROOT / "evals" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

DHH = "A mini figure of DHH, 90 mm tall, with \"DHH\" on the base."


@pytest.fixture(autouse=True)
def _no_photos_picked_by_hand(tmp_path, monkeypatch):
    monkeypatch.setattr(jl, "REFS_FILE", tmp_path / "no_refs.json")


def _canvas(seed: int, size=(64, 64)):
    """A picture whose look is set by seed: bright blocks at places the seed picks."""
    import random
    from PIL import Image, ImageDraw
    rng = random.Random(seed)
    w, h = size
    im = Image.new("RGB", size, (20, 20, 20))
    d = ImageDraw.Draw(im)
    for k in range(6):
        x, y = rng.randrange(w - 14), rng.randrange(h - 10)
        d.rectangle([x, y, x + 14, y + 10], fill=(230, 200 - 30 * (k % 3), 160))
    return im


def _picture(seed: int, fmt="JPEG") -> bytes:
    """A small picture whose look is set by seed; the same seed in another format or size is the
    same picture."""
    import io
    im = _canvas(seed)
    if fmt == "PNG":
        im = im.resize((128, 128))
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def _served(url: str) -> bytes:
    """What a photo link serves: a picture of its own (seeded by the link) in the format its
    suffix names, or an SVG's text."""
    import zlib
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith(".svg"):
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
    return _picture(zlib.crc32(url.encode()), "PNG" if path.endswith(".png") else "JPEG")


def _job(tmp_path, renders=("k",)):
    job = tmp_path / "job"
    for k in renders:
        d = job / "image" / "figure" / k
        d.mkdir(parents=True)
        (d / "style.png").write_bytes(b"png " + k.encode())
    return job


def _fake(monkeypatch, title, score, conflicts=()):
    asked = []

    def claude(prompt, folder=None, model="opus"):
        asked.append((prompt, folder and sorted(p.name for p in Path(folder).iterdir())))
        if folder is None:
            return title
        return json.dumps({"score": score, "conflicts": list(conflicts)})

    def get(url, timeout=60):
        if "api.php" in url:
            assert "David+Heinemeier+Hansson" in url or "Elon+Musk" in url
            return json.dumps({"query": {"pages": {"1": {"title": title, "description": "Danish programmer",
                                                         "original": {"source": "https://up/x/ref.jpg"}}}}}).encode()
        return _served(url)

    monkeypatch.setattr(jl, "claude", claude)
    monkeypatch.setattr(jl, "_get", get)
    return asked


def test_an_article_that_leads_with_a_logo_gives_its_first_photo(monkeypatch):
    """Petronas Towers: the lead image is a logo, and the judge could not answer."""
    items = [{"title": "File:Logo.svg", "srcset": [{"src": "//up/logo.svg.png"}]}, {"title": "File:Anthem.ogg"},
             {"title": "File:Twins 2019.JPG", "srcset": [{"src": "//up/small.jpg"}, {"src": "//up/large.jpg"}]}]
    def get(url, timeout=60):
        if "media-list/Petronas_Towers" in url:
            return json.dumps({"items": items}).encode()
        return json.dumps({"query": {"pages": {"1": {"title": "Petronas Towers",
                                                     "original": {"source": "https://up/Logo.svg?utm=x"}}}}}).encode()

    monkeypatch.setattr(jl, "_get", get)
    assert jl.reference("Petronas Towers")["url"] == "https://up/large.jpg"
    del items[2]
    with pytest.raises(jl.JudgeProblem, match="no photo"):
        jl.reference("Petronas Towers")


def test_the_reference_comes_from_the_article_the_judge_names_not_the_tools_photos(tmp_path, monkeypatch):
    """For "DHH" the tool styled a protein and every check passed a made up man (judged 3/10)."""
    job = _job(tmp_path)
    asked = _fake(monkeypatch, "David Heinemeier Hansson", 3,
                  [{"feature": "facial hair", "what": "a full beard on a clean shaven face"}])
    res = jl.judge(job, DHH)
    assert not res["pass"] and res["score"] == 3
    assert res["reference"]["title"] == "David Heinemeier Hansson"
    assert asked[1][1] == ["reference.jpg", "render.png"]  # the job's own photos are never shown


def test_a_figure_that_is_not_the_subject_fails_the_run_with_the_judges_words(tmp_path, monkeypatch):
    job = _job(tmp_path)
    _fake(monkeypatch, "David Heinemeier Hansson", 3, [{"feature": "glasses", "what": "round gold frames"}])
    grade = run.likeness_run(tmp_path, job, DHH, {"pass": True, "why": ["all checks pass"]})
    assert not grade["pass"] and grade["likeness"] == 3
    assert grade["why"] == ["likeness 3/10: glasses: round gold frames"]
    assert json.loads((tmp_path / "likeness.json").read_text())["score"] == 3


def test_a_likeness_at_the_bar_keeps_the_pass(tmp_path, monkeypatch):
    job = _job(tmp_path)
    _fake(monkeypatch, "Elon Musk", jl.PASS)
    grade = run.likeness_run(tmp_path, job, "A mini figure of Elon Musk", {"pass": True, "why": ["all checks pass"]})
    assert grade["pass"] and grade["likeness"] == jl.PASS


def test_a_judge_that_cannot_answer_fails_the_run(tmp_path, monkeypatch):
    job = tmp_path / "job"
    job.mkdir()
    grade = run.likeness_run(tmp_path, job, DHH, {"pass": True, "why": ["all checks pass"]})
    assert not grade["pass"] and "could not answer" in grade["why"][0]


def test_the_render_judged_is_the_one_the_figure_was_made_from(tmp_path):
    job = _job(tmp_path, renders=("old", "new"))
    (job / "image" / "figure" / "latest.txt").write_text(str(job / "image" / "figure" / "new" / "figure.stl"))
    assert jl.render_of(job).parent.name == "new"


def test_a_reply_of_the_wrong_shape_is_a_judge_problem():
    with pytest.raises(jl.JudgeProblem):
        jl.parse("no json here")
    with pytest.raises(jl.JudgeProblem):
        jl.parse('{"score": 11, "conflicts": []}')
    assert jl.parse('ok {"score": 7, "conflicts": [{"feature": "hair", "what": "lighter"}]}')["score"] == 7


def test_a_spec_can_set_a_higher_likeness_bar(tmp_path, monkeypatch):
    """Owner: "Those things look nothing like elon". The chibi Elon he saw was judged 5 to 7, so
    the spec for that fault asks 8, above the judge's own bar."""
    job = _job(tmp_path)
    _fake(monkeypatch, "Elon Musk", 7, [{"feature": "face", "what": "a generic cartoon face"}])
    grade = run.likeness_run(tmp_path, job, "A mini figure of Elon Musk", {"pass": True, "why": ["all checks pass"]},
                             least=8)
    assert not grade["pass"] and grade["why"] == ["likeness 7/10, the spec asks 8: face: a generic cartoon face"]
    _fake(monkeypatch, "Elon Musk", 8)
    assert run.likeness_run(tmp_path, job, "A mini figure of Elon Musk", {"pass": True, "why": []}, least=8)["pass"]


def _rejudge_module():
    s = importlib.util.spec_from_file_location("rejudge", ROOT / "evals" / "rejudge.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _run_dir(tmp_path, why, spec_text):
    rdir = tmp_path / "run"
    _job(rdir)
    sha = __import__("hashlib").sha256(spec_text).hexdigest()
    (rdir / "log.json").write_text(json.dumps({"run_id": "r", "spec": "f3_elon", "suite": "figure", "card": "S",
                                               "driver": "lfm3", "spec_sha256": sha, "pass": False, "why": why}))
    return rdir


def test_a_run_the_judge_could_not_answer_is_judged_again_and_scored(tmp_path, monkeypatch):
    """On the Mac `claude` was not signed in: Elon's run passed every check and failed unjudged."""
    rj = _rejudge_module()
    monkeypatch.setattr(rj.run, "SCORES", tmp_path / "scores.jsonl")
    spec_text = (ROOT / "evals" / "figure" / "f3_elon.json").read_bytes()
    rdir = _run_dir(tmp_path, ["likeness: the judge could not answer (Not logged in)"], spec_text)
    _fake(monkeypatch, "Elon Musk", 9)
    monkeypatch.setattr(jl, "_get", lambda url, timeout=60: json.dumps({"query": {"pages": {"1": {
        "title": "Elon Musk", "original": {"source": "https://up/e.jpg"}}}}}).encode()
        if "api.php" in url else _served(url))
    log = rj.rejudge(rdir)
    assert log["pass"] and log["likeness"] == 9 and log["rejudged"]
    assert json.loads((tmp_path / "scores.jsonl").read_text())["pass"] == 1


def test_rejudging_never_passes_a_run_that_failed_another_check(tmp_path, monkeypatch):
    rj = _rejudge_module()
    monkeypatch.setattr(rj.run, "SCORES", tmp_path / "scores.jsonl")
    spec_text = (ROOT / "evals" / "figure" / "f3_elon.json").read_bytes()
    rdir = _run_dir(tmp_path, ["height 80 mm, asked 90", "likeness: the judge could not answer (x)"], spec_text)
    _fake(monkeypatch, "Elon Musk", 9)
    monkeypatch.setattr(jl, "_get", lambda url, timeout=60: json.dumps({"query": {"pages": {"1": {
        "title": "Elon Musk", "original": {"source": "https://up/e.jpg"}}}}}).encode()
        if "api.php" in url else _served(url))
    log = rj.rejudge(rdir)
    assert not log["pass"] and log["why"][0] == "height 80 mm, asked 90"


def test_a_rejudged_run_replaces_its_own_score_line(tmp_path, monkeypatch):
    """F3: run.py had scored the unjudged run pass=0, and rejudge added a second line, so it counted twice."""
    rj = _rejudge_module()
    scores = tmp_path / "scores.jsonl"
    other = {"spec": "f4_dhh", "pass": 1, "run": "q"}
    first = {"spec": "f3_elon", "pass": 0, "run": "r"}
    scores.write_text(json.dumps(other) + "\n" + json.dumps(first) + "\n" + json.dumps({**other, "run": "s"}) + "\n")
    monkeypatch.setattr(rj.run, "SCORES", scores)
    spec_text = (ROOT / "evals" / "figure" / "f3_elon.json").read_bytes()
    rdir = _run_dir(tmp_path, ["likeness: the judge could not answer (Not logged in)"], spec_text)
    _fake(monkeypatch, "Elon Musk", 9)
    monkeypatch.setattr(jl, "_get", lambda url, timeout=60: json.dumps({"query": {"pages": {"1": {
        "title": "Elon Musk", "original": {"source": "https://up/e.jpg"}}}}}).encode()
        if "api.php" in url else _served(url))
    rj.rejudge(rdir)
    lines = [json.loads(x) for x in scores.read_text().splitlines()]
    assert [x["run"] for x in lines] == ["q", "r", "s"]
    assert lines[0] == other and lines[2] == {**other, "run": "s"}
    assert lines[1]["pass"] == 1 and lines[1]["likeness"] == 9 and lines[1]["spec"] == "f3_elon"
    assert not list(tmp_path.glob("scores.jsonl.*"))


def test_a_spec_changed_since_the_run_is_not_rejudged(tmp_path, monkeypatch):
    rj = _rejudge_module()
    rdir = _run_dir(tmp_path, ["likeness: the judge could not answer (x)"], b"an older spec")
    with pytest.raises(SystemExit, match="changed since run"):
        rj.rejudge(rdir)


def _found(job, *titles):
    d = job / "image" / "found"
    d.mkdir(parents=True)
    (d / "found.json").write_text(json.dumps({"photos": [{"title": t} for t in titles]}))


def _article(monkeypatch, files, search=(), title="Elon Musk", lead="Elon_Musk_ref.jpg"):
    """The fake article leads with https://up/x/<lead>; files are its other images and search what
    a Commons search returns, each at https://up/x/<name> (a 1600 px thumb)."""
    def get(url, timeout=60):
        if "prop=images" in url:
            return json.dumps({"query": {"pages": {"1": {"images": [{"title": f} for f in files]}}}}).encode()
        if "list=search" in url:
            return json.dumps({"query": {"search": [{"title": f} for f in search]}}).encode()
        if "prop=imageinfo" in url:
            ts = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["titles"][0].split("|")
            return json.dumps({"query": {"pages": {str(k): {"title": t, "imageinfo": [
                {"thumburl": "https://up/x/" + urllib.parse.quote(t[5:].replace(" ", "_"))}]}
                for k, t in enumerate(ts)}}}).encode()
        if "api.php" in url:
            return json.dumps({"query": {"pages": {"1": {"title": title, "description": "someone",
                                                         "original": {"source": "https://up/x/" + lead}}}}}).encode()
        return _served(url)
    monkeypatch.setattr(jl, "_get", get)


def test_the_reference_is_never_a_photo_the_tool_styled_from(tmp_path, monkeypatch):
    """Review of PR 23: the article's lead image is often Wikidata's, which the tool put first, so
    the judge compared the render with its own source and measured copying, not likeness."""
    job = _job(tmp_path)
    _found(job, "File:Elon Musk ref.jpg", "File:Elon Musk 2.jpg")
    _fake(monkeypatch, "Elon Musk", 8)
    _article(monkeypatch, ["File:Tesla logo.svg", "File:Elon Musk 2.jpg", "File:Elon Musk Royal Society.jpg"])
    res = jl.judge(job, "A mini figure of Elon Musk")
    assert res["reference"]["url"] == "https://up/x/Elon_Musk_Royal_Society.jpg"
    assert res["reference"]["instead_of"] == "Elon Musk ref.jpg"


def test_no_reference_apart_from_the_tools_photos_is_no_verdict(tmp_path, monkeypatch):
    job = _job(tmp_path)
    _found(job, "File:Elon Musk ref.jpg")
    _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, ["File:Tesla logo.svg", "File:SpaceX factory.jpg"])
    with pytest.raises(jl.JudgeProblem, match="tool"):
        jl.judge(job, "A mini figure of Elon Musk")


def test_the_judge_sees_the_lead_and_newer_photos_of_the_subject_newest_first(tmp_path, monkeypatch):
    """DHH's lead image is him in a racing suit and Jensen's is ten years old, so one photo judged
    the hair and clothes of the wrong years; more photos named for the subject go with it."""
    job = _job(tmp_path)
    _found(job, "File:David Heinemeier Hansson 2019.jpg")
    asked = _fake(monkeypatch, "David Heinemeier Hansson", 8)
    _article(monkeypatch, ["File:Ruby on Rails logo.svg", "File:David Heinemeier Hansson 2010.jpg"],
             search=["File:Porsche 911 RSR.jpg", "File:David Heinemeier Hansson 2019.jpg",
                     "File:Oreca 07 - David Heinemeier-Hansson, Fabio Scherer & Pietro Fittipaldi at Le Mans 20240616.jpg",
                     "File:David Heinemeier Hansson 2023.jpg", "File:David Heinemeier Hansson 2015.jpg"],
             title="David Heinemeier Hansson", lead="DHH_racing.jpg")
    res = jl.judge(job, DHH)
    assert [p["url"] for p in res["reference"]["photos"]] == [
        "https://up/x/DHH_racing.jpg", "https://up/x/David_Heinemeier_Hansson_2023.jpg",
        "https://up/x/David_Heinemeier_Hansson_2015.jpg"]
    prompt, shown = asked[1]
    assert shown == ["reference_1.jpg", "reference_2.jpg", "reference_3.jpg", "render.png"]
    assert "most recent" in prompt and "2019" not in prompt  # the tool's own photo never goes in


def test_no_reference_that_shows_the_subject_is_no_verdict(tmp_path, monkeypatch):
    job = _job(tmp_path)
    monkeypatch.setattr(jl, "claude", lambda prompt, folder=None, model="opus":
                        "David Heinemeier Hansson" if folder is None else
                        json.dumps({"score": 5, "conflicts": [], "usable": False}))
    _article(monkeypatch, [], search=["File:David Heinemeier Hansson 2023.jpg"],
             title="David Heinemeier Hansson", lead="DHH_racing.jpg")
    with pytest.raises(jl.JudgeProblem, match="shows the subject"):
        jl.judge(job, DHH)


def test_a_year_is_read_from_the_dates_commons_file_names_carry():
    assert jl._year("statue of liberty, new york city, 20231003 1512 1976.jpg") == 2023
    assert jl._year("jensen huang stanford 2026-04-30 011.jpg") == 2026
    assert jl._year("david heinemeier hansson (27225732035).jpg") == 0


def test_a_subject_whose_free_photos_the_tool_used_up_is_judged_by_a_photo_picked_by_hand(tmp_path, monkeypatch):
    """Every portrait of DHH on Commons was one the tool styled from, the rest are race cars, so
    the judge had none to go by; evals/likeness_refs.json names one picked outside the tool."""
    job = _job(tmp_path)
    _found(job, "File:DHH racing.jpg", "File:David Heinemeier Hansson.jpg")
    refs = tmp_path / "likeness_refs.json"
    refs.write_text(json.dumps({"David Heinemeier Hansson": [
        {"url": "https://dhh.dk/images/new-headshot.jpg", "source": "his own site, dhh.dk"}]}))
    monkeypatch.setattr(jl, "REFS_FILE", refs)
    asked = _fake(monkeypatch, "David Heinemeier Hansson", 7)
    _article(monkeypatch, [], search=["File:Oreca 07 - David Heinemeier-Hansson at Le Mans 2023.jpg"],
             title="David Heinemeier Hansson", lead="DHH_racing.jpg")
    res = jl.judge(job, DHH)
    assert res["score"] == 7
    assert res["reference"]["photos"][0]["url"] == "https://dhh.dk/images/new-headshot.jpg"
    prompt, shown = asked[1]
    assert "dhh.dk" in prompt and shown == ["reference_1.jpg", "reference_2.jpg", "render.png"]


def test_a_crop_of_the_tools_photo_is_the_tools_photo(tmp_path, monkeypatch):
    """Review of PR 24: the tool styled from "Elon Musk 2019 (cropped).jpg" and the search found
    "Elon Musk 2019.jpg", the same picture uncropped, which the judge took as independent."""
    job = _job(tmp_path)
    _found(job, "File:Elon Musk ref.jpg", "File:Elon Musk 2019 (cropped).jpg")
    _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, [], search=["File:Elon Musk 2019.jpg", "File:Elon Musk (crop2) 2015.jpg",
                                      "File:Elon Musk 2011.jpg"])
    res = jl.judge(job, "A mini figure of Elon Musk")
    assert [p["file"] for p in res["reference"]["photos"]] == ["Elon Musk (crop2) 2015.jpg", "Elon Musk 2011.jpg"]


def test_a_relative_with_the_subjects_surname_is_never_a_reference(tmp_path, monkeypatch):
    job = _job(tmp_path)
    _found(job, "File:Elon Musk ref.jpg")
    _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, [], search=["File:Kimbal Musk 2025.jpg", "File:Maye Musk 2024.jpg", "File:Elon Musk 2018.jpg"])
    res = jl.judge(job, "A mini figure of Elon Musk")
    assert [p["file"] for p in res["reference"]["photos"]] == ["Elon Musk 2018.jpg"]


def test_one_searched_photo_still_tells_the_judge_it_may_not_show_the_subject(tmp_path, monkeypatch):
    job = _job(tmp_path)
    _found(job, "File:Elon Musk ref.jpg")
    asked = _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, [], search=["File:Elon Musk Tesla Roadster 2018.jpg"])
    jl.judge(job, "A mini figure of Elon Musk")
    assert '"usable": false' in asked[1][0]


def test_a_year_still_to_come_or_run_on_from_a_word_is_no_year():
    assert jl._year("elon musk 2099.jpg") == 0
    assert jl._year("img_2019.jpg") == 0


def test_a_photo_picked_by_hand_that_the_tool_styled_from_is_never_a_reference(tmp_path, monkeypatch):
    """Review of PR 24 (second-S1): the hand-picked DHH headshot skipped the check that keeps out
    the tool's own photos, so a job built from that headshot was judged against its own source."""
    job = _job(tmp_path)
    _found(job, "File:Elon Musk ref.jpg", "File:new-headshot.jpg")
    refs = tmp_path / "likeness_refs.json"
    refs.write_text(json.dumps({"Elon Musk": [{"url": "https://dhh.dk/images/new-headshot.jpg", "source": "a site"}]}))
    monkeypatch.setattr(jl, "REFS_FILE", refs)
    _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, [], search=["File:Elon Musk 2018.jpg"])
    res = jl.judge(job, "A mini figure of Elon Musk")
    assert [p["file"] for p in res["reference"]["photos"]] == ["Elon Musk 2018.jpg"]


def test_a_reference_that_is_the_photo_the_owner_gave_is_never_shown(tmp_path, monkeypatch):
    """Review of PR 24 (second-S1): the owner gives the tool the same headshot the judge would go
    by (`stone image new-headshot.jpg`, kept as image/source.*), re-encoded or not."""
    job = _job(tmp_path)
    (job / "image" / "source.png").write_bytes(_picture(1, "PNG"))
    refs = tmp_path / "likeness_refs.json"
    refs.write_text(json.dumps({"David Heinemeier Hansson": [
        {"url": "https://dhh.dk/images/new-headshot.jpg", "source": "his own site, dhh.dk"}]}))
    monkeypatch.setattr(jl, "REFS_FILE", refs)
    asked = _fake(monkeypatch, "David Heinemeier Hansson", 9)
    _article(monkeypatch, [], search=["File:David Heinemeier Hansson 2015.jpg"],
             title="David Heinemeier Hansson", lead="DHH_racing.jpg")
    get = jl._get
    pics = {"new-headshot.jpg": _picture(1), "DHH_racing.jpg": _picture(2),
            "David_Heinemeier_Hansson_2015.jpg": _picture(3)}
    monkeypatch.setattr(jl, "_get", lambda url, timeout=60: pics.get(url.rsplit("/", 1)[-1]) or get(url, timeout))
    res = jl.judge(job, DHH)
    prompt, shown = asked[1]
    assert "dhh.dk" not in prompt and len([s for s in shown if s.startswith("reference")]) == 2
    assert "dhh.dk" not in json.dumps(res["reference"])  # first-F1: nor in the reference the result records


def test_a_lead_that_is_the_photo_the_owner_gave_leaves_its_place_to_another_photo(tmp_path, monkeypatch):
    """Review of PR 29 (first-F1, first-F3): the owner gives the tool the article's lead photo
    under a new name. It was left out only when downloaded, after the search had been asked for
    the other places, so it stayed in the reference and its place went unfilled."""
    job = _job(tmp_path)
    lead = "https://up/x/Elon_Musk_ref.jpg"
    (job / "image" / "source.png").write_bytes(_picture(__import__("zlib").crc32(lead.encode()), "PNG"))
    asked = _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, [], search=["File:Elon Musk 2018.jpg"])
    res = jl.judge(job, "A mini figure of Elon Musk")
    assert asked[1][1] == ["reference_1.jpg", "render.png"]
    assert "Elon_Musk_ref" not in json.dumps(res["reference"]) and "Elon Musk ref" not in asked[1][0]
    assert res["reference"]["url"] == "https://up/x/Elon_Musk_2018.jpg"
    _article(monkeypatch, [], search=["File:Elon Musk 2018.jpg", "File:Elon Musk 2016.jpg", "File:Elon Musk 2014.jpg"])
    res = jl.judge(job, "A mini figure of Elon Musk")
    assert asked[3][1] == ["reference_1.jpg", "reference_2.jpg", "reference_3.jpg", "render.png"]
    assert [p["file"] for p in res["reference"]["photos"]] == ["Elon Musk 2018.jpg", "Elon Musk 2016.jpg",
                                                               "Elon Musk 2014.jpg"]


def test_a_reference_is_saved_in_the_format_its_bytes_are_not_its_link(tmp_path, monkeypatch):
    """Review of PR 29 (first-F2): the suffix came from the link, so a hand-picked link with none
    that serves a PNG was saved as .jpg, and one that serves an SVG passed as a picture."""
    job = _job(tmp_path)
    refs = tmp_path / "likeness_refs.json"
    refs.write_text(json.dumps({"Elon Musk": [{"url": "https://site/photo?id=3", "source": "a site"},
                                              {"url": "https://site/drawing?id=4", "source": "a site"}]}))
    monkeypatch.setattr(jl, "REFS_FILE", refs)
    asked = _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, [], search=["File:Elon Musk 2018.jpg"])
    article = jl._get
    served = {"https://site/photo?id=3": _picture(7, "PNG"), "https://site/drawing?id=4": _served("x.svg")}
    monkeypatch.setattr(jl, "_get", lambda url, timeout=60: served.get(url) or article(url, timeout))
    res = jl.judge(job, "A mini figure of Elon Musk")
    assert asked[1][1] == ["reference_1.png", "reference_2.jpg", "reference_3.jpg", "render.png"]
    assert "drawing" not in json.dumps(res["reference"])


def test_a_phone_photo_turned_by_its_exif_is_the_same_picture_as_its_upright_copy(tmp_path):
    """Review of PR 29 (second-S1): a phone JPEG is stored on its side with EXIF Orientation 6 and
    its web copy has the turn in its pixels, so the hash missed it and the judge was shown it."""
    import io
    from PIL import Image
    im = _canvas(11, (96, 64))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())
    job = _job(tmp_path)
    (job / "image" / "source.jpg").write_bytes(buf.getvalue())
    web = io.BytesIO()
    im.transpose(Image.Transpose.ROTATE_270).resize((128, 192)).save(web, "JPEG")
    assert jl._same_picture(web.getvalue(), jl.owner_photos(job))
    assert not jl._same_picture(_picture(12), jl.owner_photos(job))


def test_each_reference_keeps_its_own_format_and_one_the_judge_cannot_read_is_left_out(tmp_path, monkeypatch):
    """Review of PR 24 (first-F1): with several photos every file was named .jpg, so a PNG lead was
    sent to the judge as a JPEG and an SVG lead as a picture it cannot read."""
    job = _job(tmp_path)
    asked = _fake(monkeypatch, "Elon Musk", 9)
    _article(monkeypatch, [], search=["File:Elon Musk 2018.jpg"], lead="Elon_Musk_ref.png")
    jl.judge(job, "A mini figure of Elon Musk")
    assert asked[1][1] == ["reference_1.png", "reference_2.jpg", "render.png"]
    _article(monkeypatch, [], search=["File:Elon Musk 2018.jpg"], lead="Elon_Musk_ref.svg")
    jl.judge(job, "A mini figure of Elon Musk")
    assert asked[3][1] == ["reference_1.jpg", "render.png"]
