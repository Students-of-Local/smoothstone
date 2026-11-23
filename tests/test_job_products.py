"""A product the catalog does not have: stone asks the person for its size and where it comes from,
then stone product add writes it to the job, and every product recipe takes it like a catalog one.

Each test here fails without climb 4: before it, stone show for "a mount for my Mac Studio" offered
the catalog's default product, and there was no stone product add.
"""
import json
import re
import shlex
from pathlib import Path

import pytest

from smoothstone import catalog, cli, match
from smoothstone import recipes as rc

REPO = Path(__file__).resolve().parent.parent
STUDIO = "an under desk mount for my Mac Studio (2025)"
STUDIO_SAYS = ("Apple's tech specs page says Height: 3.7 inches (9.5 cm), Width: 7.7 inches (19.7 cm), "
               "Depth: 7.7 inches (19.7 cm). It is https://support.apple.com/en-us/122211")
ASK = ("ask the person: Mac Studio (2025)'s width, depth and height in mm, and where the numbers come from "
       "(the maker's spec page, or their own ruler)")


@pytest.fixture
def job(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    return jobenv / "stone-job"


def _next(text: str) -> str:
    return re.findall(r"^NEXT: (.+)$", text, re.M)[-1].strip()


def _follow(nxt: str, steps: int = 10) -> tuple[str, list[str]]:
    """Run each NEXT line as evals/run.py --driver next does; (where it stopped, every output)."""
    outs = []
    for _ in range(steps):
        if not nxt.startswith("stone ") or "<" in nxt:
            break
        text, _ = cli.run(shlex.split(nxt)[1:])
        outs.append(text)
        nxt = _next(text)
    return nxt, outs


def test_product_add_writes_the_record_with_its_source(job):
    cli.run(["new", "a holder for my Acme Hub X200A"])
    text, code = cli.run(["product", "add", "Acme Hub X200A", "--size", "120", "80", "30",
                          "--source", "https://example.com/x200a/specs"])
    assert code == 0, text
    rec = json.loads((job / "products" / "acme_hub_x200a.json").read_text())
    assert rec["slug"] == "acme_hub_x200a" and rec["set"] == "job" and rec["fitted_case"] is True
    assert rec["aliases"] == ["Acme Hub X200A", "X200A"]
    assert rec["body"] == {"w": 120.0, "d": 80.0, "h": 30.0, "corner_r": 0.0}
    assert all("https://example.com/x200a/specs" in v for v in rec["body_sources"].values())
    assert catalog.sources(rec)["w"] == "https://example.com/x200a/specs"
    assert "slug acme_hub_x200a" in text


def test_product_add_refuses_without_a_source_and_says_why(job):
    cli.run(["new", "a holder for my Acme Hub"])
    text, code = cli.run(["product", "add", "Acme Hub", "--size", "120", "80", "30"])
    assert code == 1
    assert "stone never estimates a size" in text
    assert _next(text).startswith("ask the person: where do Acme Hub's numbers come from")
    assert not (job / "products").exists()


def test_a_round_product_is_a_disc():
    rec = catalog.make_product("HomePod mini", 97.9, 0, 84.3, "https://support.apple.com/en-us/111914", round_=True,
                               open_faces=["+z"])
    assert rec["body"] == {"w": 97.9, "d": 97.9, "h": 84.3, "corner_r": 48.95}
    assert rec["fitted_case"] is False and rec["open_faces"] == ["+z"] and catalog.is_round(rec)


def test_a_job_product_is_offered_to_the_kinds_that_fit_it(job):
    cli.run(["new", "a holder for my Acme Hub"])
    cli.run(["product", "add", "Acme Hub", "--size", "120", "80", "30", "--source", "measured by the person"])
    cli.run(["product", "add", "Acme Puck", "--size", "60", "60", "20", "--round", "--source", "https://example.com/p"])
    catalog.use_job(job)
    assert "acme_hub" in catalog.slugs_for("fitted_case") and "acme_hub" in catalog.slugs_for("product_mount")
    assert "acme_hub" in catalog.slugs_for("product_holder") and "acme_hub" not in catalog.slugs_for("round_case")
    assert catalog.kinds_for("acme_puck") == ["round_case"]
    assert catalog.find("a cradle for my acme puck") == "acme_puck"
    assert "acme_hub" in rc.load("product_mount", REPO / "recipes").param("product").choices
    catalog.use_job(None)
    assert "acme_hub" not in catalog.slugs_for("fitted_case") and catalog.get("acme_hub") is None


def test_next_asks_the_person_for_an_unknown_products_size_and_names_no_catalog_product(job):
    cli.run(["new", STUDIO])
    stop, outs = _follow("stone status")
    assert stop == ASK, outs[-1]
    said = "\n".join(outs)
    for slug, p in catalog.shipped().items():
        assert slug not in said and p["name"] not in said, slug
    assert _next(cli.run(["status"])[0]) == ASK
    # a set line with no product asks the same, never building the default product
    text, code = cli.run(["set", "product_mount"])
    assert code == 1 and _next(text) == ASK and not (job / "plan.json").exists()


def test_tier_s_asks_with_that_line_alone(job, monkeypatch):
    cli.run(["new", STUDIO])
    text, _ = cli.run(["show", "product_mount"])
    assert _next(text) == ASK
    assert len(text.splitlines()) == 4, text


def test_the_ask_comes_before_the_note_hint(job):
    """24B e11 s1, s2 (climb 4): with "When the person answers, run: stone note" above NEXT, the model
    noted stone's own question. NEXT comes first; the hint after it is plainly for later."""
    cli.run(["new", STUDIO])
    lines = cli.run(["show", "product_mount"])[0].splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.startswith("NEXT: "))
    assert lines[at] == "NEXT: " + ASK
    assert not any("stone note" in ln for ln in lines[:at])
    assert lines[at + 1].startswith("After the person answers (not before): stone note")


