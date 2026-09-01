"""runCycle(): one finite, bounded product-improvement cycle. Every path terminates."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import evidence as ev_mod
from . import prompts as P
from . import scan, search
from .config import EVO_DIR, Config, Mode
from .providers import Budgeted, BudgetExceeded, Provider, Role
from .state import State


@dataclass
class Ctx:
    repo: Path
    cfg: Config
    state: State
    llm: Budgeted
    mode: Mode
    cycle_id: str
    run_dir: Path
    pack: dict
    result: dict = field(default_factory=dict)
    evidence_exec: list[str] = field(default_factory=list)  # --evidence-json specs; may contain cmd: (human-typed)


def run_cycle(repo: Path, cfg: Config, provider: Provider, mode: Mode | None = None,
              from_cycle: str | None = None, pick: str | None = None, regate_cycle: str | None = None,
              evidence_json: list[str] | None = None) -> dict:
    """One bounded cycle. `from_cycle` skips search and builds the winner (or opportunity `pick`) of a previous cycle.
    `regate_cycle` re-runs verification/review/gate on a blocked cycle's existing branch.
    `evidence_json`: extra JSON evidence specs typed by the human (`cmd:` allowed there, never from config)."""
    try:
        return _run_cycle(repo, cfg, provider, mode, from_cycle, pick, regate_cycle, evidence_json)
    except BaseException as exc:  # anything that escapes the cycle is a friction signal; record, then propagate unchanged
        from .incidents import exception_incident
        exception_incident(exc, source="cycle", root=repo)
        raise


def _run_cycle(repo: Path, cfg: Config, provider: Provider, mode: Mode | None, from_cycle: str | None, pick: str | None,
               regate_cycle: str | None, evidence_json: list[str] | None) -> dict:
    mode = mode or cfg.mode
    state = State(repo)
    if not cfg.enabled or mode == Mode.OFF:
        return {"status": "disabled", "decision": "STOP", "stop_reason": "evoloop is disabled (no model calls made)", "usage": {"model_calls": 0}}
    if state.awaiting():
        ids = [c["id"] for c in state.awaiting()]
        return {"status": "paused", "decision": "STOP", "stop_reason": f"awaiting human resolution of {ids}; run `evoloop resolve <id>`",
                "usage": {"model_calls": 0}}
    state.acquire()
    cid = state.start_cycle()
    run_dir = repo / EVO_DIR / "runs" / cid
    run_dir.mkdir(parents=True, exist_ok=True)
    pack = scan.refresh(repo, scan.load_pack(repo))
    scan.save_pack(repo, pack)
    llm = Budgeted(provider, cfg.budget.max_model_calls, cfg.budget.max_tokens, cfg.models, cfg.budget.max_seconds, root=repo)
    ctx = Ctx(repo, cfg, state, llm, mode, cid, run_dir, pack, {"cycle": cid, "mode": mode.value, "provider": provider.name, "started": time.time()},
              list(evidence_json or []))
    try:
        if regate_cycle:
            from .build import regate
            prev = next((x for x in state.cycles(200) if x["id"] == regate_cycle), None)
            if not prev or not prev.get("result") or prev["result"].get("status") != "blocked":
                raise ValueError(f"{regate_cycle} is not a blocked cycle")
            ctx.result["decision"] = "BUILD"
            regate(ctx, prev["result"])
        else:
            _resume(ctx, from_cycle, pick) if from_cycle else _search(ctx)
        if ctx.result["decision"] == "BUILD" and not regate_cycle:
            from .build import build
            build(ctx)
        _learn(ctx)
        status = ctx.result.setdefault("status", "done")
    except BudgetExceeded as e:
        ctx.result.update(decision="STOP", stop_reason=f"budget exhausted: {e}", status="budget_exhausted")
        status = "budget_exhausted"
    except Exception as e:  # cycle must terminate and leave a report
        ctx.result.update(decision="STOP", stop_reason=f"error: {type(e).__name__}: {e}", status="error")
        status = "error"
    finally:
        ctx.result["usage"] = {**llm.usage.as_dict(), "wall_seconds": round(time.time() - ctx.result["started"], 1)}
        from .report import write
        write(ctx)
        state.finish_cycle(cid, status, ctx.result)
        state.release()
    return ctx.result


def _resume(c: Ctx, from_cycle: str, pick: str | None) -> None:
    """Human-approved handoff: reuse a previous cycle's problem/stakeholders/candidate, re-run only the decision."""
    prev = next((x for x in c.state.cycles(200) if x["id"] == from_cycle), None)
    if not prev or not prev.get("result"):
        raise ValueError(f"unknown cycle {from_cycle}")
    pr = prev["result"]
    cands = pr.get("opportunities") or []
    w = next((o for o in cands if o.get("id") == pick), None) if pick else pr.get("winner")
    if w and not pick and not w.get("software_required", True):
        # a process/policy winner is for humans; a build cycle falls through to the best candidate that is code
        code = [o for o in cands if o.get("software_required", True)
                and not (o.get("adversarial") or {}).get("fatal") and (o.get("adversarial") or {}).get("verdict") != "reject"]
        if code:
            c.result["process_recommendation"] = w["title"]
            w = max(code, key=lambda o: ((o.get("stakeholder_score") or 3.0), o.get("cheap_score", 0)))
    if not w:
        raise ValueError(f"cycle {from_cycle} has no {'candidate ' + pick if pick else 'winner'}; ids: {[o.get('id') for o in cands]}")
    c.result.update(problem=pr["problem"], supporting_evidence=pr.get("supporting_evidence", []), stakeholders=pr.get("stakeholders", []),
                    finalists=pr.get("finalists", []), opportunities=cands, from_cycle=from_cycle, picked=pick)
    _decide(c, [{**w, "adversarial": w.get("adversarial", {}), "stakeholder_score": w.get("stakeholder_score") or 3.0,
                 "cheap_score": w.get("cheap_score", 0)}])


