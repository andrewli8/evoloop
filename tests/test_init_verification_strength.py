import subprocess

from typer.testing import CliRunner

from evoloop.cli import app
from evoloop.commands import verification_strength
from tests.test_cli import in_repo

WEAK = {"test": "uv run pytest -q", "lint": None, "typecheck": None, "build": None}
STRONG = {"test": "uv run pytest -q", "lint": "uv run ruff check .", "typecheck": "uv run mypy .", "build": None}


def test_weak_label_and_report():
    label, lines = verification_strength(WEAK, ["python"])
    text = "\n".join(lines)
    assert label == "weak"
    assert "tests-only" in text and "weak changes can pass the delivery gate" in text
    assert "uv add --dev ruff" in text and "uv add --dev mypy" in text
    assert "config.yaml" in text
    for gate in ("test", "lint", "typecheck", "build"):
        assert f"{gate}:" in text
    assert "test: uv run pytest -q" in text and "lint: (not detected)" in text


def test_strong_and_moderate_labels():
    label, lines = verification_strength(STRONG, ["python"])
    assert label == "strong" and not any("WARNING" in l for l in lines)
    assert verification_strength({**WEAK, "lint": "ruff check ."}, [])[0] == "moderate"
    assert verification_strength({}, [])[0] == "weak"


def test_init_prints_block_and_keeps_config(tmp_path):
    r = tmp_path / "p"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["pytest"]\n')
    (r / "uv.lock").write_text("")
    (r / "tests").mkdir()
    out = in_repo(r, lambda: CliRunner().invoke(app, ["init", "--provider", "mock"]))
    assert out.exit_code == 0, out.stdout
    assert "Verification strength: weak" in out.stdout
    assert "uv add --dev ruff" in out.stdout and "Initialized .evoloop/" in out.stdout
    assert "test: uv run pytest -q" in (r / ".evoloop" / "config.yaml").read_text()
