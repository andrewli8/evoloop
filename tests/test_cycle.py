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


def test_screen_decisions_attached_and_rendered(repo):
    from evoloop.report import render
    branches = {"branches": [{"mechanism": "simplify", "candidates": [
        {"title": "Simplify the onboarding form", "summary": "Fewer fields", "mechanism": "simplify"},
        {"title": "Simplify onboarding form", "summary": "Fewer fields", "mechanism": "simplify"}]},
        {"mechanism": "automate", "candidates": [{"title": "Purge stale rows nightly", "summary": "cron", "mechanism": "delete stale rows"}]},
        {"mechanism": "no-software/process", "candidates": [{"title": "Write a setup guide", "summary": "docs", "mechanism": "no-software/process", "software_required": False}]}]}
    r = run_cycle(repo, cfg(repo, loops={"refinement": 0}), MockProvider(script={"branches": branches}), Mode.ANALYZE)
    screened = r["screened"]
    assert len(screened) == 4 and all(set(c["screen"]) == {"verdict", "matched_id", "similarity", "risk_signal", "reason"} for c in screened)
    by_title = {c["title"]: c["screen"] for c in screened}
    dup = by_title["Simplify onboarding form"]
    assert dup["verdict"] == "drop" and dup["matched_id"] == "Simplify the onboarding form" and dup["similarity"] >= 0.6
    assert by_title["Simplify the onboarding form"]["verdict"] == "keep" and by_title["Simplify the onboarding form"]["risk_signal"] is None
    assert by_title["Purge stale rows nightly"]["risk_signal"] == "mechanism:delet"
    assert r["dedup_dropped"] == sum(1 for c in screened if c["screen"]["verdict"] == "drop") == 1
    md = render(r)
    assert "dedup dropped: 1" in md
    assert "| Simplify onboarding form | drop | Simplify the onboarding form |" in md
    assert "| keep | - | - | mechanism:delet |" in md
    json.dumps(r)  # decisions serialize with the rest of the result


def test_report_renders_candidates_without_screen_decision():
    from evoloop.report import render
    md = render({"cycle": "old", "branches": ["simplify"], "opportunities": [{"id": "c1", "title": "legacy candidate"}]})
    assert "| c1 | legacy candidate | unknown | - | - | - |" in md


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
    run_cycle(repo, cfg(repo, search={**cfg(repo).search.model_dump(), "abstain_on_repeat": False}), p, Mode.ANALYZE)
    s = State(repo)
    assert s.nodes("Lesson") and s.nodes("Intervention") and s.nodes("Problem")
    prob = s.nodes("Problem")[0]
    assert s.related(prob["id"], "supported_by")
    second = MockProvider()
    r2 = run_cycle(repo, cfg(repo, search={**cfg(repo).search.model_dump(), "abstain_on_repeat": False}), second, Mode.ANALYZE)
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


def test_report_flags_repo_internal_only_evidence(repo):
    from evoloop.report import render
    r = run_cycle(repo, cfg(repo, evidence_sources=["todos"]), MockProvider(), Mode.ANALYZE)
    assert "Evidence tier: repo-internal only" in render(r)
    r2 = run_cycle(repo, cfg(repo, evidence_sources=["todos", "git_log", "notes"]), MockProvider(), Mode.ANALYZE)
    assert r2["problem"]  # mock cites the first evidence id; notes may or may not be first, so only assert no crash


def test_wall_clock_budget_enforced_without_token_telemetry(repo):
    class Untelemetered(MockProvider):
        def complete(self, role, system, prompt):
            out, _, _ = super().complete(role, system, prompt)
            return out, 0, 0  # like codex-cli: no token counts
    p = Untelemetered()
    r = run_cycle(repo, cfg(repo, budget={"max_model_calls": 40, "max_tokens": 10**9, "max_seconds": 0}), p, Mode.ANALYZE)
    assert r["status"] == "budget_exhausted" and "wall-clock" in r["stop_reason"] and p.calls == []


def test_repeated_recommendation_abstains_after_one_call(repo):
    first = run_cycle(repo, cfg(repo), MockProvider(), Mode.ANALYZE)
    assert first["decision"] == "RECOMMEND"
    p = MockProvider()
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    assert r["decision"] == "STOP" and "repeated recommendation" in r["stop_reason"]
    assert len(p.calls) == 1  # problem search only
    # new user-tier evidence lifts the abstention
    (repo / ".evoloop" / "evidence" / "users.md").write_text("Two testers said onboarding is confusing for admins\n")
    p2 = MockProvider(script={"problem_search": lambda inp: {"problems": [
        {"title": first["problem"]["title"], "evidence_ids": [e["id"] for e in inp["evidence"] if e["source"] == "notes"][:1], "confidence": 0.9}]}})
    r3 = run_cycle(repo, cfg(repo), p2, Mode.ANALYZE)
    assert r3["decision"] == "RECOMMEND" and len(p2.calls) > 1


def test_repeat_with_same_note_cited_still_abstains(repo):
    (repo / ".evoloop" / "evidence" / "constraint.md").write_text("the binding constraint is that there are no users yet\n")
    cite_note = {"problem_search": lambda inp: {"problems": [{"title": "No real usage evidence reaches the loop",
                 "evidence_ids": [e["id"] for e in inp["evidence"] if e["source"] == "notes"][:1], "confidence": 0.9}]}}
    first = run_cycle(repo, cfg(repo), MockProvider(script=cite_note), Mode.ANALYZE)
    assert first["decision"] == "RECOMMEND"
    p = MockProvider(script=cite_note)
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    assert r["decision"] == "STOP" and len(p.calls) == 1


def test_empty_sources_reported(repo):
    from evoloop.report import render
    r = run_cycle(repo, cfg(repo, evidence_sources=["todos", "issues", "notes"]), MockProvider(), Mode.ANALYZE)
    assert r["evidence_by_source"]["todos"] >= 1 and "issues" in r["empty_sources"]
    assert "configured but empty" in render(r)


def test_reworded_problem_with_same_citations_abstains(repo):
    (repo / ".evoloop" / "evidence" / "constraint.md").write_text("the binding constraint is that there are no users yet\n")
    def cite(title):
        return {"problem_search": lambda inp: {"problems": [{"title": title,
                "evidence_ids": [e["id"] for e in inp["evidence"] if e["source"] == "notes"][:1], "confidence": 0.9}]}}
    first = run_cycle(repo, cfg(repo), MockProvider(script=cite("No real usage evidence reaches the loop")), Mode.ANALYZE)
    assert first["decision"] == "RECOMMEND"
    p = MockProvider(script=cite("Evidence feeds exist but nothing emits data"))
    r = run_cycle(repo, cfg(repo), p, Mode.ANALYZE)
    assert r["decision"] == "STOP" and "repeated recommendation" in r["stop_reason"] and len(p.calls) == 1