# --- search half of the cycle ---------------------------------------------------------------

def _search(c: Ctx) -> None:
    s, r, llm = c.cfg.search, c.result, c.llm
    # OBSERVE (deterministic)
    evidence = ev_mod.collect(c.repo, c.state, c.cfg.evidence_sources, c.cfg.evidence.external, c.evidence_exec,
                              cfg=c.cfg)
    r["evidence_count"] = {k: sum(1 for e in evidence if e["class"] == k) for k in ev_mod.CLASSES}
    r["evidence_by_source"] = {src: sum(1 for e in evidence if e["source"] == src) for src in c.cfg.evidence_sources}
    r["empty_sources"] = [src for src, n in r["evidence_by_source"].items() if n == 0]
    if not evidence:
        r.update(decision="STOP", stop_reason="insufficient evidence: no evidence sources produced anything", problem=None)
        return
    context = scan.summary(c.pack)
    lessons = c.state.nodes("Lesson", 50)
    # PROBLEM SEARCH (AI, fast)
    out = llm.json(Role.FAST, P.GENERATOR, P.p("problem_search", P.problem_search(s.max_problems), {
        "context": context, "evidence": evidence[:40], "past_lessons": [l.get("reusable_implication") for l in lessons[:5]],
        "already_known_problems": [p["title"] for p in c.state.nodes("Problem", 20)]}))
    problems = search.select_problem(_list(out, "problems")[: s.max_problems], evidence)
    r["problems"] = [{k: p.get(k) for k in ("title", "workflow", "evidence_ids", "evidence_score")} for p in problems]
    if not problems:
        r.update(decision="STOP", stop_reason="insufficient evidence: no problem is supported by evidence", problem=None)
        return
    # PROBLEM SELECTION (deterministic; deep_problems bounds how many we keep in memory)
    for p in problems[: s.deep_problems]:
        pid = c.state.add("Problem", p, c.cycle_id)
        for eid in p["evidence_ids"]:
            e = next(e for e in evidence if e["id"] == eid)
            c.state.link(pid, "supported_by", c.state.add("Evidence", e, c.cycle_id))
        p["node_id"] = pid
    problem = problems[0]
    r["problem"] = problem
    r["supporting_evidence"] = [e for e in evidence if e["id"] in problem["evidence_ids"]]
    repeat = _repeated_recommendation(c, problem) if s.abstain_on_repeat else None
    if repeat:
        r.update(decision="STOP", winner=None,
                 stop_reason=f"repeated recommendation: near-identical problem already recommended in cycle {repeat} "
                             "and no new user-tier evidence (issues, notes, external, smoke, results) has arrived since; abstaining")
        return
    r["lessons_used"] = search.relevant(lessons, problem["title"] + " " + problem.get("workflow", ""), ("problem", "workflow", "mechanism"), 3)
    # STAKEHOLDER SYNTHESIS (AI, fast)
    roles = _list(llm.json(Role.FAST, P.GENERATOR, P.p("stakeholders", P.stakeholders(s.stakeholder_roles),
                                                        {"context": context, "problem": problem})), "roles")[: s.stakeholder_roles]
    r["stakeholders"] = roles
    # SOLUTION BRANCHING (AI, reasoning) + DEDUP (deterministic)
    prior = c.state.nodes("Intervention", 200)
    prior_titles = [i["title"] for i in search.relevant(prior, problem["title"], ("problem",), 30)]
    cands = _branch(c, problem, roles, prior_titles, r["lessons_used"], missing=None)
    cands, dropped = search.dedup(cands, prior_titles)
    r["dedup_dropped"] = dropped
    for i, cnd in enumerate(cands):
        cnd["id"] = f"c{i+1}"
    # CHEAP TOURNAMENT (AI fast scoring, deterministic ranking)
    ranked = _cheap(c, cands, problem)
    opportunities = ranked[: s.opportunities]
    # diversity guard: at most `loops.refinement` extra branch passes, only if too homogeneous or all weak
    for _ in range(c.cfg.loops.refinement):
        weak = all(o["cheap_score"] < 2 for o in opportunities)
        homogeneous = len(search.mechanisms(opportunities)) < min(3, len(opportunities))
        if not (weak or homogeneous):
            break
        missing = [m for m in ["remove the problem", "simplify", "automate", "guide", "validate", "change workflow", "no-software/process"]
                   if m not in search.mechanisms(cands)]
        extra, _ = search.dedup(_branch(c, problem, roles, prior_titles + [x["title"] for x in cands], r["lessons_used"], missing), prior_titles)
        for j, e in enumerate(extra):
            e["id"] = f"c{len(cands)+j+1}"
        cands += extra
        ranked = _cheap(c, cands, problem)
        opportunities = ranked[: s.opportunities]
        r["refinement_used"] = True
    r["raw_candidates"] = len(cands)
    r["branches"] = sorted(search.mechanisms(cands))
    r["opportunities"] = opportunities
    for o in opportunities:  # archive good non-winners so later cycles don't regenerate them
        o["node_id"] = c.state.add("Intervention", {**o, "problem": problem["title"]}, c.cycle_id)
        c.state.link(o["node_id"], "addresses", problem["node_id"])
    # FINALIST EVALUATION (AI fast, one call per stakeholder role)
    finalists = opportunities[: s.finalists]
    slim = [{k: f.get(k) for k in ("id", "title", "summary", "mechanism", "software_required")} for f in finalists]
    evals = {f["id"]: [] for f in finalists}
    for role in roles:
        out = _list(llm.json(Role.FAST, P.GENERATOR, P.p("stakeholder_eval", P.STAKEHOLDER_EVAL,
                                                          {"role": role, "problem": problem["title"], "finalists": slim})), "evaluations")
        for e in out:
            if e.get("id") in evals:
                evals[e["id"]].append({"role": role.get("role"), **e})
    # ADVERSARIAL REVIEW (AI reasoning, critic context)
    reviews = {rv.get("id"): rv for rv in _list(llm.json(Role.REASONING, P.CRITIC, P.p("adversarial", P.ADVERSARIAL,
                                                       {"problem": {k: problem.get(k) for k in ("title", "description", "workflow")},
                                                        "finalists": slim, "stakeholders": [{k: x.get(k) for k in ("role", "goal", "current_pain")} for x in roles]})), "reviews")}
    for f in finalists:
        sc = [search._n(e.get("score"), 3) for e in evals[f["id"]]]
        f["stakeholder_score"] = round(sum(sc) / len(sc), 2) if sc else None
        f["stakeholder_evals"] = evals[f["id"]]
        f["adversarial"] = reviews.get(f["id"], {})
    r["finalists"] = finalists
    _decide(c, finalists)


