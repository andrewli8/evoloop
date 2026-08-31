"""Generic external evidence intake: JSON from a file, stdin (`-`), or a command's stdout (`cmd:...`).

Payload: a JSON array, or `{"items": [...]}`. Items are objects (`text` required; optional `id`, `class`, `url`)
or bare strings. Every failure logs a warning and yields zero items.

Security: `cmd:` sources run a shell. They are accepted only with `allow_exec=True`, which the CLI grants to its own
`--evidence-json` flag (an explicit human action) and never to `evidence.external` in repo-local config.yaml, so
cloning a repository can not execute code on the next cycle. A bare string is always a file path; a missing file
warns instead of falling through to execution."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from . import CLASSES, _ev

log = logging.getLogger(__name__)
DEFAULT_LIMIT = 50
DEFAULT_MAX_CHARS = 300  # same cap `_ev` applies to every built-in source


MAX_BYTES = 1_000_000


def _read(source: str, cwd: Path | None, allow_exec: bool) -> str | None:
    if source == "-":
        if sys.stdin.isatty():
            log.warning("external evidence '-': stdin is a terminal, nothing piped")
            return None
        return sys.stdin.read(MAX_BYTES)
    if source.startswith("cmd:"):
        if not allow_exec:
            log.warning("external evidence %r: commands are only allowed from the CLI flag, not config.yaml", source)
            return None
        r = subprocess.run(source[4:], shell=True, cwd=cwd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log.warning("external evidence %r: command exited %s: %s", source, r.returncode, r.stderr.strip()[:200])
            return None
        return r.stdout[:MAX_BYTES]
    p = Path(source[5:] if source.startswith("file:") else source)
    if not p.is_file():
        log.warning("external evidence %r: file not found", source)
        return None
    return p.read_text(errors="ignore")[:MAX_BYTES]


def _normalize(item, source: str, i: int, max_chars: int) -> dict | None:
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict) or not str(item.get("text", "")).strip():
        return None
    cls = item.get("class") if item.get("class") in CLASSES else "observed"
    ev = _ev(source, cls, str(item["text"])[:max_chars], str(item.get("id") or item.get("url") or f"item{i + 1}")[:200])
    out = {**ev, "kind": "external"}
    if item.get("url"):
        out["url"] = str(item["url"])[:200]
    return out


def load_external_evidence(source: str, *, limit: int = DEFAULT_LIMIT, max_chars: int = DEFAULT_MAX_CHARS,
                           cwd: Path | None = None, allow_exec: bool = False) -> list[dict]:
    """Read and normalize evidence from `source` (file path, `-` for stdin, or `cmd:` with allow_exec). Never raises."""
    max_chars = min(max_chars, DEFAULT_MAX_CHARS)  # `_ev` caps every source at 300 chars; larger values are not honoured
    try:
        raw = _read(source, cwd, allow_exec)
        if raw is None:
            return []
        data = json.loads(raw)
    except Exception as e:  # unreadable file, bad JSON, timeout: warn, contribute nothing
        log.warning("external evidence %r: %s: %s", source, type(e).__name__, e)
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        log.warning("external evidence %r: expected a JSON array or {\"items\": [...]}", source)
        return []
    out = [_normalize(it, source, i, max_chars) for i, it in enumerate(items[:limit])]
    return [e for e in out if e]
