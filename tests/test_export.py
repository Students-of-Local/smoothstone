"""stone export: a built part as an editable STEP and SolidCraft design, read back before it says so."""

import json
import sys

import pytest
import trimesh

from smoothstone import cad
from test_cli import stone

# A stand-in solidcraft-cli: `run` writes the STEP and the design holding the STL's volume times
# FAKE_SCALE, `eval` reads it back; FAKE_MODE=fail exits 1 with stderr, FAKE_MODE=hang sleeps,
# FAKE_MODE=nowrite answers as if it worked and writes nothing, FAKE_MODE=nosave writes no design.
FAKE = """#!{py}
import json, os, sys, time
import trimesh
mode = os.environ.get("FAKE_MODE", "")
if sys.argv[1] == "--version":
    print("solidcraft-cli 9.9.9"); sys.exit(0)
if mode == "hang":
    time.sleep(30)
if mode == "fail":
    print("error: mesh.convert: the mesh is not closed", file=sys.stderr); print("more", file=sys.stderr); sys.exit(1)
if sys.argv[1] == "run":
    cmds = json.load(open(sys.argv[2]))["commands"]
    v = trimesh.load(cmds[0]["params"]["path"], force="mesh").volume * float(os.environ.get("FAKE_SCALE", "1"))
    outs = [c["params"]["path"] for c in cmds if c["command"] == "file.export_step"]
    if "--save" in sys.argv and mode != "nosave":
        outs.append(sys.argv[sys.argv.index("--save") + 1])
    for o in outs if mode != "nowrite" else []:
        open(o, "w").write(json.dumps({{"v": v}}))
    print(json.dumps([{{}} for _ in cmds]))
elif sys.argv[1] == "eval":
    v = json.load(open(sys.argv[2]))["v"]
    print(json.dumps({{"bodies": [{{"closed": True, "faces": 12}}], "total": {{"volume_mm3": v}}}}))
"""


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "solidcraft-cli"
    exe.parent.mkdir()
    exe.write_text(FAKE.format(py=sys.executable))
    exe.chmod(0o755)
    monkeypatch.setenv("STONE_SOLIDCRAFT", str(exe))
    return exe


def built_job(work):
    """A job whose build left a part: a 20 mm cube from the fake_hook recipe."""
    stone("new", "a wall hook")
    stone("set", "fake_hook")
    job = work / "stone-job"
    (job / "build").mkdir(exist_ok=True)
    trimesh.creation.box((20, 20, 20)).export(job / "build" / "part.stl")
    return job


def test_export_writes_step_and_design(jobenv, fake_cli):
    job = built_job(jobenv)
    text, code, nxt = stone("export")
    assert code == 0, text
    assert (job / "fake_hook.step").is_file() and (job / "fake_hook.sc").is_file()
    assert f"STEP: {job / 'fake_hook.step'} (12 faces, 8000 mm3, within 0.000% of the STL)" in text
    assert f"SolidCraft design: {job / 'fake_hook.sc'}" in text
    assert nxt == "open it in SolidCraft"
    assert "$ " in (job / "build" / "solidcraft.log").read_text()
    script = json.loads((job / "build" / "solidcraft_fake_hook.json").read_text())
    assert [c["command"] for c in script["commands"]] == ["file.insert_mesh", "mesh.convert", "file.export_step"]


def test_export_step_only(jobenv, fake_cli):
    job = built_job(jobenv)
    text, code, _ = stone("export", "--format", "step")
    assert code == 0, text
    assert (job / "fake_hook.step").is_file() and not (job / "fake_hook.sc").exists()
    assert "SolidCraft design" not in text


def test_export_needs_a_build(jobenv, fake_cli):
    stone("new", "a wall hook")
    text, code, nxt = stone("export")
    assert code == 1 and "FIX: build the part first" in text and nxt == "stone build"


def test_export_without_solidcraft(jobenv, monkeypatch, tmp_path):
    built_job(jobenv)
    monkeypatch.delenv("STONE_SOLIDCRAFT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(cad, "FALLBACKS", (str(tmp_path / "nowhere"),))
    text, code, _ = stone("export")
    assert code == 1
    assert f"FIX: SolidCraft is not installed (optional); get it at {cad.RELEASES}" in text


def test_export_names_the_cli_error(jobenv, fake_cli, monkeypatch):
    job = built_job(jobenv)
    monkeypatch.setenv("FAKE_MODE", "fail")
    text, code, _ = stone("export")
    assert code == 1
    assert "FIX: SolidCraft failed: error: mesh.convert: the mesh is not closed" in text
    assert str(job / "build" / "solidcraft.log") in text and "STEP:" not in text


def test_export_ignores_an_earlier_export(jobenv, fake_cli, monkeypatch):
    built_job(jobenv)
    assert stone("export")[1] == 0
    monkeypatch.setenv("FAKE_MODE", "nowrite")
    text, code, _ = stone("export")
    assert code == 1 and "FIX: SolidCraft wrote no fake_hook.step" in text and "STEP:" not in text


def test_export_step_keeps_the_persons_design(jobenv, fake_cli):
    job = built_job(jobenv)
    (job / "fake_hook.sc").write_text("edited in SolidCraft")
    assert stone("export", "--format", "step")[1] == 0
    assert (job / "fake_hook.sc").read_text() == "edited in SolidCraft"


def test_export_needs_the_design_too(jobenv, fake_cli, monkeypatch):
    built_job(jobenv)
    monkeypatch.setenv("FAKE_MODE", "nosave")
    text, code, _ = stone("export")
    assert code == 1 and "FIX: SolidCraft wrote no fake_hook.sc" in text and "STEP:" not in text


def test_export_refuses_a_volume_that_drifted(jobenv, fake_cli, monkeypatch):
    built_job(jobenv)
    monkeypatch.setenv("FAKE_SCALE", "1.02")
    text, code, _ = stone("export")
    assert code == 1 and "FIX: STEP volume differs from the STL by 2.0%" in text and "STEP:" not in text


def test_export_times_out(jobenv, fake_cli, monkeypatch):
    built_job(jobenv)
    monkeypatch.setenv("FAKE_MODE", "hang")
    monkeypatch.setattr(cad, "TIMEOUT", 0.5)
    text, code, _ = stone("export")
    assert code == 1 and "FIX: SolidCraft timed out after 0.5 s" in text


def test_export_with_real_solidcraft(jobenv, openscad):
    if not cad.find_cli():
        pytest.skip("no solidcraft-cli (set STONE_SOLIDCRAFT)")
    stone("new", "a plate with a hole")
    stone("set", "_demo")
    text, code, _ = stone("build")
    assert code == 0, text
    job = jobenv / "stone-job"
    text, code, nxt = stone("export")
    assert code == 0, text
    v0 = trimesh.load(job / "build" / "part.stl", force="mesh").volume
    import subprocess

    ev = json.loads(subprocess.run([cad.find_cli(), "eval", str(job / "_demo.step")], capture_output=True,
                                   text=True, timeout=300).stdout)
    assert all(b["closed"] for b in ev["bodies"])
    assert abs(ev["total"]["volume_mm3"] - v0) / v0 < 0.005
    assert (job / "_demo.sc").is_file() and nxt == "open it in SolidCraft"
