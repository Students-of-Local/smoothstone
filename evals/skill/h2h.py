"""Blind head-to-head of two skill folders: does the new card text make a small model's next step better?

  python evals/skill/h2h.py OUT OLD_SKILL_DIR NEW_SKILL_DIR S|M|L [repeats]

Haiku gets SKILL.md and the tier card, no tools, one message from scenarios.json, and writes its next commands (Haiku for
every tier: it stands in for the 3B and frontier readers, it does not measure them).
Opus grades both replies against the rubric without knowing which card wrote which. Both run as `claude -p` on the
person's sign-in (ANTHROPIC_API_KEY removed). Each case's replies and scores go to OUT; the table is printed."""

import concurrent.futures as cf
import json
import os
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY" and not k.startswith("CLAUDE_CODE")}
CLAUDE = ["claude", "-p", "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--mcp-config",
          '{"mcpServers":{}}', "--no-session-persistence"]
RESPOND = """You help a person with 3D printing. You have a shell with the stone command. This skill is loaded and you follow it:

<skill>
{skill}

# tiers/{tier}.md

{card}
</skill>

This turn no tool runs. Write only your next step: the stone command or commands you would run now, each on its own line \
starting with '$ ', and the words you would say to the person, if any. Do not invent what a command prints."""
JUDGE = """Two assistants that drive a 3D printing command line tool (stone) gave their next step. Grade blind, only on the rubric.
Context: {ctx}
The person says: {msg}
Rubric: {rubric}
Facts: these stone commands are real, and no others: {commands}. stone timelapse has --fail. stone printer lists, shows \
and keeps printer profiles. stone never starts a print or sends anything. Naming a command that does not exist is a \
serious fault.

Reply A:
<<<
{a}
>>>

Reply B:
<<<
{b}
>>>

Return only JSON: {{"score_A": 1-10, "score_B": 1-10, "pass_A": true|false, "pass_B": true|false, \
"winner": "A"|"B"|"tie", "reason": "<=30 words"}}"""


def call(model: str, system: str, prompt: str) -> str:
    r = subprocess.run([*CLAUDE, "--model", model, "--system-prompt", system], input=prompt, capture_output=True,
                       text=True, timeout=600, env=ENV, cwd="/tmp", check=True)
    return r.stdout.strip()


def respond(skill: Path, tier: str, s: dict) -> str:
    system = RESPOND.format(skill=(skill / "SKILL.md").read_text(), tier=tier, card=(skill / "tiers" / f"{tier}.md").read_text())
    before = f"So far:\n{s['transcript']}\n\n" if s.get("transcript") else ""
    return call("haiku", system, f"{before}The person says:\n{s['message']}")


def one(out: Path, skills: dict[str, Path], tier: str, s: dict, rep: int) -> dict:
    from smoothstone import cli

    replies = {arm: respond(d, tier, s) for arm, d in skills.items()}
    a, b = random.Random(f"{s['id']}{rep}").sample(sorted(skills), 2)
    said = call("opus", "You grade replies. Output JSON only.", JUDGE.format(
        ctx=s.get("transcript") or "(none)", msg=s["message"], rubric=s["rubric"], a=replies[a], b=replies[b],
        commands=" ".join(cli.COMMANDS)))
    v = json.loads(said[said.find("{"):said.rfind("}") + 1])
    d = {"id": s["id"], "rep": rep, "replies": replies, "score": {a: v["score_A"], b: v["score_B"]},
         "pass": {a: v["pass_A"], b: v["pass_B"]}, "winner": {"A": a, "B": b}.get(v["winner"], "tie"), "reason": v["reason"]}
    (out / f"{s['id']}-{rep}.json").write_text(json.dumps(d, indent=1))
    return d


def main() -> None:
    out, skills, tier = Path(sys.argv[1]), {"old": Path(sys.argv[2]), "new": Path(sys.argv[3])}, sys.argv[4]
    reps = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(s, k) for s in json.loads((HERE / "scenarios.json").read_text()) for k in range(reps)]
    with cf.ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(lambda j: one(out, skills, tier, *j), jobs))
    for d in rows:
        cells = " ".join(f"{arm}={d['score'][arm]}{'' if d['pass'][arm] else ' FAIL'}" for arm in skills)
        print(f"{d['id']:<18} {cells} {d['winner']:<4} {d['reason']}")
    for arm in skills:
        print(f"{arm}: mean {sum(d['score'][arm] for d in rows) / len(rows):.2f}, pass {sum(d['pass'][arm] for d in rows)}/{len(rows)}, "
              f"wins {sum(d['winner'] == arm for d in rows)}")


if __name__ == "__main__":
    main()
