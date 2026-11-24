"""stone doctor on real gallery photos, read by a small model: words alone against words plus --looks.

uv run python evals/doctor/photos.py split                 # writes photo_split.jsonl (once; never reshuffle)
uv run python evals/doctor/photos.py ask dev|heldout [-j 6] # a fresh responder reads each photo; appends replies
uv run python evals/doctor/photos.py score dev|heldout [--json] [--show]

The photos are failures/gallery's real ones (no synthetic frames, no healthy prints). photo_split.jsonl
puts every third photo of each failure, sorted by a hash of its file name, in "dev" (plus the owner's K2
photo, which the words were already tuned on) and the rest in "heldout". LOOK_LR and LOOK_FLOOR in
doctor.py, and any word change made after looking at photo replies, may use dev only. heldout is asked
once per skill text and scored as is.

The responder is Haiku through Donovan's Claude sign-in (`env -u ANTHROPIC_API_KEY claude -p --model
haiku`, never API billing), given only skill/doctor.md, the output stone prints for a photo, the output of
stone doctor looks, and the photo itself under a neutral name (the gallery path names the answer). It
replies with the stone doctor command it would run. stone ranks both ways from that one reply:
"words" drops --looks, "looks" keeps it, so before and after see the same reads. Replies are kept in
photo_runs.jsonl, so tests/test_doctor.py rescores them without a model. The recorded replies saw one more
line after "Photo saved", the image match's, from the change that adds it.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoothstone import doctor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GALLERY = ROOT / "failures" / "gallery"
SPLIT = HERE / "photo_split.jsonl"
RUNS = HERE / "photo_runs.jsonl"
SKILL = ROOT / "skill" / "doctor.md"
SAVED = "stone-job/doctor/case/photo.jpg"


def _rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []


def make_split() -> list[dict]:
    labels = [r for r in _rows(GALLERY / "labels.jsonl") if not r["synthetic"] and r["failure"] != "healthy"]
    by = collections.defaultdict(list)
    for r in labels:
        by[r["failure"]].append(r)
    out = []
    for fid in sorted(by):
        for i, r in enumerate(sorted(by[fid], key=lambda r: hashlib.sha1(r["file"].encode()).hexdigest())):
            split = "dev" if i % 3 == 2 or r["source"].startswith("owner") else "heldout"
            out.append({"file": r["file"], "failure": fid, "also": r["also"], "split": split})
    return out


def prompt(photo: Path) -> str:
    look = doctor.case_next({"state": "look", "image": SAVED})
    return "\n".join([
        "You are the agent in the skill below. Follow it.", "", "<skill>", SKILL.read_text(), "</skill>", "",
        "A person sent a photo of a 3D print and says only that it failed. They are away, so describe it yourself.",
        "You already ran these:", "", "$ stone doctor --image photo.jpg",
        f"Photo saved (EXIF removed, at most {doctor.MAX_PX} px): {SAVED}",
        "Look at it: describe what you see, and pass the ids that match it with --looks (each id and its look: "
        "stone doctor looks). If you cannot see images, ask the person what it looks like.",
        f"NEXT: {look}", "", "$ stone doctor looks", *doctor.looks_lines(),
        'NEXT: stone doctor "<what you see, in these words>" --looks <the ids that match, likeliest first>', "",
        f"The photo is at {photo}. Read it. Then reply with only the next stone doctor command, on one line.",
    ])


def parse(reply: str) -> tuple[str, list[str]]:
    """The words and --looks ids of the stone doctor command in a reply."""
    for line in reversed(reply.strip().strip("`").splitlines()):
        line = line.strip().strip("`").removeprefix("$ ").strip()
        if not line.startswith("stone doctor"):
            continue
        try:
            argv = shlex.split(line)[2:]
        except ValueError:
            argv = line.split()[2:]
        words, looks, i = [], "", 0
        while i < len(argv):
            if argv[i] == "--looks" and i + 1 < len(argv):
                looks, i = argv[i + 1], i + 2
            elif argv[i].startswith("--looks="):
                looks, i = argv[i].split("=", 1)[1], i + 1
            elif argv[i].startswith("--"):
                i += 2
            else:
                words.append(argv[i])
                i += 1
        return " ".join(words), doctor.look_ids(looks)[0]
    return "", []


def prompt_key() -> str:
    """The skill text and the looks lines the responder saw: a new key asks again."""
    return hashlib.sha1(prompt(Path("photo.jpg")).encode()).hexdigest()[:10]


def ask_one(row: dict, work: Path, n: int) -> dict:
    photo = work / f"p{n:03d}.jpg"  # neutral name: the gallery path says the answer
    shutil.copy(GALLERY / row["file"], photo)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    cmd = ["claude", "-p", "--model", "haiku", "--tools", "Read", "--allowedTools", "Read", "--strict-mcp-config",
           "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence", "--output-format", "json",
           prompt(photo)]
    p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=300)
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        d = {"result": "", "modelUsage": {}}
    reply = d.get("result") or ""
    words, looks = parse(reply)
    return {"file": row["file"], "split": row["split"], "skill": prompt_key(),
            "model": ",".join(d.get("modelUsage", {})) or None, "reply": reply.strip(), "words": words,
            "looks": looks}


def ask(split: str, jobs: int) -> None:
    done = {(r["file"], r["skill"]) for r in _rows(RUNS)}
    skill = prompt_key()
    todo = [r for r in _rows(SPLIT) if r["split"] == split and (r["file"], skill) not in done]
    with tempfile.TemporaryDirectory() as tmp, cf.ThreadPoolExecutor(jobs) as pool, RUNS.open("a") as fh:
        futs = []
        for n, r in enumerate(todo):
            (Path(tmp) / str(n)).mkdir()
            futs.append(pool.submit(ask_one, r, Path(tmp) / str(n), n))
        for fut in cf.as_completed(futs):
            fh.write(json.dumps(fut.result()) + "\n")
            fh.flush()
    print(f"asked {len(todo)} {split} photos")


def score(split: str, skill: str | None = None) -> dict:
    """Top-1 and top-3 for each way of ranking, on the latest skill text's replies for the split."""
    truth = {r["file"]: r for r in _rows(SPLIT) if r["split"] == split}
    runs = {}
    for r in _rows(RUNS):
        if r["file"] in truth and (skill is None or r["skill"] == skill):
            runs[r["file"]] = r  # the last reply for a photo wins
    out = {}
    for way in ("words", "looks", "looks_only"):
        rows = []
        for f, r in sorted(runs.items()):
            said = "" if way == "looks_only" else r["words"]
            d = doctor.diagnose(said, None, None, [] if way == "words" else r["looks"])
            ranked = [fid for fid, _ in d["failures"]][:3]
            want = truth[f]["failure"]
            rows.append({"file": f, "want": want, "got": ranked, "top1": ranked[:1] == [want], "top3": want in ranked})
        n = len(rows) or 1
        out[way] = {"n": len(rows), "top1": round(sum(r["top1"] for r in rows) / n, 4),
                    "top3": round(sum(r["top3"] for r in rows) / n, 4),
                    "passing": sorted(r["file"] for r in rows if r["top1"]),
                    "confusions": collections.Counter(f"{r['want']} -> {r['got'][0] if r['got'] else 'nothing'}"
                                                      for r in rows if not r["top1"]).most_common(),
                    "rows": rows}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("split", "ask", "score"))
    ap.add_argument("split", nargs="?", default="dev", choices=("dev", "heldout"))
    ap.add_argument("-j", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", action="store_true", help="every miss, with the reply")
    a = ap.parse_args(argv)
    if a.cmd == "split":
        if SPLIT.exists():
            print(f"{SPLIT.name} exists; the split is fixed")
            return 1
        rows = make_split()
        SPLIT.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(collections.Counter(r["split"] for r in rows))
        return 0
    if a.cmd == "ask":
        ask(a.split, a.j)
        return 0
    s = score(a.split)
    if a.json:
        print(json.dumps({w: {k: v for k, v in m.items() if k != "rows"} for w, m in s.items()}, indent=1))
        return 0
    for way, m in s.items():
        print(f"{a.split} {way}: n={m['n']} top-1 {m['top1']:.0%} top-3 {m['top3']:.0%}")
    for way in ("words", "looks"):
        print(f"confusions ({way}):", ", ".join(f"{k} x{v}" for k, v in s[way]["confusions"][:10]))
    if a.show:
        replies = {r["file"]: r for r in _rows(RUNS)}
        for r in s["looks"]["rows"]:
            if not r["top1"]:
                print(f"{r['file']}: got {r['got']} | looks {replies[r['file']]['looks']} | {replies[r['file']]['words'][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
