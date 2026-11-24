"""stone doctor share: offer a fixed print problem to smoothstone so the next agent on that printer learns from it.

Never forced and never silent: `stone doctor fixed` asks the person first, `stone doctor share` writes the
bundle and prints exactly what would go public, and only `stone doctor share --send` lets anything leave the
machine. With gh signed in it opens a pull request that adds failures/community/<folder>/ to the repo;
without gh it prints a prefilled issue link and the photo to attach. Private details are scrubbed first.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path

from . import config, doctor, printers

REPO = "baney75/smoothstone"
OWNER = REPO.split("/")[0]
COMMUNITY_DIR = "failures/community"
PX = 1024
LICENSE_LINE = "The photo and the words become public on GitHub under smoothstone's MIT license."
ASK = ("ask the person: Share this fix (photo, printer, material, what you saw and what fixed it) publicly on GitHub "
       "so other agents learn from it? The photo and words become public under smoothstone's MIT license. "
       "(yes / no) yes: stone doctor share. no: stone doctor share no")
# the dry run ends in a question, so --send never runs before the person has seen the words and the photo
SEND_ASK = ("ask the person: <read them the lines above and show them the photo>; send exactly this? (yes / no) "
            "yes: stone doctor share --send. no: stone doctor share no")

# what never leaves the machine, in the order it is replaced (a link before the host inside it)
PATTERNS = [
    ("link", re.compile(r"\b(?:https?|rtsp|webrtc|ws)://\S+", re.I)),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("path", re.compile(r"(?<![\w/~])(?:[A-Za-z]:)?(?:[/\\][\w.@-]+){2,}|(?<![\w/])~[/\\][\w.@/\\-]+")),
    ("address", re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)),
    ("address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b", re.I)),
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
    """Write stone-job/doctor/<case>/share/ (case.json, photo.jpg, pr.md) and return it, the data and what
    the scrub removed."""
    o, names = case["outcome"], private_names()
    said, g1 = scrub(case.get("said") or "", names)
    fixed_by, g2 = scrub(o.get("what_worked") or "", names)
    out = doctor.doctor_dir(job) / case["id"] / "share"
    shutil.rmtree(out, ignore_errors=True)
    photo = Path(case["image"]) if case.get("image") else None
    if photo and photo.is_file():
        photo = doctor.save_photo(photo, out / "photo.jpg", PX)
    else:
        photo = None
    data = {"schema": 1, "failure": o["failure"], "cause": o["cause"], "printer": o["printer"],
            "material": o.get("material"), "said": said, "fixed_by": fixed_by,
            "answers": [{"ask": a["ask"], "key": a["key"]} for a in case.get("answers", [])],
            "photo": "photo.jpg" if photo else None, "stone_version": version(), "date": o["date"], "license": "MIT"}
    h = hashlib.sha256(json.dumps(data, sort_keys=True).encode() + (photo.read_bytes() if photo else b""))
    data["id"] = f"{o['date']}-{o['printer']}-{o['failure']}-{h.hexdigest()[:7]}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "case.json").write_text(json.dumps(data, indent=1) + "\n")
    (out / "pr.md").write_text(pr_body(data))
    return out, data, g1 + g2


def title(d: dict) -> str:
    return f"Fixed: {d['failure']} on {d['printer']}"


def pr_body(d: dict) -> str:
    return "\n".join([
        f"A print problem a stone user fixed, shared with `stone doctor share`. Adds `{COMMUNITY_DIR}/{d['id']}/`.", "",
        f"- Failure: `{d['failure']}`", f"- Cause that fixed it: `{d['cause']}`", f"- Printer: `{d['printer']}`",
        f"- Material: {d['material'] or 'not given'}", f"- What they saw: \"{d['said']}\"",
        f"- What fixed it: \"{d['fixed_by']}\"", f"- stone {d['stone_version']}, {d['date']}", "",
        "The sender agreed to share the photo and text under the repo's MIT license.", "",
        "Maintainers: check the photo shows the failure and nothing private, and that the cause fits; "
        "tests/test_community.py checks the rest. Merging teaches stone doctor this printer's likeliest cause.", ""])


def issue_url(d: dict) -> str:
    q = {"template": "print-fix.yml", "title": title(d), "failure": d["failure"], "cause": d["cause"],
         "printer": d["printer"], "material": d["material"] or "", "said": d["said"][:600],
         "fixed_by": d["fixed_by"][:300], "stone_version": d["stone_version"]}
    return f"https://github.com/{REPO}/issues/new?" + urllib.parse.urlencode(q)


def _gh(args: list[str], timeout: float = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, type(e).__name__
    return r.returncode, (r.stdout or r.stderr).strip()


def send_pr(bundle: Path, d: dict) -> tuple[str | None, str]:
    """Fork (unless this is the owner), branch, add the two files through the GitHub API (no clone) and open
    the pull request. Returns (url, "") or (None, why)."""
    if shutil.which("gh") is None:
        return None, "gh is not installed"
    if _gh(["auth", "status"])[0] != 0:
        return None, "gh is not signed in"
    code, login = _gh(["api", "user", "-q", ".login"])
    if code or not login:
        return None, "gh could not read the account"
    owner = OWNER if login.lower() == OWNER else login
    if owner != OWNER:
        if _gh(["repo", "fork", REPO, "--clone=false"])[0]:
            return None, "gh could not fork the repo"
        _gh(["api", "-X", "POST", f"repos/{owner}/smoothstone/merge-upstream", "-f", "branch=main"])
    base, sha = f"repos/{owner}/smoothstone", ""
    for wait in (0, 2, 4, 8):  # a new fork takes a few seconds to appear
        time.sleep(wait)
        code, sha = _gh(["api", f"{base}/git/ref/heads/main", "-q", ".object.sha"])
        if code == 0 and sha:
            break
    else:
        return None, "the fork did not appear"
    branch = f"fix/{d['id']}"
    if _gh(["api", "-X", "POST", f"{base}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}"])[0]:
        return None, "gh could not make the branch"
    put = bundle / ".put.json"
    try:
        for name in ["case.json"] + (["photo.jpg"] if d["photo"] else []):
            body = {"message": f"{title(d)}: {name}", "branch": branch,
                    "content": base64.b64encode((bundle / name).read_bytes()).decode()}
            put.write_text(json.dumps(body))
            if _gh(["api", "-X", "PUT", f"{base}/contents/{COMMUNITY_DIR}/{d['id']}/{name}", "--input", str(put)])[0]:
                return None, f"gh could not upload {name}"
    finally:
        put.unlink(missing_ok=True)
    code, url = _gh(["pr", "create", "--repo", REPO, "--head", f"{owner}:{branch}", "--base", "main",
                     "--title", title(d), "--body-file", str(bundle / "pr.md")])
    return (url.splitlines()[-1], "") if code == 0 else (None, "gh could not open the pull request")


def cmd_share(args, job, rest: str, out):
    case = last_fixed(job)
    if case is None:
        out.fix("no fixed doctor case to share")
        out.next = 'stone doctor "<what you see>"'
        return out
    if rest.lower().startswith("no"):
        case["share"] = {"state": "declined"}
        doctor.save_case(job, case)
        out.add("Not shared. The fix stays on this machine.")
        out.next = doctor.DONE
        return out
    if (case.get("share") or {}).get("state") == "sent":
        out.add(f"Already shared: {case['share']['url']}")
        out.next = doctor.DONE
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
    bundle = doctor.doctor_dir(job) / case["id"] / "share"
    if args.send and (bundle / "case.json").is_file():
        return _send(job, case, bundle, out)
    bundle, d, gone = build(job, case)
    case["share"] = {"state": "ready", "folder": d["id"]}
    doctor.save_case(job, case)
    out.add(f"Ready to share case {case['id']}. Nothing is sent yet. This is all that goes public:")
    out.add(f"Photo: {bundle / 'photo.jpg'} (EXIF removed, at most {PX} px)" if d["photo"] else "Photo: none")
    out.add(f"Failure: {d['failure']}", f"Cause: {d['cause']}", f"Printer: {d['printer']}",
            f"Material: {d['material'] or 'not given'}", f"What you saw: \"{d['said']}\"",
            f"What fixed it: \"{d['fixed_by']}\"", f"stone {d['stone_version']}, {d['date']}")
    if gone:
        out.add("Removed first: " + ", ".join(f"{gone.count(k)} {k}" for k in dict.fromkeys(gone)))
    out.add(LICENSE_LINE, f"Where: {COMMUNITY_DIR}/{d['id']}/ in a pull request to {REPO}")
    out.next = SEND_ASK
    return out


def _send(job, case, bundle: Path, out):
    d = json.loads((bundle / "case.json").read_text())
    url, why = send_pr(bundle, d)
    if url:
        case["share"] = {"state": "sent", "folder": d["id"], "url": url}
        doctor.save_case(job, case)
        out.add(f"Sent: {url}", f"Once a maintainer merges it, stone doctor ranks {d['cause']} higher for "
                f"{d['failure']} on {d['printer']}.")
        out.next = doctor.DONE
        out.result = "doctor shared"
        return out
    link = issue_url(d)
    (bundle / "issue_url.txt").write_text(link + "\n")
    case["share"] = {"state": "link", "folder": d["id"], "url": link}
    doctor.save_case(job, case)
    out.add(f"Nothing was sent: {why}. The bundle is in {bundle}.", "Share it as a GitHub issue instead:", link)
    photo = f", attach {bundle / 'photo.jpg'}," if d["photo"] else ""
    out.next = f"ask the person: open the link above{photo} and press Submit new issue (public, MIT license)"
    return out
