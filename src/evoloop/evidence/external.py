"""Generic external evidence intake: JSON from a file, a shell command's stdout, or stdin (`-`).

Payload: a JSON array, or `{"items": [...]}`. Items are objects (`text` required; optional `id`, `class`,
`url`, `weight`, `timestamp`) or bare strings. Every failure logs a warning and yields zero items."""
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


def _read(source: str, cwd: Path | None) -> str | None:
    if source == "-":
        return sys.stdin.read()
    p = Path(source)
    if p.is_file():
        return p.read_text(errors="ignore")
    r = subprocess.run(source, shell=True, cwd=cwd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        log.warning("external evidence %r: command exited %s: %s", source, r.returncode, r.stderr.strip()[:200])
        return None
    return r.stdout


def _normalize(item, source: str, i: int, max_chars: int) -> dict | None:
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict) or not str(item.get("text", "")).strip():
        return None
    cls = item.get("class") if item.get("class") in CLASSES else "observed"
    ev = _ev(source, cls, str(item["text"])[:max_chars], str(item.get("id") or item.get("url") or f"item{i + 1}"))
    extra = {k: item[k] for k in ("url", "weight", "timestamp") if k in item}
    return {**ev, "kind": "external", **extra}


def load_external_evidence(source: str, *, limit: int = DEFAULT_LIMIT, max_chars: int = DEFAULT_MAX_CHARS,
                           cwd: Path | None = None) -> list[dict]:
    """Read and normalize evidence from `source` (file path, shell command, or `-` for stdin). Never raises."""
    try:
        raw = _read(source, cwd)
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
