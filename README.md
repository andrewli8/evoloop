# EvolveLoop

A bounded, evidence-driven product improvement loop you can drop into any git repository.

```
observe → find problems → explore diverse interventions → evaluate → build one winner → verify → learn → repeat
```

EvolveLoop uses AI for search and judgment, ordinary software for control and verification, and real-world evidence for truth. It is closer to an `autoresearch` loop for product engineering than to an agent framework: one finite `runCycle()`, at most one intervention per cycle, everything inspectable on disk.

## Install and run

```bash
uv tool install evolveloop       # PyPI name is evolveloop; the command is `evoloop`
# or, from a checkout: uv tool install /path/to/evoloop
cd your-repo
evoloop init                     # inspects the repo, writes .evoloop/
evoloop analyze                  # one cycle, recommendation only (default mode)
evoloop run --mode plan          # + implementation spec
evoloop run --mode build         # + isolated branch, implementation, verification
evoloop run --mode pr            # + push branch and open a PR (never merges)
evoloop status
evoloop resolve <cycle> --outcome kept|reverted --note "..."
evoloop disable                  # guarantees zero model calls
evoloop skill install            # thin adapter for Claude Code / Codex / Cursor
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

## Providers

Set `provider` in `config.yaml`:

| provider     | needs                | can build code |
|--------------|----------------------|----------------|
| `mock`       | nothing              | yes (fake)     |
| `claude-cli` | `claude` on PATH     | yes            |
| `codex-cli`  | `codex` on PATH      | yes            |
| `anthropic`  | `ANTHROPIC_API_KEY`  | no (analyze/plan only) |

Roles `fast`, `reasoning`, `coding`, `review` can each be mapped to a model in `models:`; by default the provider's default model is used for all.

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

A typical analyze cycle is 8–10 model calls. Each run records calls, tokens, wall time and candidate counts.

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
