"""Engineering half: contract -> worktree -> spec -> implement -> verify (repair<=N) -> review -> recheck -> gate."""
from __future__ import annotations

import json

from . import gitops, prompts as P, scan, search, verify as V
from .config import Mode
from .contract import EvaluationContract, freeze, verify_unchanged
from .cycle import Ctx
from .providers import NotSupported, Role


class SpecInvalid(RuntimeError):
    pass


def write_spec(c: Ctx, w: dict) -> dict:
    inp = {"context": scan.summary(c.pack), "winner": {k: w.get(k) for k in ("title", "summary", "mechanism")},
           "problem": {k: c.result["problem"].get(k) for k in ("title", "description", "workflow")}}
    spec = c.llm.json(Role.CODING, P.ENGINEER, P.p("spec", P.SPEC, inp))
    if not _valid_spec(spec):  # e.g. a hallucinated tool call instead of a spec; one retry, then refuse to build on garbage
        spec = c.llm.json(Role.CODING, P.ENGINEER, P.p("spec", "Previous reply was not a spec. " + P.SPEC, inp))
    if not _valid_spec(spec):
        raise SpecInvalid(f"spec step returned no usable spec: {str(spec)[:120]}")
    c.result["spec"] = spec
    (c.run_dir / "spec.json").write_text(json.dumps(spec, indent=1))
    return spec


def _valid_spec(spec) -> bool:
    return isinstance(spec, dict) and isinstance(spec.get("spec"), str) and len(spec["spec"]) > 20 and "tool_name" not in spec


def build(c: Ctx) -> None:
    r, w, cfg = c.result, c.result["winner"], c.cfg
    if cfg.mode == Mode.OFF or not cfg.enabled:
        r.update(status="blocked", stop_reason="disabled")
        return
    # 1. Evaluation contract, frozen BEFORE any code changes; lives outside the worktree.
    contract = EvaluationContract(
        cycle=c.cycle_id, intervention_id=w["node_id"], hypothesis=f"{w['title']}: {w.get('summary', '')}",
        acceptance_criteria=["all configured deterministic checks pass", "independent review approves", "stakeholder recheck score >= 3"],
        deterministic_checks=[v for v in cfg.commands.model_dump().values() if v], risk=w["risk"],
        target_metric=None)
    sha = freeze(contract, c.run_dir, c.state)
    r["contract"] = {**contract.model_dump(), "sha": sha}
    # 2. Isolation
    wt, branch, base = gitops.create_worktree(c.repo, c.cycle_id)
    r["branch"], r["worktree"], r["base"] = branch, str(wt), base
    # 3. Baseline
    r["baseline"] = V.run_all(cfg.commands, wt)
    try:
        spec = write_spec(c, w)
    except SpecInvalid as e:
        r.update(status="blocked", stop_reason=str(e), implementation="not attempted")
        gitops.remove_worktree(c.repo, wt, branch)
        return
    instructions = P.implement_instructions(spec, contract.canonical())
    # 4. Implement + verify with bounded repair loop
    attempts, failure, res = 0, None, {"ok": False, "steps": [], "ran": False}
    try:
        while attempts <= cfg.loops.repair:
            attempts += 1
            c.llm.implement(P.implement_instructions(spec, contract.canonical(), failure) if failure else instructions, wt)
            res = V.run_all(cfg.commands, wt, c.run_dir)
            if res["ok"]:
                break
            failure = V.failure_summary(res)
    except NotSupported as e:
        r.update(status="plan_only", stop_reason=str(e), implementation="not attempted")
        gitops.remove_worktree(c.repo, wt, branch)
        return
    r["verification"] = {**res, "attempts": attempts}
    # 5. Independent review (separate context) — one more repair if it blocks and budget remains
    review = _review(c, wt, base, spec)
    if review.get("verdict") == "block" and attempts <= cfg.loops.repair and review.get("blocking"):
        attempts += 1
        c.llm.implement(P.implement_instructions(spec, contract.canonical(), "Review blocked:\n" + "\n".join(review["blocking"])), wt)
        res = V.run_all(cfg.commands, wt, c.run_dir)
        r["verification"] = {**res, "attempts": attempts}
        review = _review(c, wt, base, spec)
    gate(c, wt, branch, base, res, review, contract.hypothesis)


