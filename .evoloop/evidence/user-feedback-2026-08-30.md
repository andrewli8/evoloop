no PyPI release yet: users must install from git; `uvx evolveloop` does not work
init does not detect lint/typecheck/build for python projects without ruff/mypy config; verification then runs tests only
no adapter pulls real end-user analytics (PostHog/Sentry-style) automatically; workaround exists via --evidence-json and cmd:, and smoke-running commands covers runtime failures
codex-cli adapter reports zero token usage, so budgets cannot be enforced for it
screening decisions (dedup drops, risk escalations) are not logged per cycle, so screening misses are invisible until someone notices a duplicate build
meta-loop (optimize) has no mutation proposer; strategies must be hand-written JSON
user wants README updated after each improvement and a running TL;DR release-notes doc kept
[observed] design decision 2026-08-31: shell execution for evidence intake is restricted to the human-typed CLI flag (`--evidence-json cmd:...`) on purpose; a cloned repo's config must never cause command execution. Do not propose re-enabling config-driven or agent-relayed execution of config-declared commands.
