"""The three figure modes against their held-out bar (LOG.md, 2026-11-19): photos chosen by seed with
the last held back, the likeness of each mode, the traits judge kept blind, the per-mode bar and
the ratchet's groups. No network, no model, no GPU: the judges and stone are stand-ins."""

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "src"))


def _load(name: str, file: str):
    s = importlib.util.spec_from_file_location(name, ROOT / "evals" / file)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


run = _load("run_modes", "run.py")
bar = _load("bar_modes", "bar.py")
import ratchet  # noqa: E402

REQUEST = "A figure of the man in these photos, 100 mm tall, zebra-quartz request text."


def _jpg(seed: int) -> bytes:
    """A small JPEG whose look is set by seed."""
    import random
    from PIL import Image, ImageDraw
    rng = random.Random(seed)
    im = Image.new("RGB", (64, 64), (20, 20, 20))
    d = ImageDraw.Draw(im)
    for k in range(6):
        x, y = rng.randrange(50), rng.randrange(54)
        d.rectangle([x, y, x + 14, y + 10], fill=(230, 200 - 30 * (k % 3), 160))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def _photo_spec(tmp: Path, n: int = 3) -> Path:
    d = tmp / "figure-photo"
    d.mkdir(parents=True)
    names = [f"p9_case_{k}.jpg" for k in range(1, n + 1)]
    for k, name in enumerate(names, 1):
        (d / name).write_bytes(_jpg(k))
    p = d / "p9_case.json"
    p.write_text(json.dumps({"id": "p9_case", "request": REQUEST, "photos": names,
                             "expect": {"recipe": "figure"}}))
    return p


def _fake_stone(monkeypatch):
    """stone new as a stand-in: --image copies the photo to image/source.<ext>, as image.process
    does. Returns the argv of every call."""
    calls = []

    def fake(argv, env=None, **kw):
        calls.append(argv)
        job = Path(env["STONE_JOB"])
        job.mkdir(parents=True, exist_ok=True)
        if "--image" in argv:
            src = Path(argv[argv.index("--image") + 1])
            (job / "image").mkdir(exist_ok=True)
            (job / "image" / ("source" + src.suffix.lower())).write_bytes(src.read_bytes())
        return subprocess.CompletedProcess(argv, 0, stdout="Job ready.\nNEXT: stone status", stderr="")

    monkeypatch.setattr(run.subprocess, "run", fake)
    return calls


def _setup(tmp: Path, spec_path: Path, seed: int):
    rdir = tmp / f"run_s{seed}"
    rdir.mkdir()
    env = {"STONE_JOB": str(rdir / "job")}
    spec = json.loads(spec_path.read_text())
    out, photos = run.setup_job(spec, spec_path, seed, env, rdir)
    return rdir / "job", photos


def _given(job: Path) -> list[bytes]:
    from smoothstone.job import Job
    return [p.read_bytes() for p in Job(job).photos()]


@pytest.mark.parametrize("seed", [1, 2])
def test_the_reference_photo_never_reaches_the_job(tmp_path, monkeypatch, seed):
    spec_path = _photo_spec(tmp_path)
    calls = _fake_stone(monkeypatch)
    job, photos = _setup(tmp_path, spec_path, seed)
    ref = spec_path.parent / "p9_case_3.jpg"
    assert photos["reference"] == "p9_case_3.jpg"
    assert not any(str(ref) in " ".join(c) for c in calls)
    assert not any(f.is_file() and f.read_bytes() == ref.read_bytes() for f in job.rglob("*"))


def test_seed_1_gives_the_tool_photo_1_only(tmp_path, monkeypatch):
    spec_path = _photo_spec(tmp_path)
    _fake_stone(monkeypatch)
    job, photos = _setup(tmp_path, spec_path, 1)
    assert photos == {"given": ["p9_case_1.jpg"], "reference": "p9_case_3.jpg"}
    assert _given(job) == [(spec_path.parent / "p9_case_1.jpg").read_bytes()]


