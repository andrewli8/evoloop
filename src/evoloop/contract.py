"""Evaluation Contract: frozen before an experiment; implementation cannot alter it.

Stored outside the worktree (.evoloop/runs/<cycle>/contract.json) with its sha256 in state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field


class EvaluationContract(BaseModel):
    cycle: str
    intervention_id: str
    hypothesis: str
    acceptance_criteria: list[str]
    target_metric: str | None = None
    guardrail_metrics: list[str] = Field(default_factory=list)
    deterministic_checks: list[str] = Field(default_factory=list)
    experiment_protocol: str = "engineering verification + simulated stakeholder evaluation; real validation pending"
    risk: str = "low"  # low | medium | high (high => human gated)
    rollback_condition: str = "any deterministic check fails or review blocks"

    model_config = {"frozen": True}

    def canonical(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True)

    def sha(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


def freeze(contract: EvaluationContract, run_dir: Path, state) -> str:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "contract.json").write_text(contract.canonical())
    state.freeze_contract(contract.cycle, contract.sha(), contract.canonical())
    return contract.sha()


def verify_unchanged(run_dir: Path, state, cycle: str) -> bool:
    p = run_dir / "contract.json"
    if not p.exists():
        return False
    return hashlib.sha256(p.read_text().encode()).hexdigest() == state.contract_sha(cycle)


def classify_risk(text: str, terms: list[str]) -> str:
    low = text.lower()
    hits = [t for t in terms if t in low]
    return "high" if hits else "low"
