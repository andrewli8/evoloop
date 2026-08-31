import json
import subprocess
from pathlib import Path

from evoloop.config import Config, Mode
from evoloop.cycle import run_cycle
from evoloop.providers import MockProvider, NotSupported, Provider
from evoloop.state import State


def cfg(repo, **kw):
    return Config.model_validate({**Config.load(repo).model_dump(), **kw})


def impl_ok(instr, cwd):
    (cwd / "src" / "feature.ts").write_text("export const feature = 1;\n")
    return "done"


def test_build_isolated_worktree_and_gate(repo):
    p = MockProvider(implement_fn=impl_ok)
    r = run_cycle(repo, cfg(repo), p, Mode.BUILD)
    assert r["decision"] == "BUILD" and r["status"] == "awaiting_human", r.get("stop_reason")
    assert r["gate"]["passed"] and r["verification"]["ok"] and r["verification"]["attempts"] == 1
    assert r["changed_files"] == ["src/feature.ts"]
    assert not (repo / "src" / "feature.ts").exists()  # main tree untouched
    branches = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert r["branch"] in branches
    assert r["claim"].startswith("passed engineering verification")
    assert (repo / ".evoloop" / "runs" / r["cycle"] / "contract.json").exists()
    # continuous mode pauses until resolved
    r2 = run_cycle(repo, cfg(repo), MockProvider(), Mode.BUILD)
    assert r2["status"] == "paused"


def test_failed_verification_blocks_delivery_and_repair_terminates(repo):
    calls = []

    def impl_fail(instr, cwd):
        calls.append(instr)
        (cwd / "package.json").write_text('{"name":"x","scripts":{"lint":"true","test":"exit 1"}}')
        return "broke it"
    p = MockProvider(implement_fn=impl_fail)
    r = run_cycle(repo, cfg(repo), p, Mode.BUILD)
    assert r["status"] == "blocked" and not r["gate"]["passed"]
    assert r["verification"]["attempts"] == 1 + Config().loops.repair
    assert len(calls) == 3 and "failed verification" in calls[1]
    assert "commit" not in r


def test_repair_loop_recovers(repo):
    n = {"i": 0}

    def impl(instr, cwd):
        n["i"] += 1
        (cwd / "package.json").write_text('{"name":"x","scripts":{"lint":"true","test":"%s"}}' % ("exit 1" if n["i"] == 1 else "true"))
        return "ok"
    r = run_cycle(repo, cfg(repo), MockProvider(implement_fn=impl), Mode.BUILD)
    assert r["verification"]["ok"] and r["verification"]["attempts"] == 2 and r["status"] == "awaiting_human"


def test_review_block_blocks_delivery(repo):
    p = MockProvider(implement_fn=impl_ok, script={"review": {"blocking": ["sql injection"], "verdict": "block"}})
    r = run_cycle(repo, cfg(repo, loops={"repair": 0}), p, Mode.BUILD)
    assert r["status"] == "blocked" and r["gate"]["review"] == "block"


def test_contract_mutation_detected(repo):
    def impl_tamper(instr, cwd):
        impl_ok(instr, cwd)
        run = sorted((repo / ".evoloop" / "runs").iterdir())[-1]
        c = json.loads((run / "contract.json").read_text())
        c["acceptance_criteria"] = []
        (run / "contract.json").write_text(json.dumps(c))
        return "tampered"
    r = run_cycle(repo, cfg(repo), MockProvider(implement_fn=impl_tamper), Mode.BUILD)
    assert r["status"] == "blocked" and r["gate"]["contract_unchanged"] is False


def test_contract_model_is_frozen():
    from evoloop.contract import EvaluationContract
    import pytest
    c = EvaluationContract(cycle="x", intervention_id="i", hypothesis="h", acceptance_criteria=["a"])
    with pytest.raises(Exception):
        c.hypothesis = "changed"


def test_provider_without_implement_yields_plan_only(repo):
    class TextOnly(MockProvider):
        def implement(self, instructions, cwd):
            raise NotSupported("text-only provider")
    r = run_cycle(repo, cfg(repo), TextOnly(), Mode.BUILD)
    assert r["status"] == "plan_only" and r["spec"] and "worktree" in r
    assert not Path(r["worktree"]).exists()


def test_plan_mode_writes_spec_no_code(repo):
    r = run_cycle(repo, cfg(repo), MockProvider(), Mode.PLAN)
    assert r["decision"] == "RECOMMEND" and r["spec"] and "worktree" not in r


def test_build_from_previous_cycle(repo):
    a = run_cycle(repo, cfg(repo), MockProvider(), Mode.ANALYZE)
    assert a["decision"] == "RECOMMEND"
    p = MockProvider(implement_fn=impl_ok)
    r = run_cycle(repo, cfg(repo), p, Mode.BUILD, from_cycle=a["cycle"])
    assert r["from_cycle"] == a["cycle"] and r["winner"]["title"] == a["winner"]["title"]
    assert r["status"] == "awaiting_human" and r["gate"]["passed"]
    assert not any(c[0] in ("problem_search", "branches", "adversarial") for c in p.calls)  # no re-search
    assert r["problem"]["title"] == a["problem"]["title"]


def test_build_pick_and_high_risk_still_gated(repo):
    a = run_cycle(repo, cfg(repo), MockProvider(), Mode.ANALYZE)
    other = next(o for o in a["opportunities"] if o["id"] != a["winner"]["id"] and o.get("software_required", True))
    r = run_cycle(repo, cfg(repo), MockProvider(implement_fn=impl_ok), Mode.BUILD, from_cycle=a["cycle"], pick=other["id"])
    assert r["winner"]["title"] == other["title"] and r["status"] == "awaiting_human"
    from evoloop.state import State
    State(repo).db.execute("UPDATE cycles SET status='done'")  # clear awaiting so another build can run
    a2 = run_cycle(repo, cfg(repo, high_risk_terms=["option"]), MockProvider(), Mode.ANALYZE)
    State(repo).db.execute("UPDATE cycles SET status='done'")
    r2 = run_cycle(repo, cfg(repo, high_risk_terms=["option"]), MockProvider(implement_fn=impl_ok), Mode.BUILD, from_cycle=a2["cycle"])
    assert r2["decision"] == "RECOMMEND" and "human gated" in r2["stop_reason"]


def test_invalid_spec_blocks_before_coding(repo):
    bad = {"tool_name": "Bash", "input": {"command": "ls"}}
    p = MockProvider(implement_fn=impl_ok, script={"spec": bad})
    r = run_cycle(repo, cfg(repo), p, Mode.BUILD)
    assert r["status"] == "blocked" and "no usable spec" in r["stop_reason"]
    assert sum(1 for c in p.calls if c[0] == "spec") == 2 and not any(c[0] == "implement" for c in p.calls)
    assert not Path(r["worktree"]).exists()