def test_seed_2_gives_every_photo_but_the_last_with_photo_1_first(tmp_path, monkeypatch):
    # the figure crops the face from job.photos()[0], so photo 1 must stay first
    spec_path = _photo_spec(tmp_path)
    _fake_stone(monkeypatch)
    job, photos = _setup(tmp_path, spec_path, 2)
    assert photos["given"] == ["p9_case_1.jpg", "p9_case_2.jpg"]
    assert _given(job) == [(spec_path.parent / f"p9_case_{k}.jpg").read_bytes() for k in (1, 2)]


def test_a_two_photo_case_gives_photo_1_on_both_seeds(tmp_path, monkeypatch):
    spec_path = _photo_spec(tmp_path, n=2)
    _fake_stone(monkeypatch)
    for seed in (1, 2):
        job, photos = _setup(tmp_path, spec_path, seed)
        assert photos == {"given": ["p9_case_1.jpg"], "reference": "p9_case_2.jpg"}
        assert len(_given(job)) == 1


def test_a_spec_with_no_photos_makes_the_job_as_before(tmp_path, monkeypatch):
    p = tmp_path / "figure-research" / "r9.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"id": "r9", "request": "A figure of someone", "expect": {"recipe": "figure"}}))
    calls = _fake_stone(monkeypatch)
    job, photos = _setup(tmp_path, p, 1)
    assert photos is None and calls[0][1:] == ["new", "A figure of someone"]


# --- likeness per mode ----------------------------------------------------------------------


def _job(tmp: Path) -> Path:
    job = tmp / "job"
    d = job / "image" / "figure" / "k"
    d.mkdir(parents=True)
    (d / "style.png").write_bytes(b"png")
    (job / "build").mkdir()
    (job / "build" / "views.png").write_bytes(b"views")
    (job / "build" / "boundaries.png").write_bytes(b"bounds")
    return job


@pytest.fixture
def judges(monkeypatch):
    """Every claude call goes to a stand-in that records the prompt and the folder's files."""
    import judge_likeness as jl
    import judge_traits

    asked = []
    reply = {"text": ""}

    def claude(prompt, folder=None, model="opus"):
        files = {p.name: p.read_bytes() for p in Path(folder).iterdir()} if folder else None
        asked.append({"prompt": prompt, "folder": str(folder), "files": files})
        return reply["text"]

    for m in {id(jl): jl, id(judge_traits.judge_likeness): judge_traits.judge_likeness}.values():
        monkeypatch.setattr(m, "claude", claude)
        monkeypatch.setattr(m, "_get", lambda *a, **k: pytest.fail("no network in these tests"))
    return asked, reply


def test_a_photo_case_is_judged_against_the_held_back_photo_at_7(tmp_path, monkeypatch, judges):
    asked, reply = judges
    spec_path = _photo_spec(tmp_path)
    spec = json.loads(spec_path.read_text())
    job = _job(tmp_path)
    (job / "image" / "source.jpg").write_bytes((spec_path.parent / "p9_case_1.jpg").read_bytes())
    reply["text"] = json.dumps({"score": 6, "conflicts": [{"feature": "hair", "what": "shorter"}]})
    grade = run.likeness_for(tmp_path, job, spec, spec_path, spec["expect"], {"pass": True, "why": ["all checks pass"]})
    assert not grade["pass"] and grade["likeness"] == 6  # 6 passes the judge's own bar, not the mode's
    files = asked[0]["files"]
    assert sorted(files) == ["reference.jpg", "render.png"]
    assert files["reference.jpg"] == (spec_path.parent / "p9_case_3.jpg").read_bytes()
    assert "p9_case" not in asked[0]["prompt"]
    reply["text"] = json.dumps({"score": 7, "conflicts": []})
    assert run.likeness_for(tmp_path, job, spec, spec_path, spec["expect"], {"pass": True, "why": []})["pass"]


def test_a_reference_the_tool_was_given_is_no_verdict(tmp_path, judges):
    import judge_likeness as jl

    spec_path = _photo_spec(tmp_path)
    job = _job(tmp_path)
    ref = spec_path.parent / "p9_case_3.jpg"
    (job / "image" / "source.jpg").write_bytes(ref.read_bytes())
    with pytest.raises(jl.JudgeProblem):
        jl.judge_photo(job, REQUEST, ref)


