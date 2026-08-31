"""evoloop CLI."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__, gitops, scan, skill as skill_mod
from .config import EVO_DIR, Config, Mode
from .providers import detect_provider, make_provider
from .state import LockedError, State

app = typer.Typer(help="EvolveLoop: bounded, evidence-driven product improvement loop.", no_args_is_help=True)
skill_app = typer.Typer(help="Host coding-agent skill adapters.")
app.add_typer(skill_app, name="skill")

GITIGNORE = "state.sqlite\nstate.sqlite-*\nruns/\nworktrees/\noptimize/\n"


def _repo() -> Path:
    p = Path.cwd()
    if not gitops.is_repo(p):
        typer.echo("not a git repository", err=True)
        raise typer.Exit(2)
    return p


def scaffold(repo: Path, provider: str | None = None, force: bool = False, evidence_sources: list[str] | None = None) -> dict:
    """Create/refresh .evoloop/ deterministically. Returns the project context pack."""
    d = repo / EVO_DIR
    d.mkdir(exist_ok=True)
    pack = scan.scan(repo)
    scan.save_pack(repo, pack)
    if not Config.path(repo).exists() or force:
        cfg = Config(provider=provider or detect_provider(), commands=Config.model_validate({"commands": pack["commands"]["value"]}).commands)
        if evidence_sources:
            cfg = cfg.model_copy(update={"evidence_sources": evidence_sources})
        cfg.save(repo)
    (d / "evals.yaml").write_text("# Product metrics EvolveLoop may cite as real evidence. Empty => it can only recommend.\n"
                                  "target_metrics: []\nguardrail_metrics: []\n")
    (d / "skill.md").write_text(skill_mod.SKILL)
    (d / ".gitignore").write_text(GITIGNORE)
    (d / "evidence").mkdir(exist_ok=True)
    (d / "evidence" / "README.md").write_text("Drop .md files here with observed evidence (support tickets, feedback, analytics notes), one item per line.\n"
                                             "Prefix a line with [inferred] or [hypothetical] when it is not directly observed.\n")
    State(repo)
    return pack


@app.command()
def init(provider: str = typer.Option(None, help="claude-cli | codex-cli | anthropic | mock (default: auto-detect)"),
         force: bool = typer.Option(False, help="overwrite existing config")):
    """Inspect the repository and create .evoloop/ (config, project context pack, evals, skill)."""
    repo = _repo()
    pack = scaffold(repo, provider, force)
    typer.echo(f"Initialized {EVO_DIR}/\n")
    typer.echo(scan.describe(pack))
    prov = Config.load(repo).provider
    typer.echo(f"  - provider: {prov}" + ("  (WARNING: mock returns placeholder output; install `claude` or `codex`, or set ANTHROPIC_API_KEY)" if prov == "mock" else ""))


def _cycle(mode: Mode | None, provider: str | None, from_cycle: str | None = None, pick: str | None = None):
    repo = _repo()
    cfg = Config.load(repo)
    if not cfg.enabled or (mode or cfg.mode) == Mode.OFF:
        typer.echo("evoloop is disabled; no model calls made")
        raise typer.Exit(0)
    if mode == Mode.EXPERIMENT:
        typer.echo("experiment mode needs real metrics in evals.yaml; not wired in V1. Use pr.", err=True)
        raise typer.Exit(2)
    from .cycle import run_cycle
    name = provider or cfg.provider
    if name == "mock":
        typer.echo("WARNING: provider=mock — output is placeholder text for testing, not analysis. Set provider in .evoloop/config.yaml.", err=True)
    try:
        r = run_cycle(repo, cfg, make_provider(name, cfg.models), mode, from_cycle, pick)
    except LockedError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(3)
    typer.echo(f"cycle {r.get('cycle')} status={r.get('status')} decision={r.get('decision')}")
    if r.get("winner"):
        typer.echo(f"winner: {r['winner']['title']}")
    typer.echo(r.get("stop_reason") or "")
    if r.get("cycle"):
        typer.echo(f"report: {EVO_DIR}/runs/{r['cycle']}/report.md")
    typer.echo(f"usage: {r.get('usage')}")


@app.command()
def analyze(provider: str = typer.Option(None)):
    """Run one cycle in ANALYZE mode: recommend 0-1 intervention, change no code."""
    _cycle(Mode.ANALYZE, provider)


@app.command()
def run(mode: Mode = typer.Option(None, help="analyze | plan | build | pr (default: config mode)"),
        provider: str = typer.Option(None)):
    """Run one bounded cycle. Continuous use = a scheduler calling this repeatedly."""
    _cycle(mode, provider)


@app.command()
def build(cycle: str, pick: str = typer.Option(None, help="opportunity id (c1, c2, ...) instead of the winner"),
          pr: bool = typer.Option(False, help="open a PR after the gate passes"), provider: str = typer.Option(None)):
    """Implement a recommendation from a previous analyze/plan cycle: no new search, same contract/verify/review/gate."""
    _cycle(Mode.PR if pr else Mode.BUILD, provider, cycle, pick)


@app.command()
def status():
    """Show mode, enabled flag, recent cycles and anything awaiting a human."""
    repo = _repo()
    cfg = Config.load(repo)
    st = State(repo)
    typer.echo(f"enabled={cfg.enabled} mode={cfg.mode.value} provider={cfg.provider}")
    for c in st.cycles(5):
        r = c["result"] or {}
        typer.echo(f"  {c['id']} {c['status']} decision={r.get('decision')} winner={(r.get('winner') or {}).get('title')} calls={r.get('usage', {}).get('model_calls')}")
    if st.awaiting():
        typer.echo(f"awaiting human: {[c['id'] for c in st.awaiting()]} (evoloop resolve <id> --outcome kept|reverted)")


@app.command()
def enable():
    """Allow cycles to run."""
    repo = _repo()
    cfg = Config.load(repo)
    cfg.model_copy(update={"enabled": True}).save(repo)
    typer.echo("enabled")


@app.command()
def disable():
    """Disable evoloop: guarantees zero model calls."""
    repo = _repo()
    cfg = Config.load(repo)
    cfg.model_copy(update={"enabled": False}).save(repo)
    typer.echo("disabled")


@app.command()
def resolve(cycle: str, outcome: str = typer.Option(..., help="kept | reverted"),
            note: str = typer.Option("", help="what happened in the real world"),
            level: int = typer.Option(2, help="3 only if a real metric moved; 2 = merged/reviewed; 1 = engineering only")):
    """Record the human/real-world outcome of a built cycle so continuous runs can resume."""
    repo = _repo()
    st = State(repo)
    cs = [c for c in st.cycles(100) if c["id"] == cycle]
    if not cs:
        typer.echo("unknown cycle", err=True)
        raise typer.Exit(2)
    r = cs[0]["result"] or {}
    rid = st.add("Result", {"intervention": (r.get("winner") or {}).get("title"), "outcome": outcome, "note": note, "level": level}, cycle)
    if (r.get("winner") or {}).get("node_id"):
        st.link(rid, "of", r["winner"]["node_id"])
    st.finish_cycle(cycle, f"resolved_{outcome}", {**r, "resolution": {"outcome": outcome, "note": note, "level": level}})
    if r.get("worktree") and Path(r["worktree"]).exists():
        gitops.remove_worktree(repo, Path(r["worktree"]), r.get("branch") if outcome == "reverted" else None)
    typer.echo(f"recorded {outcome} for {cycle}")


@skill_app.command("install")
def skill_install(target: list[str] = typer.Option(None, help="claude | codex | cursor | generic (default: detect)")):
    """Install a thin skill adapter for the host coding agent."""
    repo = _repo()
    for p in skill_mod.install(repo, target or skill_mod.detect(repo)):
        typer.echo(f"wrote {p}")


@app.command()
def optimize(fixtures: list[Path] = typer.Option(None, help="benchmark fixture repos (must be evoloop-initialized)"),
             patch: str = typer.Option("{}", help='JSON strategy patch, e.g. {"search":{"branches":4}}')):
    """Experimental meta-loop: benchmark a strategy mutation against the baseline (mock provider only)."""
    repo = _repo()
    cfg = Config.load(repo)
    if not cfg.optimize.enabled:
        typer.echo("optimize is disabled (set optimize.enabled: true in .evoloop/config.yaml)", err=True)
        raise typer.Exit(2)
    from . import optimize as O
    fx = fixtures or [repo]
    base = O.run_benchmark(fx, O.Strategy(), lambda: make_provider("mock"))
    strat = O.mutate(json.loads(patch))
    cand = O.run_benchmark(fx, strat, lambda: make_provider("mock"))
    kept = cand.dominates(base)
    p = O.archive(repo, strat, base, cand, kept)
    typer.echo(f"baseline={base}\ncandidate={cand}\nkept={kept}\narchived {p}")


@app.command()
def version():
    typer.echo(__version__)
