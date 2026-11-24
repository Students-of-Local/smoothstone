"""stone doctor: from what a person sees to the likely failure, its causes, one question, and the fix.

Simple and inspectable on purpose, so a small model can follow it and a person can check it:
- failures are ranked by the words and phrases people use for them (failures/catalog.json),
- the causes of the top failure start from a prior and are multiplied by printer and material
  modifiers, then updated by Bayes' rule with each answer the person gives,
- the next question is the tell with the highest expected information gain over the causes.
The weights are stone's modeling assumptions, checked by evals/doctor (top-1 and top-3 accuracy).
Everything lives in stone-job/doctor/<case>/case.json, so a model that loses context continues.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from . import config, printers
from . import refs as reftool
from .job import read_json, write_json

FAIL_DIR = Path(__file__).resolve().parent / "failures"
CATALOG = FAIL_DIR / "catalog.json"
LABELS = config.REPO_ROOT / "failures" / "gallery" / "labels.jsonl"  # the gallery, at the checkout root like recipes/
SURE = 0.70  # the top cause past this: stop asking, try its fix
MAX_PX = 1280
NOT_SEEN = ("clog", "heat_creep", "feeder_grinding", "multi_material_feed", "thermal_error", "other")


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(CATALOG.read_text())


def failure(fid: str) -> dict | None:
    return next((f for f in catalog()["failures"] if f["id"] == fid), None)


def source_text(key: str) -> str:
    s = catalog()["sources"].get(key) or {}
    return f"{s.get('cite', key)}, {s.get('url', '')}".rstrip(", ")


# words


def stem(t: str) -> str:
    """A light suffix trim so "curls", "curled" and "curling" all match "curl"; both sides use it."""
    for suf, keep in (("ing", 4), ("ed", 4), ("es", 4), ("s", 3)):
        if t.endswith(suf) and not t.endswith("ss") and len(t) - len(suf) >= keep:
            if suf == "es" and not t[:-2].endswith(("s", "x", "z", "ch", "sh")):
                continue
            t = t[: -len(suf)]
            if suf in ("ing", "ed") and len(t) > 3 and t[-1] == t[-2] and t[-1] not in "lsz":
                t = t[:-1]  # dragged, clogged
            return t
    return t


def norm(text: str) -> str:
    t = text.lower().replace("\u2019", "'")
    t = re.sub(r"[^a-z0-9']+", " ", t)
    return " " + " ".join(stem(w) for w in t.split()) + " "


# A person's guess at the cause ("I thought it was wet filament") says less about what happened than
# what they saw, so a clause holding a guess counts this much (assumption, checked by evals/doctor).
GUESS = 0.25
GUESS_WORDS = ("i thought", "i figured", "i blamed", "i think", "i guess", "i suspect", "i assumed", "i'm sure",
               "im sure", "pretty sure", "must be", "must have", "or something", "maybe", "probably", "likely due",
               "my guess", "definitely", "surely", "should be")
# a yes-or-no question is a guess ("Is my nozzle worn out?"); "Why does my print look like this?" describes
GUESS_ASK = ("is", "are", "could", "should", "can", "do", "does", "did", "was", "would", "will")


def clauses(said: str) -> list[tuple[str, float]]:
    """The text in sentences, split again at "but" and "because" (what comes after is what they saw), each
    with its weight: a guess or a question counts GUESS."""
    out = []
    for sent in re.findall(r"[^.;!?]+[.;!?]*", said.lower()):
        first = sent.split()[0] if sent.split() else ""
        ask = sent.rstrip().endswith("?") and first in GUESS_ASK
        for p in re.split(r"\bbut\b|\bbecause\b", sent):
            if p.strip(" .;!?"):
                out.append((p, GUESS if ask or any(g in f" {p} " for g in GUESS_WORDS) else 1.0))
    return out


NEGATE = {stem(w) for w in ("no", "not", "nothing", "never", "didn't", "didnt", "wasn't", "isn't", "without",
                             "hasn't", "hadn't")}


def _phrase_score(text: str, words: list[str]) -> float:
    """Phrases found, longest first; one with a "not", "never" or "nothing" just before it does not count
    ("nothing lifted off the plate" says the part stayed put)."""
    text, score = norm(text), 0.0
    for w in sorted(words, key=lambda w: -len(w.split())):
        p = norm(w)
        at = text.find(p) if p.strip() else -1
        if at < 0:
            continue
        before = text[:at].split()[-3:]
        text = text.replace(p, " | ", 1)
        if not NEGATE & set(before):
            score += len(w.split())
    return score


def word_score(said: str, words: list[str], not_words: list[str] = (), guess: bool = True) -> float:
    """Each phrase found adds its word count: "came off the bed" (4) outweighs "came off" (2).
    With guess=True a phrase inside the person's own guess at the cause counts GUESS."""
    parts = clauses(said) if guess else [(said, 1.0)]
    score = sum(w * _phrase_score(p, words) for p, w in parts)
    t = norm(said)
    score -= sum(len(w.split()) for w in not_words if norm(w) in t)
    return max(score, 0.0)