def _repeated_recommendation(c: Ctx, problem: dict) -> str | None:
    """Cycle id of a recent RECOMMEND/STOP whose problem matches this one, when only repo-internal evidence backs it.
    Spending eight more model calls to re-derive the same answer is the failure mode this guards against."""
    from .report import BEHAVIOUR_SOURCES
    tier = lambda ev: {e.get("text") for e in ev if e.get("source") in BEHAVIOUR_SOURCES or e.get("kind") == "external"}  # noqa: E731
    now = tier(c.result.get("supporting_evidence", []))
    for prev in c.state.cycles(12):
        res = prev.get("result") or {}
        pt = (res.get("problem") or {}).get("title")
        if pt and res.get("decision") in ("RECOMMEND", "STOP") and res.get("status") in ("done", "budget_exhausted") \
                and search.jaccard(pt, problem["title"]) >= 0.6 and now <= tier(res.get("supporting_evidence", [])):
            return prev["id"]  # same problem, and every user-tier item cited now was already cited then
    return None


def _branch(c: Ctx, problem, roles, prior_titles, lessons, missing) -> list[dict]:
    s = c.cfg.search
    out = c.llm.json(Role.REASONING, P.GENERATOR, P.p("branches", P.branches(s.branches, s.candidates_per_branch), {
        "context": scan.summary(c.pack), "problem": {k: problem.get(k) for k in ("title", "description", "workflow")},
        "stakeholders": [x.get("role") for x in roles],
        "already_explored": prior_titles[:30], "lessons": lessons, "missing_mechanisms": missing}))
    cands = []
    # the mandatory "no software" branch survives truncation
    branches = sorted(_list(out, "branches"), key=lambda b: not any(x.get("software_required") is False for x in (b.get("candidates") or [])))
    for b in branches[: s.branches]:
        for cnd in (b.get("candidates") or [])[: s.candidates_per_branch]:
            if cnd.get("title"):
                cands.append({**cnd, "mechanism": cnd.get("mechanism") or b.get("mechanism", "")})
    return cands


