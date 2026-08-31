"""Git isolation: one worktree + branch per cycle. Never merges, never pushes to main."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import EVO_DIR


def _git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[-300:]}")
    return r.stdout


def is_repo(path: Path) -> bool:
    return subprocess.run(["git", "rev-parse", "--git-dir"], cwd=path, capture_output=True).returncode == 0


def create_worktree(repo: Path, cycle_id: str) -> tuple[Path, str]:
    branch = f"evoloop/{cycle_id}"
    wt = repo / EVO_DIR / "worktrees" / cycle_id
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", branch, str(wt), "HEAD")
    return wt, branch


def diff(wt: Path, max_chars: int = 12000) -> str:
    _git(wt, "add", "-A")
    d = _git(wt, "diff", "--cached", "--stat") + "\n" + _git(wt, "diff", "--cached")
    return d[:max_chars] + ("\n... [diff truncated]" if len(d) > max_chars else "")


def changed_files(wt: Path) -> list[str]:
    _git(wt, "add", "-A")
    return [l for l in _git(wt, "diff", "--cached", "--name-only").splitlines() if l]


def commit(wt: Path, message: str) -> str | None:
    _git(wt, "add", "-A")
    if not _git(wt, "diff", "--cached", "--name-only").strip():
        return None
    _git(wt, "-c", "user.email=evoloop@local", "-c", "user.name=evoloop", "commit", "-q", "-m", message)
    return _git(wt, "rev-parse", "--short", "HEAD").strip()


def remove_worktree(repo: Path, wt: Path, branch: str | None = None) -> None:
    _git(repo, "worktree", "remove", "--force", str(wt), check=False)
    if branch:
        _git(repo, "branch", "-D", branch, check=False)


def open_pr(wt: Path, branch: str, title: str, body: str) -> str | None:
    import shutil
    if not shutil.which("gh"):
        return None
    if subprocess.run(["git", "push", "-u", "origin", branch], cwd=wt, capture_output=True).returncode != 0:
        return None
    r = subprocess.run(["gh", "pr", "create", "--title", title, "--body", body, "--head", branch],
                       cwd=wt, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None
