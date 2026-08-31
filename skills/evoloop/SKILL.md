---
name: evoloop
description: >
  Operate EvolveLoop, the bounded evidence-driven product improvement loop (`evoloop` CLI). Use when the user asks what
  to improve next, wants a grounded product recommendation, asks to run an improvement cycle, mentions "evoloop",
  or (in ultra level) when a task is finished and nothing else is queued. Do NOT use for feature requests the user
  already specified.
argument-hint: "[off|full|ultra]"
license: MIT
---

# EvolveLoop

You operate the `evoloop` CLI; it holds the logic, you hold the conversation. One finite cycle:
observe evidence → problem → stakeholders → diverse solution branches → tournament → adversarial review →
decide (STOP / RECOMMEND / BUILD) → verify → learn. One intervention per cycle at most.

## Levels

| level | behaviour |
|-------|-----------|
| off   | dormant; never invoke evoloop |
| full  | run cycles when the user asks; obey contracts, gates and delivery modes (default) |
| ultra | full, plus after each finished task run `evoloop run` until a cycle pauses, blocks or awaits a human |

Switch with `/evoloop off|full|ultra`; `/evoloop default <level>` persists across sessions; "stop evoloop" turns it off.

## Commands

- `evoloop status` — always first. Shows enabled flag, mode, recent cycles, anything awaiting a human.
- `evoloop init` — once per repo. Read its provider line: `mock` means placeholder output; tell the user to install `claude`/`codex` or set `ANTHROPIC_API_KEY` and set `provider:` in `.evoloop/config.yaml`.
- `evoloop analyze` — recommendation only. No code changes.
- `evoloop run --mode plan|build|pr` — only when the user asked for that mode. Never pass a mode the user did not ask for.
- `evoloop resolve <cycle> --outcome kept|reverted --note "..."` — only on the human's instruction.

Read `.evoloop/runs/<cycle>/report.md`; summarize problem, evidence, finalists, winner, verification, gate. Never paste raw logs.

## Hard rules

- The Evaluation Contract (`.evoloop/runs/<cycle>/contract.json`) is read-only once an experiment starts.
- Never edit `.evoloop/config.yaml` to enable, escalate mode, or set `auto_merge`. Never merge, deploy, or push to main.
- Stakeholder evaluations are simulated. Never present them as customer validation.
- `disabled`, `paused`, `awaiting_human`, `blocked`, `budget_exhausted`: stop and tell the user why.
- A cycle through a CLI agent takes minutes; say so before running one.