@pytest.mark.parametrize("note", [
    ASK[len("ask the person: "):],
    "Ask for the Mac Studio (2025) width, depth and height in mm and where they come from",
    # 24B e11 s2 (climb 4, after round 2): reworded with a request, the overlap fell under the bar,
    # and "your own ruler" in the question was then kept as the person's source
    "Mac Studio (2025) under desk mount: please provide its width, depth, and height in mm, and where "
    "those numbers come from (e.g., maker's spec page or your own ruler).",
    "I need the Mac Studio (2025) dimensions: please provide its width, depth, and height in mm, and "
    "where you got them (e.g., Apple's spec page or your own ruler).",
])
def test_note_refuses_stones_own_question(job, note):
    cli.run(["new", STUDIO])
    cli.run(["show", "product_mount"])
    text, code = cli.run(["note", note])
    assert code == 1 and "that is your question, not the person's answer" in text
    assert _next(text) == ASK and json.loads((job / "notes.json").read_text() if (job / "notes.json").exists() else "[]") == []


def test_note_refuses_the_question_when_it_speaks_to_the_person(job):
    """24B e12 s2 (climb 4): no request word, but it says "you" to the person, and "your own ruler" in it
    became the source "measured by the person", which no spec cites."""
    cli.run(["new", "a snug cup that holds my HomePod mini on a shelf"])
    cli.run(["show", "round_case"])
    text, code = cli.run(["note", "HomePod mini diameter and height in mm, and where did you get them from "
                                  "(the maker's spec page or your own ruler)"])
    assert code == 1 and "that is your question, not the person's answer" in text
    assert not (job / "notes.json").exists() or json.loads((job / "notes.json").read_text()) == []


@pytest.mark.parametrize("answer", [
    "I don't have it with me; I'll measure it tonight",
    "Could not find it online, I measured it: 197 by 197 by 95 mm",
    "It is the one on apple.com, what is the next step?",
])
def test_a_persons_answer_is_still_noted(job, answer):
    """The question check refuses only a note that asks for a size with no number or URL of its own."""
    cli.run(["new", STUDIO])
    cli.run(["show", "product_mount"])
    text, _ = cli.run(["note", answer])
    assert "that is your question" not in text


def test_a_round_product_is_asked_its_diameter_and_height(job):
    """LFM3 e12 s1 (climb 4): asked a depth Apple does not give, it noted "97.9 x ? x 84.3 mm" and stalled."""
    cli.run(["new", "a snug cup that holds my HomePod mini on a shelf"])
    text, _ = cli.run(["show", "round_case"])
    assert _next(text) == ("ask the person: HomePod mini's diameter and height in mm, and where the numbers "
                           "come from (the maker's spec page, or their own ruler)")
    text, _ = cli.run(["note", "HomePod mini: 97.9 x ? x 84.3 mm, https://support.apple.com/en-us/111914"])
    assert _next(text) == ('stone product add \'HomePod mini\' --size 97.9 97.9 84.3 --round --open +z '
                           '--source https://support.apple.com/en-us/111914')


