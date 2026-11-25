"""stone printer: the profiles, the config write, and the read-only Gantrel bridge (mocked; no real printer)."""

import json
import re
import subprocess
import tomllib

import pytest

from smoothstone import cli, config, printers

URL = re.compile(r"^https?://\S+")
OWNERS = "creality_k2"
WANT = {
    "creality_k2", "creality_k2_plus", "creality_k1c", "creality_k1_max", "creality_ender3_v3",
    "creality_ender3_v3_se", "bambu_x1c", "bambu_p1s", "bambu_p1p", "bambu_a1", "bambu_a1_mini", "bambu_h2d",
    "prusa_mk4s", "prusa_core_one", "prusa_mini", "voron_24", "elegoo_centauri_carbon", "elegoo_neptune_4_pro",
    "anycubic_kobra_3", "sovol_sv08", "qidi_q1_pro",
}


def stone(*argv):
    text, code = cli.run(list(argv))
    lines = text.splitlines()
    assert len(lines) <= cli.MAX_LINES, text
    assert lines[-1].startswith("NEXT: "), text
    assert sum(ln.startswith("NEXT:") for ln in lines) == 1, text
    assert "Traceback" not in text and "ERROR" not in text, text
    assert "\u2014" not in text and "\u2013" not in text
    return text, code, lines[-1][len("NEXT: "):]


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.chdir(w)
    monkeypatch.setenv("STONE_JOB", str(w / "stone-job"))
    return w


@pytest.fixture(autouse=True)
def no_real_subprocess(monkeypatch):
    """No test reaches a real printer: any subprocess call the bridge did not get mocked out fails loudly."""
    def boom(*a, **k):
        raise AssertionError(f"real subprocess call: {a}")
    monkeypatch.setattr(subprocess, "run", boom)


# the profiles


def test_every_wanted_model_loads():
    lib = printers.load()
    assert WANT <= set(lib), WANT - set(lib)
    assert len(lib) >= 21


@pytest.mark.parametrize("pid", sorted(WANT))
def test_profile_contract(pid):
    p = printers.load()[pid]
    assert p["id"] == pid and p["name"] and p["maker"]
    assert p["firmware"] in ("klipper", "marlin", "bambu", "prusa", "rrf", "other")
    assert p["kinematics"] in ("corexy", "bedslinger", "corexz", "delta")
    assert len(p["build_volume_mm"]) == 3 and all(v > 0 for v in p["build_volume_mm"])
    assert isinstance(p["enclosed"], bool) and isinstance(p["chamber_heater"], bool)
    assert p["nozzle_mm"] == 0.4
    for k in ("max_hotend_c", "max_bed_c"):
        assert p[k] is None or 60 <= p[k] <= 450
    assert p["limits_source"]
    s = p["bed_surface"]
    assert s["type"] and s["clean"] and URL.match(s["source"]), s
    assert s["clean_by"].startswith(("maker", "fallback", "none"))
    if s["clean_by"] == "fallback":
        assert "gives no plate cleaning steps" in s["clean"]
    assert p["auto_level"] and p["multi_material"]
    cam = p["camera"]
    assert cam["timelapse_mode"] in ("fixed", "head-parked")
    if cam.get("pos_mm"):
        assert cam.get("assumption") or cam.get("source")
    if cam.get("where"):
        assert URL.match(cam.get("source", "")), cam
    assert p["speeds"]["max_accel_mm_s2"] > 0 and URL.match(p["speeds"]["source"])
    for q in p["quirks"]:
        assert q["failure"] and q["note"] and URL.match(q["source"]), q
    assert p["connect"]["gantrel_type"]
    assert p["sources"] and all(URL.match(u) for u in p["sources"])
    assert p["checked"] == "2026-11-24"
    text = json.dumps(p, ensure_ascii=False)
    assert "\u2014" not in text and "\u2013" not in text


def test_owners_k2():
    p = printers.get(OWNERS)
    assert p["build_volume_mm"] == [260, 260, 260]
    assert p["multi_material"].startswith("CFS") and p["firmware"] == "klipper"
    assert "dish soap" in p["bed_surface"]["clean"] and "wiki.creality.com" in p["bed_surface"]["source"]
    assert p["camera"]["ir_night"] and "assumption" in p["camera"]
    assert {q["failure"] for q in p["quirks"]} >= {"bed_adhesion", "blob_on_nozzle"}


