"""stone doctor: the catalog, the ranking, the case flow and the accuracy floor (no real printer)."""

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from smoothstone import cli, doctor, printers

REPO = Path(__file__).resolve().parent.parent
TAX = ("bed_adhesion warping spaghetti blob_on_nozzle stringing under_extrusion over_extrusion clog layer_shift "
       "elephant_foot z_wobble layer_separation ringing overhang_droop poor_bridging support_failure first_layer "
       "surface_zits z_seam wet_filament heat_creep feeder_grinding toppled cracking pillowing multi_material_feed "
       "not_sticking_supports_to_part thermal_error other").split()
OWNER = json.loads((REPO / "evals" / "doctor" / "r_k2_detached_plate.json").read_text())


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
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"subprocess {a}")))
    return w


# the catalog


def test_catalog_covers_the_taxonomy_with_sourced_causes():
    cat = doctor.catalog()
    assert sorted(f["id"] for f in cat["failures"]) == sorted(TAX)
    for f in cat["failures"]:
        assert f["name"] and f["looks_like"]["camera"] and f["looks_like"]["part"]
        if f["id"] != "other":
            assert f["words"] and f["causes"] and 2 <= len(f["differentials"]) + 1, f["id"]
        for d in f["differentials"]:
            assert d["id"] in TAX and d["tell_apart"]
        for c in f["causes"]:
            assert c["id"] and c["cause"] and 0 < c["prior"] <= 1 and c["fix"], c
            assert re.match(r"https?://", cat["sources"][c["source"]]["url"]), c["source"]
            for t in c["tells"]:
                assert t["ask"] and set(t["answers"]) <= set(cat["answers"]), t
            assert c.get("failure", "bed_adhesion") in TAX
    text = json.dumps(cat, ensure_ascii=False)
    assert "\u2014" not in text and "\u2013" not in text


def test_required_safety_lines():
    blob = " ".join(doctor.failure("blob_on_nozzle")["safety"]).lower()
    assert "print temperature" in blob and "thermistor" in blob and "heater" in blob and "sock" in blob
    assert "switch the printer off" in " ".join(doctor.failure("thermal_error")["safety"]).lower()


# the words


def test_stem_negation_and_guesses():
    assert doctor.norm("Curled, curling corners!") == doctor.norm("curl curl corner")
    assert doctor.word_score("the corners curled up", ["corners curl"]) == 2
    assert doctor.word_score("nothing lifted off the plate", ["lifted off"]) == 0
    assert doctor.word_score("it lifted off the plate", ["lifted off"]) == 2
    # what they saw counts in full; their guess, a yes-or-no question or a "definitely" counts a quarter
    assert doctor.word_score("I thought it was wet filament", ["wet filament"]) == 2 * doctor.GUESS
    assert doctor.word_score("Is my nozzle worn out?", ["nozzle worn"]) == 2 * doctor.GUESS
    assert doctor.word_score("Why are there cobwebs?", ["cobwebs"]) == 1
    assert doctor.word_score("I think the bed is bad because the layers shifted", ["layers shifted"]) == 2


def test_owner_case_ranks_the_loose_part_first():
    d = doctor.diagnose(OWNER["said"], printers.get("creality_k2"), "PLA")
    ranked = [f for f, _ in d["failures"]]
    assert ranked[0] == "bed_adhesion" and "blob_on_nozzle" in ranked[:3]
    assert "plate_contaminated" in [c for c, _ in doctor.top_causes(d["causes"])]
    assert "bead" in d["question"]["ask"]


def test_a_blob_described_alone_stays_a_blob():
    d = doctor.diagnose("the part detached and now there's plastic wrapped all around the hotend, a big glob stuck "
                        "on the nozzle")
    assert [f for f, _ in d["failures"]][:2] == ["blob_on_nozzle", "bed_adhesion"]


def test_answers_and_the_best_question():
    f = doctor.failure("bed_adhesion")
    post = doctor.cause_priors(f, "it came off the bed", set())
    q = doctor.best_question(f, post, [])
    assert q and q[2] > 0
    assert doctor.answer_key("it beads up into drops", ["beads", "film"]) == "beads"
    assert doctor.answer_key("spreads out flat like a film", ["beads", "film"]) == "film"
    assert doctor.answer_key("no idea honestly", ["yes", "no"]) == "unknown"
    assert doctor.answer_key("purple", ["yes", "no"]) is None
    lik = doctor.likelihood(f, q[0], q[1])
    after = doctor.update(post, lik, q[1][0])
    assert abs(sum(after.values()) - 1) < 1e-9


