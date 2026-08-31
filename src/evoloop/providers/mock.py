"""Deterministic mock provider. Zero network. Routes on the [phase:x] tag at the start of each prompt."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .base import Provider, Role

MECHANISMS = ["remove the problem", "simplify", "automate", "guide", "validate", "no-software/process"]


def _input(prompt: str) -> dict:
    m = re.search(r"INPUT:\s*(\{.*\})", prompt, re.S)
    return json.loads(m.group(1)) if m else {}


def _phase(prompt: str) -> str:
    m = re.match(r"\[phase:(\w+)\]", prompt)
    return m.group(1) if m else "unknown"


class MockProvider(Provider):
    name = "mock"

    def __init__(self, script: dict[str, Callable[[dict], object] | object] | None = None,
                 implement_fn: Callable[[str, Path], str] | None = None, tokens_per_call: int = 500):
        self.script = script or {}
        self.implement_fn = implement_fn
        self.tokens = tokens_per_call
        self.calls: list[tuple[str, str]] = []

    def complete(self, role: Role, system: str, prompt: str) -> tuple[str, int, int]:
        phase, inp = _phase(prompt), _input(prompt)
        self.calls.append((phase, role.value))
        if phase in self.script:
            r = self.script[phase]
            out = r(inp) if callable(r) else r
        else:
            out = getattr(self, f"_{phase}", self._unknown)(inp)
        return (out if isinstance(out, str) else json.dumps(out)), self.tokens, self.tokens // 4

    def implement(self, instructions: str, cwd: Path) -> str:
        self.calls.append(("implement", "coding"))
        if self.implement_fn:
            return self.implement_fn(instructions, cwd)
        (cwd / "EVOLOOP_IMPLEMENTED.md").write_text(instructions[:200])
        return "mock implementation written"

    # --- synthetic but coherent phase outputs ----------------------------------
    def _problem_search(self, inp):
        ev = inp.get("evidence", [])
        n = min(5, max(1, len(ev)))
        return {"problems": [{"title": f"Problem {i+1}: {ev[i]['text'][:40]}" if i < len(ev) else f"Problem {i+1}",
                              "description": "Users hit friction here.", "workflow": "main workflow",
                              "evidence_ids": [ev[i]["id"]] if i < len(ev) else [], "confidence": 0.8 - i * 0.1}
                             for i in range(n)]}

    def _stakeholders(self, inp):
        return {"roles": [{"role": r, "goal": f"{r} goal", "workflow": "main", "current_pain": "friction",
                           "constraints": "time", "likely_behavior": "adopts if easy", "success_condition": "faster",
                           "possible_downside": "more steps", "confidence": "inferred"}
                          for r in ["end user", "maintainer", "operator", "support", "extra"]]}

    def _branches(self, inp):
        want = inp.get("missing_mechanisms") or MECHANISMS
        return {"branches": [{"mechanism": m, "candidates": [
            {"title": f"{m} option A", "summary": f"Address it via {m}.", "mechanism": m, "software_required": m != "no-software/process"},
            {"title": f"{m} option B", "summary": f"Alternative via {m}.", "mechanism": m, "software_required": True}]}
            for m in want]}

    def _cheap_scores(self, inp):
        return {"scores": [{"id": c["id"], "impact": 2 if c.get("software_required") is False else 4 - (i % 3),
                            "effort": 2 + (i % 3), "risk": 1 + (i % 2)} for i, c in enumerate(inp.get("candidates", []))]}

    def _stakeholder_eval(self, inp):
        return {"evaluations": [{"id": c["id"], "pain_fit": 4, "utility": 4, "behavior_change": 3, "adoption_friction": 2,
                                 "new_work": 1, "failure_cases": "edge case", "unintended": "none obvious", "score": 4}
                                for c in inp.get("finalists", [])]}

    def _adversarial(self, inp):
        return {"reviews": [{"id": c["id"], "symptom_only": False, "simpler_alternative": None, "key_assumption": "users care",
                             "loser": "none", "new_failure_mode": "none", "fatal": False, "verdict": "proceed", "confidence": 0.7}
                            for c in inp.get("finalists", [])]}

    def _spec(self, inp):
        return {"spec": "Implement the winner minimally.", "acceptance": ["tests pass"], "files": [], "rollback": "revert branch"}

    def _review(self, inp):
        return {"blocking": [], "warnings": [], "verdict": "approve"}

    def _stakeholder_recheck(self, inp):
        return {"still_solves_problem": True, "tradeoffs": "none", "score": 4}

    def _lesson(self, inp):
        return {"what_worked": "bounded search", "what_failed": "nothing", "reusable_implication": "keep it small", "confidence": 0.6}

    def _unknown(self, inp):
        return {}