def test_the_products_own_name_is_no_size(job):
    """24B e11 (climb 4): "Mac Studio (2025)'s width" read as a width of 2025 mm."""
    assert "w" not in match.size_answer("Mac Studio (2025)'s width is on the spec page", "Mac Studio (2025)")


AFTER_LINE = 'After the person answers (not before): stone note "<their answer>", then run the NEXT line it prints.'
CUP_ASK = ("ask the person: HomePod mini's diameter and height in mm, and where the numbers come from "
           "(the maker's spec page, or their own ruler)")
CUP = "a snug cup that holds my HomePod mini on a shelf"
CUP_SAYS = ("Apple lists Height: 3.3 inches (84.3 mm), Width: 3.9 inches (97.9 mm) at "
            "https://support.apple.com/en-us/111914")


@pytest.mark.parametrize("items", [
    ["product_mount", "width=196", "depth=196", "height=94"],
    ["product_mount", "height=93.98mm", "w=195.58", "d=195.58"],
    ["product_mount", "size=197x197x95"],
    ["product_mount", "width=196"],
])
def test_sizes_set_before_a_note_go_to_the_persons_words(job, items):
    """LFM3 e11 s1, s2 and 24B e11 s1 to s3 (climb 4 round 2): the model skipped stone note, converted
    Apple's inches itself (195.58, 196) and set them; the redirect made them the product add line and
    the part pressed 0.7 mm into the product. Sizes come from the person's own words, read by stone.
    PR 76 review: NEXT is the ask itself, never a stone note placeholder a model that has not asked
    yet would fill with its own guess; the note comes after the person answers."""
    cli.run(["new", STUDIO])
    cli.run(["show", "product_mount"])
    for _ in range(3):  # asked again, it says the same, and never sends the model to the person stuck
        text, code = cli.run(["set", *items])
        assert code == 1 and _next(text) == ASK, text
        assert "the sizes were not set" in text and text.splitlines()[-1] == AFTER_LINE
    assert "stone note \"<the person" not in text
    assert not (job / "plan.json").exists() and not list((job / "products").glob("*.json"))


def test_a_guessed_set_then_a_note_with_no_source_never_reaches_product_add(job):
    """PR 76 review: a model that sets its own guess, then notes that guess, has given no source, so
    stone asks where the numbers come from and never writes the product."""
    cli.run(["new", STUDIO])
    cli.run(["show", "product_mount"])
    text, _ = cli.run(["set", "product_mount", "width=196", "depth=196", "height=94"])
    assert _next(text) == ASK
    text, _ = cli.run(["note", "Mac Studio (2025) is 196 x 196 x 94 mm"])
    assert _next(text).startswith("ask the person: where Mac Studio (2025)'s numbers come from"), text
    for cmd in (["set", "product_mount", "width=196", "depth=196", "height=94"], ["show", "product_mount"]):
        text, _ = cli.run(cmd)
        assert not _next(text).startswith("stone product add"), text
    assert not list((job / "products").glob("*.json"))


@pytest.mark.parametrize("items,differs", [
    (["product_mount", "width=196", "depth=196", "height=94"], True),
    (["product_mount", "width=195.58", "depth=195.58", "height=93.98"], True),
    (["product_mount", "width=197", "depth=197", "height=95"], False),
    (["product_mount", "width=197.04", "depth=197", "height=95"], False),
])
def test_noted_sizes_win_over_sizes_set_after_them(job, items, differs):
    """Once the person's answer is noted, a set with other numbers keeps the noted ones, and the metric
    figure Apple prints beside the inches ("3.7 inches (9.5 cm)") is the one stone reads."""
    cli.run(["new", STUDIO])
    cli.run(["show", "product_mount"])
    cli.run(["note", STUDIO_SAYS])
    cli.run(["show", "product_mount"])  # a show again keeps what the person said
    text, code = cli.run(["set", *items])
    assert code == 1 and _next(text) == ('stone product add \'Mac Studio (2025)\' --size 197 197 95 '
                                         '--source https://support.apple.com/en-us/122211')
    assert ("differ from what the person said" in text) == differs
    if differs:
        assert "stone keeps the noted numbers" in text


