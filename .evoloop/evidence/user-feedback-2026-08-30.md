no PyPI release yet: users must install from git; `uvx evolveloop` does not work
init does not detect lint/typecheck/build for python projects without ruff/mypy config; verification then runs tests only
[observed] the binding constraint on evidence quality is that this project has no published release and no users yet: issues source (gh issue list) exists but the repo has zero issues, analytics feeds exist via --evidence-json but nothing emits data. This is not solvable by more intake code; it needs a PyPI release and real users. Do not propose further evidence adapters until data exists.
codex-cli adapter reports zero token usage, so budgets cannot be enforced for it
report.md shows screened/dropped counts, but not WHICH candidate was dropped against which match, nor which risk signal fired; that detail is the residual observability gap
meta-loop (optimize) has no mutation proposer; strategies must be hand-written JSON
user wants README updated after each improvement and a running TL;DR release-notes doc kept
[observed] design decision 2026-08-31: shell execution for evidence intake is restricted to the human-typed CLI flag (`--evidence-json cmd:...`) on purpose; a cloned repo's config must never cause command execution. Do not propose re-enabling config-driven or agent-relayed execution of config-declared commands.
[observed] 2026-08-31 cycle 2ae3: the structured risk classifier flagged a pure report/observability feature as high risk because its surfaces mentioned cli/report internals; surface-based escalation over-fires on this repo's own module names and needs the sensitive-surface list scoped to genuinely dangerous surfaces (auth, billing, migrations, delivery, contract)
