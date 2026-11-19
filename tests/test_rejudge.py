"""evals/rejudge.py: a finished figure run judged for likeness again, and its one score line."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rejudge_module():
    s = importlib.util.spec_from_file_location("rejudge", ROOT / "evals" / "rejudge.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _run_dir(tmp_path, why, passed):
    rdir = tmp_path / "run"
    (rdir / "job").mkdir(parents=True)
    sha = hashlib.sha256((ROOT / "evals" / "figure" / "f3_elon.json").read_bytes()).hexdigest()
    (rdir / "log.json").write_text(json.dumps({"run_id": "r", "spec": "f3_elon", "suite": "figure", "card": "S",
                                               "driver": "lfm3", "spec_sha256": sha, "pass": passed, "why": why}))
    return rdir


def _likeness(rj, monkeypatch, score):
    def fake(rdir, job, request, grade, least=None):
        return {**grade, "likeness": score}
    monkeypatch.setattr(rj.run, "likeness_run", fake)


def test_a_passed_run_rejudged_with_a_passing_likeness_stays_passed(tmp_path, monkeypatch):
    """first-F3: a passed run's why is ["all checks pass"], and rejudge read that as a failing check."""
    rj = _rejudge_module()
    monkeypatch.setattr(rj.run, "SCORES", tmp_path / "scores.jsonl")
    rdir = _run_dir(tmp_path, ["all checks pass"], True)
    _likeness(rj, monkeypatch, 9)
    log = rj.rejudge(rdir)
    assert log["pass"] and log["why"] == ["all checks pass"] and log["likeness"] == 9
    assert json.loads((tmp_path / "scores.jsonl").read_text())["pass"] == 1


def test_a_rejudged_score_line_keeps_the_sha_and_date_of_the_run(tmp_path, monkeypatch):
    """second-S3: rejudging on another host or at a later commit wrote this host's sha and date."""
    rj = _rejudge_module()
    scores = tmp_path / "scores.jsonl"
    old = {"date": "2026-11-17T09:00:00-0600", "sha": "abc1234", "suite": "figure", "spec": "f3_elon",
           "card": "S", "driver": "lfm3", "pass": 0, "total": 1, "judge": None, "likeness": None, "run": "r",
           "note": "kept"}
    scores.write_text(json.dumps(old) + "\n")
    monkeypatch.setattr(rj.run, "SCORES", scores)
    rj.replace_score({"run_id": "r", "spec": "f3_elon", "suite": "figure", "card": "S", "driver": "lfm3",
                      "pass": True, "likeness": 9, "judge": None})
    line = json.loads(scores.read_text())
    assert line["sha"] == "abc1234" and line["date"] == "2026-11-17T09:00:00-0600"
    assert line["pass"] == 1 and line["likeness"] == 9 and line["note"] == "kept"
    assert {k: v for k, v in line.items() if k not in ("pass", "likeness")} == \
        {k: v for k, v in old.items() if k not in ("pass", "likeness")}


def test_a_run_with_no_score_line_gets_a_whole_new_one(tmp_path, monkeypatch):
    rj = _rejudge_module()
    scores = tmp_path / "scores.jsonl"
    monkeypatch.setattr(rj.run, "SCORES", scores)
    rj.replace_score({"run_id": "r", "spec": "f3_elon", "suite": "figure", "card": "S", "driver": "lfm3",
                      "pass": True, "likeness": 9})
    line = json.loads(scores.read_text())
    assert line["run"] == "r" and line["pass"] == 1 and line["date"] and "sha" in line