def test_a_research_case_needs_7_from_the_wikipedia_judge(tmp_path, monkeypatch):
    import judge_likeness as jl

    p = tmp_path / "figure-research" / "r9.json"
    p.parent.mkdir()
    spec = {"id": "r9", "request": "A figure of someone", "expect": {"recipe": "figure"}}
    seen = []
    monkeypatch.setattr(jl, "judge", lambda job, request: seen.append(request) or
                        {"score": 6, "pass": True, "conflicts": []})
    grade = run.likeness_for(tmp_path, _job(tmp_path), spec, p, spec["expect"], {"pass": True, "why": []})
    assert seen == ["A figure of someone"] and not grade["pass"]
    assert grade["why"] == ["likeness 6/10, the spec asks 7: "]


# --- description traits ---------------------------------------------------------------------


def _desc(tmp: Path, traits: list[str]):
    p = tmp / "figure-desc" / "d9_secret_case.json"
    p.parent.mkdir()
    spec = {"id": "d9_secret_case", "request": REQUEST, "expect": {"recipe": "figure", "traits": traits}}
    p.write_text(json.dumps(spec))
    return spec, p


def test_the_traits_judge_sees_only_the_views_and_the_traits(tmp_path, judges):
    asked, reply = judges
    spec, p = _desc(tmp_path, ["a gray beard", "a green cap"])
    reply["text"] = json.dumps({"traits": [{"n": 1, "visible": True, "why": "gray"},
                                           {"n": 2, "visible": True, "why": "green"}]})
    grade = run.likeness_for(tmp_path, _job(tmp_path), spec, p, spec["expect"], {"pass": True, "why": ["all checks pass"]})
    assert grade["pass"] and grade["traits"] == "2/2"
    a = asked[0]
    assert sorted(a["files"]) == ["views.png"] and a["files"]["views.png"] == b"views"
    for secret in ("zebra-quartz", REQUEST, "d9_secret_case", "secret", str(tmp_path)):
        assert secret not in a["prompt"] and secret not in a["folder"]
    assert "a gray beard" in a["prompt"] and "a green cap" in a["prompt"]


def test_a_trait_not_visible_fails_the_case(tmp_path, judges):
    asked, reply = judges
    spec, p = _desc(tmp_path, ["a gray beard", "a green cap"])
    reply["text"] = json.dumps({"traits": [{"n": 1, "visible": True, "why": "gray"},
                                           {"n": 2, "visible": False, "why": "the cap is red"}]})
    grade = run.likeness_for(tmp_path, _job(tmp_path), spec, p, spec["expect"], {"pass": True, "why": ["all checks pass"]})
    assert not grade["pass"] and grade["traits"] == "1/2"
    assert grade["why"] == ["likeness: not visible: a green cap (the cap is red)"]
    assert json.loads((tmp_path / "traits.json").read_text())["pass"] is False


def test_a_trait_the_judge_leaves_out_is_not_visible(tmp_path, judges):
    asked, reply = judges
    spec, p = _desc(tmp_path, ["a gray beard", "a green cap"])
    reply["text"] = json.dumps({"traits": [{"n": 1, "visible": True, "why": "gray"}]})
    grade = run.likeness_for(tmp_path, _job(tmp_path), spec, p, spec["expect"], {"pass": True, "why": []})
    assert not grade["pass"] and "a green cap (the judge did not answer)" in grade["why"][0]


def test_a_traits_judge_that_cannot_answer_fails_the_case(tmp_path, judges):
    asked, reply = judges
    spec, p = _desc(tmp_path, ["a gray beard"])
    reply["text"] = "I cannot tell"
    grade = run.likeness_for(tmp_path, _job(tmp_path), spec, p, spec["expect"], {"pass": True, "why": []})
    assert not grade["pass"] and "could not answer" in grade["why"][0]


