---
name: evoloop
description: Run EvolveLoop, a bounded evidence-driven product improvement cycle, when asked to find or build the next valuable product improvement, or when asked "what should we improve next".
---

# EvolveLoop (thin adapter — the `evoloop` CLI is the source of truth)

What it is: a finite cycle — observe evidence → problem → stakeholders → diverse solution branches → tournament →
adversarial review → decide (STOP / RECOMMEND / BUILD) → verify → learn. One intervention per cycle, max.

When to invoke: user asks what to improve, wants a grounded product recommendation, or asks to run an improvement cycle.
Do NOT invoke for ordinary feature requests the user already specified.

How to run:
- `evoloop status` — mode, enabled, last cycles, anything awaiting a human.
- `evoloop analyze` — recommendation only (no code changes). Default.
- `evoloop build <cycle> [--pick cN]` — implement a recommendation the user approved from a previous report (isolated branch, verification, review, gate).
- `evoloop run --mode plan|build|pr` — only if the user asked for that mode. Never pass a mode the user did not ask for.
- `evoloop resolve <cycle> --outcome kept|reverted --note "..."` — after the human decides.

Inspect results: `.evoloop/runs/<cycle>/report.md` (human) and `result.json` (machine). Do not paste raw logs into chat.

Rules you must respect:
- The Evaluation Contract at `.evoloop/runs/<cycle>/contract.json` is read-only during an experiment. Never edit it.
- Delivery modes are set by the human via `.evoloop/config.yaml`; never enable, merge, deploy, or raise permissions yourself.
- Stakeholder evaluations are simulated. Never describe them as customer validation.
- If `evoloop` reports disabled/paused, stop and tell the user why.
