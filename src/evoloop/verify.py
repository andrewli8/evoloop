"""Deterministic verification: run repo commands, summarize output without feeding logs to models."""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .config import Commands

ERR = re.compile(r"(error|fail|exception|traceback|✗|FAILED|Error:)", re.I)


def run_cmd(cmd: str, cwd: Path, timeout: int = 900) -> dict:
    t = time.time()
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        out, code = "timeout", 124
    lines = out.splitlines()
    hits = [l.strip() for l in lines if ERR.search(l)][:15]
    return {"cmd": cmd, "ok": code == 0, "code": code, "seconds": round(time.time() - t, 1),
            "summary": "\n".join(hits or lines[-10:])[:2000], "log": out}


def run_all(commands: Commands, cwd: Path, log_dir: Path | None = None) -> dict:
    """Ordered: targeted-ish (typecheck, lint) before broader (test, build). Stops at first failure."""
    results, ok = [], True
    for key in ("typecheck", "lint", "test", "build"):
        cmd = getattr(commands, key)
        if not cmd:
            continue
        r = run_cmd(cmd, cwd)
        if log_dir:
            (log_dir / f"{key}.log").write_text(r.pop("log"))
        else:
            r.pop("log")
        results.append({"step": key, **r})
        if not r["ok"]:
            ok = False
            break
    return {"ok": ok, "steps": results, "ran": bool(results)}


def failure_summary(res: dict) -> str:
    return "\n".join(f"[{s['step']}] {s['cmd']} -> exit {s['code']}\n{s['summary']}" for s in res["steps"] if not s["ok"])