@pytest.mark.parametrize("items", [
    ["round_case", "size=97.9", "height=84.3"],
    ["round_case", "diameter=98", "height=85"],
    ["round_case", "size=97.9x84.3"],
])
def test_round_case_takes_size_and_diameter_on_set(job, items):
    """24B e12 s1 (climb 4 round 2): size=97.9 height=84.3 on round_case read no diameter, and stone
    asked the question again, eleven times. On a round product size= is the diameter, routed to the
    note, then to the noted numbers."""
    cli.run(["new", CUP])
    cli.run(["show", "round_case"])
    text, _ = cli.run(["set", *items])
    assert _next(text) == CUP_ASK and "the sizes were not set" in text, text
    cli.run(["note", CUP_SAYS])
    text, _ = cli.run(["set", *items])
    assert _next(text) == ('stone product add \'HomePod mini\' --size 97.9 97.9 84.3 --round --open +z '
                           '--source https://support.apple.com/en-us/111914')


def test_after_the_answer_next_is_the_product_add_line(job):
    cli.run(["new", STUDIO])
    _follow("stone status")
    text, _ = cli.run(["note", STUDIO_SAYS])
    assert _next(text) == ('stone product add \'Mac Studio (2025)\' --size 197 197 95 '
                           '--source https://support.apple.com/en-us/122211')
    assert "Answer:" not in (job / "brief.md").read_text()  # the sizes are the product's, not the part's
    text, _ = cli.run(shlex.split(_next(text))[1:])
    assert _next(text) == "stone set product_mount product=mac_studio_2025"


def test_a_cup_for_a_round_product_asks_for_a_disc_open_on_top(job):
    cli.run(["new", "a snug cup that holds my HomePod mini on a shelf"])
    _follow("stone status")
    text, _ = cli.run(["note", "Apple says it is 3.3 inches high (84.3 mm) and 3.9 inches wide (97.9 mm), on "
                               "https://support.apple.com/en-us/111914"])
    assert _next(text) == ('stone product add \'HomePod mini\' --size 97.9 97.9 84.3 --round --open +z '
                           '--source https://support.apple.com/en-us/111914')


def test_an_answer_without_a_source_asks_where_the_numbers_come_from(job):
    cli.run(["new", STUDIO])
    _follow("stone status")
    text, _ = cli.run(["note", "197 x 197 x 95 mm"])
    assert _next(text).startswith("ask the person: where Mac Studio (2025)'s numbers come from")
    text, _ = cli.run(["note", "https://support.apple.com/en-us/122211"])
    assert _next(text).startswith('stone product add \'Mac Studio (2025)\' --size 197 197 95 ')


@pytest.mark.parametrize("text,want", [
    ("Height: 3.7 inches (9.5 cm), Width: 7.7 inches (19.7 cm), Depth: 7.7 inches (19.7 cm)",
     {"w": 197.0, "d": 197.0, "h": 95.0}),
    ("3.3 inches high (84.3 mm) and 3.9 inches wide (97.9 mm)", {"w": 97.9, "h": 84.3}),
    ("I measured it with a ruler: 120 x 80 x 30 mm", {"w": 120.0, "d": 80.0, "h": 30.0,
                                                       "source": "measured by the person"}),
])
def test_size_answer_reads_the_makers_own_rows(text, want):
    got = match.size_answer(text)
    assert {k: got[k] for k in want} == want


def test_product_named_reads_the_product_a_part_is_for():
    assert match.product_named(STUDIO) == "Mac Studio (2025)"
    assert match.product_named("a snug cup that holds my HomePod mini on a shelf") == "HomePod mini"
    assert match.product_named("a gridfinity bin 2 by 1") is None


def test_a_box_product_builds_in_a_fitted_case(job, openscad):
    cli.run(["new", "a case for my Acme Hub X200A"])
    cli.run(["product", "add", "Acme Hub X200A", "--size", "60", "40", "20", "--source", "https://example.com/x200a"])
    text, _ = cli.run(["set", "fitted_case", "product=acme_hub_x200a"])
    assert _next(text) == "stone build", text
    text, code = cli.run(["build"])
    assert code == 0 and "Part ready" in text, text
    eng = json.loads((job / "build" / "engineering.json").read_text())
    assert eng["sources"]["w"] == "https://example.com/x200a"