def gate(c: Ctx, wt, branch: str, base: str, res: dict, review: dict, hypothesis: str) -> None:
    """Steps 6-7: stakeholder recheck of the implemented behaviour, then the delivery gate. Reused by `evoloop regate`."""
    r, w = c.result, c.result["winner"]
    r["review"] = review
    r["changed_files"] = gitops.changed_files(wt, base)
    recheck = c.llm.json(Role.FAST, P.GENERATOR, P.p("stakeholder_recheck", P.RECHECK, {
        "problem": r["problem"]["title"], "stakeholders": [s.get("role") for s in r["stakeholders"]],
        "winner": w["title"], "changed_files": r["changed_files"], "diff": gitops.diff(wt, base, 6000)}))
    r["recheck"] = recheck
    contract_ok = verify_unchanged(c.run_dir, c.state, c.cycle_id)
    passed = res["ok"] and review.get("verdict") == "approve" and bool(recheck.get("still_solves_problem")) \
        and search._n(recheck.get("score"), 1) >= 3 and contract_ok and bool(r["changed_files"])
    r["gate"] = {"deterministic": res["ok"], "review": review.get("verdict"), "recheck": bool(recheck.get("still_solves_problem")),
                 "contract_unchanged": contract_ok, "changed_files": bool(r["changed_files"]), "passed": passed}
    if not passed:
        r.update(status="blocked", implementation="left on branch for inspection", stop_reason="delivery gate failed")
        return
    r["commit"] = gitops.commit(wt, f"evoloop: {w['title']}\n\ncycle {c.cycle_id}. Hypothesis: {hypothesis[:300]}")
    if c.mode == Mode.PR:
        r["pr"] = gitops.open_pr(wt, branch, f"evoloop: {w['title']}", _pr_body(c))
    r.update(status="awaiting_human", implementation="committed on branch",
             claim="passed engineering verification and simulated evaluation; recommended for real validation")
    if c.cfg.auto_merge:
        _auto_merge(c, wt, branch, w)


def _auto_merge(c: Ctx, wt, branch: str, w: dict) -> None:
    """auto_merge is set by the human in config.yaml, never by the tool. Merge the gated branch into the checked-out
    branch, prove the merged tree with the same deterministic checks, auto-resolve at level 1 (engineering only).
    A failed post-merge verification backs the merge out and leaves the branch awaiting a human."""
    r = c.result
    if not gitops.clean(c.repo):
        r["auto_merge"] = {"done": False, "reason": "working tree has uncommitted changes"}
        return
    sha = gitops.merge(c.repo, branch, f"evoloop: merge {branch}\n\n{w['title']} (cycle {c.cycle_id}, gate passed)")
    res = V.run_all(c.cfg.commands, c.repo, c.run_dir)
    if not res["ok"]:
        gitops.undo_merge(c.repo)
        r["auto_merge"] = {"done": False, "reason": "post-merge verification failed", "verification": res}
        return
    r["auto_merge"] = {"done": True, "merge_sha": sha, "verification": res}
    rid = c.state.add("Result", {"intervention": w["title"], "outcome": "kept", "note": f"auto-merged {sha}", "level": 1}, c.cycle_id)
    if w.get("node_id"):
        c.state.link(rid, "of", w["node_id"])
    gitops.remove_worktree(c.repo, wt)
    r.update(status="merged", implementation=f"auto-merged as {sha}", resolution={"outcome": "kept", "level": 1, "note": "auto-merge"})


def regate(c: Ctx, prev: dict) -> None:
    """Re-run verification, review, recheck and gate on a blocked cycle's existing branch (no new coding call)."""
    from pathlib import Path
    wt = Path(prev["worktree"])
    if not wt.exists():
        raise ValueError("cycle has no worktree to regate")
    base = prev.get("base") or gitops.merge_base(c.repo, prev["branch"])  # cycles built before `base` was recorded
    c.result.update({k: prev[k] for k in ("problem", "stakeholders", "winner", "spec", "contract", "branch", "worktree", "base") if k in prev})
    c.result["regate_of"] = prev["cycle"]
    _reload_contract(c, prev)
    res = V.run_all(c.cfg.commands, wt, c.run_dir)
    c.result["verification"] = {**res, "attempts": 0}
    gate(c, wt, prev["branch"], base, res, _review(c, wt, base, prev["spec"]), prev["contract"]["hypothesis"])


def _reload_contract(c: Ctx, prev: dict) -> None:
    """Freeze the previous cycle's contract under the new cycle id so the unchanged-check applies to it."""
    data = {k: v for k, v in prev["contract"].items() if k != "sha"}
    contract = EvaluationContract(**{**data, "cycle": c.cycle_id})
    freeze(contract, c.run_dir, c.state)
    c.result["contract"] = {**contract.model_dump(), "sha": contract.sha()}


def _review(c: Ctx, wt, base: str, spec) -> dict:
    return c.llm.json(Role.REVIEW, P.CRITIC, P.p("review", P.REVIEW, {"spec": spec, "commits": gitops.branch_log(wt, base),
                                                                       "diff": gitops.diff(wt, base)}))


def _pr_body(c: Ctx) -> str:
    r = c.result
    return (f"Problem: {r['problem']['title']}\n\nHypothesis: {r['contract']['hypothesis']}\n\n"
            f"Verification: {'passed' if r['verification']['ok'] else 'failed'} ({r['verification']['attempts']} attempts)\n"
            f"Claim: passed engineering verification and simulated stakeholder evaluation only. Real validation pending.\n\n"
            f"Report: .evoloop/runs/{c.cycle_id}/report.md")
