"""Git-history evidence: churn and revert/fix-follow-fix hotspots per file. One `git log --numstat` call, never raises."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..scan import SKIP_DIRS
from . import _ev

REVERT_RE = re.compile(r"^revert\b|this reverts commit", re.I)
FIXISH_RE = re.compile(r"\b(fix|bug|hotfix|patch|regress)\w*\b", re.I)
FOLLOW_WINDOW_S = 14 * 86400


def collect_churn_evidence(repo_root: Path, *, window_days: int = 90, max_items: int = 10) -> list[dict]:
    if not shutil.which("git"):
        return []
    try:
        r = subprocess.run(
            ["git", "log", f"--since={window_days}.days", "--numstat", "--format=%x01%H%x02%ct%x02%s"],
            cwd=repo_root, capture_output=True, text=True, check=False)
    except Exception:
        return []
    if r.returncode != 0 or not r.stdout.strip():
        return []

    stats: dict[str, dict] = {}  # path -> {churn, commits, reverts, fix_ts}
    ts, is_revert, is_fix = 0, False, False
    for line in r.stdout.splitlines():
        if line.startswith("\x01"):
            _, _, rest = line[1:].partition("\x02")
            ts_s, _, subject = rest.partition("\x02")
            ts = int(ts_s) if ts_s.isdigit() else 0
            is_revert = bool(REVERT_RE.search(subject))
            is_fix = bool(FIXISH_RE.search(subject))
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if any(p in SKIP_DIRS for p in Path(path).parts):
            continue
        s = stats.setdefault(path, {"churn": 0, "commits": 0, "reverts": 0, "fix_ts": []})
        if added.isdigit() and deleted.isdigit():  # binary rows are "-\t-": count the commit, 0 churn
            s["churn"] += int(added) + int(deleted)
        s["commits"] += 1
        if is_revert:
            s["reverts"] += 1
        if is_fix:
            s["fix_ts"].append(ts)

    max_churn = max((s["churn"] for s in stats.values()), default=0)
    scored = []
    for path, s in stats.items():
        fts = sorted(s["fix_ts"])
        fff = sum(1 for a, b in zip(fts, fts[1:]) if b - a <= FOLLOW_WINDOW_S)
        churn_norm = s["churn"] / max_churn if max_churn else 0.0
        score = churn_norm + 2 * s["reverts"] + 3 * fff
        if score <= 0:
            continue
        text = (f"{path}: churn={s['churn']} lines over {s['commits']} commits, "
                f"{s['reverts']} revert, {fff} fix-follow-fix")
        scored.append((score, path, {**_ev("churn", "observed", text, path), "score": round(score, 4)}))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [item for _, _, item in scored[:max_items]]