def test_the_craft_judge_scores_a_mode_run_without_failing_it(tmp_path, monkeypatch):
    import judge_views

    monkeypatch.setattr(judge_views, "judge", lambda build, request: {"score": 7, "faults": []})
    assert run.craft_run(tmp_path, _job(tmp_path), REQUEST) == 7
    assert json.loads((tmp_path / "judge.json").read_text())["score"] == 7

    def broken(build, request):
        raise SystemExit("claude exited 1")
    monkeypatch.setattr(judge_views, "judge", broken)
    assert run.craft_run(tmp_path, _job(tmp_path / "b"), REQUEST) is None


# --- the bar and the ratchet ------------------------------------------------------------------


def _evals(tmp: Path) -> Path:
    ev = tmp / "evals"
    for mode, ids in (("figure-research", ["r1", "r2"]), ("figure-photo", ["p1"]), ("figure-desc", ["d1"])):
        (ev / mode).mkdir(parents=True)
        for i in ids:
            (ev / mode / f"{i}.json").write_text("{}")
    return ev


def _run(runs: Path, suite: str, spec: str, seed: int, ok: bool, judge: float | None = 9, stamp: str = "1"):
    d = runs / f"{spec}__cardS__s{seed}__{stamp}"
    (d / "job").mkdir(parents=True)
    (d / "log.json").write_text(json.dumps({"run_id": d.name, "spec": spec, "suite": suite, "seed": seed,
                                            "card": "S", "driver": "lfm3", "pass": ok,
                                            "why": ["all checks pass"] if ok else ["likeness 4/10: hair"]}))
    if judge is not None:
        (d / "judge.json").write_text(json.dumps({"score": judge, "faults": []}))
    return d


def _control(runs: Path, of: Path, score: float):
    c = runs.parent / f"control_{of.name}"
    c.mkdir()
    (c / "control.json").write_text(json.dumps({"job": str(of / "job")}))
    (c / "judge.json").write_text(json.dumps({"score": score, "faults": []}))


def _all_pass(tmp: Path) -> Path:
    runs = tmp / "runs"
    for suite, spec in (("figure-research", "r1"), ("figure-research", "r2"), ("figure-photo", "p1"),
                        ("figure-desc", "d1")):
        for seed in (1, 2):
            d = _run(runs, suite, spec, seed, True)
            if seed == 1 and spec in ("r1", "p1", "d1"):
                _control(runs, d, 3)
    return runs


def test_the_bar_holds_when_every_mode_passes_with_a_caught_control(tmp_path):
    ev = _evals(tmp_path)
    lines, ok = bar.bar([_all_pass(tmp_path), tmp_path], evals=ev)
    assert ok, lines
    assert lines[0] == "figure-research: 4 of 4 runs pass checks and likeness (2 cases x 2 seeds), 100% (bar 80%): holds"


def test_a_missing_run_counts_as_failed_and_a_lenient_control_breaks_the_craft_bar(tmp_path):
    ev = _evals(tmp_path)
    runs = _all_pass(tmp_path)
    for d in runs.glob("r2__*s2__*"):
        import shutil
        shutil.rmtree(d)
    (tmp_path / "control_p1__cardS__s1__1" / "judge.json").write_text(json.dumps({"score": 8}))
    lines, ok = bar.bar([runs, tmp_path], evals=ev)
    assert not ok
    text = "\n".join(lines)
    assert "figure-research: 3 of 4 runs" in text and "75% (bar 80%): below" in text and "r2 s2: not run" in text
    photo_craft = lines[lines.index(next(x for x in lines if x.startswith("figure-photo"))) + 1]
    assert "control 8" in photo_craft and photo_craft.endswith("below")


def test_a_craft_mean_under_8_is_below_the_bar(tmp_path):
    ev = _evals(tmp_path)
    runs = tmp_path / "runs"
    _control(runs, _run(runs, "figure-desc", "d1", 1, True, judge=7), 2)
    _run(runs, "figure-desc", "d1", 2, True, judge=8)
    lines, ok = bar.bar([runs, tmp_path], evals=ev)
    desc = lines[lines.index(next(x for x in lines if x.startswith("figure-desc"))) + 1]
    assert "mean 7.50 over 2 runs" in desc and desc.endswith("below") and not ok