# the accuracy floor


def _run():
    spec = importlib.util.spec_from_file_location("doctor_run", REPO / "evals" / "doctor" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("suite", ["doctor", "doctor_heldout"])
def test_accuracy_floor(suite):
    """evals/floor.json keeps the measured top-1 and top-3; a change to the words may not lower either."""
    run = _run()
    folder = REPO / "evals" / suite
    rows = [run.score(c) for c in run.cases(folder)]
    now = run.measure(rows, suite)
    floor = json.loads((REPO / "evals" / "floor.json").read_text())
    for k in ("top1", "top3"):
        key = f"{suite}/{k}"
        assert now[key]["rate"] >= floor[key]["rate"], (key, now[key]["rate"], floor[key]["rate"])
        lost = set(floor[key]["passing"]) - set(now[key]["passing"])
        assert not lost, (key, sorted(lost))
    assert len(rows) >= 40
    if suite == "doctor":
        owner = next(r for r in rows if r["id"] == "r_k2_detached_plate")
        assert owner["top1"] and owner["top3"] and owner["causes"]


# the case flow


def _photo(path: Path, size=(3000, 2000)) -> Path:
    im = Image.new("RGB", size, (90, 90, 90))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x0110] = "PhoneModel"
    im.save(path, "JPEG", exif=exif.tobytes())
    assert Image.open(path).getexif()
    return path


def test_owner_flow_photo_words_answer_try_fixed(work):
    stone("printer", "set", "creality_k2")
    text, code, nxt = stone("doctor", "--image", str(_photo(work / "frame.jpg")))
    assert "EXIF removed" in text and nxt.startswith('stone doctor "<what you see in ')
    case_dir = next((work / "stone-job" / "doctor").glob("2*"))
    saved = Image.open(case_dir / "photo.jpg")
    assert max(saved.size) == doctor.MAX_PX and not saved.getexif()
    assert stone("status")[2] == nxt  # a model that lost context gets the same NEXT back

    text, code, nxt = stone("doctor", OWNER["said"], "--material", "PLA")
    lines = text.splitlines()
    assert lines[0].startswith(f"Case {case_dir.name}, Creality K2, PLA")  # the photo's case took the words
    assert lines[1] == "Most likely: Part came loose from the plate (bed_adhesion)"
    assert any(ln.startswith("Also check: blob_on_nozzle: ") for ln in lines)
    assert re.search(r"^Cause 1: .*\(plate_contaminated\) \d+%$", text, re.M)
    assert "Clean it (maker's steps): Hand sweat" in text
    assert any(ln.startswith("SAFETY: Heat the hotend") for ln in lines)
    assert nxt.startswith("ask the person: Wet the cold plate") and nxt.endswith('stone doctor answer "<their answer>"')
    assert stone("status")[2] == nxt

    text, code, nxt = stone("doctor", "answer", "purple")
    assert "could not tell" in text and nxt.startswith("ask the person: Wet the cold plate")
    text, code, nxt = stone("doctor", "answer", "it beads up into little drops")
    assert "Answer taken as: beads." in text and nxt == "stone doctor try plate_contaminated"

    text, code, nxt = stone("doctor", "try", "plate_contaminated")
    assert "1. Wash the cold plate" in text and "On your Creality K2: Plate: PEI" in text
    assert "wiki.creality.com" in text and nxt.startswith("ask the person: did that fix it?")

    text, code, nxt = stone("doctor", "fixed", "washed the plate with dish soap")
    assert nxt == doctor.DONE
    case = json.loads((case_dir / "case.json").read_text())
    assert case["outcome"]["cause"] == "plate_contaminated" and case["outcome"]["printer"] == "creality_k2"
    shared = json.loads((work / "stone-job" / "doctor" / "outcomes.jsonl").read_text().splitlines()[-1])
    assert shared == doctor.share_payload(case) and "said" not in shared
    assert stone("status")[2] == cli.NEW_NEXT  # nothing open now


def test_no_match_asks_and_no_case_fixes(work):
    text, code, nxt = stone("doctor", "answer", "yes")
    assert code == 1 and "FIX: no open doctor case" in text
    text, code, nxt = stone("doctor", "it looks weird")
    assert "No failure matched" in text and nxt.startswith("ask the person: what does the print look like")


def test_looks_fits_one_screen(work):
    text, code, nxt = stone("doctor", "looks")
    lines = text.splitlines()
    assert len(lines) <= cli.MAX_LINES
    assert lines[0].split(":")[0] in TAX and lines[-2].startswith("Not seen in a photo: clog")
    assert "thermal_error" not in "".join(lines[:-2])


