---
name: evoloop-cycle
description: Run exactly one bounded EvolveLoop cycle now and report it. Use for "/evoloop-cycle", "run a cycle", or as the target of a /loop schedule (e.g. /loop 30m /evoloop:evoloop-cycle).
license: MIT
---

Run one bounded cycle and report. Do not start a second one.

1. `evoloop status`. If it prints `awaiting human`, `disabled`, or no `.evoloop/` exists: report that in one line and stop. A cycle awaiting resolution is the human's turn; do not resolve it yourself.
2. `evoloop run` (mode from `.evoloop/config.yaml`; never pass `--mode`). It takes 1–10 minutes.
3. Read `.evoloop/runs/<cycle>/report.md`. Report in under 10 lines: decision, problem, winner or stop reason, and for builds the gate result, branch and review findings. If the branch is `awaiting_human`, say what the human must do (`evoloop resolve <cycle> --outcome kept|reverted`).
4. Stop. Never merge, push to main, edit `.evoloop/config.yaml`, or change the level.