# the printer and material


ALIASES = {"voron_24": ["voron 2 4", "voron"]}


def _spaced(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower().replace("-", " ")).split())


def _forms(p: dict) -> list[str]:
    """The ways a person names this printer, as whole words: "Creality K2 Plus", "k2 plus", "creality k2"...
    A form without the maker needs a model token with a digit (k2, x1c, mk4s) or two words (core one), so
    "mini" or "24" alone never names a printer."""
    short = printers.short_name(p)
    maker = p["maker"].split()[0]
    out = {_spaced(p["name"]), _spaced(f"{maker} {short}")} | {_spaced(a) for a in ALIASES.get(p["id"], [])}
    for f in {_spaced(short), _spaced(p["id"].split("_", 1)[1].replace("_", " ")), _spaced(short).replace(" ", "")}:
        toks = f.split()
        if any(re.search(r"[a-z]", t) and re.search(r"[0-9]", t) for t in toks) or \
                (len(toks) >= 2 and toks[0].isalpha()):
            out.add(f)
    return [f for f in out if f]


def printer_named(said: str) -> tuple[dict | None, bool]:
    """The printer the words name on whole-word boundaries, longest name first, and whether the naming is
    clear (the maker, or a model name of 4 or more letters and digits) rather than a 2 or 3 letter guess."""
    t = f" {_spaced(said)} "
    best = None
    for p in printers.load().values():
        for form in _forms(p):
            if f" {form} " in t and (best is None or len(form) > len(best[1])):
                best = (p, form)
    if best is None:
        return None, False
    p, form = best
    return p, p["maker"].split()[0].lower() in form.split() or len(form.replace(" ", "")) >= 4


def find_printer(said: str) -> dict | None:
    return printer_named(said)[0]


def find_material(said: str) -> str | None:
    t = said.lower()
    for key, m in reftool.MATERIALS.items():
        if re.search(m.words, t):
            return "PLA" if key == "PLA+" else key
    return None


def surface_kind(p: dict) -> str:
    t = p["bed_surface"]["type"].lower()
    for k in ("textured", "satin", "smooth", "glass", "cool", "engineering"):
        if k in t:
            return k
    return "other"


def context(p: dict | None, material: str | None) -> set[str]:
    out = set()
    if material:
        out.add(f"material:{material.upper()}")
    if p:
        out |= {f"printer:{p['id']}", f"firmware:{p['firmware']}", f"kinematics:{p['kinematics']}",
                f"enclosed:{str(bool(p['enclosed'])).lower()}", f"chamber_heater:{str(bool(p.get('chamber_heater'))).lower()}",
                f"surface:{surface_kind(p)}", f"multi_material:{p.get('multi_material') or 'none'}"}
    return out


def _mods(mods: dict, ctx: set[str]) -> float:
    return math.prod(v for k, v in mods.items() if k in ctx) if mods else 1.0


# ranking


DIFF_SHARE = 0.10  # assumption: a differential nobody described still deserves a look, below any match
ROOT_SHARE = 0.5  # assumption: a described root cause leads once it carries half the top failure's weight