@pytest.mark.parametrize("text,want", [
    ("creality_k2", "creality_k2"), ("creality-k2", "creality_k2"), ("Creality K2", "creality_k2"),
    ("K2", "creality_k2"), ("k2 plus", "creality_k2_plus"), ("X1 Carbon", "bambu_x1c"), ("MK4S", "prusa_mk4s"), ("core one", "prusa_core_one"),
    ("Q1 Pro", "qidi_q1_pro"), ("nope", None), ("", None),
])
def test_get_forgives(text, want):
    p = printers.get(text)
    assert (p["id"] if p else None) == want


# stone.toml


def test_set_writes_only_the_test_config_and_keeps_other_keys(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    f = xdg / "smoothstone" / "stone.toml"
    f.parent.mkdir(parents=True)
    f.write_text('[slicer]\nname = "orca"\n\n[printer]\nmodel = "bambu_a1"\nold = 1\n\n[tier]\nlevel = "S"\n')
    assert printers.set_model("creality_k2") == f
    data = tomllib.loads(f.read_text())
    assert data["printer"] == {"model": "creality_k2"}
    assert data["slicer"] == {"name": "orca"} and data["tier"] == {"level": "S"}
    assert printers.current()["id"] == "creality_k2"
    assert str(config.user_config_dir()).startswith(str(tmp_path))


def test_job_toml_overrides_machine(tmp_path, monkeypatch):
    printers.set_model("bambu_p1s")
    job = tmp_path / "job"
    job.mkdir()
    (job / "stone.toml").write_text('[printer]\nmodel = "creality_k2"\n')
    assert printers.current(job)["id"] == "creality_k2"
    assert printers.current()["id"] == "bambu_p1s"


# the command


def test_list_set_show(work):
    text, code, nxt = stone("printer")
    assert "21 printers" in text and "creality_k2: Creality K2, 260 x 260 x 260 mm" in text
    assert nxt.startswith("ask the person: which printer")
    text, code, nxt = stone("printer", "set", "Creality K2")
    assert code == 0 and nxt == "stone printer show creality_k2"
    assert printers.config_file().is_file()
    assert "creality_k2: Creality K2, 260 x 260 x 260 mm (yours)" in stone("printer")[0]
    text, code, nxt = stone("printer", "show")
    assert "Creality K2 (creality_k2): corexy, klipper firmware, enclosed" in text
    assert "Clean it (maker's steps): Hand sweat" in text and "Known issue (blob_on_nozzle)" in text
    assert "Multi-material: CFS" in text and "IR night view" in text
    assert nxt == cli.NEW_NEXT
    text, code, nxt = stone("printer", "bambu_a1")  # an id alone means show
    assert "Bambu Lab A1 (bambu_a1)" in text and "open frame" in text


def test_set_unknown(work):
    text, code, nxt = stone("printer", "set", "makerbot")
    assert code == 1 and "FIX: no printer makerbot" in text and nxt == "stone printer"
    assert not printers.config_file().exists()


def test_status_without_gantrel(work, monkeypatch):
    monkeypatch.setattr(printers, "gantrel", lambda: None)
    stone("printer", "set", "creality_k2")
    for action in ("status", "camera"):
        text, code, nxt = stone("printer", action)
        lines = text.splitlines()
        assert "uv tool install git+https://github.com/baney75/Gantrel" in lines[1]
        assert "--type creality" in lines[2] and "--model creality-k2" in lines[2]
        assert nxt.startswith("ask the person: install and pair")


class FakeGantrel:
    """Answers like gantrel-printer and records what it was asked."""

    def __init__(self, rows, frame=True):
        self.rows, self.frame, self.calls = rows, frame, []

    def __call__(self, argv, timeout=60):
        self.calls.append(argv[1:])
        if argv[1] == "list":
            return 0, json.dumps({"printers": self.rows, "next": "x"})
        if argv[1] == "status":
            return 0, f"{argv[2]}: printing 42%\nnozzle 220 C, bed 60 C\nNEXT: gantrel-printer camera {argv[2]}\n"
        if argv[1] == "camera" and self.frame:
            out = argv[argv.index("--out") + 1]
            open(out, "wb").write(b"\xff\xd8\xff\xd9")
            return 0, f"saved {out}\n"
        return 1, "camera unavailable\n"


K2ROW = {"name": "k2", "type": "creality", "host": "192.0.2.10", "model": "creality-k2", "camera": True}


def test_status_and_camera_read_only(work, monkeypatch):
    fake = FakeGantrel([K2ROW, {"name": "mini", "type": "bambu", "model": "bambu-a1-mini"}])
    monkeypatch.setattr(printers, "gantrel", lambda: "/fake/gantrel-printer")
    monkeypatch.setattr(printers, "_run", fake)
    stone("printer", "set", "creality_k2")
    text, code, nxt = stone("printer", "status")
    assert "Printer k2 (creality-k2):" in text and "printing 42%" in text
    assert text.count("NEXT:") == 1 and nxt == "stone printer camera"
    text, code, nxt = stone("printer", "camera", "--out", str(work / "frame.jpg"))
    assert code == 0 and (work / "frame.jpg").is_file()
    assert nxt == f'stone doctor "<what you see in the frame>" --image {work / "frame.jpg"}'
    # only reads: never start, resume, pause or cancel
    assert {c[0] for c in fake.calls} <= {"list", "status", "camera"}


def test_camera_default_path_and_failure(work, monkeypatch):
    monkeypatch.setattr(printers, "gantrel", lambda: "/fake/gantrel-printer")
    monkeypatch.setattr(printers, "_run", FakeGantrel([K2ROW]))
    text, code, nxt = stone("printer", "camera")
    assert (work / "stone-job" / "camera.jpg").is_file()
    monkeypatch.setattr(printers, "_run", FakeGantrel([K2ROW], frame=False))
    text, code, nxt = stone("printer", "camera", "--out", str(work / "none.jpg"))
    assert code == 1 and "FIX: no camera frame from k2" in text and nxt.startswith("ask the person:")


def test_pick_and_unpaired(work, monkeypatch):
    monkeypatch.setattr(printers, "gantrel", lambda: "/fake/gantrel-printer")
    monkeypatch.setattr(printers, "_run", FakeGantrel([]))
    text, code, nxt = stone("printer", "status")
    assert "No printer is paired yet." in text and nxt.startswith("ask the person: pair")
    two = [{"name": "a", "type": "bambu", "model": "bambu-x1c"}, {"name": "b", "type": "bambu", "model": "bambu-p1s"}]
    monkeypatch.setattr(printers, "_run", FakeGantrel(two))
    text, code, nxt = stone("printer", "status")
    assert "Paired: a, b" in text and nxt == "stone printer status --name a"
    text, code, nxt = stone("printer", "status", "--name", "b")
    assert "Printer b (bambu-p1s):" in text


def test_run_reports_a_missing_binary_without_raising(monkeypatch):
    def gone(*a, **k):
        raise FileNotFoundError("gantrel-printer")
    monkeypatch.setattr(subprocess, "run", gone)
    code, text = printers._run(["gantrel-printer", "list", "--json"])
    assert code == 1 and "gantrel-printer" in text


# the slicer's settings for each printer and plastic (tools/orca_profiles.py)

PLASTICS = ("PLA", "PETG", "ABS", "ASA", "PC", "PA", "TPU", "PLA-CF", "PETG-CF")


@pytest.mark.parametrize("pid", sorted(WANT))
def test_every_printer_has_its_slicer_settings_for_every_plastic(pid):
    p = printers.get(pid)
    proc = printers.process(p)
    assert 10 <= proc["speeds"]["first_layer"] <= proc["speeds"]["travel"] <= 1000
    assert all(0.3 <= w <= 0.8 for w in proc["widths"].values()) and proc["shells"]["wall_loops"] >= 2
    assert all(100 <= a <= 40000 for a in proc["accels"].values()) and 0.2 <= proc["retract_mm"] <= 6
    for m in PLASTICS:
        e = printers._settings()[f"orca.{pid}.{m}"]
        raw, s = e["value"], printers.settings(p, m)
        assert 190 <= raw["nozzle"] <= 320 and 20 <= raw["bed"] <= 120 and 20 <= raw.get("chamber", 20) <= 70, (m, raw)
        assert 0 <= raw["fan_min"] <= raw["fan_max"] <= 100 and 0 <= raw["fan_max_layer_s"] <= raw["fan_min_layer_s"] <= 100, (m, raw)
        assert 0 <= s["fan_over"] <= 100 and s["fan_over"] == raw.get("fan_over", raw["fan_max"]), (m, raw)
        assert 1 <= raw["max_flow"] <= 40 and raw["diameter"] == 1.75 and e["url"].startswith("https://github.com/OrcaSlicer/")
        assert s["nozzle"] <= (p["max_hotend_c"] or 320) and s["bed"] <= (p["max_bed_c"] or 120) and (p["enclosed"] or "chamber" not in s)
    heat = {m: printers.settings(p, m)["nozzle"] for m in PLASTICS}
    assert heat["PLA"] < heat["ABS"] and heat["PLA"] < heat["PC"]


def test_one_profile_says_one_thing_on_every_printer():
    said = {}
    for e in printers._settings().values():  # the bed may differ: it depends on the plate
        said.setdefault(e["url"], set()).add(json.dumps({k: v for k, v in e["value"].items() if k != "bed"}, sort_keys=True))
    assert len(said) > 50 and all(len(v) == 1 for v in said.values()), {k: v for k, v in said.items() if len(v) > 1}


def test_no_printer_takes_another_brands_product_for_the_plain_plastic():
    for k, e in printers._settings().items():
        name = e["cite"].removeprefix("OrcaSlicer ")
        assert k.endswith(".process") or "Generic" in name or name.startswith(("Prusament", "Bambu", "Elegoo", "Qidi", "Creality")), (k, name)


def test_the_plate_and_the_fan_are_the_ones_orca_uses():
    """Bambu printers have every plate type (their textured plate's heat); a Prusa one. Fan off on long layers unless kept on."""
    v = lambda k: printers._settings()[f"orca.{k}"]["value"]  # noqa: E731
    assert v("bambu_x1c.PETG")["bed"] == 70 and v("prusa_mk4s.ASA")["bed"] == 110
    assert v("bambu_h2d.ABS")["chamber"] == 60  # its profile's other spelling of it
    k2, a1 = printers.get(OWNERS), printers.get("bambu_a1")
    assert printers.settings(k2, "PA")["fan_long"] == 0 < printers.settings(k2, "PA")["fan_min"]
    assert printers.settings(a1, "PLA")["fan_long"] == printers.settings(a1, "PLA")["fan_min"] > 0
    assert printers.settings(printers.get("bambu_h2d"), "ABS")["chamber_heated"] and not printers.settings(k2, "ABS")["chamber_heated"]


def test_a_process_is_the_callers_own_copy():
    printers.process(printers.get(OWNERS))["speeds"]["outer_wall"] = 1
    assert printers.process(printers.get(OWNERS))["speeds"]["outer_wall"] == 200


def test_the_k2s_process_is_the_one_the_refs_already_cite():
    from smoothstone import refs

    proc = printers.process(printers.get(OWNERS))
    for k in ("widths", "speeds", "shells"):
        want = refs.get(f"slicer.k2_{k}")["value"]
        assert {n: proc[k][n] for n in want} == want, k


def test_heat_the_printer_does_not_reach_is_cut_and_said():
    s = printers.settings(printers.get("creality_k2"), "PC")  # the profile asks for 110 C
    assert s["bed"] == 100 and s["cut"] == ["OrcaSlicer Generic PC @System wants the bed at 110 C; the Creality K2 reaches 100 C"]
    assert printers.settings(printers.get("creality_k2"), "pla")["cut"] == []
    s = printers.settings(printers.get("creality_ender3_v3"), "PLA")  # nothing around it holds the profile's 35 C air
    assert "chamber" not in s and "open frame" in s["cut"][0] and printers.settings(printers.get("creality_k2"), "ABS")["chamber"] == 60
    assert printers.settings(printers.get("creality_k2"), "HIPS") is None and printers.settings({"id": "other"}, "PLA") is None


@pytest.mark.parametrize("layer_s, share", [(40, 0.0), (30, 0.10), (21, 0.35), (12, 0.6), (3, 0.6)])
def test_the_fan_runs_faster_on_layers_that_take_less_time(layer_s, share):
    s = {"fan_min": 10, "fan_max": 60, "fan_long": 0, "fan_min_layer_s": 30, "fan_max_layer_s": 12, "fan_over": 50}
    assert printers.fan(s, layer_s) == pytest.approx(share)
    assert printers.fan({**s, "fan_max_layer_s": 30}, 30) == 0.6  # no slope to speak of
    assert printers.fan(s, layer_s, over=True) == pytest.approx(max(share, 0.5))  # Orca never slows it there
