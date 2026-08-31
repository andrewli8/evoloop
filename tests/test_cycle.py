import json
import threading
from pathlib import Path

import pytest

from evoloop.config import Config, Mode
from evoloop.cycle import run_cycle
from evoloop.providers import MockProvider
from evoloop.state import LockedError, State


def cfg(repo, **kw):
    return Config.model_validate({**Config.load(repo).model_dump(), **kw})


def test_off_makes_zero_model_calls(repo):
    p = MockProvider()
    r = run_cycle(repo, cfg(repo, enabled=False), p)
    assert r["status"] == "disabled" and p.calls == []
    r = run_cycle(repo, cfg(repo), p, Mode.OFF)
    assert r["status"] == "disabled" and p.calls == []


def test_analyze_cycle_terminates_and_is_bounded(repo):
    p = MockProvider()
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    c = cfg(repo).search
    assert r["decision"] in ("RECOMMEND", "STOP", "BUILD") and r["status"] == "done"
    assert r["decision"] == "RECOMMEND"  # analyze never builds
    assert len(r["problems"]) <= c.max_problems
    assert 2 <= len(r["stakeholders"]) <= c.stakeholder_roles
    assert len(r["opportunities"]) <= c.opportunities
    assert len(r["finalists"]) <= c.finalists
    assert r["raw_candidates"] <= c.branches * c.candidates_per_branch * (1 + Config().loops.refinement)
    assert r["dedup_dropped"] == 0
    assert r["winner"]["title"]
    assert r["usage"]["model_calls"] == p.calls.__len__() <= cfg(repo).budget.max_model_calls
    run_dir = repo / ".evoloop" / "runs" / r["cycle"]
    assert (run_dir / "report.md").exists() and json.loads((run_dir / "result.json").read_text())["cycle"] == r["cycle"]
    assert "no-software/process" in r["branches"]
    assert all(e["class"] in ("observed", "inferred") for e in r["supporting_evidence"])


def test_no_evidence_stops_without_ideation(tmp_path):
    from .conftest import make_repo
    repo = make_repo(tmp_path / "e")
    for f in ("src/a.ts", "README.md"):
        (repo / f).write_text("clean\n")
    import subprocess
    subprocess.run(["git", "commit", "-qam", "clean"], cwd=repo)
    p = MockProvider()
    r = run_cycle(repo, cfg(repo, evidence_sources=["todos", "docs", "notes"]), p, Mode.ANALYZE)
    assert r["decision"] == "STOP" and "insufficient evidence" in r["stop_reason"]
    assert p.calls == []


def test_problem_without_evidence_dropped(repo):
    p = MockProvider(script={"problem_search": {"problems": [{"title": "made up", "evidence_ids": [], "confidence": 0.9}]}})
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    assert r["decision"] == "STOP" and r["problem"] is None


def test_duplicates_removed(repo):
    dup = {"branches": [{"mechanism": "simplify", "candidates": [
        {"title": "Simplify the onboarding form", "summary": "Fewer fields", "mechanism": "simplify"},
        {"title": "Simplify onboarding form", "summary": "Fewer fields", "mechanism": "simplify"}]},
        {"mechanism": "no-software/process", "candidates": [{"title": "Write a setup guide", "summary": "docs", "mechanism": "no-software/process", "software_required": False}]}]}
    p = MockProvider(script={"branches": dup})
    r = run_cycle(repo, cfg(repo, loops={"refinement": 0}), p, Mode.ANALYZE)
    assert r["dedup_dropped"] == 1 and r["raw_candidates"] == 2


def test_budget_enforced(repo):
    p = MockProvider()
    r = run_cycle(repo, cfg(repo, budget={"max_model_calls": 3, "max_tokens": 10**9}), p, Mode.ANALYZE)
    assert r["status"] == "budget_exhausted" and len(p.calls) == 3


def test_refinement_loop_bounded_when_homogeneous(repo):
    same = {"branches": [{"mechanism": "automate", "candidates": [{"title": f"auto {i}", "summary": f"x{i}", "mechanism": "automate"}]} for i in range(5)]}
    p = MockProvider(script={"branches": same})
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    assert [c for c in p.calls if c[0] == "branches"].__len__() == 2  # initial + exactly one refinement
    assert r["refinement_used"]


def test_adversarial_reject_stops(repo):
    p = MockProvider(script={"adversarial": lambda inp: {"reviews": [{"id": f["id"], "fatal": True, "verdict": "reject"} for f in inp["finalists"]]}})
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    assert r["decision"] == "STOP" and r["winner"] is None


def test_concurrent_cycles_prevented(repo):
    s = State(repo)
    s.acquire()
    with pytest.raises(LockedError):
        run_cycle(repo, cfg(repo), MockProvider(), Mode.ANALYZE)
    s.release()


def test_memory_retrieval_and_archive(repo):
    p = MockProvider()
    run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    s = State(repo)
    assert s.nodes("Lesson") and s.nodes("Intervention") and s.nodes("Problem")
    prob = s.nodes("Problem")[0]
    assert s.related(prob["id"], "supported_by")
    second = MockProvider()
    r2 = run_cycle(repo, cfg(repo), second, Mode.ANALYZE)
    branch_call = next(c for c in second.calls if c[0] == "branches")
    assert r2["lessons_used"]  # relevant lesson retrieved
    assert r2["dedup_dropped"] > 0  # previously archived candidates not regenerated


def test_high_risk_gated(repo):
    p = MockProvider(script={"branches": {"branches": [{"mechanism": "automate", "candidates": [
        {"title": "Auto-reset password on login failure", "summary": "auth flow", "mechanism": "automate"}]}]}})
    r = run_cycle(repo, cfg(repo, loops={"refinement": 0}), p, Mode.BUILD)
    assert r["decision"] == "RECOMMEND" and r["winner"]["risk"] == "high" and "human gated" in r["stop_reason"]
    assert "worktree" not in r


def test_paused_while_awaiting_human(repo):
    s = State(repo)
    cid = s.start_cycle()
    s.finish_cycle(cid, "awaiting_human", {})
    p = MockProvider()
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    assert r["status"] == "paused" and p.calls == []


def test_problem_backed_only_by_fix_commits_dropped(repo):
    def probs(inp):
        fixes = [e["id"] for e in inp["evidence"] if e["source"] == "git_log"]
        other = [e["id"] for e in inp["evidence"] if e["source"] != "git_log"][:1]
        return {"problems": [{"title": "ghost of a fixed bug", "evidence_ids": fixes, "confidence": 0.9},
                             {"title": "real problem", "evidence_ids": other + fixes[:1], "confidence": 0.5}]}
    r = run_cycle(repo, cfg(repo), MockProvider(script={"problem_search": probs}), Mode.ANALYZE)
    assert r["problem"]["title"] == "real problem"
    assert all(p["title"] != "ghost of a fixed bug" for p in r["problems"])