def rank_failures(said: str, ctx: set[str]) -> list[tuple[str, float]]:
    """Failures by the words said; the top failure's differentials (the ones the catalog says to tell
    apart from it) follow at a small share, so "Also check" lists them even when nobody named them."""
    scores = {}
    for f in catalog()["failures"]:
        s = word_score(said, f["words"], f.get("not_words", []))
        if s > 0:
            scores[f["id"]] = s * _mods(f.get("modifiers", {}), ctx)
    if scores:
        top = max(scores, key=scores.get)
        # root first: when a cause of the top failure is another failure the person also described
        # (the blob formed because the part came loose), that failure is what to fix
        roots = [c["failure"] for c in failure(top)["causes"]
                 if scores.get(c.get("failure"), 0) >= ROOT_SHARE * scores[top]]
        if roots:
            root = max(roots, key=scores.get)
            scores[root], top = scores[top] * 1.05, root
        for i, d in enumerate(failure(top).get("differentials", [])):  # the catalog lists the likeliest first
            scores.setdefault(d["id"], scores[top] * DIFF_SHARE * (1 - 0.1 * i))
    total = sum(scores.values()) or 1.0
    return sorted(((i, s / total) for i, s in scores.items()), key=lambda x: -x[1])


def cause_priors(f: dict, said: str, ctx: set[str]) -> dict[str, float]:
    raw = {}
    for c in f["causes"]:
        w = c["prior"] * _mods(c.get("modifiers", {}), ctx)
        if c.get("words") and word_score(said, c["words"], guess=False) > 0:
            w *= 2.0  # the person named this cause themselves
        raw[c["id"]] = w
    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}


def questions(f: dict) -> dict[str, list[str]]:
    """Every question asked for this failure's causes, with the answer keys it takes."""
    out: dict[str, list[str]] = {}
    for c in f["causes"]:
        for t in c["tells"]:
            keys = out.setdefault(t["ask"], [])
            keys += [k for k in t["answers"] if k not in keys]
    return out


def likelihood(f: dict, ask: str, keys: list[str]) -> dict[str, dict[str, float]]:
    """P(answer | cause): each cause's multipliers for this question, normalized; a cause the question
    says nothing about answers every way alike."""
    out = {}
    for c in f["causes"]:
        t = next((t for t in c["tells"] if t["ask"] == ask), None)
        m = {k: (t["answers"].get(k, 1.0) if t else 1.0) for k in keys}
        s = sum(m.values())
        out[c["id"]] = {k: v / s for k, v in m.items()}
    return out


def _entropy(p: dict[str, float]) -> float:
    return -sum(v * math.log2(v) for v in p.values() if v > 0)


def update(post: dict[str, float], lik: dict[str, dict[str, float]], key: str) -> dict[str, float]:
    raw = {c: post[c] * lik[c][key] for c in post}
    total = sum(raw.values()) or 1.0
    return {c: v / total for c, v in raw.items()}


def best_question(f: dict, post: dict[str, float], asked: list[str]) -> tuple[str, list[str], float] | None:
    """The unasked question with the highest expected information gain over the causes."""
    best = None
    h0 = _entropy(post)
    for ask, keys in questions(f).items():
        if ask in asked:
            continue
        lik = likelihood(f, ask, keys)
        gain = h0
        for k in keys:
            pa = sum(post[c] * lik[c][k] for c in post)
            if pa > 0:
                gain -= pa * _entropy(update(post, lik, k))
        if best is None or gain > best[2] + 1e-9:
            best = (ask, keys, gain)
    return best if best and best[2] > 0.01 else None


def described(said: str) -> list[str]:
    """The failures the person's words actually describe (not differentials stone added to check)."""
    return [f["id"] for f in catalog()["failures"] if word_score(said, f["words"], f.get("not_words", [])) > 0]


def safety_lines(seen: list[str], limit: int = 4) -> list[str]:
    """SAFETY for the failures the person described. A thermal fault leads with its power-off lines, which
    are never cut, and drops any step that heats the hotend while the fault stands."""
    order = (["thermal_error"] if "thermal_error" in seen else []) + [f for f in seen if f != "thermal_error"]
    out: list[str] = []
    for fid in order:
        for line in failure(fid).get("safety", []):
            if "thermal_error" in seen and line.lower().startswith("heat "):
                continue
            if line not in out:
                out.append(line)
    keep = len(failure("thermal_error")["safety"]) if "thermal_error" in seen else 0
    return out[:max(limit, keep)]


