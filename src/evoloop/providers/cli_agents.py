"""Adapters that shell out to coding-agent CLIs (Claude Code, Codex). No SDKs required."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .base import Provider, Role

CODE_TOOLS = "Edit,Write,Read,Bash,Grep,Glob"


def _run(cmd: list[str], cwd: Path | None, stdin: str | None = None, timeout: int = 1800, env: dict | None = None) -> str:
    r = subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({r.returncode}): {r.stderr[-500:]}")
    return r.stdout


class ClaudeCLI(Provider):
    name = "claude-cli"

    def __init__(self, models: dict[str, str] | None = None):
        if not shutil.which("claude"):
            raise RuntimeError("`claude` CLI not found")
        self.models = models or {}

    def _cmd(self, role: Role) -> list[str]:
        # strict-mcp-config: without it every call carries the user's MCP tool schemas (~150k cached tokens)
        cmd = ["claude", "-p", "--output-format", "json", "--strict-mcp-config", "--no-session-persistence"]
        if role.value in self.models:
            cmd += ["--model", self.models[role.value]]
        return cmd

    def complete(self, role, system, prompt):
        # text-only judgment calls: no tools, no settings/plugins/CLAUDE.md -> ~400 tokens of overhead instead of ~16k
        # fast role = scoring/extraction: extended thinking there was 70-90% of all output tokens for no content gain
        env = {**os.environ, "MAX_THINKING_TOKENS": "0"} if role == Role.FAST else None
        out = _run(self._cmd(role) + ["--system-prompt", system, "--tools", "", "--setting-sources", ""], None, stdin=prompt, env=env)
        data = json.loads(out)
        u = data.get("usage", {})
        inp = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        return data.get("result", ""), inp, u.get("output_tokens", 0), u.get("cache_read_input_tokens", 0)

    def implement(self, instructions, cwd):
        out = _run(self._cmd(Role.CODING) + ["--permission-mode", "acceptEdits", "--allowedTools", CODE_TOOLS],
                   cwd, stdin=instructions)
        return json.loads(out).get("result", "")[-2000:]


class CodexCLI(Provider):
    name = "codex-cli"

    def __init__(self, models: dict[str, str] | None = None):
        if not shutil.which("codex"):
            raise RuntimeError("`codex` CLI not found")
        self.models = models or {}

    def complete(self, role, system, prompt):
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only"]
        if role.value in self.models:
            cmd += ["-m", self.models[role.value]]
        out = _run(cmd + ["-"], None, stdin=f"{system}\n\n{prompt}")
        return out, 0, 0  # codex exec does not report usage on stdout

    def implement(self, instructions, cwd):
        return _run(["codex", "exec", "--full-auto", "--skip-git-repo-check", "-"], cwd, stdin=instructions)[-2000:]
