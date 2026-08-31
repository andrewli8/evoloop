import subprocess
from pathlib import Path

import pytest



def make_repo(path: Path, kind: str = "node", evidence: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    if kind == "node":
        (path / "package.json").write_text('{"name":"x","scripts":{"test":"node -e \\"process.exit(0)\\"","lint":"true"},"dependencies":{"next":"1","posthog-js":"1"}}')
        (path / "package-lock.json").write_text("{}")
        (path / "src").mkdir()
        (path / "src" / "a.ts").write_text("// TODO: onboarding is confusing for admins\nexport interface Order {}\n")
    elif kind == "python":
        (path / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["fastapi","pytest","ruff"]\n')
        (path / "tests").mkdir()
        (path / "app.py").write_text("# FIXME: export is slow for large accounts\nclass User(Base): pass\n")
    elif kind == "go":
        (path / "go.mod").write_text("module x\n")
        (path / "main.go").write_text("package main\n// TODO: retries are manual\ntype Job struct{}\n")
    (path / "README.md").write_text("# App\n## Onboarding\nAdmins find the manual setup confusing.\n## Billing\nCustomers and admins.\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "fix: crash on login"], cwd=path, check=True)
    init_evoloop(path)
    return path


def init_evoloop(path: Path):
    from evoloop.cli import scaffold
    scaffold(path, "mock", evidence_sources=["todos", "git_log", "docs", "notes", "results"])  # no `gh issues` in tests


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "r")