def diagnose(said: str, printer: dict | None = None, material: str | None = None) -> dict:
    """The whole first pass, with no files: used by the command and by evals/doctor/run.py."""
    ctx = context(printer, material)
    ranked = rank_failures(said, ctx)
    out = {"failures": ranked, "causes": {}, "question": None, "described": described(said)}
    if ranked:
        f = failure(ranked[0][0])
        out["causes"] = cause_priors(f, said, ctx)
        q = best_question(f, out["causes"], [])
        out["question"] = {"ask": q[0], "keys": q[1]} if q else None
    return out


def top_causes(causes: dict[str, float], n: int = 3) -> list[tuple[str, float]]:
    return sorted(causes.items(), key=lambda x: -x[1])[:n]


ANSWER_NEGATE = NEGATE | {stem(w) for w in ("doesn't", "doesnt", "don't", "dont", "won't", "wont", "isnt", "aren't")}
LEAD = {"yes": {"yes", "yeah", "yep", "yup", "sure", "correct"}, "no": {"no", "nope", "nah"}}


def answer_key(text: str, keys: list[str]) -> str | None:
    """The answer key the person's words mean for this question, or None to ask again.
    "can't tell" words give "unknown". A reply that starts with yes or no is that. Otherwise each key's
    words count unless "not", "doesn't" or "never" comes just before them ("it doesn't bead" is not beads);
    with two keys, a denied one means the other. Two keys at once is unclear: ask again, never guess."""
    t = norm(text)
    words = catalog()["answers"]
    if any(norm(w) in t for w in words.get("unknown", [])):
        return "unknown"
    toks = t.split()
    for k, lead in LEAD.items():
        if k in keys and toks and toks[0] in lead:
            return k
    said, denied = set(), set()
    for part in re.split(r"[,.;:!?]|\bbut\b|\band\b", text.lower()):  # a "not" reaches only its own clause
        c = norm(part)
        for k in keys:
            for w in words.get(k, []):
                p, at = norm(w), 0
                while (at := c.find(p, at)) >= 0:
                    before = set(c[:at].split()[-3:])
                    (denied if k != "no" and before & ANSWER_NEGATE else said).add(k)
                    at += 1
    if len(said) == 1:
        return next(iter(said))
    if not said and len(denied) == 1 and len(keys) == 2:
        return next(k for k in keys if k not in denied)
    return None


# the gallery Track G writes (failures/gallery/labels.jsonl; its printer field is a name, not an id)


def examples(fid: str, printer_id: str | None, n: int = 3) -> list[str]:
    if not LABELS.is_file():
        return []
    rows = []
    for ln in LABELS.read_text().splitlines():
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if r.get("failure") == fid and r.get("file"):
            rows.append(r)
    p = printers.get(printer_id) if printer_id else None
    mine = {printer_id, p["name"] if p else None, printers.short_name(p) if p else None} - {None}
    rows.sort(key=lambda r: r.get("printer") not in mine)
    return [str((LABELS.parent / r["file"]).resolve()) for r in rows[:n]]


# the case on disk: stone-job/doctor/<case>/case.json, and doctor/open.txt names the open one

DONE = "none, the print problem is fixed"
ASK_WORDS = {"beads": "beads", "film": "spreads as a film", "yes": "yes", "no": "no", "unknown": "can't tell"}


def doctor_dir(job) -> Path:
    return Path(job.root) / "doctor"


def open_case(job) -> dict | None:
    ptr = doctor_dir(job) / "open.txt"
    if not ptr.is_file():
        return None
    return read_json(doctor_dir(job) / ptr.read_text().strip() / "case.json")


def save_case(job, case: dict) -> Path:
    d = doctor_dir(job) / case["id"]
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / "case.json", case)
    ptr = doctor_dir(job) / "open.txt"
    if case.get("state") == "fixed":
        ptr.unlink(missing_ok=True)
    else:
        ptr.write_text(case["id"] + "\n")
    return d / "case.json"


def save_photo(src: Path, dest: Path) -> Path:
    """The photo as a JPEG at most MAX_PX on its long side, turned upright, with EXIF (GPS, camera) left out."""
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_PX, MAX_PX))
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=90)  # no exif= argument: nothing from the original carries over
    return dest