def test_status_inside_a_job_shows_a_newer_case(work):
    (work / "stone-job").mkdir()
    job = cli.Job(work / "stone-job")
    job.update(next="stone build", stage="plan")
    text, code, nxt = stone("doctor", "the print came off the bed", "--printer", "bambu_p1s")
    assert "Doctor case" in stone("status")[0] and stone("status")[2] == nxt
    assert json.loads((work / "stone-job" / "status.json").read_text())["next"] == "stone build"  # untouched
    job.update(last_command="stone build")  # back to the build: its NEXT leads, the case still shows
    text, code, nxt = stone("status")
    assert "Doctor case" in text and nxt == "stone build"


def test_unknown_printer_and_missing_image(work):
    text, code, nxt = stone("doctor", "stringy", "--printer", "makerbot")
    assert code == 1 and nxt == "stone printer"
    text, code, nxt = stone("doctor", "stringy", "--image", str(work / "nope.jpg"))
    assert code == 1 and "no image at" in text


def test_camera_without_and_with_gantrel(work, monkeypatch):
    monkeypatch.setattr(printers, "gantrel", lambda: None)
    text, code, nxt = stone("doctor", "spaghetti everywhere", "--camera")
    assert "No camera frame: gantrel-printer is not installed" in text and "Most likely: " in text

    def fake(argv, timeout=60):
        if argv[1] == "list":
            return 0, json.dumps({"printers": [{"name": "k2", "type": "creality", "model": "creality-k2"}]})
        assert argv[1] == "camera"
        _photo(Path(argv[argv.index("--out") + 1]), (1920, 1080))
        return 0, "saved"
    monkeypatch.setattr(printers, "gantrel", lambda: "/fake/gantrel-printer")
    monkeypatch.setattr(printers, "_run", fake)
    text, code, nxt = stone("doctor", "spaghetti everywhere", "--camera", "--printer", "creality_k2")
    shot = Path(re.search(r"^Photo: (.+)$", text, re.M).group(1))
    assert shot.name == "camera.jpg" and max(Image.open(shot).size) == doctor.MAX_PX
    assert not Image.open(shot).getexif()


def test_gallery_examples(tmp_path, monkeypatch):
    lab = tmp_path / "labels.jsonl"
    (tmp_path / "a.jpg").write_bytes(b"x")
    lab.write_text("\n".join([json.dumps({"file": "a.jpg", "failure": "stringing", "printer": "bambu_a1"}),
                              "not json", json.dumps({"file": "b.jpg", "failure": "stringing", "printer": "creality_k2"}),
                              json.dumps({"file": "c.jpg", "failure": "warping"})]))
    monkeypatch.setattr(doctor, "LABELS", lab)
    ex = doctor.examples("stringing", "creality_k2")
    assert [Path(p).name for p in ex] == ["b.jpg", "a.jpg"]
    monkeypatch.setattr(doctor, "LABELS", tmp_path / "missing.jsonl")
    assert doctor.examples("stringing", None) == []


# review round 1 (PR #92)


@pytest.mark.parametrize("said", ["the top half shifted back 2 mm", "there is a 1 mm gap at the bottom",
                                  "layer 2 moved over by a 1 mm step"])
def test_f1_printer_names_match_whole_words_only(said):
    assert doctor.find_printer(said) is None


@pytest.mark.parametrize("said,want", [("my Creality K2 dropped the part", "creality_k2"),
                                       ("on my k2 plus the part came off", "creality_k2_plus"),
                                       ("ender 3 v3 se stringing", "creality_ender3_v3_se"),
                                       ("X1C left a blob", "bambu_x1c"), ("my mk4s warps abs", "prusa_mk4s")])
def test_f1_printer_names_still_found(said, want):
    assert doctor.find_printer(said)["id"] == want


def test_f1_configured_printer_wins_over_a_guess(work):
    stone("printer", "set", "prusa_mk4s")
    text, code, nxt = stone("doctor", "the top half shifted back 2 mm")
    assert text.splitlines()[0].endswith("Original Prusa MK4S"), text
    text, code, nxt = stone("doctor", "on my k2 the top half shifted back 2 mm")  # a bare 2-letter model: a guess
    assert text.splitlines()[0].endswith("Original Prusa MK4S"), text
    text, code, nxt = stone("doctor", "my Creality K2 Plus shifted layers")  # named clearly: that one
    assert text.splitlines()[0].endswith("Creality K2 Plus"), text


