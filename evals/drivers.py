"""Drivers for evals/run.py beyond lfm3 and next, so the same spec, card and grading run on every
model class: a small or large local model behind an OpenAI-compatible server, and frontier models
through Claude Code and Codex on the person's own sign-in.

  openai  POST <base-url>/chat/completions with native tool calling and the one stone tool, one
          step per request, the same 10 step budget as lfm3. Works with llama.cpp server, LM
          Studio, Ollama and vLLM. --api-key-env NAME reads a key from that variable; the key is
          sent as a Bearer header and never logged or printed.
  claude  claude -p on the person's sign-in. ANTHROPIC_API_KEY is always removed from its
          environment, so it can never bill the API. Its only tool is Bash, and only stone
          commands are allowed. The card is the appended system prompt.
  codex   codex exec on the person's sign-in (OPENAI_API_KEY and CODEX_API_KEY removed), in the
          job folder with the workspace-write sandbox, the card ahead of the request.

For claude and codex the transcript is what the CLI emits (stream-json, --json), read back into
the same messages and steps the other drivers log, so grade_job and distill.py read them alike.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

MODEL_DRIVERS = ("openai", "claude", "codex")
# variables that would switch a CLI from the person's sign-in to paid API billing
BILLING_ENV = {"claude": ("ANTHROPIC_API_KEY",), "codex": ("OPENAI_API_KEY", "CODEX_API_KEY")}
OPENAI_SAMPLING = {"temperature": 0.1}  # the lfm3 temperature; top_k and repeat_penalty are not in the API
# a CLI has its own shell tool, not one named stone; this goes after the harness's system line
CLI_NOTE = ("The stone tool is the stone command: run it with your shell tool, one stone command per call, "
            "for example: stone status. No other command is allowed.")


def slug(model: str) -> str:
    """A model name as a piece of a condition: lower case, runs of other characters one dash."""
    s = re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-.")
    return s or "model"


def cond_name(driver: str, card: str, compact_at: int = 0, model: str | None = None) -> str:
    """The run's condition. lfm3 and next keep their old names (cardS, cardS_compact4, next), so
    their floors do not move; the model drivers carry the driver and the model."""
    if driver == "next":
        return "next"
    c = f"card{card}" + (f"_compact{compact_at}" if compact_at else "")
    if driver == "lfm3":
        return c
    return f"{driver}-{slug(model or 'model')}_{c}"


# --- openai: any /v1/chat/completions server with tool calling ---------------------------------
def openai_step(base_url: str, model: str, messages: list, tools: list, seed: int, max_new: int,
                api_key_env: str | None = None, timeout: int = 900) -> dict:
    """One assistant turn. Returns {"content", "reasoning", "tool_calls", "finish_reason", "usage"}."""
    body = {"model": model, "messages": messages, "tools": tools, "tool_choice": "auto",
            "max_tokens": max_new, "seed": seed, **OPENAI_SAMPLING}
    headers = {"Content-Type": "application/json"}
    if api_key_env:
        key = os.environ.get(api_key_env)
        if not key:
            raise SystemExit(f"--api-key-env {api_key_env}: that variable is not set")
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read())
    ch = (resp.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    calls = []
    for i, c in enumerate(msg.get("tool_calls") or []):
        fn = c.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, dict):  # Ollama sends an object, the API a JSON string
            args = json.dumps(args)
        calls.append({"id": c.get("id") or f"call{i}", "type": "function",
                      "function": {"name": fn.get("name") or "", "arguments": args or "{}"}})
    return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
            "tool_calls": calls, "finish_reason": ch.get("finish_reason"), "usage": resp.get("usage")}


# --- claude and codex: a CLI on the person's sign-in -------------------------------------------
def cli_env(driver: str, env: dict, stone_bin: Path) -> dict:
    """The CLI's environment: the run's, with stone's folder first on PATH and every billing key
    removed."""
    out = {k: v for k, v in env.items() if k not in BILLING_ENV[driver]}
    out["PATH"] = str(stone_bin) + os.pathsep + env.get("PATH", "")
    return out


def claude_argv(model: str, system: str, prompt: str, resume: str | None = None) -> list[str]:
    """claude -p with Bash as its only tool, only stone commands allowed, nothing else asked: a
    command outside stone is denied, not prompted. --safe-mode leaves out the person's CLAUDE.md,
    skills, hooks and MCP servers, so the card is the only instruction it gets."""
    argv = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
            "--tools", "Bash", "--allowedTools", "Bash(stone:*)", "--permission-mode", "dontAsk",
            "--append-system-prompt", system, "--safe-mode", "--strict-mcp-config"]
    if resume:
        argv += ["--resume", resume]
    return argv


def codex_argv(model: str, job: Path, prompt: str, last_file: Path, resume: str | None = None) -> list[str]:
    """codex exec in the job folder with the workspace-write sandbox, JSONL events on stdout."""
    head = ["codex", "exec"] + (["resume"] if resume else [])
    argv = head + ["-m", model, "--json", "--skip-git-repo-check", "-o", str(last_file)]
    if not resume:  # resume takes the session's sandbox and folder
        argv += ["-s", "workspace-write", "-C", str(job)]
    return argv + ([resume] if resume else []) + [prompt]


def codex_prompt(system: str, user: str) -> str:
    """Codex has no appended system prompt in exec, so the card goes ahead of the request."""
    return system + "\n\n---\n\n" + user


def run_cli(argv: list[str], env: dict, cwd: Path, timeout: int) -> tuple[str, str, int | None, float]:
    """(stdout, stderr, exit code or None on a timeout, seconds). Its own process group, so a
    timeout also stops the stone it started."""
    t0 = time.time()
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env=env, cwd=cwd, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        code = p.returncode
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                break
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        out, err = p.communicate()
        code = None
    return out or "", err or "", code, round(time.time() - t0, 1)


def _stone_args(command: str) -> dict:
    return {"command": command.strip()}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def parse_claude(stream: str, phase: int = 0) -> dict:
    """claude stream-json to {"messages", "steps", "session", "result", "error"}: one step per
    assistant turn, each Bash call a stone tool call with its result."""
    msgs, steps, by_id = [], [], {}
    session = result = error = None
    usage = init = None
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        session = ev.get("session_id") or session
        if kind == "system" and ev.get("subtype") == "init":
            # apiKeySource "none" is the person's sign-in; the model is the one the alias resolved to
            init = {k: ev.get(k) for k in ("model", "apiKeySource", "tools", "permissionMode")}
        elif kind == "assistant":
            parts = (ev.get("message") or {}).get("content") or []
            text = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
            think = "\n".join(p.get("thinking", "") for p in parts if p.get("type") == "thinking").strip()
            uses = [p for p in parts if p.get("type") == "tool_use"]
            if not (text or think or uses):
                continue
            am = {"role": "assistant", "content": text}
            st = {"step": len([s for s in steps if s["phase"] == phase]) + 1, "phase": phase, "tool_calls": []}
            if think:
                st["reasoning"] = think
            if uses:
                am["tool_calls"] = []
                for u in uses:
                    inp = u.get("input") or {}
                    name = "stone" if u.get("name") == "Bash" else u.get("name", "")
                    args = _stone_args(inp.get("command", "")) if u.get("name") == "Bash" else inp
                    am["tool_calls"].append({"id": u.get("id", ""), "type": "function",
                                             "function": {"name": name, "arguments": json.dumps(args)}})
                    tc = {"name": name, "args": args, "result": None}
                    st["tool_calls"].append(tc)
                    by_id[u.get("id")] = tc
            msgs.append(am)
            steps.append(st)
        elif kind == "user":
            for p in (ev.get("message") or {}).get("content") or []:
                if isinstance(p, dict) and p.get("type") == "tool_result":
                    res = _text_of(p.get("content")).strip()[:3000]
                    if p.get("tool_use_id") in by_id:
                        by_id[p["tool_use_id"]]["result"] = res
                    msgs.append({"role": "tool", "tool_call_id": p.get("tool_use_id", ""), "content": res})
        elif kind == "result":
            result = ev.get("result")
            usage = {k: ev.get(k) for k in ("num_turns", "duration_ms", "usage") if k in ev}
            if ev.get("is_error"):
                error = str(ev.get("result") or ev.get("subtype"))
    return {"messages": msgs, "steps": steps, "session": session, "result": result, "error": error, "usage": usage,
            "init": init}


def parse_codex(stream: str, phase: int = 0) -> dict:
    """codex exec --json events to the same shape: each finished command a stone tool call, each
    agent message an assistant turn."""
    msgs, steps = [], []
    session = error = result = None
    usage = None
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type", "")
        session = ev.get("thread_id") or ev.get("session_id") or session
        if kind == "turn.completed":
            usage = ev.get("usage")
        elif kind in ("turn.failed", "error"):
            error = str((ev.get("error") or {}).get("message") if isinstance(ev.get("error"), dict) else ev.get("message") or ev)
        if kind != "item.completed":
            continue
        it = ev.get("item") or {}
        st = {"step": len([s for s in steps if s["phase"] == phase]) + 1, "phase": phase, "tool_calls": []}
        if it.get("type") == "command_execution":
            cmd = it.get("command", "")
            m = re.match(r"^(?:\S*/)?(?:ba|z)?sh -l?c (['\"])(.*)\1$", cmd, re.S)  # codex wraps it in a shell
            cmd = m.group(2) if m else cmd
            args = _stone_args(cmd)
            res = str(it.get("aggregated_output") or "").strip()[:3000]
            cid = it.get("id", f"c{len(steps)}")
            msgs.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": "stone", "arguments": json.dumps(args)}}]})
            msgs.append({"role": "tool", "tool_call_id": cid, "content": res})
            st["tool_calls"].append({"name": "stone", "args": args, "result": res, "exit_code": it.get("exit_code")})
        elif it.get("type") in ("agent_message", "assistant_message"):
            result = it.get("text", "")
            msgs.append({"role": "assistant", "content": result})
        elif it.get("type") == "reasoning":
            st["reasoning"] = it.get("text", "")
        else:
            continue
        steps.append(st)
    return {"messages": msgs, "steps": steps, "session": session, "result": result, "error": error, "usage": usage,
            "init": None}


def cli_phase(driver: str, model: str, system: str, user: str, env: dict, stone_bin: Path, job: Path, rdir: Path,
              phase: int, resume: str | None, timeout: int) -> dict:
    """Run one phase (the request, or a follow-up) through a CLI. Returns the parse plus "argv"
    (the prompt left out), "exit", "seconds" and "stderr"."""
    cenv = cli_env(driver, env, stone_bin)
    prompt = user if (resume or driver == "claude") else codex_prompt(system, user)
    if driver == "claude":
        argv = claude_argv(model, system, user, resume)
        out, err, code, secs = run_cli(argv, cenv, job, timeout)
        got = parse_claude(out, phase)
    else:
        argv = codex_argv(model, job, prompt, rdir / f"codex_last{phase}.txt", resume)
        out, err, code, secs = run_cli(argv, cenv, job, timeout)
        got = parse_codex(out, phase)
    (rdir / f"{driver}_stream{phase}.jsonl").write_text(out)
    if code is None:
        got["error"] = (got["error"] + "; " if got["error"] else "") + f"timed out after {timeout} s"
    elif code and not got["error"]:
        got["error"] = f"exit {code}: " + (err.strip().splitlines() or [""])[-1][:300]
    shown = ["<card>" if x == system else "<request>" if x in (user, prompt) else x for x in argv]
    return {**got, "argv": shown, "exit": code, "seconds": secs, "stderr": err[-2000:]}