def test_a_round_product_open_on_top_gets_a_cup_with_no_rim(job, openscad):
    import trimesh

    cli.run(["new", "a cup that holds my Acme Puck"])
    cli.run(["product", "add", "Acme Puck", "--size", "40", "40", "15", "--round", "--open", "+z",
             "--source", "https://example.com/puck"])
    cli.run(["set", "round_case", "product=acme_puck"])
    text, code = cli.run(["build"])
    assert code == 0, text
    m = trimesh.load(job / "build" / "part.stl")
    eng = json.loads((job / "build" / "engineering.json").read_text())
    cx, cy = (eng["frame"][0][3] + 20, eng["frame"][1][3] + 20)  # the puck's axis in the part
    top = m.vertices[m.vertices[:, 2] > m.bounds[1][2] - 0.01]
    # the top edge is the wall alone: nothing reaches in over the puck (r 20, 0.2 clearance)
    assert ((top[:, 0] - cx) ** 2 + (top[:, 1] - cy) ** 2).min() ** 0.5 >= 20.15


CUP_ADD = ('stone product add \'HomePod mini\' --size 97.9 97.9 84.3 --round --open +z '
           '--source https://support.apple.com/en-us/111914')


@pytest.mark.parametrize("line", [
    # LFM3 e12 s2 (climb 4 round 2): stone read all of it as the name, and asked for the source three times
    'stone product add "HomePod mini" size=97.9,97.9,84.3 round open z source="https://support.apple.com/en-us/111914"',
    'stone product add --name="HomePod mini" --size=97.9,97.9,84.3 --round --open z '
    '--source="https://support.apple.com/en-us/111914"',
    'stone product add name="HomePod mini" diameter=97.9 h=84.3 open=+z source=https://support.apple.com/en-us/111914',
    'stone product add "HomePod mini" source=https://support.apple.com/en-us/111914 size=97.9x84.3 round open=top',
    'stone product add "HomePod mini" size=97.9 97.9 84.3 --round --open +z --source https://support.apple.com/en-us/111914',
])
def test_product_add_reads_name_value_words(job, line):
    """stone product add reads name=value words in any order, as stone set does."""
    cli.run(["new", CUP])
    cli.run(["show", "round_case"])
    text, code = cli.run(shlex.split(line)[1:])
    assert code == 0, text
    rec = json.loads((job / "products" / "homepod_mini.json").read_text())
    assert rec["name"] == "HomePod mini" and rec["body"]["w"] == 97.9 and rec["body"]["h"] == 84.3
    assert rec["open_faces"] == ["+z"] and rec["sources"] == ["https://support.apple.com/en-us/111914"]
    assert _next(text).startswith("stone set round_case product=homepod_mini")


def test_product_add_box_from_w_d_h(job):
    cli.run(["new", STUDIO])
    cli.run(["show", "product_mount"])
    text, code = cli.run(["product", "add", "Mac Studio (2025)", "w=197", "d=197", "h=95",
                          "source=https://support.apple.com/en-us/122211"])
    assert code == 0, text
    assert json.loads((job / "products" / "mac_studio_2025.json").read_text())["body"]["d"] == 197


def test_product_add_gives_the_corrected_line_for_words_it_cannot_read(job):
    cli.run(["new", CUP])
    cli.run(["show", "round_case"])
    text, code = cli.run(["product", "add", "HomePod mini", "size=97.9x84.3", "round", "open=z", "color=white",
                          "source=https://support.apple.com/en-us/111914"])
    assert code == 1 and "could not read: color=white" in text
    assert _next(text) == CUP_ADD and not list((job / "products").glob("*.json"))
    text, code = cli.run(shlex.split(_next(text))[1:])
    assert code == 0, text


def test_a_question_noted_after_the_set_redirect_is_refused(job):
    cli.run(["new", CUP])
    cli.run(["show", "round_case"])
    cli.run(["set", "round_case", "diameter=98", "height=85"])
    text, code = cli.run(["note", "What are the HomePod mini's diameter and height in mm?"])
    assert code == 1 and "that is your question" in text
    text, _ = cli.run(["note", CUP_SAYS])
    assert _next(text) == CUP_ADD