@pytest.mark.parametrize("text,keys,want", [
    ("yes, I never wash it", ["yes", "no"], "yes"),
    ("it doesn't bead, it spreads", ["beads", "film"], "film"),
    ("it doesn't bead", ["beads", "film"], "film"),
    ("it does not spread at all", ["beads", "film"], "beads"),
    ("the water beads up", ["beads", "film"], "beads"),
    ("it is not", ["yes", "no"], None),  # yes and no both: ask again
    ("not sure", ["yes", "no"], "unknown"),
])
def test_f2_answers_read_negation_and_ask_again_when_mixed(text, keys, want):
    assert doctor.answer_key(text, keys) == want


@pytest.mark.parametrize("said", ["thermal runaway", "the printer stopped with a thermal runaway error",
                                  "heater error and it shut down"])
def test_f1sol_no_blob_steps_for_a_thermal_fault(work, said):
    text, code, nxt = stone("doctor", said)
    assert "Most likely: " in text and "(thermal_error)" in text.splitlines()[1]
    safety = [ln for ln in text.splitlines() if ln.startswith("SAFETY: ")]
    assert safety and "switch the printer off" in safety[0]
    assert not any(ln.startswith("SAFETY: Heat the hotend") for ln in safety), text


def test_f1sol_a_blob_with_a_thermal_fault_keeps_power_off_first(work):
    text, code, nxt = stone("doctor", "big blob of plastic on the nozzle and now a thermal runaway error")
    safety = [ln for ln in text.splitlines() if ln.startswith("SAFETY: ")]
    assert "switch the printer off" in safety[0]
    assert not any("Heat the hotend" in ln for ln in safety), text


def test_f2sol_photo_case_keeps_its_printer_and_material(work):
    stone("printer", "set", "creality_k2")
    stone("doctor", "--image", str(_photo(work / "f.jpg")), "--printer", "bambu_a1", "--material", "PETG")
    text, code, nxt = stone("doctor", "the part came off the bed")
    assert text.splitlines()[0].endswith("Bambu Lab A1, PETG"), text
    case = doctor.open_case(cli.Job(work / "stone-job"))
    assert case["printer"] == "bambu_a1" and case["material"] == "PETG"


def _gantrel(monkeypatch, rows, calls):
    def fake(argv, timeout=60):
        calls.append(argv[1:])
        if argv[1] == "list":
            return 0, json.dumps({"printers": rows})
        _photo(Path(argv[argv.index("--out") + 1]), (800, 600))
        return 0, "saved"
    monkeypatch.setattr(printers, "gantrel", lambda: "/fake/gantrel-printer")
    monkeypatch.setattr(printers, "_run", fake)


def test_f3sol_camera_refuses_another_printers_frame(work, monkeypatch):
    calls = []
    _gantrel(monkeypatch, [{"name": "mini", "type": "bambu", "model": "bambu-a1-mini"}], calls)
    text, code, nxt = stone("doctor", "--camera", "--printer", "creality_k2")
    assert code == 1 and "mini" in text and "Creality K2" in text
    assert nxt.startswith("ask the person:") and "stone printer status" in nxt
    assert not any(c[0] == "camera" for c in calls)


def test_f3sol_camera_takes_the_matching_printer(work, monkeypatch):
    calls = []
    _gantrel(monkeypatch, [{"name": "mini", "type": "bambu", "model": "bambu-a1-mini"},
                           {"name": "big", "type": "creality", "model": "creality-k2"}], calls)
    text, code, nxt = stone("doctor", "spaghetti everywhere", "--camera", "--printer", "creality_k2")
    assert ["camera", "big", "--out"] == [c for c in calls if c[0] == "camera"][0][:3]
    case = doctor.open_case(cli.Job(work / "stone-job"))
    assert case["camera"] == {"name": "big", "model": "creality-k2"}


def test_f3_status_after_try_repeats_the_did_it_work_ask(work):
    stone("doctor", "the print came off the bed")
    text, code, nxt = stone("doctor", "try", "plate_contaminated")
    assert stone("status")[2] == nxt and nxt.startswith("ask the person: did that fix it?")
    assert "stone doctor try " in nxt  # the next thing to try if it did not


def test_f4sol_status_after_an_unmatched_description_asks_for_one(work):
    text, code, nxt = stone("doctor", "it looks weird")
    assert stone("status")[2] == nxt and "None" not in nxt


