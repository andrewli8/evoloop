"""Engineering half: contract -> worktree -> spec -> implement -> verify (repair<=N) -> review -> recheck -> gate."""
from __future__ import annotations

import json

from . import gitops, prompts as P, scan, search, verify as V
from .config import Mode
from .contract import EvaluationContract, freeze, verify_unchanged
from .cycle import Ctx
from .providers import NotSupported, Role


def write_spec(c: Ctx, w: dict) -> dict:
    spec = c.llm.json(Role.CODING, P.ENGINEER, P.p("spec", P.SPEC, {"context": scan.summary(c.pack),
                                                                    "winner": w, "problem": c.result["problem"]}))
    c.result["spec"] = spec
    (c.run_dir / "spec.json").write_text(json.dumps(spec, indent=1))
    return spec


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
    wt, branch = gitops.create_worktree(c.repo, c.cycle_id)
    r["branch"], r["worktree"] = branch, str(wt)
    # 3. Baseline
    r["baseline"] = V.run_all(cfg.commands, wt)
    spec = write_spec(c, w)
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
    r["changed_files"] = gitops.changed_files(wt)
    # 5. Independent review (separate context) — one more repair if it blocks and budget remains
    review = _review(c, wt, spec)
    if review.get("verdict") == "block" and attempts <= cfg.loops.repair and review.get("blocking"):
        attempts += 1
        c.llm.implement(P.implement_instructions(spec, contract.canonical(), "Review blocked:\n" + "\n".join(review["blocking"])), wt)
        res = V.run_all(cfg.commands, wt, c.run_dir)
        r["verification"] = {**res, "attempts": attempts}
        review = _review(c, wt, spec)
    r["review"] = review
    # 6. Stakeholder recheck against implemented behaviour (simulated, not customer validation)
    recheck = c.llm.json(Role.FAST, P.GENERATOR, P.p("stakeholder_recheck", P.RECHECK, {
        "problem": r["problem"]["title"], "stakeholders": [s.get("role") for s in r["stakeholders"]],
        "winner": w["title"], "changed_files": r["changed_files"], "diff": gitops.diff(wt, 6000)}))
    r["recheck"] = recheck
    # 7. Delivery gate: deterministic AND review AND recheck AND contract untouched
    contract_ok = verify_unchanged(c.run_dir, c.state, c.cycle_id)
    passed = res["ok"] and review.get("verdict") == "approve" and bool(recheck.get("still_solves_problem")) \
        and search._n(recheck.get("score"), 1) >= 3 and contract_ok and bool(r["changed_files"])
    r["gate"] = {"deterministic": res["ok"], "review": review.get("verdict"), "recheck": bool(recheck.get("still_solves_problem")),
                 "contract_unchanged": contract_ok, "changed_files": bool(r["changed_files"]), "passed": passed}
    if not passed:
        r.update(status="blocked", implementation="left on branch for inspection", stop_reason="delivery gate failed")
        return
    sha = gitops.commit(wt, f"evoloop: {w['title']}\n\ncycle {c.cycle_id}. Hypothesis: {contract.hypothesis[:300]}")
    r["commit"] = sha
    if c.mode == Mode.PR:
        r["pr"] = gitops.open_pr(wt, branch, f"evoloop: {w['title']}", _pr_body(c))
    r.update(status="awaiting_human", implementation="committed on branch",
             claim="passed engineering verification and simulated evaluation; recommended for real validation")


def _review(c: Ctx, wt, spec) -> dict:
    return c.llm.json(Role.REVIEW, P.CRITIC, P.p("review", P.REVIEW, {"spec": spec, "diff": gitops.diff(wt)}))


def _pr_body(c: Ctx) -> str:
    r = c.result
    return (f"Problem: {r['problem']['title']}\n\nHypothesis: {r['contract']['hypothesis']}\n\n"
            f"Verification: {'passed' if r['verification']['ok'] else 'failed'} ({r['verification']['attempts']} attempts)\n"
            f"Claim: passed engineering verification and simulated stakeholder evaluation only. Real validation pending.\n\n"
            f"Report: .evoloop/runs/{c.cycle_id}/report.md")
