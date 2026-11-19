import importlib.util
import json
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
        return b"jpeg"

    monkeypatch.setattr(jl, "claude", claude)
    monkeypatch.setattr(jl, "_get", get)
    return asked


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
