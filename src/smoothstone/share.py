"""stone doctor share: offer a fixed print problem to smoothstone so the next agent on that printer learns from it.

Never forced and never silent, and stone itself sends nothing: `stone doctor fixed` asks the person first,
`stone doctor share` writes the scrubbed bundle, prints exactly what would go public and a prefilled print-fix
issue link, and the person opens the link, attaches the photo and submits it on GitHub themselves. A maintainer
reads the issue and adds failures/community/<folder>/ in a pull request. Private details are scrubbed first.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import shutil
import socket
import urllib.parse
from pathlib import Path

from . import config, doctor, printers

REPO = "baney75/smoothstone"
COMMUNITY_DIR = "failures/community"
PX = 1024
LICENSE_LINE = "The photo and the words become public on GitHub under smoothstone's MIT license."
ASK = ("ask the person: Share this fix (photo, printer, material, what you saw and what fixed it) publicly on GitHub "
       "so other agents learn from it? The photo and words become public under smoothstone's MIT license. "
       "(yes / no) yes: stone doctor share. no: stone doctor share no")
# stone never uploads: the person reads the words, sees the photo and submits the issue on GitHub themselves
LINK_ASK = ("ask the person: <read them the lines above and show them the photo>. To share it, open the link "
            "above, attach the photo, read it there and submit the issue yourself; stone sends nothing. "
            "Did you submit it? (yes / no) yes: stone doctor share done. no: stone doctor share no")
# a path from a filesystem root goes whole, spaces included, to the end of its last segment: a name with an
# extension, or a closing quote, bracket, comma or semicolon, or the end of the line
ROOTED = re.compile(r"(?:(?<![\w/~.])/(?i:Users|home|Volumes|mnt|media|private|tmp|var)[/\\]"
                    r"|(?<![\w/])~[/\\]|(?<![\w/\\])[A-Za-z]:[/\\])"
                    r"(?:[^\n\"'\[\](){}<>,;]*?\.(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,8}(?=$|[\s\"'\[\](){}<>,;:!?]|\.(?:\s|$))"
                    r"|[^\n\"'\[\](){}<>,;]*)", re.M)

# what never leaves the machine, in the order it is replaced (a link before the host inside it)
PATTERNS = [
    ("link", re.compile(r"\b(?:https?|rtsp|webrtc|ws)://\S+", re.I)),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("path", ROOTED),
    ("path", re.compile(r"(?<![\w/~])(?:[A-Za-z]:)?(?:[/\\][\w.@-]+){2,}|(?<![\w/])~[/\\][\w.@/\\-]+")),
    ("address", re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)),
    # IPv6 with :: first (fd00::1234, ::1), so a full-form match never takes half of one; then IPv4, full IPv6
    ("address", re.compile(r"(?<![\w:])(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,6}::(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,6})?"
                           r"|::[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,6})(?![\w:]|\.\d)"
                           r"|\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b", re.I)),
    ("host", re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:local|lan|home|internal|localdomain|ts\.net)\b", re.I)),
    ("serial", re.compile(r"\b(?:serial(?:\s+(?:number|no\.?))?|s/?n)\b[\s:#]*(?:s/?n\b[\s:#]*)?"
                          r"[A-Za-z0-9-]*\d[A-Za-z0-9-]*", re.I)),
    ("serial", re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{10,}\b")),
]


def private_names() -> list[str]:
    """Words that name this person or machine: the login, the home folder, the host, the printer names."""
    names = {getpass.getuser(), Path.home().name, socket.gethostname(), socket.gethostname().split(".")[0]}
    raw = config._toml(None).get("printer")
    if isinstance(raw, dict) and raw.get("name"):
        names.add(str(raw["name"]))
    binary = printers.gantrel()
    if binary:
        try:
            names |= {str(r.get("name")) for r in printers.paired(binary) if r.get("name")}
        except Exception:  # a paired list that will not load hides no names; the rest still scrub
            pass
    return sorted((n for n in names if n and len(n) >= 3), key=len, reverse=True)


def scrub(text: str, names: list[str] | tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """The text with private details replaced by [link], [email], [path], [address], [host], [serial] or
    [name], and the kinds removed."""
    gone = []
    for kind, rx in PATTERNS:
        text, n = rx.subn(f"[{kind}]", text)
        gone += [kind] * n
    for name in names:
        text, n = re.subn(rf"(?<!\w){re.escape(name)}(?!\w)", "[name]", text, flags=re.I)
        gone += ["name"] * n
    return text, gone


def leaks(text: str) -> list[str]:
    """What scrub would still remove: empty for a case that is safe to publish."""
    return [m.group(0) for _, rx in PATTERNS for m in rx.finditer(text)]


def bundle_leaks(d, names: list[str] | tuple[str, ...] = ()) -> list[str]:
    """What scrub would still remove from any text anywhere in the bundle data, private names included."""
    if isinstance(d, dict):
        return [x for v in d.values() for x in bundle_leaks(v, names)]
    if isinstance(d, list):
        return [x for v in d for x in bundle_leaks(v, names)]
    if not isinstance(d, str):
        return []
    return leaks(d) + [n for n in names if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", d, re.I)]


def version() -> str:
    from importlib.metadata import PackageNotFoundError, version as v

    try:
        return v("smoothstone")
    except PackageNotFoundError:
        return "unknown"


def last_fixed(job) -> dict | None:
    """The newest case that `stone doctor fixed` closed."""
    for f in sorted(doctor.doctor_dir(job).glob("*/case.json"), reverse=True):
        case = json.loads(f.read_text())
        if case.get("outcome"):
            return case
    return None


def build(job, case: dict) -> tuple[Path, dict, list[str]]:
    """Write stone-job/doctor/<case>/share/ (case.json, photo.jpg) and return it, the data and what the scrub
    removed."""
    o, names, gone = case["outcome"], private_names(), []

    def clean(text):  # every free-text field goes through the same scrub
        if text is None:
            return None
        text = re.sub(r"\s*\u2014\s*", ", ", str(text)).replace("\u2013", "-")  # em and en dashes fail the CI check
        text, g = scrub(text, names)
        gone.extend(g)
        return text

    said, fixed_by, material = clean(case.get("said") or ""), clean(o.get("what_worked") or ""), clean(o.get("material"))
    out = doctor.doctor_dir(job) / case["id"] / "share"
    shutil.rmtree(out, ignore_errors=True)
    photo = Path(case["image"]) if case.get("image") else None
    if photo and photo.is_file():
        photo = doctor.save_photo(photo, out / "photo.jpg", PX)
    else:
        photo = None
    data = {"schema": 1, "failure": o["failure"], "cause": o["cause"], "printer": o["printer"],
            "material": material, "said": said, "fixed_by": fixed_by,
            "answers": [{"ask": clean(a["ask"]), "key": a["key"]} for a in case.get("answers", [])],
            "photo": "photo.jpg" if photo else None, "stone_version": version(), "date": o["date"], "license": "MIT"}
    h = hashlib.sha256(json.dumps(data, sort_keys=True).encode() + (photo.read_bytes() if photo else b""))
    data["id"] = f"{o['date']}-{o['printer']}-{o['failure']}-{h.hexdigest()[:7]}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "case.json").write_text(json.dumps(data, indent=1) + "\n")
    return out, data, gone


def title(d: dict) -> str:
    return f"Fixed: {d['failure']} on {d['printer']}"


def issue_url(d: dict) -> str:
    q = {"template": "print-fix.yml", "title": title(d), "failure": d["failure"], "cause": d["cause"],
         "printer": d["printer"], "material": d["material"] or "", "said": d["said"][:600],
         "fixed_by": d["fixed_by"][:300], "stone_version": d["stone_version"]}
    return f"https://github.com/{REPO}/issues/new?" + urllib.parse.urlencode(q)


def cmd_share(args, job, rest: str, out):
    case = last_fixed(job)
    if case is None:
        out.fix("no fixed doctor case to share")
        out.next = 'stone doctor "<what you see>"'
        return out
    bundle = doctor.doctor_dir(job) / case["id"] / "share"
    st, word = case.get("share") or {}, rest.lower().split()[0] if rest.split() else ""
    if st.get("state") == "linked":
        out.add("Already shared: the person submitted it as a print-fix issue.")
        out.next = doctor.DONE
        return out
    if word == "no":
        shutil.rmtree(bundle, ignore_errors=True)
        case["share"] = {"state": "declined"}
        doctor.save_case(job, case)
        out.add("Not shared. The fix stays on this machine.")
        out.next = doctor.DONE
        return out
    if word == "done":
        if st.get("state") != "ready":
            out.fix("stone has not shown this case's words and link yet")
            out.next = "stone doctor share"
            return out
        case["share"] = {"state": "linked", "folder": st["folder"]}
        doctor.save_case(job, case)
        out.add("Thanks. A maintainer reads the issue and adds the case; then stone doctor ranks this cause "
                "higher on this printer.")
        out.next = doctor.DONE
        out.result = "doctor shared"
        return out
    if args.printer:
        p = printers.get(args.printer)
        if p is None:
            out.fix(f"no printer {args.printer}; ids: stone printer")
            out.next = "stone printer"
            return out
        case["outcome"]["printer"] = p["id"]
    if not case["outcome"].get("printer"):
        out.fix("the shared case needs the printer model")
        out.next = "ask the person: which printer was it? Then: stone doctor share --printer <id from stone printer>"
        return out
    bundle, d, gone = build(job, case)
    found = bundle_leaks(d, private_names())
    if found:  # the last look before the person sees a link: a detail the scrub missed gives no link at all
        case["share"] = {"state": "held"}
        doctor.save_case(job, case)
        out.fix(f"the bundle still holds {len(found)} private detail(s) the scrub should have removed, so there "
                "is no link to share it. The case stays on this machine.")
        out.next = doctor.DONE
        return out
    case["share"] = {"state": "ready", "folder": d["id"]}
    doctor.save_case(job, case)
    out.add(f"Ready to share case {case['id']}. stone sends nothing. This is all that would go public:")
    out.add(f"Photo: {bundle / 'photo.jpg'} (EXIF removed, at most {PX} px)" if d["photo"] else "Photo: none")
    out.add(f"Failure: {d['failure']}", f"Cause: {d['cause']}", f"Printer: {d['printer']}",
            f"Material: {d['material'] or 'not given'}", f"What you saw: \"{d['said']}\"",
            f"What fixed it: \"{d['fixed_by']}\"", f"stone {d['stone_version']}, {d['date']}")
    if gone:
        out.add("Removed first: " + ", ".join(f"{gone.count(k)} {k}" for k in dict.fromkeys(gone)))
    out.add(LICENSE_LINE, f"Where: a print-fix issue on {REPO}; a maintainer reads it and adds the case.",
            "Prefilled issue link:", issue_url(d))
    out.next = LINK_ASK
    return out