def test_the_later_run_of_a_case_and_seed_counts(tmp_path):
    ev = _evals(tmp_path)
    runs = tmp_path / "runs"
    _run(runs, "figure-photo", "p1", 1, False, stamp="20261119-1000")
    _run(runs, "figure-photo", "p1", 1, True, stamp="20261119-1100")
    lines, _ = bar.bar([runs], evals=ev)
    assert next(x for x in lines if x.startswith("figure-photo")).startswith("figure-photo: 1 of 2 runs")


@pytest.mark.parametrize("mode", ["figure-research", "figure-photo", "figure-desc"])
def test_the_ratchet_takes_a_mode_as_a_new_group_and_never_lowers_it(tmp_path, mode, capsys):
    floor = tmp_path / "floor.json"
    old = {"tuning/S": {"rate": 1.0, "judge": None, "total": 1, "passing": ["t1"]}}
    floor.write_text(json.dumps(old))
    runs = tmp_path / "runs"
    _run(runs, mode, "x1", 1, True, judge=9)
    _run(runs, mode, "x1", 2, True, judge=8)
    assert ratchet.check_runs([runs], floor) == 0
    got = json.loads(floor.read_text())
    assert got["tuning/S"] == old["tuning/S"]
    assert got[f"{mode}/S"] == {"rate": 1.0, "judge": 8.5, "total": 2, "passing": ["x1"]}
    worse = tmp_path / "worse"
    _run(worse, mode, "x1", 1, False, judge=9)
    _run(worse, mode, "x1", 2, True, judge=9)
    assert ratchet.check_runs([worse], floor) == 1
    assert f"{mode}/S: x1 passed at the floor and fails now" in capsys.readouterr().out
    assert json.loads(floor.read_text())[f"{mode}/S"]["rate"] == 1.0


def test_check_git_refuses_a_lowered_mode_floor(tmp_path, capsys):
    root = tmp_path / "repo"
    (root / "evals").mkdir(parents=True)
    floor = {"figure-photo/S": {"rate": 0.83, "judge": 8.2, "total": 6, "passing": ["p1_x"]}}
    (root / "evals" / "floor.json").write_text(json.dumps(floor))
    (root / "LOG.md").write_text("# Log\n")
    for a in (["init", "-q", "-b", "main"], ["add", "."],
              ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"]):
        subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)
    assert ratchet.check_git("HEAD", root) == 0
    floor["figure-photo/S"]["judge"] = 7.9
    (root / "evals" / "floor.json").write_text(json.dumps(floor))
    assert ratchet.check_git("HEAD", root) == 1
    assert "floor figure-photo/S judge lowered from 8.2 to 7.9" in capsys.readouterr().out


def test_the_later_run_counts_across_folders_in_any_order(tmp_path):
    """Review of PR 41 (second-F5): folders were read in argument order, so an older pass in the
    second folder overwrote a newer fail in the first."""
    ev = _evals(tmp_path)
    new, old = tmp_path / "new", tmp_path / "old"
    _run(new, "figure-photo", "p1", 1, False, stamp="20261119-1100")
    _run(old, "figure-photo", "p1", 1, True, stamp="20261119-1000")
    for dirs in ([new, old], [old, new]):
        lines, _ = bar.bar(dirs, evals=ev)
        assert next(x for x in lines if x.startswith("figure-photo")).startswith("figure-photo: 0 of 2 runs")


def test_a_run_with_no_craft_score_counts_0_in_the_mean(tmp_path):
    """Review of PR 41 (second-F4): the mean was taken over the judged runs only, so a mode whose
    runs died before views.png was judged on its one survivor."""
    ev = _evals(tmp_path)
    runs = _all_pass(tmp_path)
    (next(runs.glob("d1__*s2__*")) / "judge.json").unlink()
    lines, ok = bar.bar([runs, tmp_path], evals=ev)
    desc = lines[lines.index(next(x for x in lines if x.startswith("figure-desc"))) + 1]
    assert "mean 4.50 over 2 runs (1 judged" in desc and desc.endswith("below") and not ok


