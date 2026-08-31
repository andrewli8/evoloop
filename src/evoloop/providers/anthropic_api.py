"""Direct Claude API adapter via urllib (no SDK). Cannot edit code; analyze/plan only."""
from __future__ import annotations

import json
import os
import urllib.request

from .base import Provider, Role

DEFAULT_MODELS = {"fast": "claude-haiku-4-5-20251001", "reasoning": "claude-sonnet-5",
                  "coding": "claude-sonnet-5", "review": "claude-sonnet-5"}


class AnthropicAPI(Provider):
    name = "anthropic"

    def __init__(self, models: dict[str, str] | None = None):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self.models = {**DEFAULT_MODELS, **(models or {})}

    def complete(self, role: Role, system: str, prompt: str):
        body = json.dumps({"model": self.models[role.value], "max_tokens": 4000, "system": system,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
        text = "".join(b.get("text", "") for b in data.get("content", []))
        u = data.get("usage", {})
        return text, u.get("input_tokens", 0), u.get("output_tokens", 0)
