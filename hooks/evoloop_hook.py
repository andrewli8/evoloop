#!/usr/bin/env python3
"""EvolveLoop session-mode hook for Claude Code / Codex.

  session  -> SessionStart: emit the ruleset for the active level (+ `evoloop status` if the cwd is initialized)
  prompt   -> UserPromptSubmit: track `/evoloop off|full|ultra`, `/evoloop default <level>`, "stop evoloop"

Mode flag: $CLAUDE_CONFIG_DIR/.evoloop-mode (default ~/.claude). Persistent default: ~/.config/evoloop/config.json.
Stdlib only, never blocks: every failure exits 0 with empty output.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

LEVELS = ("off", "full", "ultra")
DEFAULT = "full"
IS_CODEX = bool(os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SANDBOX"))

RULES = {
    "full": """EVOLOOP MODE ACTIVE — level: full

EvolveLoop is a bounded, evidence-driven product improvement loop installed as the `evoloop` CLI. The CLI is the source of truth; you are its operator.

When to run it: the user asks what to improve next, wants a grounded product recommendation, or asks for an improvement cycle. Not for feature requests the user already specified.
How: `evoloop status` first. `evoloop analyze` for a recommendation (no code changes). `evoloop run --mode plan|build|pr` only when the user asked for that mode. Repo not initialized: offer `evoloop init`, then check its provider line (mock = placeholder output, tell the user).
Results: read `.evoloop/runs/<cycle>/report.md`; summarize problem, evidence, finalists, winner, gate. Never paste raw logs.
Rules: the Evaluation Contract (`.evoloop/runs/<cycle>/contract.json`) is read-only during an experiment. Never enable modes, merge, deploy, or raise permissions yourself. Stakeholder evaluations are simulated; never call them customer validation. Disabled/paused output means stop and tell the user why.
Switch: `/evoloop off|full|ultra`. Off: "stop evoloop".""",
    "ultra": """EVOLOOP MODE ACTIVE — level: ultra (autonomous)

Everything in full, plus: when you finish a task and the user has not queued another, run one bounded cycle with `evoloop run` (the mode comes from `.evoloop/config.yaml`; never pass --mode to escalate) and report the result. Stop looping the moment a cycle returns paused, awaiting_human, blocked, disabled, budget_exhausted or error. Never resolve a cycle yourself; `evoloop resolve` is the human's call. Never merge or deploy.
Switch: `/evoloop off|full`. Off: "stop evoloop".""",
}


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def flag() -> Path:
    return config_dir() / ".evoloop-mode"


def default_mode() -> str:
    env = os.environ.get("EVOLOOP_DEFAULT_MODE", "").lower()
    if env in LEVELS:
        return env
    p = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "evoloop" / "config.json"
    try:
        m = json.loads(p.read_text()).get("defaultMode", "").lower()
        return m if m in LEVELS else DEFAULT
    except (OSError, ValueError):
        return DEFAULT


def write_default(mode: str) -> None:
    p = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "evoloop" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"defaultMode": mode}))


def read_mode() -> str | None:
    try:
        m = flag().read_text().strip()
        return m if m in LEVELS else None
    except OSError:
        return None


def set_mode(mode: str) -> None:
    try:
        flag().parent.mkdir(parents=True, exist_ok=True)
        flag().write_text(mode)
    except OSError:
        pass


def emit(event: str, mode: str, context: str) -> None:
    if IS_CODEX:
        out = {"systemMessage": f"EVOLOOP:{mode.upper()}"}
        if context:
            out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": context}
        sys.stdout.write(json.dumps(out))
    elif event == "SessionStart":
        sys.stdout.write(context)
    elif context:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}))


def status_line() -> str:
    """Cheap repo context: `evoloop status` if the cwd is initialized and the CLI is present."""
    if not (Path.cwd() / ".evoloop" / "config.yaml").exists():
        return ""
    if not shutil.which("evoloop"):
        return "\n\nThis repo has .evoloop/ but the `evoloop` CLI is not on PATH: `uv tool install git+https://github.com/andrewli8/evoloop`."
    try:
        r = subprocess.run(["evoloop", "status"], capture_output=True, text=True, timeout=4)
        return "\n\nevoloop status:\n" + r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def session() -> None:
    mode = default_mode()
    if mode == "off":
        flag().unlink(missing_ok=True)
        emit("SessionStart", "off", "")
        return
    set_mode(mode)
    emit("SessionStart", mode, RULES[mode] + status_line())


def prompt() -> None:
    try:
        data = json.loads(sys.stdin.read().lstrip("﻿") or "{}")
    except ValueError:
        return
    text = (data.get("prompt") or "").strip().lower()
    stripped = re.sub(r"[.!?\s]+$", "", text)
    if stripped in ("stop evoloop", "evoloop off"):
        flag().unlink(missing_ok=True)
        emit("UserPromptSubmit", "off", "EVOLOOP MODE OFF")
        return
    m = re.match(r"^[/@$]evoloop(?::evoloop)?(?:\s+(\S+))?(?:\s+(\S+))?", text)
    if not m:
        return
    arg, arg2 = m.group(1) or "", m.group(2) or ""
    if arg == "default" and arg2 in LEVELS:
        write_default(arg2)
        emit("UserPromptSubmit", arg2, f"EVOLOOP DEFAULT SET — new sessions start in {arg2}.")
    elif arg == "off":
        flag().unlink(missing_ok=True)
        emit("UserPromptSubmit", "off", "EVOLOOP MODE OFF")
    elif arg in LEVELS:
        set_mode(arg)
        emit("UserPromptSubmit", arg, f"EVOLOOP MODE CHANGED — level: {arg}\n\n" + RULES[arg])
    elif arg == "":
        mode = read_mode() or "off"
        emit("UserPromptSubmit", mode, f"EVOLOOP MODE — level: {mode}")


if __name__ == "__main__":
    try:
        {"session": session, "prompt": prompt}[sys.argv[1]]()
    except Exception:  # never block the host session
        pass
    sys.exit(0)
