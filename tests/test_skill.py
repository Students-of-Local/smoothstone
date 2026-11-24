"""The skill files: every stone command they name is real, and SKILL.md leads to every card."""

import re

import pytest

from smoothstone import cli, config

CARDS = sorted(config.skill_dir().rglob("*.md"))
PROSE = set("already also and answers asks builds commands converts counts cuts did does found like message never passes printed prints "
            "ranks saves says sends turns weighs".split())  # "stone never guesses": words that are not commands


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_every_command_a_card_names_exists(card):
    named = set(re.findall(r"\bstone ([a-z]+)\b", re.sub(r"\s+", " ", card.read_text())))
    assert named - PROSE <= set(cli.COMMANDS), named - PROSE - set(cli.COMMANDS)


def test_skill_md_leads_to_every_card():
    text = (config.skill_dir() / "SKILL.md").read_text()
    assert not [c.name for c in CARDS if c.name != "SKILL.md" and c.name not in text]


def test_every_tiers_stop_rule_names_the_checks_a_part_needs():
    """stone status reprints the Rules after a compaction, so the exception to "stop" has to be in them."""
    for tier, words in (("S", ("stone strength", "stone heat", "ask that and stop")), ("M", ("load", "heat", "that check first")),
                        ("L", ("load", "heat", "not checked"))):
        stop = [x for x in config.tier_rules(tier) if "Stop when" in x][0]
        assert all(w in stop for w in words), (tier, stop)


def test_tier_s_answers_the_question_doctor_asked():
    rules = " ".join(config.tier_rules("S"))
    assert "SAFETY" in rules and "stone doctor answer" in rules
