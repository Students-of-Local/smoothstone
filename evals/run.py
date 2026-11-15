"""Round 2 harness: one model, one tool (stone), one job folder per run.

uv run python evals/run.py <spec.json> --seed N [--card S|M|L|none] [--driver lfm3|next]
                          [--compact-at K] [--out DIR] [--server URL]

Fixed for every condition (same as lfm3-3d-skill harness v3): 10 steps, 2048 new tokens per
step, the model card's sampling, a cut step continues the same thought on the next step. Only
the card and the compaction change.

Drivers:
  lfm3  a llama.cpp server (raw chat template through /apply-template, then /completion)
  next  no model: runs stone status, then every NEXT line stone prints, until it stops. This
        is the baseline that shows what the tool does without any model.

--compact-at K: after step K, every earlier turn is dropped. The model keeps only the system
prompt and the request, plus a note that its context was compacted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smoothstone import check as checks  # noqa: E402
from smoothstone import recipes as rc  # noqa: E402

HARNESS = "r2 (v3 settings; one stone tool; optional forced compaction)"
MAX_STEPS = 10
MAX_NEW = 2048
SAMPLING = {"temperature": 0.1, "top_k": 50, "repeat_penalty": 1.1}
STONE = str(ROOT / ".venv" / "bin" / "stone")

SYSTEM = ("You are an agent that makes 3D printable parts. Use the stone tool to do the task. "
          "When the part is ready, reply with a short final message and no tool call.")
COMPACTED = ("Your context was compacted, so your earlier steps are gone. The job is still on disk. "
             "Run stone status to see where you are.")
TOOLS = [{"type": "function", "function": {
    "name": "stone",
    "description": "Run one stone command, for example: stone status",
    "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "the stone command line"}},
                   "required": ["command"]}}}]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_stone(command: str, env: dict, cwd: Path) -> str:
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return f"FIX: could not read the command ({e}). Write it like: stone status"
    if argv and argv[0] == "stone":
        argv = argv[1:]
    if not argv:
        return "FIX: empty command.\nNEXT: stone status"
    try:
        p = subprocess.run([STONE, *argv], capture_output=True, text=True, env=env, cwd=cwd, timeout=420)
    except subprocess.TimeoutExpired:
        return "FIX: the command ran too long.\nNEXT: stone status"
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr and not p.stdout else "")
    return out.strip()[:3000]


def last_next(text: str) -> str | None:
    m = re.findall(r"^NEXT: (.+)$", text, re.M)
    return m[-1].strip() if m else None


# --- llama.cpp driver -------------------------------------------------------------------------
def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


TOOL_RE = re.compile(r"<tool_call>\s*<function=([^>\s]+)>(.*?)</function>\s*</tool_call>", re.S)
PARAM_RE = re.compile(r"<parameter=([^>\s]+)>\n?(.*?)\n?</parameter>", re.S)


def parse_turn(text):
    if "</think>" in text:
        reasoning, rest = text.split("</think>", 1)
    else:
        reasoning, rest = text, ""
    calls = []
    for i, m in enumerate(TOOL_RE.finditer(rest)):
        args = {k: v for k, v in PARAM_RE.findall(m.group(2))}
        calls.append({"id": f"call{i}", "type": "function", "function": {"name": m.group(1), "arguments": json.dumps(args)}})
    return reasoning.strip(), TOOL_RE.sub("", rest).strip(), calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--card", default="S", choices=["S", "M", "L", "none"])
    ap.add_argument("--driver", default="lfm3", choices=["lfm3", "next"])
    ap.add_argument("--compact-at", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT.parent / "runs2"))
    ap.add_argument("--server", default="http://127.0.0.1:8091")
    ap.add_argument("--model-name", default="LFM3-1.7B Q4_K_M (LiquidAI/LFM3-1.7B-GGUF)")
    a = ap.parse_args()

    spec_path = Path(a.spec).resolve()
    spec = json.loads(spec_path.read_text())
    cond = a.driver if a.driver == "next" else f"card{a.card}" + (f"_compact{a.compact_at}" if a.compact_at else "")
    run_id = f"{spec['id']}__{cond}__s{a.seed}__{time.strftime('%Y%m%d-%H%M%S')}"
    rdir = Path(a.out) / run_id
    job = rdir / "job"
    rdir.mkdir(parents=True)
    env = {**os.environ, "STONE_JOB": str(job), "STONE_TIER": a.card if a.card != "none" else "S"}

    # the environment, set up before the model starts: the job with the request (and picture)
    new = ["new", spec["request"]]
    if spec.get("image"):
        new += ["--image", str((spec_path.parent / spec["image"]).resolve())]
    setup = subprocess.run([STONE, *new], capture_output=True, text=True, env=env, cwd=rdir).stdout

    system = SYSTEM
    card_sha = None
    if a.card != "none":
        card = (ROOT / "skill" / "tiers" / f"{a.card}.md").read_text()
        card_sha = sha(card.encode())
        system += "\n\nA skill is loaded for this task. Follow it.\n\n" + card
    user = spec["request"] + ("\nThe picture is already in the job." if spec.get("image") else "") + \
        "\nThe job is ready; use the stone tool."
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    log = {"run_id": run_id, "spec": spec["id"], "spec_sha256": sha(spec_path.read_bytes()), "condition": cond,
           "seed": a.seed, "driver": a.driver, "card": a.card, "card_sha256": card_sha, "compact_at": a.compact_at,
           "model": a.model_name if a.driver == "lfm3" else None, "sampling": SAMPLING if a.driver == "lfm3" else None,
           "harness": HARNESS, "max_steps": MAX_STEPS, "max_new_tokens": MAX_NEW, "setup": setup,
           "system_sha256": sha(system.encode()), "steps": [], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    t0 = time.time()
    pending = ""
    nxt = "stone status"
    print(f"{spec['id']}  {cond}  seed {a.seed}", flush=True)

    for step in range(1, MAX_STEPS + 1):
        st = {"step": step, "t": round(time.time() - t0, 2)}
        if a.compact_at and step == a.compact_at + 1 and a.driver == "lfm3":
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user + "\n\n" + COMPACTED}]
            pending = ""
            st["compacted"] = True
            print(f"{step:>2} (context compacted)", flush=True)
        if a.driver == "next":
            if not nxt or "<" in nxt or nxt.startswith("none"):
                st["final"] = f"stopped: NEXT is {nxt!r}"
                log["steps"].append(st)
                break
            calls = [{"id": f"n{step}", "type": "function", "function": {"name": "stone", "arguments": json.dumps({"command": nxt})}}]
            am = {"role": "assistant", "content": "", "tool_calls": calls}
        else:
            prompt = _post(a.server, "/apply-template", {"messages": messages, "tools": TOOLS})["prompt"] + pending
            r = _post(a.server, "/completion", {"prompt": prompt, "n_predict": MAX_NEW, "seed": a.seed, "stop": ["<|im_end|>"],
                                                "cache_prompt": True, **SAMPLING})
            text, cut = r["content"], r.get("stop_type") == "limit"
            st.update({"generated": text, "tokens_predicted": r.get("tokens_predicted"), "stop_type": r.get("stop_type"),
                       "continued_from_cut": bool(pending)})
            if cut:
                pending += text
                st["tool_calls"] = []
                log["steps"].append(st)
                print(f"{step:>2} (cut at {MAX_NEW} tokens, continues)", flush=True)
                continue
            reasoning, content, calls = parse_turn(pending + text)
            pending = ""
            am = {"role": "assistant", "content": content}
            if reasoning:
                am["reasoning_content"] = reasoning
            if calls:
                am["tool_calls"] = calls
        messages.append(am)
        st["tool_calls"] = []
        for c in calls:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if c["function"]["name"] != "stone":
                result = "FIX: the only tool is stone. Call it with a command like: stone status"
            else:
                result = run_stone(str(args.get("command", "")), env, rdir)
            nxt = last_next(result) or nxt
            st["tool_calls"].append({"name": c["function"]["name"], "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": result})
            print(f"{step:>2} {args.get('command', '?')[:70]}  ->  {(last_next(result) or result.splitlines()[-1] if result else '')[:60]}", flush=True)
        log["steps"].append(st)
        if not calls:
            print(f"{step:>2} (stopped, no tool call)", flush=True)
            break

    grade = grade_job(job, spec)
    log.update({"seconds": round(time.time() - t0, 1), **grade, "messages": messages})
    (rdir / "log.json").write_text(json.dumps(log, indent=1))
    print(("PASS  " if grade["pass"] else "FAIL  ") + "; ".join(grade["why"])[:160], flush=True)


def grade_job(job: Path, spec: dict) -> dict:
    """Outside the model's reach: did stone done write a part that passes the checks and the spec?"""
    why = []
    built = json.loads((job / "build" / "params.json").read_text()) if (job / "build" / "params.json").exists() else {}
    recipe = built.get("recipe")
    params = built.get("params", {})
    final = job / f"{recipe}.stl" if recipe else None
    done = bool(final and final.exists())
    if not done:
        why.append("stone done never wrote the part")
    exp = spec["expect"]
    if recipe != exp["recipe"]:
        why.append(f"recipe {recipe} (want {exp['recipe']})")
    for k, want in exp.get("params", {}).items():
        got = params.get(k)
        ok = (isinstance(want, list) and isinstance(got, (int, float)) and want[0] <= got <= want[1]) or \
             (not isinstance(want, list) and (got == want or (isinstance(want, (int, float)) and isinstance(got, (int, float)) and abs(got - want) < 1e-6)))
        if not ok:
            why.append(f"{k}={got!r} (want {want})")
    for s in exp.get("sum", []):
        tot = sum(params.get(k, 0) or 0 for k in s["params"])
        if tot != s["eq"]:
            why.append(f"{'+'.join(s['params'])}={tot} (want {s['eq']})")
    if exp.get("image_used") and not params.get(exp["image_used"]):
        why.append("the picture was not used")
    res = []
    if done and recipe:
        off = job / "build" / "part.off"
        r = rc.load(recipe)
        res = [x.to_dict() for x in checks.check_stl(off if off.exists() else final, recipe=r, params=params)]
        bad = [x["name"] for x in res if not x["ok"]]
        if bad:
            why.append("print checks fail: " + ", ".join(bad))
    stl_sha = sha(final.read_bytes()) if done else None
    return {"pass": not why, "why": why or ["all checks pass"], "recipe": recipe, "params": params,
            "checks": res, "stl": str(final) if done else None, "stl_sha256": stl_sha}


if __name__ == "__main__":
    main()
