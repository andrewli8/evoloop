"""Experimental meta-loop foundations: mutate EvolveLoop's *strategy*, never its evaluator.

Strategy (mutable): search params, loop counts, prompt overrides, model routing.
Immutable: safety rules, delivery permissions, evaluation harness, benchmark truth, risk gates, hard limits.
Benchmarks run against fixed fixtures with the mock provider; results are Pareto-compared, never a single scalar.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import EVO_DIR, Config, Mode

MUTABLE = {"search", "loops", "prompts", "models"}
IMMUTABLE = {"enabled", "mode", "auto_merge", "high_risk_terms", "budget", "evidence_sources", "provider", "optimize"}
HARD_LIMITS = {"search.branches": 8, "search.candidates_per_branch": 3, "search.finalists": 5,
               "search.stakeholder_roles": 6, "search.opportunities": 8, "loops.refinement": 2, "loops.repair": 3}


class ImmutableViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class Strategy:
    search: dict = field(default_factory=dict)
    loops: dict = field(default_factory=dict)
    prompts: dict = field(default_factory=dict)  # phase -> override text (reserved; not wired in V1)
    models: dict = field(default_factory=dict)

    def apply(self, cfg: Config) -> Config:
        """Return a NEW config with the strategy applied; refuses to touch immutable fields or exceed hard limits."""
        data = cfg.model_dump()
        for section in ("search", "loops"):
            for k, v in getattr(self, section).items():
                key = f"{section}.{k}"
                if k not in data[section]:
                    raise ImmutableViolation(f"unknown strategy key {key}")
                if key in HARD_LIMITS and v > HARD_LIMITS[key]:
                    raise ImmutableViolation(f"{key}={v} exceeds hard limit {HARD_LIMITS[key]}")
                data[section] = {**data[section], k: v}
        data["models"] = {**data["models"], **self.models}
        return Config.model_validate(data)


def mutate(patch: dict) -> Strategy:
    """Build a strategy from a proposed patch; any immutable key is rejected outright."""
    bad = set(patch) & IMMUTABLE
    if bad or not set(patch) <= MUTABLE:
        raise ImmutableViolation(f"cannot mutate {sorted(bad or set(patch) - MUTABLE)}")
    return Strategy(**patch)


@dataclass(frozen=True)
class Metrics:
    quality: float      # fraction of cycles that reached a decision with a winner or a justified STOP
    correctness: float  # fraction of cycles without error status
    cost: float         # model calls per cycle (lower is better)
    latency: float      # wall seconds per cycle
    safety: float       # 1.0 if no gate/contract/immutable violation observed

    def dominates(self, other: "Metrics") -> bool:
        better_or_equal = (self.quality >= other.quality and self.correctness >= other.correctness and self.cost <= other.cost
                           and self.latency <= other.latency and self.safety >= other.safety)
        strictly = (self.quality > other.quality or self.correctness > other.correctness or self.cost < other.cost
                    or self.latency < other.latency or self.safety > other.safety)
        return better_or_equal and strictly


def run_benchmark(fixture_repos: list[Path], strategy: Strategy, provider_factory) -> Metrics:
    """Run one analyze cycle per fixture with the strategy applied. Evaluator (this function) is not part of the strategy."""
    from .cycle import run_cycle
    results, t = [], time.time()
    for repo in fixture_repos:
        cfg = strategy.apply(Config.load(repo))
        results.append(run_cycle(repo, cfg, provider_factory(), Mode.ANALYZE))
    n = max(1, len(results))
    ok = [r for r in results if r.get("status") not in ("error", "budget_exhausted")]
    decided = [r for r in ok if r.get("winner") or r.get("stop_reason", "").startswith("insufficient evidence")
               or r.get("decision") == "STOP"]
    return Metrics(quality=len(decided) / n, correctness=len(ok) / n,
                   cost=sum(r.get("usage", {}).get("model_calls", 0) for r in results) / n,
                   latency=(time.time() - t) / n,
                   safety=1.0 if all(r.get("gate", {}).get("contract_unchanged", True) for r in results) else 0.0)


def archive(repo: Path, strategy: Strategy, baseline: Metrics, candidate: Metrics, kept: bool) -> Path:
    d = repo / EVO_DIR / "optimize"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    p.write_text(json.dumps({"strategy": strategy.__dict__, "baseline": baseline.__dict__, "candidate": candidate.__dict__, "kept": kept}, indent=1))
    return p