def matching_device(rows: list[dict], printer: dict | None) -> tuple[dict | None, str]:
    """The paired Gantrel printer that is this printer model, or why there is none. Never another model's
    camera: a frame from the wrong printer would be diagnosed as this one."""
    if printer is None:
        return (rows[0], "") if len(rows) == 1 else \
            (None, "several printers are paired and no printer is set" if rows else "no printer is paired")
    c = printer.get("connect") or {}
    hits = [r for r in rows if r.get("model") == c["gantrel_model"]] if c.get("gantrel_model") else \
        [r for r in rows if r.get("type") == c.get("gantrel_type")]
    if len(hits) == 1:
        return hits[0], ""
    paired = ", ".join(f"{r['name']} ({r.get('model') or r.get('type')})" for r in rows) or "none"
    if hits:
        return None, f"{len(hits)} paired printers could be the {printer['name']}: {paired}"
    return None, f"no paired printer is a {printer['name']} (paired: {paired})"


def camera_frame(job, dest: Path, printer: dict | None) -> tuple[Path | None, str, dict | None, bool]:
    """One frame from this printer's camera through gantrel-printer (read-only):
    (frame, why not, device, refused). Refused: no paired device is this printer, so no frame is taken."""
    binary = printers.gantrel()
    if binary is None:
        return None, f"{printers.GANTREL} is not installed: stone printer camera says how to add it", None, False
    row, why = matching_device(printers.paired(binary), printer)
    if row is None:
        return None, why, None, True
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, text = printers._run([binary, "camera", row["name"], "--out", str(dest)])
    if code == 0 and dest.is_file():
        return dest, "", row, False
    return None, f"the camera on {row['name']} did not answer", row, False


def _question_next(q: dict) -> str:
    answers = " / ".join(ASK_WORDS.get(k, k) for k in q["keys"] + ["unknown"])
    return f'ask the person: {q["ask"]} ({answers}) Then: stone doctor answer "<their answer>"'


DESCRIBE = ("ask the person: what does the print look like (came loose, strings, gaps, a blob on the nozzle, "
            'shifted layers)? Then: stone doctor "<their words>"')


def case_next(case: dict) -> str:
    """The one NEXT for the case's state: what the command printed, and what stone status repeats."""
    if case.get("state") == "fixed":
        return DONE
    if case.get("state") == "look":
        if not case.get("image"):
            return DESCRIBE
        return f'stone doctor "<what you see in {case["image"]}: the part, the plate, the nozzle>"'
    if case.get("state") == "try":
        left = [k for k, _ in top_causes(case["causes"], 99) if k not in case.get("tried", [])]
        return ('ask the person: did that fix it? If it did: stone doctor fixed "<what worked>"'
                + (f"; if not: stone doctor try {left[0]}" if left else ""))
    top = top_causes(case["causes"], 1)
    if case.get("question") and top and top[0][1] < SURE:
        return _question_next(case["question"])
    return f"stone doctor try {top[0][0]}" if top else DONE


def status_hook(job) -> tuple[str, str] | None:
    """For stone status: (line, NEXT) of the open doctor case, or None."""
    case = open_case(job)
    if not case:
        return None
    what = failure(case["failure"])["name"] if case.get("failure") else "waiting for a description"
    return f"Doctor case {case['id']}: {what} (its NEXT: {case_next(case)})", case_next(case)


def share_payload(case: dict) -> dict:
    """What Track C's stone doctor share sends: the outcome without the person's words or photo."""
    o = case.get("outcome") or {}
    return {k: o.get(k) for k in ("failure", "cause", "what_worked", "printer", "material", "date")}


# what the person reads


def _printer_lines(p: dict | None, fids: list[str], causes: list[str]) -> list[str]:
    if not p:
        return []
    out = [f"Your printer: {p['name']} ({p['id']})"]
    plate = any(c.get("plate") for fid in fids[:1] for c in failure(fid)["causes"] if c["id"] in causes)
    if plate or fids[0] in ("bed_adhesion", "first_layer", "warping"):
        out += [printers.surface_line(p), printers.clean_line(p)]
    for q in [q for q in p.get("quirks", []) if q["failure"] in fids[:3]][:2]:
        out.append(f"Known issue ({q['failure']}): {q['note']} ({q['source']})")
    return out


