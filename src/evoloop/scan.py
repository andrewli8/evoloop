"""Deterministic repository inspection -> Project Context Pack (.evoloop/project.json).

Reads manifests, structure and targeted greps only. Every fact carries a status:
observed (read from a file), inferred (heuristic), unknown.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import EVO_DIR, Commands

MANIFESTS = {
    "package.json": "javascript", "pyproject.toml": "python", "requirements.txt": "python",
    "go.mod": "go", "Cargo.toml": "rust", "Gemfile": "ruby", "pom.xml": "java", "build.gradle": "java",
    "composer.json": "php", "mix.exs": "elixir", "Package.swift": "swift",
}
LOCKS = {"pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lockb": "bun", "bun.lock": "bun",
         "package-lock.json": "npm", "uv.lock": "uv", "poetry.lock": "poetry", "Pipfile.lock": "pipenv",
         "go.sum": "go", "Cargo.lock": "cargo", "Gemfile.lock": "bundler"}
SIGNALS = {  # dependency name -> capability label
    "posthog": "analytics", "@segment": "analytics", "mixpanel": "analytics", "amplitude": "analytics",
    "sentry": "error tracking", "@sentry": "error tracking", "launchdarkly": "feature flags", "unleash": "feature flags",
    "growthbook": "feature flags", "celery": "background jobs", "bullmq": "background jobs", "sidekiq": "background jobs",
    "rq": "background jobs", "inngest": "background jobs", "trigger.dev": "background jobs", "prisma": "orm",
    "drizzle": "orm", "sqlalchemy": "orm", "django": "framework", "next": "framework", "fastapi": "framework",
    "express": "framework", "rails": "framework", "expo": "mobile", "react-native": "mobile", "stripe": "billing",
    "supabase": "backend-as-a-service", "playwright": "e2e tests", "cypress": "e2e tests", "pytest": "tests",
    "vitest": "tests", "jest": "tests",
}
AGENT_FILES = ["CLAUDE.md", "AGENTS.md", ".cursorrules", ".github/copilot-instructions.md", "GEMINI.md"]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__", ".next", EVO_DIR}
ROLE_WORDS = ["admin", "customer", "user", "manager", "operator", "worker", "agent", "client", "owner",
              "member", "guest", "reviewer", "moderator", "developer", "merchant", "driver", "patient", "student", "teacher"]


def fact(value, status: str):
    return {"value": value, "status": status}


def _read(p: Path, limit: int = 20000) -> str:
    try:
        return p.read_text(errors="ignore")[:limit]
    except OSError:
        return ""


def _git_head(repo: Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    return r.stdout.strip() or None


def _deps(repo: Path) -> set[str]:
    deps: set[str] = set()
    pj = repo / "package.json"
    if pj.exists():
        try:
            d = json.loads(_read(pj))
            for k in ("dependencies", "devDependencies"):
                deps |= set(d.get(k, {}))
        except json.JSONDecodeError:
            pass
    for name in ("pyproject.toml", "requirements.txt", "Gemfile", "go.mod", "Cargo.toml"):
        p = repo / name
        if p.exists():
            txt = _read(p)
            deps |= set(re.findall(r'^\s*"?([A-Za-z0-9_.@/-]+)', txt, re.M))
            deps |= set(re.findall(r'"([A-Za-z0-9_.-]+)\s*[>=<~!\[";]', txt))  # quoted entries in dependency lists
    return {d.lower() for d in deps}


def _commands(repo: Path, deps: set[str]) -> Commands:
    c = Commands()
    pj = repo / "package.json"
    if pj.exists():
        try:
            scripts = json.loads(_read(pj)).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        pm = next((v for k, v in LOCKS.items() if (repo / k).exists() and v in ("pnpm", "yarn", "bun", "npm")), "npm")
        run = f"{pm} run" if pm != "npm" else "npm run"
        for key, names in (("test", ["test"]), ("build", ["build"]), ("lint", ["lint"]), ("typecheck", ["typecheck", "type-check", "tsc"])):
            for n in names:
                if n in scripts:
                    setattr(c, key, f"{run} {n}")
                    break
    if (repo / "pyproject.toml").exists() or (repo / "requirements.txt").exists():
        runner = "uv run " if (repo / "uv.lock").exists() else ""
        if "pytest" in deps or (repo / "tests").exists():
            c.test = c.test or f"{runner}pytest -q"
        if "ruff" in deps:
            c.lint = c.lint or f"{runner}ruff check ."
        if "mypy" in deps:
            c.typecheck = c.typecheck or f"{runner}mypy ."
    if (repo / "go.mod").exists():
        c.test, c.build = c.test or "go test ./...", c.build or "go build ./..."
    if (repo / "Cargo.toml").exists():
        c.test, c.build = c.test or "cargo test", c.build or "cargo build"
    mk = repo / "Makefile"
    if mk.exists():
        targets = set(re.findall(r"^([a-zA-Z_-]+):", _read(mk), re.M))
        for key in ("test", "build", "lint"):
            if key in targets and getattr(c, key) is None:
                setattr(c, key, f"make {key}")
    return c


def _entities(repo: Path) -> list[str]:
    pats = [r"^\s*model\s+(\w+)\s*\{", r"^class\s+(\w+)\(.*(?:Model|Base|BaseModel)\)", r"^\s*(?:export\s+)?(?:interface|type)\s+([A-Z]\w+)\b",
            r"^\s*create_table\s+[\"':](\w+)", r"^\s*type\s+([A-Z]\w+)\s+struct"]
    found: dict[str, int] = {}
    for p in _walk(repo, {".prisma", ".py", ".ts", ".tsx", ".rb", ".go"}, max_files=400):
        txt = _read(p, 40000)
        for pat in pats:
            for m in re.findall(pat, txt, re.M):
                found[m] = found.get(m, 0) + 1
    return sorted(found, key=lambda k: -found[k])[:25]


def _walk(repo: Path, exts: set[str], max_files: int):
    n = 0
    for p in sorted(repo.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix in exts:
            yield p
            n += 1
            if n >= max_files:
                return


def _docs(repo: Path) -> dict:
    headings, roles, text = [], {}, ""
    files = [repo / "README.md"] + (sorted((repo / "docs").glob("*.md"))[:10] if (repo / "docs").exists() else [])
    for p in files:
        if p.exists():
            t = _read(p)
            text += t + "\n"
            headings += [h.strip() for h in re.findall(r"^#{1,3}\s+(.+)$", t, re.M)]
    low = text.lower()
    for w in ROLE_WORDS:
        c = len(re.findall(rf"\b{w}s?\b", low))
        if c >= 2:
            roles[w] = c
    return {"headings": headings[:40], "roles": sorted(roles, key=lambda k: -roles[k])[:8], "has_readme": (repo / "README.md").exists()}


WORKSPACE_DIRS = ("apps", "packages", "services", "libs")


def _workspaces(repo: Path) -> list[Path]:
    """Sub-projects with their own manifest when the root has none (monorepo without a root package)."""
    return [d for w in WORKSPACE_DIRS if (repo / w).is_dir()
            for d in sorted((repo / w).iterdir()) if d.is_dir() and any((d / m).exists() for m in MANIFESTS)]


def _join(cmds: list[str]) -> str | None:
    # ponytail: chained subshells; split into per-workspace commands if a monorepo needs parallel runs
    return " && ".join(f"(cd {c[0]} && {c[1]})" for c in cmds) or None


def scan(repo: Path) -> dict:
    manifests = [m for m in MANIFESTS if (repo / m).exists()]
    roots = [repo] if manifests else _workspaces(repo)
    ws_rel = [str(r.relative_to(repo)) for r in roots if r != repo]
    manifests = sorted({m for r in roots for m in MANIFESTS if (r / m).exists()})
    langs = sorted({MANIFESTS[m] for m in manifests})
    pm = sorted({v for r in roots for k, v in LOCKS.items() if (r / k).exists()})
    deps = set().union(*(_deps(r) for r in roots)) if roots else set()
    caps = sorted({label for dep, label in SIGNALS.items() if any(d == dep or d.startswith(dep + "/") or d.startswith(dep + "-") for d in deps)})
    dirs = sorted(p.name for p in repo.iterdir() if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith("."))
    ci = [p.name for p in (repo / ".github" / "workflows").glob("*.y*ml")] if (repo / ".github" / "workflows").exists() else []
    agents = [a for a in AGENT_FILES if (repo / a).exists()]
    docs = _docs(repo)
    entities = _entities(repo)
    if ws_rel:
        per = {w: _commands(repo / w, _deps(repo / w)).model_dump() for w in ws_rel}
        cmds = Commands(**{k: _join([(w, c[k]) for w, c in per.items() if c[k]]) for k in ("build", "test", "lint", "typecheck")})
    else:
        cmds = _commands(repo, deps)
    return {
        "git_head": _git_head(repo),
        "workspaces": fact(ws_rel, "observed" if ws_rel else "unknown"),
        "languages": fact(langs, "observed" if langs else "unknown"),
        "package_manager": fact(pm, "observed" if pm else "unknown"),
        "manifests": fact(manifests, "observed"),
        "directories": fact(dirs, "observed"),
        "capabilities": fact(caps, "inferred" if caps else "unknown"),
        "ci": fact(ci, "observed" if ci else "unknown"),
        "commands": fact(cmds.model_dump(), "inferred" if any(cmds.model_dump().values()) else "unknown"),
        "entities": fact(entities, "inferred" if entities else "unknown"),
        "roles": fact(docs["roles"], "inferred" if docs["roles"] else "unknown"),
        "workflows": fact(docs["headings"], "inferred" if docs["headings"] else "unknown"),
        "agent_instructions": fact(agents, "observed" if agents else "unknown"),
        "documentation": fact({"readme": docs["has_readme"], "docs_dir": (repo / "docs").exists()}, "observed"),
        "architecture": fact(None, "unknown"),
        "changed_since_scan": [],
    }


def refresh(repo: Path, pack: dict) -> dict:
    """Update the pack from git changes since last scan; full rescan only if manifests changed."""
    head = _git_head(repo)
    old = pack.get("git_head")
    if not head or not old or head == old:
        return pack
    r = subprocess.run(["git", "diff", "--name-only", old, head], cwd=repo, capture_output=True, text=True)
    changed = [l for l in r.stdout.splitlines() if l and not l.startswith(EVO_DIR + "/")]
    if any(Path(c).name in MANIFESTS or Path(c).name in LOCKS for c in changed):
        return scan(repo)
    return {**pack, "git_head": head, "changed_since_scan": (pack.get("changed_since_scan", []) + changed)[-200:]}


def summary(pack: dict) -> str:
    """Compact text for prompts (a few hundred tokens, not the repo)."""
    g = lambda k: pack.get(k, {}).get("value")  # noqa: E731
    lines = [f"languages: {g('languages')} ({pack['languages']['status']})",
             f"package manager: {g('package_manager')}",
             f"directories: {g('directories')}",
             f"capabilities: {g('capabilities')} ({pack['capabilities']['status']})",
             f"commands: {g('commands')}",
             f"entities (inferred): {g('entities')}",
             f"roles (inferred): {g('roles')}",
             f"workflows/doc headings (inferred): {(g('workflows') or [])[:20]}",
             f"agent instructions: {g('agent_instructions')}",
             f"recently changed files: {pack.get('changed_since_scan', [])[-20:]}"]
    return "\n".join(lines)


def load_pack(repo: Path) -> dict:
    return json.loads((repo / EVO_DIR / "project.json").read_text())


def save_pack(repo: Path, pack: dict) -> None:
    (repo / EVO_DIR / "project.json").write_text(json.dumps(pack, indent=1))


def describe(pack: dict) -> str:
    """Human summary for `evoloop init`: only what was found, plus what to check."""
    g = lambda k: pack.get(k, {}).get("value")  # noqa: E731
    fmt = lambda v: ", ".join(map(str, v)) if isinstance(v, list) else str(v)  # noqa: E731
    rows = [("Language", g("languages")), ("Package manager", g("package_manager")), ("Workspaces", g("workspaces")),
            ("Capabilities", g("capabilities")), ("CI", g("ci")), ("Agent instructions", g("agent_instructions")),
            ("Roles (inferred)", g("roles")), ("Entities (inferred)", (g("entities") or [])[:8])]
    L = ["Found:"] + [f"  {k:<20} {fmt(v)}" for k, v in rows if v]
    cmds = {k: v for k, v in (g("commands") or {}).items() if v}
    L += ["Commands:"] + ([f"  {k:<10} {v}" for k, v in cmds.items()] or ["  none detected"])
    missing = [k for k in ("test", "lint", "typecheck", "build") if k not in cmds]
    L += ["", "Next:"]
    if missing:
        L += [f"  - set {', '.join(missing)} under commands: in .evoloop/config.yaml (verification needs at least test)"]
    L += ["  - drop real feedback/tickets into .evoloop/evidence/*.md (observed evidence ranks highest)",
          "  - choose a provider in .evoloop/config.yaml (mock | claude-cli | codex-cli | anthropic)",
          "  - run `evoloop analyze`"]
    return "\n".join(L)
