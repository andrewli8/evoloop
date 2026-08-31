"""Verification-strength report for inferred gate commands (pure; no I/O)."""
from __future__ import annotations

GATES = ("test", "lint", "typecheck", "build")

REMEDIATION = {
    "python": [
        "    lint:      uv add --dev ruff && uv run ruff check .",
        "    typecheck: uv add --dev mypy && uv run mypy src",
    ],
}


def verification_strength(commands: dict, languages: list[str] | None = None) -> tuple[str, list[str]]:
    """Classify gate signals: strong (3+), moderate (2), weak (<=1). Returns (label, report lines)."""
    present = [g for g in GATES if commands.get(g)]
    label = "strong" if len(present) >= 3 else "moderate" if len(present) == 2 else "weak"
    lines = [f"Verification strength: {label} ({len(present)}/{len(GATES)} gate signals)"]
    lines += [f"  [{'x' if commands.get(g) else ' '}] {g}: {commands.get(g) or '(not detected)'}" for g in GATES]
    if label == "weak":
        lines += ["  WARNING: verification is tests-only; weak changes can pass the delivery gate."]
    missing = [g for g in GATES if not commands.get(g)]
    if missing:
        lines += ["  To add more gate signals:"]
        for lang in languages or []:
            lines += REMEDIATION.get(lang, [])
        lines += ["    or set them manually under commands: in .evoloop/config.yaml"]
    return label, lines
