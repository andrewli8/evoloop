import json
from pathlib import Path

from evoloop import scan
from .conftest import make_repo


def test_scan_stacks(tmp_path):
    for kind, lang in (("node", "javascript"), ("python", "python"), ("go", "go")):
        r = make_repo(tmp_path / kind, kind)
        pack = json.loads((r / ".evoloop" / "project.json").read_text())
        assert lang in pack["languages"]["value"]
        assert pack["languages"]["status"] == "observed"
        assert pack["commands"]["value"]["test"], kind
        assert pack["architecture"]["status"] == "unknown"  # never invented


def test_node_details(repo):
    assert scan.load_pack(repo)["package_manager"]["value"] == ["npm"]
    (repo / "package-lock.json").unlink()
    (repo / "pnpm-lock.yaml").write_text("")
    pack = scan.scan(repo)
    assert pack["package_manager"]["value"] == ["pnpm"]
    assert pack["commands"]["value"]["test"] == "pnpm run test"
    assert "analytics" in pack["capabilities"]["value"] and "framework" in pack["capabilities"]["value"]
    assert "Order" in pack["entities"]["value"] and pack["entities"]["status"] == "inferred"
    assert "admin" in pack["roles"]["value"]


def test_refresh_uses_git_diff(repo):
    import subprocess
    pack = scan.load_pack(repo)
    (repo / "src" / "b.ts").write_text("export const x = 1;\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add b"], cwd=repo, check=True)
    new = scan.refresh(repo, pack)
    assert new["changed_since_scan"] == ["src/b.ts"] and new["git_head"] != pack["git_head"]
    assert pack["changed_since_scan"] == []  # original not mutated


def test_monorepo_workspaces(tmp_path):
    import subprocess
    r = tmp_path / "mono"
    (r / "apps" / "web").mkdir(parents=True)
    (r / "apps" / "web" / "package.json").write_text('{"scripts":{"test":"true","lint":"true"}}')
    (r / "apps" / "api").mkdir(parents=True)
    (r / "apps" / "api" / "pyproject.toml").write_text('[project]\nname="api"\ndependencies=["pytest"]\n')
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    pack = scan.scan(r)
    assert pack["workspaces"]["value"] == ["apps/api", "apps/web"]
    assert pack["languages"]["value"] == ["javascript", "python"]
    assert pack["commands"]["value"]["test"] == "(cd apps/api && pytest -q) && (cd apps/web && npm run test)"
    assert pack["commands"]["value"]["lint"] == "(cd apps/web && npm run lint)"
    assert "Workspaces" in scan.describe(pack) and "Next:" in scan.describe(pack)
