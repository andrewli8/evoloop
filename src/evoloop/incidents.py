"""Failure-only incident log: .evoloop/incidents.jsonl. Written on provider errors and unhandled cycle exceptions,
read back as evidence. Best-effort by design: recording never raises, so it can never mask the original failure."""
from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .config import EVO_DIR, Config

INCIDENTS_FILENAME = "incidents.jsonl"
DETAIL_MAX_CHARS = 4000
MAX_RECORDS = 500  # keep the file bounded: it is read in full on every evidence collect


def incidents_path(root: Path) -> Path:
    return root / EVO_DIR / INCIDENTS_FILENAME


def record_incident(kind: str, *, summary: str, detail: str = "", source: str = "", exit_code: int | None = None,
                    root: Path | None = None) -> None:
    """Append one record. Swallows every error: a failing incident write must not replace the failure being recorded."""
    try:
        root = Path(root or Path.cwd())
        if Config.path(root).exists() and not Config.load(root).capture_incidents:
            return
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, "summary": summary,
               "detail": detail[:DETAIL_MAX_CHARS], "source": source, "exit_code": exit_code}
        p = incidents_path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        if len(lines) > MAX_RECORDS:
            p.write_text("\n".join(lines[-MAX_RECORDS:]) + "\n", encoding="utf-8")
    except Exception:
        return


def load_incidents(root: Path | None = None, limit: int = 50) -> list[dict]:
    """Most recent `limit` records, oldest first. Missing file => []; malformed lines skipped; never creates anything."""
    p = incidents_path(Path(root or Path.cwd()))
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out[-limit:]


def exception_incident(exc: BaseException, *, source: str, root: Path | None = None) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    record_incident("exception", summary=f"{type(exc).__name__}: {exc}", detail=detail, source=source, root=root)
