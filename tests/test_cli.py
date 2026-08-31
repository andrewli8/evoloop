import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from evoloop.cli import app

runner = CliRunner()


def in_repo(path, fn):
    cwd = os.getcwd()
    os.chdir(path)
    try:
        return fn()
    finally:
        os.chdir(cwd)


def test_cli_flow(tmp_path):
    r = tmp_path / "p"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "package.json").write_text('{"name":"x","scripts":{"test":"true"}}')
    (r / "app.js").write_text("// TODO: slow search\n")
    (r / ".claude").mkdir()
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init"], cwd=r, check=True)
    assert in_repo(r, lambda: runner.invoke(app, ["init", "--provider", "mock"])).exit_code == 0
    assert (r / ".evoloop" / "config.yaml").exists() and (r / ".evoloop" / "project.json").exists()
    out = in_repo(r, lambda: runner.invoke(app, ["analyze"]))
    assert out.exit_code == 0 and "decision=RECOMMEND" in out.stdout, out.stdout
    assert "MOCK PROVIDER" in next((r / ".evoloop" / "runs").iterdir()).joinpath("report.md").read_text()
    assert in_repo(r, lambda: runner.invoke(app, ["disable"])).exit_code == 0
    out = in_repo(r, lambda: runner.invoke(app, ["run", "--mode", "build"]))
    assert "disabled" in out.stdout
    assert in_repo(r, lambda: runner.invoke(app, ["enable"])).exit_code == 0
    out = in_repo(r, lambda: runner.invoke(app, ["status"]))
    assert "enabled=True" in out.stdout and "RECOMMEND" in out.stdout
    out = in_repo(r, lambda: runner.invoke(app, ["skill", "install"]))
    assert (r / ".claude" / "skills" / "evoloop" / "SKILL.md").exists()
    out = in_repo(r, lambda: runner.invoke(app, ["optimize"]))
    assert out.exit_code == 2  # disabled by default