def report(case: dict, p: dict | None) -> list[str]:
    ranked = [fid for fid, _ in case["failures"]]
    top = failure(ranked[0])
    lines = [f"Most likely: {top['name']} ({top['id']})"]
    tell = {d["id"]: d["tell_apart"] for d in top.get("differentials", [])}
    for fid in ranked[1:4]:
        lines.append(f"Also check: {fid}: {tell.get(fid) or failure(fid)['looks_like']['camera']}")
    causes = top_causes(case["causes"])
    by_id = {c["id"]: c for c in top["causes"]}
    for i, (cid, pr) in enumerate(causes, 1):
        lines.append(f"Cause {i}: {by_id[cid]['cause']} ({cid}) {pr:.0%}")
    lines += _printer_lines(p, ranked, [c for c, _ in causes])
    seen = [f for f in ranked[:3] if f in case.get("described", ranked[:1])]
    lines += [f"SAFETY: {s}" for s in safety_lines(seen or ranked[:1])]
    for fid in ranked[:3]:
        ex = examples(fid, p["id"] if p else None)
        if ex:
            lines.append(f"Examples of {fid}: " + ", ".join(ex))
    return lines


def looks_lines() -> list[str]:
    seen = [f for f in catalog()["failures"] if f["id"] not in NOT_SEEN]
    return [f"{f['id']}: {f['looks_like']['camera']}" for f in seen] + \
        ["Not seen in a photo: " + ", ".join(i for i in NOT_SEEN if i != "other") + " (ask what the printer did)"]


# stone doctor "<what they see>" | answer "<their answer>" | try [cause] | fixed "<what worked>" | looks

SUBS = ("answer", "try", "fixed", "looks")


def cmd_doctor(args, job):
    from .cli import Out

    out = Out(owns_next=False)
    words = list(args.words or [])
    sub = words[0].lower() if words and words[0].lower() in SUBS else None
    rest = " ".join(words[1:] if sub else words).strip()
    if sub == "looks":
        out.add(*looks_lines())
        out.next = 'stone doctor "<what you see, in these words>"'
        return out
    if sub is None:
        return _new(args, job, rest, out)
    case = open_case(job)
    if case is None or not case.get("failure"):
        out.fix("no open doctor case with a description yet")
        out.next = 'stone doctor "<what you see>"'
        return out
    p = printers.get(case.get("printer"))
    f = failure(case["failure"])
    if sub == "answer":
        return _answer(job, case, f, rest, out)
    if sub == "try":
        return _try(job, case, f, p, rest, out)
    return _fixed(job, case, rest, out)


def _new(args, job, said: str, out):
    p = printers.get(args.printer) if args.printer else None
    if args.printer and p is None:
        out.fix(f"no printer {args.printer}; ids: stone printer")
        out.next = "stone printer"
        return out
    prior = open_case(job)
    reuse = prior if prior and prior.get("state") == "look" and not args.image and not args.camera else None
    named, clear = printer_named(said)
    # the printer asked for, then a model the words name clearly ("Creality K2 Plus", "mk4s"), then the one
    # a photo's case was opened with, then the one set with stone printer set, then a guess
    kept = printers.get((reuse or {}).get("printer"))
    p = p or (named if clear else None) or kept or printers.current(job.root) or named
    material = (args.material or find_material(said) or (reuse or {}).get("material") or "").upper() or None
    now = _dt.datetime.now()
    case = reuse or {"id": now.strftime("%Y%m%d-%H%M%S"), "created": now.isoformat(timespec="seconds"),
                     "image": None, "asked": [], "answers": [], "tried": []}
    case_dir = doctor_dir(job) / case["id"]
    if args.image:
        src = Path(args.image).expanduser()
        if not src.is_file():
            out.fix(f"no image at {src}")
            out.next = 'stone doctor "<what you see>"'
            return out
        try:
            case["image"] = str(save_photo(src, case_dir / "photo.jpg"))
        except OSError as e:
            out.fix(f"cannot read the image {src} ({type(e).__name__})")
            out.next = 'stone doctor "<what you see>"'
            return out
    elif args.camera:
        frame, why, device, refused = camera_frame(job, case_dir / "camera.jpg", p)
        if refused:
            out.fix(f"no camera frame: {why}")
            out.next = ("ask the person: which printer is it? Pair it (stone printer status shows how) or "
                        'describe what you see. Then: stone doctor "<what you see>"')
            return out
        if frame is None:
            out.add(f"No camera frame: {why}.")
        else:
            case["image"] = str(save_photo(frame, frame))
            case["camera"] = {"name": device["name"], "model": device.get("model")}
    case.update(said=said, printer=p["id"] if p else None, material=material)
    d = diagnose(said, p, material) if said else {"failures": []}
    head = f"Case {case['id']}" + (f", {p['name']}" if p else "") + (f", {material}" if material else "")
    if not d["failures"]:
        case.update(state="look", failure=None, failures=[], causes={}, question=None)
        save_case(job, case)
        out.add(head)
        if case["image"]:
            out.add(f"Photo saved (EXIF removed, at most {MAX_PX} px): {case['image']}",
                    "Look at it and describe what you see; if you cannot see images, ask the person what the print "
                    "looks like. The words each failure goes by: stone doctor looks")
            out.next = case_next(case)
        else:
            out.add("No failure matched those words. The words each failure goes by: stone doctor looks")
            out.next = case_next(case)
        return out
    case.update(state="asking", failures=d["failures"][:5], failure=d["failures"][0][0], causes=d["causes"],
                question=d["question"], described=d["described"], asked=[], answers=[], tried=[])
    save_case(job, case)
    out.add(head, *report(case, p))
    if case["image"]:
        out.add(f"Photo: {case['image']}")
    out.next = case_next(case)
    out.result = f"doctor {case['failure']}"
    return out