def _sealed_run(tmp: Path, suite: str, spec: str, why: list[str]) -> Path:
    import hashlib
    sp = ROOT / "evals" / suite / f"{spec}.json"
    rdir = tmp / "run"
    job = _job(rdir)
    (rdir / "log.json").write_text(json.dumps({
        "run_id": "x1", "spec": spec, "suite": suite, "seed": 1, "card": "S", "driver": "lfm3",
        "pass": False, "why": why, "spec_sha256": hashlib.sha256(sp.read_bytes()).hexdigest()}))
    return rdir, job, sp


def test_rejudge_takes_a_photo_run_to_its_held_back_photo_at_7(tmp_path, monkeypatch, judges):
    """Review of PR 41 (first-F1): rejudge is the only way to score a held-out run again."""
    rejudge = _load("rejudge_modes", "rejudge.py")
    monkeypatch.setattr(rejudge.run, "SCORES", tmp_path / "scores.jsonl")
    asked, reply = judges
    rdir, job, sp = _sealed_run(tmp_path, "figure-photo", "p1_trench_coat_woman", ["likeness: the judge could not answer"])
    spec = json.loads(sp.read_text())
    (job / "image" / "source.jpg").write_bytes((sp.parent / spec["photos"][0]).read_bytes())
    reply["text"] = json.dumps({"score": 6, "conflicts": [{"feature": "hair", "what": "short"}]})
    log = rejudge.rejudge(rdir)
    assert not log["pass"] and log["likeness"] == 6 and "the spec asks 7" in log["why"][0]
    assert asked[-1]["files"]["reference.jpg"] == (sp.parent / spec["photos"][-1]).read_bytes()
    reply["text"] = json.dumps({"score": 8, "conflicts": []})
    assert rejudge.rejudge(rdir)["pass"]


def test_rejudge_takes_a_description_run_to_the_traits_judge(tmp_path, monkeypatch, judges):
    rejudge = _load("rejudge_modes", "rejudge.py")
    monkeypatch.setattr(rejudge.run, "SCORES", tmp_path / "scores.jsonl")
    asked, reply = judges
    rdir, job, sp = _sealed_run(tmp_path, "figure-desc", "d1_old_man_beard_cap", ["likeness: not visible: flat cap (bare head)"])
    n = len(json.loads(sp.read_text())["expect"]["traits"])
    reply["text"] = json.dumps({"traits": [{"n": i + 1, "visible": True, "why": "seen"} for i in range(n)]})
    log = rejudge.rejudge(rdir)
    assert log["pass"] and log["traits"] == f"{n}/{n}" and sorted(asked[-1]["files"]) == ["views.png"]
    assert json.loads((tmp_path / "scores.jsonl").read_text())["pass"] == 1


def test_a_spec_that_wants_a_clean_slice_fails_a_part_with_pieces_in_the_air(tmp_path, monkeypatch):
    """The figure recipe may lean on slicer supports, so its islands check passes with spots in the
    air; a spec with "slices": true still fails it (random five, round 6: the owner, PRINTABLE)."""
    from smoothstone import check as checks

    job = tmp_path / "job"
    (job / "build").mkdir(parents=True)
    (job / "build" / "params.json").write_text(json.dumps({"recipe": "figure", "params": {"height": 90, "name": "INDE"}}))
    (job / "figure.stl").write_bytes(b"solid")
    air = checks.Result("islands", True, 2, "2 spots start in the air (1.2 mm2 at 73.1 mm up): in the slicer, supports on, everywhere")
    monkeypatch.setattr(run.checks, "check_stl", lambda *a, **k: [air])
    spec = {"expect": {"recipe": "figure", "params": {"height": 90, "name": "INDE"}}}
    assert run.grade_job(job, spec)["pass"]
    spec["expect"]["slices"] = True
    got = run.grade_job(job, spec)
    assert not got["pass"] and "starts in the air" in got["why"][0]
