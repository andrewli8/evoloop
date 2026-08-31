"""Provider interface: text completion by role + optional code implementation."""
from __future__ import annotations

import json
import re
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
    by_role: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"model_calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "by_role": self.by_role}


class Provider:
    """Subclass and implement `complete`; `implement` is optional (only agents that edit code)."""
    name = "base"

    def complete(self, role: Role, system: str, prompt: str) -> tuple[str, int, int]:
        raise NotImplementedError

    def implement(self, instructions: str, cwd: Path) -> str:
        raise NotSupported(f"{self.name} cannot edit code; use claude-cli or codex-cli for build mode")


class Budgeted:
    """Wraps a provider: counts usage, enforces hard budget, parses JSON replies."""

    def __init__(self, provider: Provider, max_calls: int, max_tokens: int, models: dict[str, str] | None = None):
        self.p, self.max_calls, self.max_tokens = provider, max_calls, max_tokens
        self.usage = Usage()
        self.models = models or {}

    def text(self, role: Role, system: str, prompt: str) -> str:
        if self.usage.calls >= self.max_calls:
            raise BudgetExceeded(f"model call budget {self.max_calls} reached")
        if self.usage.input_tokens + self.usage.output_tokens >= self.max_tokens:
            raise BudgetExceeded(f"token budget {self.max_tokens} reached")
        out, i, o = self.p.complete(role, system, prompt)
        self.usage.calls += 1
        self.usage.input_tokens += i
        self.usage.output_tokens += o
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
        if self.usage.calls >= self.max_calls:
            raise BudgetExceeded("model call budget reached")
        self.usage.calls += 1
        self.usage.by_role["coding"] = self.usage.by_role.get("coding", 0) + 1
        return self.p.implement(instructions, cwd)


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
