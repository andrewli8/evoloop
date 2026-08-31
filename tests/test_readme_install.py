"""Docs contract: README install instructions must match the packaged CLI."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()


def test_install_is_uv_tool_install_from_git():
    assert "uv tool install git+" in README


def test_uvx_mentions_use_the_real_dist_name():
    # `uvx evoloop` runs a stranger's package (name taken on PyPI). `uvx evolveloop` is fine once released.
    for line in README.splitlines():
        if "uvx" in line:
            # `uvx --from <release wheel url>` pins the dist explicitly, so it is safe too.
            assert "uvx evolveloop" in line or "uvx --from" in line


def test_release_asset_wheel_matches_pyproject():
    """A concrete wheel URL is optional pre-release (they 404 until the first tag), but when one
    appears it must be the un-pinned latest/ path for the current dist name; the releases page
    must always be linked so the install path exists either way."""
    assert "https://github.com/andrewli8/evoloop/releases" in README
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    normalized = re.sub(r"[-_.]+", "_", project["name"]).lower()
    wheel = f"{normalized}-{project['version']}-py3-none-any.whl"
    for url in re.findall(r"https://github\.com/\S+?\.whl", README):
        assert url.endswith(f"/releases/latest/download/{wheel}")


def test_readme_cli_name_matches_project_scripts():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    scripts = pyproject["project"]["scripts"]
    # first CLI invocation in the quick start, e.g. `evoloop --help`
    match = re.search(r"^(\S+) --help", README, flags=re.MULTILINE)
    assert match, "README quick start should show a `<cli> --help` command"
    assert match.group(1) in scripts
