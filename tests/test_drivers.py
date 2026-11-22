"""The model drivers of evals/run.py (evals/drivers.py): openai against a fake server, claude and
codex against fake CLIs, and the condition names. No network, no model."""
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_harness_drivers", ROOT / "evals" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
drivers = run.drivers
FAN = ROOT / "evals" / "tuning" / "t1_fan_guard.json"
DUMMY = "dummy-value-for-tests-42"  # stands in for a key; must never reach a log or a CLI
HAS_STONE = (ROOT / ".venv" / "bin" / "stone").exists()


# --- condition names ---------------------------------------------------------------------------
def test_lfm3_and_next_keep_their_condition_names():
    # the floors in floor.json and every old run folder use these
    assert drivers.cond_name("lfm3", "S") == "cardS"
    assert drivers.cond_name("lfm3", "M", 4) == "cardM_compact4"
    assert drivers.cond_name("lfm3", "none") == "cardnone"
    assert drivers.cond_name("next", "S", model="anything") == "next"


def test_a_model_driver_names_the_driver_and_the_model():
    assert drivers.cond_name("openai", "S", model="Qwen3-8B Q4_K_M") == "openai-qwen3-8b-q4-k-m_cardS"
    assert drivers.cond_name("claude", "M", model="haiku") == "claude-haiku_cardM"
    assert drivers.cond_name("codex", "L", model="gpt-6.1-sol") == "codex-gpt-6.1-sol_cardL"
    assert drivers.cond_name("openai", "S", 3, "lfm3:1.7b") == "openai-lfm3-1.7b_cardS_compact3"
    # run folders split on "__": a model name never adds one
    assert "__" not in drivers.cond_name("openai", "S", model="a__b//c")


# --- openai: a fake /v1/chat/completions that plays a model --------------------------------------
SCRIPT = ["stone status", "stone recipes", "stone show fan_guard", "stone set fan_guard size=120 thickness=3",
          "stone build"]