@pytest.mark.parametrize("cmd", [
    # 24B e11 s2 (climb 4 round 3): after a full note, the shell split size=196 196 94, set read no size,
    # and stone asked the person again, a loop to the step limit
    ["set", "product_mount", "size=196", "196", "94"],
    ["set", "product_mount"],
    ["show", "product_mount"],
])
def test_after_a_full_note_stone_never_asks_again(job, cmd):
    cli.run(["new", STUDIO])
    cli.run(["show", "product_mount"])
    cli.run(["note", STUDIO_SAYS])
    text, _ = cli.run(cmd)
    assert _next(text) == ('stone product add \'Mac Studio (2025)\' --size 197 197 95 '
                           '--source https://support.apple.com/en-us/122211'), text
    assert "ask the person" not in text and "no sourced sizes" not in text


def test_size_split_by_the_shell_is_read_whole(job):
    assert cli.set_sizes(["product_mount", "size=196", "196", "94"]) == {"w": 196, "d": 196, "h": 94}


def _shell_args(line: str, cwd) -> list[str]:
    """The words a real shell hands the command on this NEXT line (printf stands in for stone)."""
    import subprocess

    cmd = "printf '%s\\n' " + line.split(" ", 1)[1]
    out = subprocess.run(["sh", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=10)
    return out.stdout.splitlines()


def test_free_text_on_a_next_line_reads_back_literally(job, tmp_path):
    """PR 76 review: a request or source with shell characters must never run inside a NEXT line, as
    an agent's shell runs it; the shell hands stone the literal text."""
    name_req = "a stand for my `touch pwned` hub"
    x = match.product_named(name_req)
    assert "`touch pwned`" in x
    line = cli.product_add_line(x, {"w": 100, "d": 80, "h": 30, "source": "spec page $(touch pwned2)"}, False, [])
    argv = _shell_args(line, tmp_path)
    assert argv[2] == x and argv[argv.index("--source") + 1] == "spec page $(touch pwned2)"
    assert shlex.split(line)[3] == x
    cli.run(["new", CUP])
    cli.run(["show", "round_case"])
    text, code = cli.run(["product", "add", "HomePod mini", "size=97.9x84.3", "round", "color=white",
                          "source=measured $(touch pwned3) `touch pwned4`"])
    argv = _shell_args(_next(text), tmp_path)
    assert code == 1 and argv[2] == "HomePod mini"
    assert argv[argv.index("--source") + 1] == "measured $(touch pwned3) `touch pwned4`"
    assert not list(tmp_path.glob("pwned*"))


@pytest.mark.parametrize("text,url", [
    ("see https://example.com/spec$(id) now", "https://example.com/spec"),
    ("https://example.com/a`whoami`", "https://example.com/a"),
    ("https://example.com/a;rm -rf x", "https://example.com/a"),
    ("(https://support.apple.com/en-us/122211)", "https://support.apple.com/en-us/122211"),
])
def test_first_url_stops_at_shell_characters(text, url):
    assert catalog.first_url(text) == url


@pytest.mark.parametrize("v", ["HELLO $(touch pwned)", "a`touch pwned`b", 'say "hi"', "it's", "x;y", "plain words"])
def test_recipe_text_values_read_back_literally(v, tmp_path):
    p = rc.Param(name="text", type="text", default="")
    assert _shell_args("stone text=" + rc.fmt_value(p, v), tmp_path) == ["text=" + v]


@pytest.mark.parametrize("answer,size", [
    # PR 76 review: the first triple was the inches, and stone read 93.98 x 195.58 x 195.58
    ("3.7 x 7.7 x 7.7 in (9.5 x 19.7 x 19.7 cm), https://support.apple.com/en-us/122211", (95, 197, 197)),
    ("7.7 x 7.7 x 3.7 in (19.7 x 19.7 x 9.5 cm), https://support.apple.com/en-us/122211", (197, 197, 95)),
    ("197 x 197 x 95 mm (7.7 x 7.7 x 3.7 in)", (197, 197, 95)),
    ("7.7 x 7.7 x 3.7 in", (195.58, 195.58, 93.98)),
])
def test_the_metric_triple_wins_over_inches(answer, size):
    got = match.size_answer(answer, "Mac Studio (2025)")
    assert (got["w"], got["d"], got["h"]) == size