def _cheap(c: Ctx, cands, problem) -> list[dict]:
    if not cands:
        return []
    out = c.llm.json(Role.FAST, P.GENERATOR, P.p("cheap_scores", P.CHEAP_SCORES, {"problem": problem["title"], "candidates": cands}))
    return search.cheap_rank(cands, _list(out, "scores"))


def _decide(c: Ctx, finalists: list[dict]) -> None:
    from .search import classify_candidate_risk
    r = c.result
    viable = [f for f in finalists if not f["adversarial"].get("fatal") and f["adversarial"].get("verdict") != "reject"
              and (f["stakeholder_score"] or 0) >= 3.0]
    if not viable:
        r.update(decision="STOP", winner=None, stop_reason="no finalist survived stakeholder and adversarial evaluation")
        return
    w = max(viable, key=lambda f: (f["stakeholder_score"], f["cheap_score"]))
    w["risk"] = classify_candidate_risk(w, c.cfg.high_risk_terms)  # structured signal can only raise the keyword risk
    r["winner"] = w
    if not w.get("software_required", True):
        r.update(decision="RECOMMEND", stop_reason="winner is a process/policy change; nothing to build")
    elif c.mode in (Mode.ANALYZE, Mode.PLAN):
        r.update(decision="RECOMMEND", stop_reason=f"mode={c.mode.value}: recommendation only")
    elif w["risk"] == "high":
        r.update(decision="RECOMMEND", stop_reason="high-risk area (security/billing/data): human gated")
    else:
        r["decision"] = "BUILD"
    if c.mode == Mode.PLAN and r["decision"] == "RECOMMEND":
        from .build import write_spec
        write_spec(c, w)


def _learn(c: Ctx) -> None:
    r = c.result
    if not r.get("problem"):
        return
    w = r.get("winner") or {}
    if r.get("verification"):  # only an implemented experiment yields something worth a model's interpretation
        out = c.llm.json(Role.FAST, P.GENERATOR, P.p("lesson", P.LESSON, {
            "problem": r["problem"]["title"], "decision": r["decision"], "winner": w.get("title"), "stop_reason": r.get("stop_reason"),
            "verification": r["verification"].get("ok"), "review": r.get("review", {}).get("verdict"), "gate": r.get("gate")}))
    else:
        out = {"what_worked": None, "what_failed": None, "confidence": 0.3,
               "reusable_implication": f"{r['decision']}: {r.get('stop_reason') or 'recommended ' + str(w.get('title'))}"}
    lesson = {"problem": r["problem"]["title"], "workflow": r["problem"].get("workflow"), "mechanism": w.get("mechanism"),
              "prediction": (w.get("summary") or "")[:200], "observed_result": r.get("status", r["decision"]),
              "what_worked": out.get("what_worked"), "what_failed": out.get("what_failed"),
              "confidence": out.get("confidence", 0.5), "reusable_implication": out.get("reusable_implication")}
    r["lesson"] = lesson
    lid = c.state.add("Lesson", lesson, c.cycle_id)
    if w.get("node_id"):
        c.state.link(lid, "about", w["node_id"])
    r.setdefault("status", "done")


def _list(out, key: str) -> list:
    v = out.get(key) if isinstance(out, dict) else out
    return [x for x in (v or []) if isinstance(x, dict)]
