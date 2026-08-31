import re
import tomllib
from pathlib import Path

import evoloop

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
WORKFLOW = (ROOT / ".github/workflows/publish.yml").read_text()


def test_distribution_metadata():
    project = PYPROJECT["project"]
    assert project["name"] == "evolveloop"
    assert project["version"] == evoloop.__version__
    for key in ("description", "readme", "requires-python", "license"):
        assert key in project
    assert project["scripts"]["evolveloop"] == "evoloop.cli:app"
    assert project["scripts"]["evoloop"] == "evoloop.cli:app"


def test_publish_workflow_uses_trusted_publishing():
    assert re.search(r"tags:\s*\[\s*['\"]v\*['\"]\s*\]", WORKFLOW)
    assert "id-token: write" in WORKFLOW
    assert "environment: pypi" in WORKFLOW
    assert "uv build" in WORKFLOW
    assert "pypa/gh-action-pypi-publish@release/v1" in WORKFLOW
    for forbidden in ("PYPI_API_TOKEN", "password:", "user:"):
        assert forbidden not in WORKFLOW
    assert "tomllib" in WORKFLOW and "removeprefix" in WORKFLOW


def test_publish_step_only_runs_on_tags():
    publish_step = WORKFLOW.split("pypa/gh-action-pypi-publish@release/v1")[1]
    assert "if: github.ref_type == 'tag'" in publish_step


def test_readme_quick_start_uses_pypi():
    readme = (ROOT / "README.md").read_text()
    quick_start = readme.split("## Quick start")[1].split("## ")[0]
    assert "uvx evolveloop" in quick_start
