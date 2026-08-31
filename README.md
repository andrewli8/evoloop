# EvolveLoop

A bounded, evidence-driven product improvement loop you can drop into any git repository.

```
observe → find problems → explore diverse interventions → evaluate → build one winner → verify → learn → repeat
```

EvolveLoop uses AI for search and judgment, ordinary software for control and verification, and real-world evidence for truth. It is closer to an `autoresearch` loop for product engineering than to an agent framework: one finite `runCycle()`, at most one intervention per cycle, everything inspectable on disk.

## Quick start

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), and one model provider. The easiest is a coding-agent CLI you already have: [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude`) or [Codex](https://github.com/openai/codex) (`codex`). Without one, set `ANTHROPIC_API_KEY` (analyze/plan only, no code changes).

```bash
uv tool install git+https://github.com/andrewli8/evoloop   # installs the `evoloop` command

cd your-repo
evoloop init          # scans the repo, writes .evoloop/, picks the provider it finds
evoloop analyze       # one cycle: problem -> opportunities -> finalists -> recommendation
```

`init` prints what it detected. Check three things before the first real run:

1. **Provider line.** The last line of `init` output says which provider it chose. If it says `mock`, no `claude`/`codex`/API key was found; every model call returns placeholder text and the report is meaningless. Fix by installing one and editing `provider:` in `.evoloop/config.yaml`.
2. **Commands.** `init` infers `test`, `lint`, `typecheck`, `build`. If any are missing or wrong, edit `commands:` in `.evoloop/config.yaml`. Build mode refuses to deliver anything that fails these.
3. **Evidence.** The scan only sees `TODO`s, fix commits, open GitHub issues and pain words in docs. Real feedback beats all of that: drop support tickets, user quotes, or analytics notes into `.evoloop/evidence/*.md`, one item per line.

Optional model routing in `config.yaml` (Claude Code aliases shown; omit to use the CLI's default model for everything):

```yaml
provider: claude-cli
models: {fast: haiku, reasoning: sonnet, coding: sonnet, review: sonnet}
```

A real analyze cycle makes 8–10 model calls. Through a CLI agent that is 3–10 minutes, mostly process startup. Read the result in `.evoloop/runs/<cycle>/report.md`.

Then, when you trust a recommendation:

```bash
evoloop build <cycle>            # implement that cycle's winner: isolated branch, verify, review, gate
evoloop build <cycle> --pick c3  # or one of its other opportunities (ids in the report)
evoloop run --mode plan          # search + implementation spec in one cycle
evoloop run --mode build         # + isolated branch, implementation, verification
evoloop run --mode pr            # + push branch and open a PR (never merges)
evoloop status
evoloop resolve <cycle> --outcome kept|reverted --note "..."
evoloop disable                  # guarantees zero model calls
evoloop skill install            # thin adapter so Claude Code / Codex / Cursor know how to call it
evoloop optimize                 # experimental meta-loop, off by default
```

Your application never depends on EvolveLoop. Everything it writes lives in `.evoloop/`.

```
.evoloop/
├── config.yaml      # mode, provider, search bounds, budgets, commands  (commit this)
├── project.json     # Project Context Pack, every fact tagged observed|inferred|unknown
├── evals.yaml       # real product metrics, if you have any
├── skill.md         # source for `evoloop skill install`
├── evidence/        # drop support tickets / analytics notes here (observed evidence)
├── state.sqlite     # knowledge graph + cycles + lock        (gitignored)
├── runs/<cycle>/    # report.md, result.json, contract.json, logs (gitignored)
└── worktrees/       # one git worktree per build cycle        (gitignored)
```

## Inside your coding agent (session mode)

EvolveLoop also ships as a Claude Code / Codex plugin, the same shape as `caveman` or `ponytail`: a session level the agent obeys, switched with a slash command.

```
/plugin marketplace add andrewli8/evoloop
/plugin install evoloop@evoloop
```

| level   | what the agent does |
|---------|---------------------|
| `off`   | dormant; never invokes evoloop |
| `full`  | runs `evoloop analyze` when you ask, walks you through the report, implements the one you approve with `evoloop build <cycle>`, obeys contracts and gates (default) |
| `ultra` | full, plus after each finished task runs one `evoloop run` (mode from `config.yaml`) until a cycle pauses, blocks or awaits you |

`/evoloop off|full|ultra` switches for the session, `/evoloop default <level>` persists it (`~/.config/evoloop/config.json`, or `EVOLOOP_DEFAULT_MODE`), "stop evoloop" turns it off. On session start the hook also injects `evoloop status` when the current repo is initialized, so the agent knows about cycles awaiting you. The plugin never raises a delivery mode; `build`/`pr` still come from `.evoloop/config.yaml` that you edit.

**On a cadence.** Inside Claude Code, `/loop 30m /evoloop:evoloop-cycle` runs one cycle every 30 minutes for the life of the session; ticks while a build is `awaiting_human` cost zero model calls and just remind you to resolve. Unattended, use cron or CI on the CLI directly: `*/30 * * * * cd /repo && evoloop run` (with `mode: build` or `pr` in `config.yaml`); the plugin is not involved and nothing merges without you.

Without the plugin, `evoloop skill install` writes a thin `SKILL.md` / `AGENTS.md` section that teaches the host agent the same rules.

## Providers

Set `provider` in `config.yaml`:

| provider     | needs                | can build code |
|--------------|----------------------|----------------|
| `mock`       | nothing              | placeholder output, tests only |
| `claude-cli` | `claude` on PATH     | yes            |
| `codex-cli`  | `codex` on PATH      | yes            |
| `anthropic`  | `ANTHROPIC_API_KEY`  | no (analyze/plan only) |

`init` picks the first of `claude-cli`, `codex-cli`, `anthropic` it finds and falls back to `mock`. Roles `fast`, `reasoning`, `coding`, `review` can each be mapped to a model in `models:`; by default the provider's default model is used for all.

## What one cycle does

1. **Observe** (deterministic): refresh the context pack from `git diff`, collect evidence from sources that exist: `TODO`/`FIXME`, fix commits, open GitHub issues, pain words in docs, your notes in `.evoloop/evidence/`, outcomes of previous cycles. Evidence is classed `observed > inferred > hypothetical > simulated`.
2. **Problem search** (1 fast call): problems must cite evidence ids; uncited ones are dropped. No evidence → the cycle stops with *insufficient evidence* and makes no further calls.
3. **Stakeholders** (1 fast call): 2–4 roles inferred from the repo and problem. Simulated, never customer validation.
4. **Solution branching** (1 reasoning call): ≤5 neighborhoods that differ in mechanism, ≤2 candidates each, one branch must be "no software". Deterministic dedup against this batch and archived candidates.
5. **Cheap tournament** (1 fast call + deterministic ranking): keep ~5 opportunities. One refinement pass only if candidates are weak or homogeneous.
6. **Finalist evaluation** (1 fast call per stakeholder): 3 finalists scored on pain fit, utility, behaviour change, friction, new work, failure cases.
7. **Adversarial review** (1 reasoning call, separate critic system prompt): symptom vs cause, simpler alternative, who loses, new failure modes.
8. **Decision** (deterministic): `STOP`, `RECOMMEND`, or `BUILD`. Analyze/plan modes never build. High-risk areas (auth, billing, migrations, deletes, secrets) are always human-gated.
9. **Build** (build/pr modes): freeze an **Evaluation Contract** outside the worktree, create `evoloop/<cycle>` worktree, record baseline, write spec, implement via the coding agent, run typecheck → lint → test → build with ≤2 repair iterations, independent diff review, stakeholder recheck of the implemented behaviour, then the delivery gate. Anything failing leaves the branch for inspection and blocks delivery.
10. **Learn**: one compact lesson node; no chain-of-thought stored.

A built cycle ends in `awaiting_human`; further cycles pause until `evoloop resolve`.

## Bounds and budget (config.yaml)

```yaml
search: {max_problems: 5, deep_problems: 2, branches: 5, candidates_per_branch: 2, opportunities: 5, finalists: 3, stakeholder_roles: 4}
loops:  {refinement: 1, repair: 2}
budget: {max_model_calls: 40, max_tokens: 300000}
```

A typical analyze cycle is 8–10 model calls. Each run records calls, tokens, wall time and candidate counts. The budget counts uncached input and output tokens; prompt-cache reads (mostly the host CLI's own system prompt) are reported separately and not budgeted.

## Claims

Without a real metric EvolveLoop only ever claims a change *passed engineering verification*, *passed simulated evaluation*, and *is recommended for real validation*. Level-3 (real outcome) evidence enters only through `evoloop resolve --level 3`.

## Meta-loop (experimental, disabled)

`evoloop optimize` benchmarks a strategy mutation (search bounds, loop counts, model routing) against the baseline on fixture repos with the mock provider and keeps it only on Pareto improvement across quality, correctness, cost, latency and safety. Safety rules, delivery permissions, risk terms, budgets and the evaluator itself are immutable and any patch touching them is rejected.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
```

Tests use the mock provider and synthetic git repos; no network, no paid calls.
