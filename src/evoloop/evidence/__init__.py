"""Deterministic evidence collection. Only sources that exist are used. No model calls."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..config import EVO_DIR
from ..scan import SKIP_DIRS

CLASSES = ("observed", "inferred", "hypothetical", "simulated")
PAIN_WORDS = re.compile(r"\b(slow|confus|manual|workaround|annoy|error|fail|bug|hard to|difficult|unclear|missing|broken|painful|tedious)\w*", re.I)


def _ev(source: str, cls: str, text: str, ref: str) -> dict:
    assert cls in CLASSES
    return {"source": source, "class": cls, "text": text.strip()[:300], "ref": ref}


def todos(repo: Path, limit: int = 30) -> list[dict]:
    if not shutil.which("git"):
        return []
    r = subprocess.run(["git", "grep", "-nIE", r"(TODO|FIXME|HACK|XXX)[:\s]"], cwd=repo, capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines()[:limit]:
        f, _, rest = line.partition(":")
        if any(part in SKIP_DIRS for part in Path(f).parts):
            continue
        out.append(_ev("todos", "observed", rest.split(":", 1)[-1], f"{f}:{rest.split(':', 1)[0]}"))
    return out


def git_log(repo: Path, limit: int = 20) -> list[dict]:
    r = subprocess.run(["git", "log", "--no-merges", "-n", "200", "--format=%h %s"], cwd=repo, capture_output=True, text=True)
    fixes = [l for l in r.stdout.splitlines() if re.search(r"\b(fix|bug|revert|hotfix|regress)", l, re.I)]
    return [_ev("git_log", "observed", l.split(" ", 1)[1], l.split(" ", 1)[0]) for l in fixes[:limit]]


def issues(repo: Path, limit: int = 20) -> list[dict]:
    if not shutil.which("gh"):
        return []
    r = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", str(limit), "--json", "number,title,labels"],
                       cwd=repo, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    return [_ev("issues", "observed", f"{i['title']} [{','.join(l['name'] for l in i.get('labels', []))}]", f"#{i['number']}") for i in data]


def docs(repo: Path, limit: int = 15) -> list[dict]:
    out = []
    files = [repo / "README.md"] + (sorted((repo / "docs").rglob("*.md"))[:20] if (repo / "docs").exists() else [])
    for p in files:
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(errors="ignore").splitlines()[:600], 1):
            if PAIN_WORDS.search(line) and 20 < len(line) < 300:
                out.append(_ev("docs", "inferred", line, f"{p.relative_to(repo)}:{i}"))
                if len(out) >= limit:
                    return out
    return out


def notes(repo: Path, limit: int = 30) -> list[dict]:
    """User-supplied evidence: .evoloop/evidence/*.md (support tickets, feedback, analytics notes).
    A line starting with `[inferred]`/`[hypothetical]` overrides the default `observed` class."""
    d = repo / EVO_DIR / "evidence"
    out = []
    for p in sorted(d.glob("*.md")) if d.exists() else []:
        if p.name == "README.md":
            continue
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            line = line.strip("-* ").strip()
            if len(line) < 10:
                continue
            cls = "observed"
            m = re.match(r"\[(observed|inferred|hypothetical|simulated)\]\s*(.*)", line)
            if m:
                cls, line = m.group(1), m.group(2)
            out.append(_ev("notes", cls, line, f"{p.name}:{i}"))
            if len(out) >= limit:
                return out
    return out


def results(state, limit: int = 10) -> list[dict]:
    """Outcomes of previous experiments recorded via `evoloop resolve`."""
    return [_ev("results", "observed" if r.get("level") == 3 else "simulated",
                f"{r.get('intervention', '?')}: {r.get('outcome', '?')} {r.get('note', '')}", r["id"])
            for r in state.nodes("Result", limit)]


SOURCES = {"todos": todos, "git_log": git_log, "issues": issues, "docs": docs, "notes": notes}


def collect(repo: Path, state, sources: list[str], external: list[str] = ()) -> list[dict]:
    """`external`: JSON evidence specs (file path, shell command, or `-`), see `evidence.external`."""
    ev: list[dict] = []
    for s in sources:
        try:
            ev += results(state) if s == "results" else SOURCES[s](repo) if s in SOURCES else []
        except Exception as e:  # a broken source must not kill the cycle
            ev.append(_ev(s, "hypothetical", f"source failed: {e}", "-"))
    if external:
        from .external import load_external_evidence
        for spec in external:
            ev += load_external_evidence(spec, cwd=repo)
    rank = {c: i for i, c in enumerate(CLASSES)}
    ev.sort(key=lambda e: rank[e["class"]])
    for i, e in enumerate(ev):
        e["id"] = f"ev{i+1}"
    return ev