def test_f4_shared_outcome_has_no_paths_addresses_or_emails(work):
    stone("doctor", "the print came off the bed")
    stone("doctor", "fixed", "washed it after my kid smeared sunscreen at 12 Elm St, see /Users/me/notes.txt "
                             "or mail me@example.com, call 555-123-4567")
    line = (work / "stone-job" / "doctor" / "outcomes.jsonl").read_text()
    for bad in ("12 Elm St", "/Users/me", "me@example.com", "555-123-4567"):
        assert bad not in line, line
    assert "sunscreen" in line


def test_gallery_from_the_repo_is_found():
    ex = doctor.examples("spaghetti", None)
    assert ex and all(Path(p).is_file() for p in ex)


# review round 2 (PR #92)

THERMAL_SAID = [
    "the part came off the plate and turned into a spaghetti bird nest, a big lump of plastic around the nozzle, "
    "and the screen said thermal runaway",
    "big lump of plastic around the nozzle, the part came off the bed, strings everywhere, and MINTEMP",
    "nothing comes out of the nozzle and now the screen shows a thermal runaway",
]


@pytest.mark.parametrize("said", THERMAL_SAID)
def test_r2_thermal_fault_leads_whatever_else_scores(work, said):
    assert doctor.diagnose(said)["failures"][0][0] == "thermal_error"
    text, code, nxt = stone("doctor", said)
    lines = text.splitlines()
    assert lines[1] == "Most likely: Heater or thermistor error (thermal_error)", text
    first = next(i for i, ln in enumerate(lines) if ln.startswith("SAFETY: "))
    assert lines[first].startswith("SAFETY: Thermal errors are the firmware stopping a heater"), text
    assert first < min(i for i, ln in enumerate(lines) if ln.startswith(("Also check", "Cause 1"))), text
    assert not any(h in text.lower() for h in ("heat the hotend", "with the hotend hot", "heat up and push")), text


def test_r2_two_photo_cases_in_one_second_keep_their_own_folders(work, monkeypatch):
    import datetime as real

    class Frozen(real.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 24, 1, 2, 3)

    monkeypatch.setattr(doctor, "_dt", type("dt", (), {"datetime": Frozen, "date": real.date}))
    stone("doctor", "--image", str(_photo(work / "a.jpg")))
    first = sorted((work / "stone-job" / "doctor").glob("2*"))
    first_bytes = (first[0] / "photo.jpg").read_bytes()
    Image.new("RGB", (900, 700), (10, 200, 10)).save(work / "b.jpg", "JPEG")
    stone("doctor", "--image", str(work / "b.jpg"))
    cases = sorted((work / "stone-job" / "doctor").glob("2*"))
    assert len(cases) == 2, cases
    assert (first[0] / "photo.jpg").read_bytes() == first_bytes  # the first photo was not overwritten
    assert json.loads((first[0] / "case.json").read_text())["id"] == first[0].name


def test_r2_a_case_keeps_the_printer_it_was_opened_with(work):
    stone("doctor", "--image", str(_photo(work / "a.jpg")), "--printer", "bambu_a1")
    said = "The part came off the bed. It looks like the failure I had on my Creality K2 Plus."
    text, code, nxt = stone("doctor", said)
    assert text.splitlines()[0].endswith("Bambu Lab A1"), text
    case_dir = next((work / "stone-job" / "doctor").glob("2*"))
    assert json.loads((case_dir / "case.json").read_text())["printer"] == "bambu_a1"


@pytest.mark.parametrize("text,want", [
    ("I never wash it", None),  # a negator says nothing about yes or no: ask again
    ("it never gets washed", None),
    ("no, I wash it before every print", "no"),
    ("nope", "no"),
    ("yes it has", "yes"),
])
def test_r2_a_bare_negator_is_not_a_no(text, want):
    assert doctor.answer_key(text, ["yes", "no"]) == want


def test_r2_owner_flow_reads_the_wash_question_and_reaches_plate_contaminated(work):
    stone("printer", "set", "creality_k2")
    stone("doctor", OWNER["said"], "--material", "PLA")
    text, code, nxt = stone("doctor", "answer", "can't tell")
    wash = nxt
    assert "wash" in wash and " or " not in wash.split("?")[0], wash  # one fact per question
    text, code, nxt = stone("doctor", "answer", "I never wash it")
    assert "could not tell" in text and nxt == wash, text
    text, code, nxt = stone("doctor", "answer", "yes")
    assert re.search(r"^Cause 1: .*\(plate_contaminated\)", text, re.M), text  # "I never wash it" no longer lowers it
    text, code, nxt = stone("doctor", "answer", "no, they were pressed flat")
    assert nxt == "stone doctor try plate_contaminated", nxt
