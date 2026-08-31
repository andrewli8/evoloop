no PyPI release yet: users must install from git; `uvx evolveloop` does not work
init does not detect lint/typecheck/build for python projects without ruff/mypy config; verification then runs tests only
[observed] the binding constraint on evidence quality is that this project has no published release and no users yet: issues source (gh issue list) exists but the repo has zero issues, analytics feeds exist via --evidence-json but nothing emits data. This is not solvable by more intake code; it needs a PyPI release and real users. Do not propose further evidence adapters until data exists.
codex-cli adapter reports zero token usage, so budgets cannot be enforced for it
screening decisions (dedup drops, risk escalations) are not logged per cycle, so screening misses are invisible until someone notices a duplicate build
meta-loop (optimize) has no mutation proposer; strategies must be hand-written JSON
user wants README updated after each improvement and a running TL;DR release-notes doc kept
[observed] design decision 2026-08-31: shell execution for evidence intake is restricted to the human-typed CLI flag (`--evidence-json cmd:...`) on purpose; a cloned repo's config must never cause command execution. Do not propose re-enabling config-driven or agent-relayed execution of config-declared commands.