def _answer(job, case, f, text, out):
    q = case.get("question")
    if not q:
        out.add("No question is waiting.")
        out.next = case_next(case)
        return out
    key = answer_key(text, q["keys"])
    if key is None:
        out.add(f"I could not tell which answer that is ({' / '.join(ASK_WORDS.get(k, k) for k in q['keys'])}).")
        out.next = _question_next(q)
        return out
    if key != "unknown":
        case["causes"] = update(case["causes"], likelihood(f, q["ask"], q["keys"]), key)
    case["asked"].append(q["ask"])
    case["answers"].append({"ask": q["ask"], "said": text, "key": key})
    nq = best_question(f, case["causes"], case["asked"])
    case["question"] = {"ask": nq[0], "keys": nq[1]} if nq else None
    save_case(job, case)
    by_id = {c["id"]: c for c in f["causes"]}
    out.add(f"Answer taken as: {ASK_WORDS.get(key, key)}.")
    for i, (cid, pr) in enumerate(top_causes(case["causes"]), 1):
        out.add(f"Cause {i}: {by_id[cid]['cause']} ({cid}) {pr:.0%}")
    out.next = case_next(case)
    return out


def _try(job, case, f, p, cid, out):
    by_id = {c["id"]: c for c in f["causes"]}
    cid = cid.split()[0] if cid else top_causes(case["causes"], 1)[0][0]
    c = by_id.get(cid)
    if c is None:
        out.fix(f"no cause {cid} for {f['id']}; causes: " + " ".join(by_id))
        out.next = case_next(case)
        return out
    out.add(f"Fix for {c['cause']} ({cid}), cheapest and safest first:")
    out.add(*[f"{i}. {step}" for i, step in enumerate(c["fix"], 1)])
    if c.get("plate") and p:
        out.add(f"On your {p['name']}: {printers.surface_line(p)}", printers.clean_line(p))
    seen = case.get("described") or [f["id"]]
    out.add(*[f"SAFETY: {s}" for s in safety_lines([f["id"]] + [x for x in seen if x == "thermal_error"])])
    out.add(f"Source: {source_text(c['source'])}")
    case["tried"] = [t for t in case.get("tried", []) if t != cid] + [cid]
    case["state"] = "try"
    save_case(job, case)
    out.next = case_next(case)
    return out


def _fixed(job, case, text, out):
    cause = (case.get("tried") or [top_causes(case["causes"], 1)[0][0]])[-1]
    case["outcome"] = {"failure": case["failure"], "cause": cause, "what_worked": text or None,
                       "printer": case.get("printer"), "material": case.get("material"),
                       "date": _dt.date.today().isoformat()}
    case["state"] = "fixed"
    f = save_case(job, case)
    with open(doctor_dir(job) / "outcomes.jsonl", "a") as fh:
        fh.write(json.dumps(share_payload(case)) + "\n")
    out.add(f"Recorded: {case['failure']}, cause {cause}" + (f", fixed by: {text}" if text else "") + f" ({f})")
    out.next = DONE
    out.result = f"doctor fixed {cause}"
    return out
