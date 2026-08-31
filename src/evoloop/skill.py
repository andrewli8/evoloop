"""Thin skill adapters for host coding agents. The CLI stays the source of truth."""
from __future__ import annotations

from pathlib import Path

from .config import EVO_DIR

SKILL = """---
name: evoloop
description: Run EvolveLoop, a bounded evidence-driven product improvement cycle, when asked to find or build the next valuable product improvement, or when asked "what should we improve next".
---

# EvolveLoop (thin adapter — the `evoloop` CLI is the source of truth)

What it is: a finite cycle — observe evidence → problem → stakeholders → diverse solution branches → tournament →
adversarial review → decide (STOP / RECOMMEND / BUILD) → verify → learn. One intervention per cycle, max.

When to invoke: user asks what to improve, wants a grounded product recommendation, or asks to run an improvement cycle.
Do NOT invoke for ordinary feature requests the user already specified.

How to run:
- `evoloop status` — mode, enabled, last cycles, anything awaiting a human.
- `evoloop analyze` — recommendation only (no code changes). Default.
- `evoloop run --mode plan|build|pr` — only if the user asked for that mode. Never pass a mode the user did not ask for.
- `evoloop resolve <cycle> --outcome kept|reverted --note "..."` — after the human decides.

Inspect results: `.evoloop/runs/<cycle>/report.md` (human) and `result.json` (machine). Do not paste raw logs into chat.

Rules you must respect:
- The Evaluation Contract at `.evoloop/runs/<cycle>/contract.json` is read-only during an experiment. Never edit it.
- Delivery modes are set by the human via `.evoloop/config.yaml`; never enable, merge, deploy, or raise permissions yourself.
- Stakeholder evaluations are simulated. Never describe them as customer validation.
- If `evoloop` reports disabled/paused, stop and tell the user why.
"""

TARGETS = {
    "claude": Path(".claude") / "skills" / "evoloop" / "SKILL.md",
    "codex": Path("AGENTS.md"),
    "cursor": Path(".cursor") / "rules" / "evoloop.mdc",
    "generic": Path("AGENTS.md"),
}


def detect(repo: Path) -> list[str]:
    found = []
    if (repo / ".claude").exists() or (repo / "CLAUDE.md").exists():
        found.append("claude")
    if (repo / "AGENTS.md").exists():
        found.append("codex")
    if (repo / ".cursor").exists():
        found.append("cursor")
    return found or ["generic"]


def install(repo: Path, targets: list[str]) -> list[Path]:
    src = repo / EVO_DIR / "skill.md"
    text = src.read_text() if src.exists() else SKILL
    written = []
    for t in targets:
        dest = repo / TARGETS[t]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.name == "AGENTS.md":
            body = text.split("---", 2)[-1].strip()  # strip frontmatter for a plain markdown section
            existing = dest.read_text() if dest.exists() else ""
            if "# EvolveLoop" not in existing:
                dest.write_text(existing.rstrip() + ("\n\n" if existing else "") + body + "\n")
        else:
            dest.write_text(text)
        written.append(dest)
    return written
