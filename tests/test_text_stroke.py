"""text: letters too thin for a 0.4 mm nozzle fail, and the FIX grows the one setting that sizes them."""

import shutil

import pytest

from smoothstone import check
from test_cli import REPO, stone


def echo(size, font="sans", param="label_size", at=None):
    return f'ECHO: stone_text = [{size}, "{font}", "{param}", {size if at is None else at}]\n'


def test_font_table_gives_the_smallest_letters():
    # 2 lines of a 0.4 mm nozzle: sans bold needs about 5.3 mm letters, serif bold about 11.4 mm
    assert check.MIN_STROKE == 0.8
    assert check.MIN_STROKE / check.TEXT_STROKE["sans"] == pytest.approx(5.33, abs=0.01)
    assert check.MIN_STROKE / check.TEXT_STROKE["serif"] == pytest.approx(11.43, abs=0.01)


def test_text_results_fail_thin_letters_and_keep_the_worst():
    assert check.text_results("no echo here") == []
    (ok,) = check.text_results(echo(6))
    assert ok.ok and ok.value == pytest.approx(0.9)
    (bad,) = check.text_results(echo(6) + echo(10, "serif", "w", 160))
    assert not bad.ok
    assert bad.param == "w" and bad.at == 160 and bad.measured == 10
    assert "0.70 mm" in bad.detail


# Each starts from settings an audit found too thin, and must reach a passing part by its NEXT line.
CASES = [
    # the panel examples gauges (4.5 mm) and keystone_4 (5 mm)
    ("panel", ["label=TEMP  VOLTS  AMPS", "label_size=4.5", "w=120", "d=60"], "stone set label_size=6"),
    ("box", ["label=TOOLS", "label_size=4", "part=lid"], "stone set label_size=6"),
    ("sign", ["text=12", "text_size=8", "font=serif"], "stone set text_size=12"),
    ("keychain", ["text=ALEXANDRIA", "size=30"], "stone set size=49"),
]


@pytest.mark.parametrize("recipe,settings,first_next", CASES, ids=[c[0] for c in CASES])
def test_thin_text_fix_leads_to_a_passing_part(recipe, settings, first_next, jobenv, recipes_root, openscad):
    shutil.copytree(REPO / "recipes" / recipe, recipes_root / recipe)
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib")
    stone("new", f"a {recipe} with text")
    text, code, nxt = stone("set", recipe, *settings)
    assert code == 0, text
    text, code, nxt = stone("build")
    assert code == 1 and "FIX: text letter strokes" in text, text
    assert nxt == first_next, text
    stone(*nxt.split()[1:])
    text, code, nxt = stone("build")
    assert "Part ready" in text, text
