import subprocess
from pathlib import Path

from evoloop.evidence import collect, todos
from evoloop.evidence.churn import collect_churn_evidence


def git(cwd: Path, *args: str):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit(repo: Path, msg: str, **files: str):
    for name, content in files.items():
        (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")
    return path


def churn_repo(path: Path) -> Path:
    repo = make_repo(path)
    commit(repo, "feat: hot 1", **{"hot.py": "\n".join(f"line{i}" for i in range(100))})
    commit(repo, "feat: hot 2", **{"hot.py": "\n".join(f"edit{i}" for i in range(100))})
    commit(repo, "feat: hot 3", **{"hot.py": "\n".join(f"more{i}" for i in range(100))})
    commit(repo, "feat: cold", **{"cold.py": "x = 1\n"})
    return repo


def test_ranks_high_churn_above_low(tmp_path):
    items = collect_churn_evidence(churn_repo(tmp_path / "r"))
    paths = [i["ref"] for i in items]
    assert paths.index("hot.py") < paths.index("cold.py")
    assert "churn=" in items[0]["text"] and "hot.py" in items[0]["text"]


def test_revert_increases_score(tmp_path):
    plain = churn_repo(tmp_path / "a")
    reverted = churn_repo(tmp_path / "b")
    commit(reverted, 'Revert "feat: cold"', **{"cold.py": "y = 2\n"})
    score = lambda items, p: next(i["score"] for i in items if i["ref"] == p)
    assert score(collect_churn_evidence(reverted), "cold.py") > score(collect_churn_evidence(plain), "cold.py")


def test_fix_follow_fix_counted(tmp_path):
    repo = churn_repo(tmp_path / "r")
    commit(repo, "fix: cold bug 1", **{"cold.py": "y = 2\n"})
    commit(repo, "fix: cold bug 2", **{"cold.py": "z = 3\n"})
    item = next(i for i in collect_churn_evidence(repo) if i["ref"] == "cold.py")
    assert "1 fix-follow-fix" in item["text"]


def test_not_a_git_repo_returns_empty(tmp_path):
    assert collect_churn_evidence(tmp_path) == []


def test_deterministic_ordering(tmp_path):
    repo = churn_repo(tmp_path / "r")
    a, b = collect_churn_evidence(repo), collect_churn_evidence(repo)
    assert [i["ref"] for i in a] == [i["ref"] for i in b]


def test_item_shape_matches_existing_source(tmp_path):
    repo = churn_repo(tmp_path / "r")
    commit(repo, "feat: todo", **{"t.py": "# TODO: something confusing\n"})
    todo_keys = set(todos(repo)[0].keys())
    for item in collect_churn_evidence(repo):
        assert todo_keys <= set(item.keys())
        assert item["source"] == "churn" and item["class"] == "observed"


def test_score_positive_and_max_items(tmp_path):
    items = collect_churn_evidence(churn_repo(tmp_path / "r"), max_items=1)
    assert len(items) <= 1
    assert all(i["score"] > 0 for i in items)


def test_binary_rows_are_skipped_entirely(tmp_path):
    repo = make_repo(tmp_path / "b")
    for n in (30, 40):
        (repo / "logo.png").write_bytes(b"\x89PNG\r\n" + bytes(range(n)))
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", f"fix: binary asset {n}")
    commit(repo, "feat: code", **{"code.py": "x = 1\n" * 20})
    items = collect_churn_evidence(repo)
    assert all("logo.png" not in i["ref"] for i in items)


def test_renamed_paths_use_new_name(tmp_path):
    repo = make_repo(tmp_path / "rn")
    commit(repo, "feat: module", **{"old_name.py": "x = 1\n" * 30})
    git(repo, "mv", "old_name.py", "new_name.py")
    commit(repo, "fix: rename and rework", **{"new_name.py": "x = 2\n" * 40})
    refs = [i["ref"] for i in collect_churn_evidence(repo)]
    assert "new_name.py" in refs and all("=>" not in r for r in refs)

def test_collect_includes_churn_by_default_and_gates_on_config(tmp_path):
    from evoloop.config import Config
    repo = churn_repo(tmp_path / "r")
    assert "churn" in Config().evidence_sources  # on by default
    on = collect(repo, None, ["git_log", "churn"], cfg=Config())
    assert any(e["source"] == "churn" for e in on)
    off = collect(repo, None, ["git_log", "churn"], cfg=Config(evidence={"churn_enabled": False}))
    assert not any(e["source"] == "churn" for e in off)


def test_todo_inside_string_literal_is_not_evidence(tmp_path):
    repo = make_repo(tmp_path / "t")
    commit(repo, "feat: files", **{"real.py": "# TODO: real work here\nx = 1\n",
                                    "fixture.py": 'SAMPLE = "// TODO: fake marker in a string"\n'})
    refs = [e["ref"] for e in todos(repo)]
    assert any(r.startswith("real.py") for r in refs) and not any(r.startswith("fixture.py") for r in refs)
