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
    cli.run(["new", "a snug cup that holds my HomePod mini on a shelf"])
    text, _ = cli.run(["show", "round_case"])
    assert _next(text) == ("ask the person: HomePod mini's width, depth and height in mm, and where the numbers "
                           "come from (the maker's spec page, or their own ruler)")
    assert len(text.splitlines()) == 4, text


def test_after_the_answer_next_is_the_product_add_line(job):
    cli.run(["new", STUDIO])
    _follow("stone status")
    text, _ = cli.run(["note", STUDIO_SAYS])
    assert _next(text) == ('stone product add "Mac Studio (2025)" --size 197 197 95 '
                           '--source "https://support.apple.com/en-us/122211"')
    assert "Answer:" not in (job / "brief.md").read_text()  # the sizes are the product's, not the part's
    text, _ = cli.run(shlex.split(_next(text))[1:])
    assert _next(text) == "stone set product_mount product=mac_studio_2025"


def test_a_cup_for_a_round_product_asks_for_a_disc_open_on_top(job):
    cli.run(["new", "a snug cup that holds my HomePod mini on a shelf"])
    _follow("stone status")
    text, _ = cli.run(["note", "Apple says it is 3.3 inches high (84.3 mm) and 3.9 inches wide (97.9 mm), on "
                               "https://support.apple.com/en-us/111914"])
    assert _next(text) == ('stone product add "HomePod mini" --size 97.9 97.9 84.3 --round --open +z '
                           '--source "https://support.apple.com/en-us/111914"')


def test_an_answer_without_a_source_asks_where_the_numbers_come_from(job):
    cli.run(["new", STUDIO])
    _follow("stone status")
    text, _ = cli.run(["note", "197 x 197 x 95 mm"])
    assert _next(text).startswith("ask the person: where Mac Studio (2025)'s numbers come from")
    text, _ = cli.run(["note", "https://support.apple.com/en-us/122211"])
    assert _next(text).startswith('stone product add "Mac Studio (2025)" --size 197 197 95 ')


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
