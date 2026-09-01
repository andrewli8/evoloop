"""Provider interface: text completion by role + optional code implementation."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Role(str, Enum):
    FAST = "fast"
    REASONING = "reasoning"
    CODING = "coding"
    REVIEW = "review"


class NotSupported(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0  # reported, not budgeted: cache reads are ~10% cost and mostly host-CLI baggage
    by_role: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"model_calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cached_input_tokens": self.cached_input_tokens, "by_role": self.by_role}


class Provider:
    """Subclass and implement `complete`; `implement` is optional (only agents that edit code)."""
    name = "base"

    def complete(self, role: Role, system: str, prompt: str) -> tuple[str, int, int] | tuple[str, int, int, int]:
        """Return (text, input_tokens, output_tokens[, cached_input_tokens])."""
        raise NotImplementedError

    def implement(self, instructions: str, cwd: Path) -> str:
        raise NotSupported(f"{self.name} cannot edit code; use claude-cli or codex-cli for build mode")


class Budgeted:
    """Wraps a provider: counts usage, enforces hard budget, parses JSON replies."""

    def __init__(self, provider: Provider, max_calls: int, max_tokens: int, models: dict[str, str] | None = None,
                 max_seconds: int | None = None, root: Path | None = None):
        self.p, self.max_calls, self.max_tokens, self.max_seconds = provider, max_calls, max_tokens, max_seconds
        self.root = root  # where provider failures are recorded (.evoloop/incidents.jsonl)
        self.started = time.time()
        self.usage = Usage()
        self.models = models or {}
        self.calls: list[dict] = []  # per-call audit trail, written to runs/<cycle>/calls.jsonl

    def _call(self, fn, *args):
        """Run one provider call; a raise is recorded as a provider_error incident and re-raised unchanged."""
        try:
            return fn(*args)
        except Exception as e:
            from ..incidents import record_incident
            m = re.search(r"failed \((-?\d+)\)", str(e))  # cli_agents._run message; CalledProcessError carries returncode
            code = getattr(e, "returncode", None)
            record_incident("provider_error", source=self.p.name, exit_code=code if isinstance(code, int) else int(m.group(1)) if m else None,
                            summary=f"{type(e).__name__}: {str(e)[:200]}", detail=str(e)[-2000:], root=self.root)
            raise

    def _check(self) -> None:
        if self.usage.calls >= self.max_calls:
            raise BudgetExceeded(f"model call budget {self.max_calls} reached")
        if self.usage.input_tokens + self.usage.output_tokens >= self.max_tokens:
            raise BudgetExceeded(f"token budget {self.max_tokens} reached")
        if self.max_seconds is not None and time.time() - self.started >= self.max_seconds:
            raise BudgetExceeded(f"wall-clock budget {self.max_seconds}s reached")

    def text(self, role: Role, system: str, prompt: str) -> str:
        self._check()
        t = time.time()
        out, i, o, *rest = self._call(self.p.complete, role, system, prompt)
        m = re.match(r"\[phase:(\w+)\]", prompt)
        self.calls.append({"phase": m.group(1) if m else "?", "role": role.value, "input_tokens": i, "output_tokens": o,
                           "cached_input_tokens": rest[0] if rest else 0, "prompt_chars": len(prompt), "reply_chars": len(out),
                           "seconds": round(time.time() - t, 1)})
        self.usage.calls += 1
        self.usage.input_tokens += i
        self.usage.output_tokens += o
        self.usage.cached_input_tokens += rest[0] if rest else 0
        self.usage.by_role[role.value] = self.usage.by_role.get(role.value, 0) + 1
        return out

    def json(self, role: Role, system: str, prompt: str) -> dict | list:
        out = self.text(role, system, prompt + "\n\nReply with JSON only.")
        try:
            return parse_json(out)
        except ValueError:
            out = self.text(role, system, "Your previous reply was not valid JSON. " + prompt + "\n\nReply with JSON only.")
            return parse_json(out)

    def implement(self, instructions: str, cwd: Path) -> str:
        self._check()
        self.usage.calls += 1
        self.usage.by_role["coding"] = self.usage.by_role.get("coding", 0) + 1
        return self._call(self.p.implement, instructions, cwd)


def parse_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON found")
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        end = max(text.rfind("}"), text.rfind("]"))
        return json.loads(text[start:end + 1])
