"""Typed configuration for .evoloop/config.yaml."""
from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

EVO_DIR = ".evoloop"

HIGH_RISK_TERMS = [
    "auth", "login", "password", "session", "permission", "billing", "payment",
    "stripe", "invoice", "delete", "drop", "migration", "pii", "secret", "token",
    "credential", "encrypt",
]


class Mode(str, Enum):
    OFF = "off"
    ANALYZE = "analyze"
    PLAN = "plan"
    BUILD = "build"
    PR = "pr"
    EXPERIMENT = "experiment"


class Search(BaseModel):
    max_problems: int = 5
    deep_problems: int = 2
    branches: int = 5
    candidates_per_branch: int = 2
    opportunities: int = 5
    finalists: int = 3
    stakeholder_roles: int = 4


class Loops(BaseModel):
    refinement: int = 1
    repair: int = 2


class Budget(BaseModel):
    max_model_calls: int = 40
    max_tokens: int = 300_000


class Commands(BaseModel):
    build: str | None = None
    test: str | None = None
    lint: str | None = None
    typecheck: str | None = None


class Optimize(BaseModel):
    enabled: bool = False


class Evidence(BaseModel):
    external: list[str] = Field(default_factory=list)  # JSON evidence files (or `-`); `cmd:` is refused here, CLI flag only


class Config(BaseModel):
    enabled: bool = True
    mode: Mode = Mode.ANALYZE
    provider: str = "mock"
    models: dict[str, str] = Field(default_factory=dict)  # role -> model id override
    search: Search = Search()
    loops: Loops = Loops()
    budget: Budget = Budget()
    commands: Commands = Commands()
    evidence_sources: list[str] = Field(default_factory=lambda: ["todos", "git_log", "issues", "docs", "notes", "results"])
    evidence: Evidence = Evidence()
    high_risk_terms: list[str] = Field(default_factory=lambda: list(HIGH_RISK_TERMS))
    auto_merge: bool = False  # never flipped by the tool itself
    optimize: Optimize = Optimize()

    @staticmethod
    def path(repo: Path) -> Path:
        return repo / EVO_DIR / "config.yaml"

    @classmethod
    def load(cls, repo: Path) -> "Config":
        p = cls.path(repo)
        if not p.exists():
            raise FileNotFoundError(f"{p} missing; run `evoloop init`")
        return cls.model_validate(yaml.safe_load(p.read_text()) or {})

    def save(self, repo: Path) -> None:
        p = self.path(repo)
        p.parent.mkdir(exist_ok=True)
        p.write_text(yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False))