class FakeChat(BaseHTTPRequestHandler):
    seen: list = []
    auth: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeChat.seen.append({"path": self.path, "body": body})
        FakeChat.auth.append(self.headers.get("Authorization"))
        n = sum(m["role"] == "tool" for m in body["messages"])
        if n < len(SCRIPT):
            msg = {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"call_{n}", "type": "function",
                 "function": {"name": "stone", "arguments": json.dumps({"command": SCRIPT[n]})}}]}
            finish = "tool_calls"
        else:
            msg, finish = {"role": "assistant", "content": "The fan guard is ready."}, "stop"
        out = json.dumps({"choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                          "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_chat():
    FakeChat.seen, FakeChat.auth = [], []
    srv = HTTPServer(("127.0.0.1", 0), FakeChat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def _main(monkeypatch, tmp_path, *args):
    monkeypatch.setattr(run, "SCORES", tmp_path / "scores.jsonl")
    monkeypatch.setattr(sys, "argv", ["run.py", str(FAN), "--seed", "1", "--out", str(tmp_path / "runs"), *args])
    run.main()
    (log,) = list((tmp_path / "runs").glob("*/log.json"))
    return json.loads(log.read_text()), log


@pytest.mark.skipif(not HAS_STONE, reason="no stone in .venv")
def test_the_openai_driver_builds_a_part_through_tool_calls(monkeypatch, tmp_path, fake_chat, openscad):
    monkeypatch.setenv("FAKE_KEY", DUMMY)
    log, path = _main(monkeypatch, tmp_path, "--driver", "openai", "--model", "fake-model", "--base-url", fake_chat,
                      "--api-key-env", "FAKE_KEY")
    assert log["pass"], log["why"]
    assert log["recipe"] == "fan_guard" and log["params"]["size"] == 120 and log["stl_sha256"]
    assert log["condition"] == "openai-fake-model_cardS"
    assert path.parent.name.startswith("t1_fan_guard__openai-fake-model_cardS__s1__")
    assert log["driver"] == "openai" and log["model"] == "fake-model"
    assert log["card_sha256"] == run.sha((ROOT / "skill" / "tiers" / "S.md").read_bytes())
    assert isinstance(log["seconds"], float) and log["api_key_env"] == "FAKE_KEY"
    # the same transcript as lfm3: one step per turn, each stone call with its result
    cmds = [c["args"]["command"] for s in log["steps"] for c in s["tool_calls"]]
    assert cmds == SCRIPT and len(log["steps"]) == len(SCRIPT) + 1
    assert "Part ready" in log["steps"][4]["tool_calls"][0]["result"]
    # the request: one tool named stone, the card in the system message, the key as a Bearer header only
    first = FakeChat.seen[0]
    assert first["path"] == "/v1/chat/completions" and first["body"]["model"] == "fake-model"
    assert [t["function"]["name"] for t in first["body"]["tools"]] == ["stone"]
    assert "A skill is loaded" in first["body"]["messages"][0]["content"]
    assert set(FakeChat.auth) == {"Bearer " + DUMMY}
    assert DUMMY not in path.read_text() and DUMMY not in (tmp_path / "scores.jsonl").read_text()
    line = json.loads((tmp_path / "scores.jsonl").read_text())
    assert line["driver"] == "openai" and line["condition"] == "openai-fake-model_cardS" and line["pass"] == 1


def test_the_openai_driver_reads_ollama_style_arguments(monkeypatch):
    class R:
        def __init__(self, body):
            self.body = body

        def read(self):
            return json.dumps(self.body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass
    body = {"choices": [{"message": {"content": None, "tool_calls": [
        {"function": {"name": "stone", "arguments": {"command": "stone status"}}}]}, "finish_reason": "stop"}]}
    monkeypatch.setattr(drivers.urllib.request, "urlopen", lambda req, timeout: R(body))
    r = drivers.openai_step("http://x/v1", "m", [], run.TOOLS, 1, 10)
    assert r["tool_calls"][0]["id"] == "call0"
    assert json.loads(r["tool_calls"][0]["function"]["arguments"]) == {"command": "stone status"}


# --- claude and codex: argument building --------------------------------------------------------
def test_the_claude_call_never_bills_the_api():
    env = drivers.cli_env("claude", {"ANTHROPIC_API_KEY": DUMMY, "PATH": "/usr/bin", "HOME": "/h"}, Path("/v/bin"))
    assert "ANTHROPIC_API_KEY" not in env and env["PATH"] == "/v/bin" + os.pathsep + "/usr/bin"
    argv = drivers.claude_argv("haiku", "SYSTEM CARD", "make a fan guard")
    assert argv[:3] == ["claude", "-p", "make a fan guard"]
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--tools") + 1] == "Bash"
    assert argv[argv.index("--allowedTools") + 1] == "Bash(stone:*)"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--append-system-prompt") + 1] == "SYSTEM CARD"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert not any(x in a.lower() for a in argv for x in ("api-key", "api_key", "max-budget", "betas", "bare"))
    assert "--dangerously-skip-permissions" not in argv
    assert drivers.claude_argv("haiku", "S", "p", resume="abc")[-2:] == ["--resume", "abc"]


def test_the_codex_call_runs_in_the_job_on_the_sign_in(tmp_path):
    env = drivers.cli_env("codex", {"OPENAI_API_KEY": DUMMY, "CODEX_API_KEY": DUMMY, "PATH": "/usr/bin"},
                          Path("/v/bin"))
    assert "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env
    argv = drivers.codex_argv("gpt-6.1-sol", tmp_path / "job", "CARD\n\n---\n\nREQ", tmp_path / "last.txt")
    assert argv[:2] == ["codex", "exec"] and argv[-1] == "CARD\n\n---\n\nREQ"
    assert argv[argv.index("-m") + 1] == "gpt-6.1-sol"
    assert argv[argv.index("-s") + 1] == "workspace-write"
    assert argv[argv.index("-C") + 1] == str(tmp_path / "job")
    assert "--json" in argv and "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert not any("api" in a.lower() and "key" in a.lower() for a in argv)
    p = drivers.codex_prompt("CARD", "REQ")
    assert p.startswith("CARD") and p.endswith("REQ")
    again = drivers.codex_argv("m", tmp_path, "more", tmp_path / "l.txt", resume="t-1")
    assert again[:3] == ["codex", "exec", "resume"] and again[-2:] == ["t-1", "more"]


# --- claude and codex end to end through fake CLIs ----------------------------------------------
FAKE_CLAUDE = r'''#!{py}
import json, os, subprocess, sys
open(os.environ["FAKE_SEEN"], "w").write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(),
    "anthropic": "ANTHROPIC_API_KEY" in os.environ, "job": os.environ.get("STONE_JOB")}}))
def out(ev): print(json.dumps(ev), flush=True)
out({{"type": "system", "subtype": "init", "session_id": "sess-1", "model": "claude-haiku-5-5",
     "apiKeySource": "none", "tools": ["Bash"], "permissionMode": "dontAsk"}})
for i, cmd in enumerate(["stone status", "stone recipes"]):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out({{"type": "assistant", "session_id": "sess-1", "message": {{"content": [
        {{"type": "thinking", "thinking": "run it"}}, {{"type": "text", "text": "Running."}},
        {{"type": "tool_use", "id": f"tu{{i}}", "name": "Bash", "input": {{"command": cmd}}}}]}}}})
    out({{"type": "user", "session_id": "sess-1", "message": {{"content": [
        {{"type": "tool_result", "tool_use_id": f"tu{{i}}", "content": r.stdout}}]}}}})
out({{"type": "assistant", "session_id": "sess-1", "message": {{"content": [{{"type": "text", "text": "Stopped."}}]}}}})
out({{"type": "result", "subtype": "success", "is_error": False, "result": "Stopped.", "session_id": "sess-1",
     "num_turns": 3, "duration_ms": 10}})
'''

FAKE_CODEX = r'''#!{py}
import json, os, subprocess, sys
open(os.environ["FAKE_SEEN"], "w").write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(),
    "openai": "OPENAI_API_KEY" in os.environ, "job": os.environ.get("STONE_JOB")}}))
def out(ev): print(json.dumps(ev), flush=True)
out({{"type": "thread.started", "thread_id": "th-1"}})
out({{"type": "turn.started"}})
r = subprocess.run("stone status", shell=True, capture_output=True, text=True)
out({{"type": "item.completed", "item": {{"id": "item_0", "type": "reasoning", "text": "status first"}}}})
out({{"type": "item.completed", "item": {{"id": "item_1", "type": "command_execution",
     "command": "/bin/bash -lc 'stone status'", "aggregated_output": r.stdout, "exit_code": 0, "status": "completed"}}}})
out({{"type": "item.completed", "item": {{"id": "item_2", "type": "agent_message", "text": "Which fan size?"}}}})
out({{"type": "turn.completed", "usage": {{"input_tokens": 5, "output_tokens": 3}}}})
'''


def _fake_cli(tmp_path, monkeypatch, name, text):
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    exe = bindir / name
    exe.write_text(text.format(py=sys.executable))
    exe.chmod(0o755)
    seen = tmp_path / f"{name}_seen.json"
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_SEEN", str(seen))
    return seen


@pytest.mark.skipif(not HAS_STONE, reason="no stone in .venv")
def test_the_claude_driver_logs_its_stream_and_grades_the_job(monkeypatch, tmp_path):
    seen = _fake_cli(tmp_path, monkeypatch, "claude", FAKE_CLAUDE)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY)
    log, path = _main(monkeypatch, tmp_path, "--driver", "claude", "--model", "haiku")
    got = json.loads(seen.read_text())
    assert got["anthropic"] is False  # the key was set here and never reached claude
    assert got["cwd"] == got["job"] == str(path.parent / "job")
    assert "Bash(stone:*)" in got["argv"] and got["argv"][got["argv"].index("--model") + 1] == "haiku"
    card = got["argv"][got["argv"].index("--append-system-prompt") + 1]
    assert drivers.CLI_NOTE in card and (ROOT / "skill" / "tiers" / "S.md").read_text() in card
    assert log["condition"] == "claude-haiku_cardS" and log["model"] == "haiku" and log["card_sha256"]
    # the stone the fake ran was found on PATH, in the job the harness made
    assert [c["args"]["command"] for s in log["steps"] for c in s["tool_calls"]] == ["stone status", "stone recipes"]
    assert "NEXT: stone recipes" in log["steps"][0]["tool_calls"][0]["result"]
    assert log["steps"][0]["reasoning"] == "run it"
    assert [m["role"] for m in log["messages"]] == ["system", "user", "assistant", "tool", "assistant", "tool",
                                                    "assistant"]
    assert log["cli"][0]["session"] == "sess-1" and log["cli"][0]["exit"] == 0 and log["cli"][0]["error"] is None
    assert "<card>" in log["cli"][0]["argv"] and "<request>" in log["cli"][0]["argv"]
    assert log["cli"][0]["init"] == {"model": "claude-haiku-5-5", "apiKeySource": "none", "tools": ["Bash"],
                                     "permissionMode": "dontAsk"}
    # graded like every other driver: the job on disk, no part
    assert log["pass"] is False and log["why"] == ["no finished part", "recipe None (want fan_guard)",
                                                   "size=None (want 120)", "thickness=None (want 3)"]
    assert (path.parent / "claude_stream0.jsonl").exists() and DUMMY not in path.read_text()


@pytest.mark.skipif(not HAS_STONE, reason="no stone in .venv")
def test_the_codex_driver_logs_its_events_and_grades_the_job(monkeypatch, tmp_path):
    seen = _fake_cli(tmp_path, monkeypatch, "codex", FAKE_CODEX)
    monkeypatch.setenv("OPENAI_API_KEY", DUMMY)
    log, path = _main(monkeypatch, tmp_path, "--driver", "codex", "--model", "gpt-6.1-sol", "--card", "M")
    got = json.loads(seen.read_text())
    assert got["openai"] is False and got["cwd"] == got["job"] == str(path.parent / "job")
    assert got["argv"][got["argv"].index("-C") + 1] == str(path.parent / "job")
    assert got["argv"][-1].startswith(run.SYSTEM) and got["argv"][-1].endswith("The job is ready; use the stone tool.")
    assert log["condition"] == "codex-gpt-6.1-sol_cardM"
    assert [c["args"]["command"] for s in log["steps"] for c in s["tool_calls"]] == ["stone status"]
    assert log["messages"][-1] == {"role": "assistant", "content": "Which fan size?"}
    assert log["cli"][0]["session"] == "th-1" and log["cli"][0]["usage"] == {"input_tokens": 5, "output_tokens": 3}
    assert log["pass"] is False and "no finished part" in log["why"]


def test_a_cli_that_fails_says_why(monkeypatch, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text("#!/bin/sh\necho 'Not logged in. Please run /login' >&2\nexit 1\n")
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    job = tmp_path / "job"
    job.mkdir()
    got = drivers.cli_phase("claude", "haiku", "SYS", "REQ", dict(os.environ), Path("/nonexistent"), job, tmp_path,
                            0, None, 30)
    assert got["exit"] == 1 and got["error"] == "exit 1: Not logged in. Please run /login"
    assert got["steps"] == [] and got["argv"][2] == "<request>"


def test_summary_keeps_model_conditions_apart(tmp_path):
    for i, (cond, ok) in enumerate([("cardS", True), ("claude-haiku_cardS", False),
                                    ("openai-qwen3-8b-q4-k-m_cardS", True)]):
        d = tmp_path / f"r{i}"
        d.mkdir()
        (d / "log.json").write_text(json.dumps({"spec": "t1_fan_guard", "condition": cond, "seed": 1, "pass": ok,
                                                "why": ["all checks pass" if ok else "no finished part"]}))
    out = subprocess.run([sys.executable, str(ROOT / "evals" / "summary.py"), str(tmp_path)], capture_output=True,
                         text=True, check=True).stdout.splitlines()
    assert out[0].split() == ["spec", "cardS", "claude-haiku_cardS", "openai-qwen3-8b-q4-k-m_cardS"]
    assert out[1].split() == ["t1_fan_guard", "1/1", "0/1", "1/1"]
    # each column starts where its name does, so long names do not run together
    assert out[1].index("0/1") == out[0].index("claude-haiku_cardS")
