"""Machine-readable result.json + concise human report.md per cycle."""
from __future__ import annotations

import json


def write(c) -> None:
    r = c.result
    (c.run_dir / "result.json").write_text(json.dumps(r, indent=1, default=str))
    (c.run_dir / "report.md").write_text(render(r))


def render(r: dict) -> str:
    L = [f"# EvolveLoop cycle {r.get('cycle')} — {r.get('mode')} — decision: {r.get('decision')}", ""]
    if r.get("stop_reason"):
        L += [f"**Outcome:** {r['stop_reason']}", ""]
    p = r.get("problem")
    if p:
        L += ["## Problem", f"**{p['title']}** (workflow: {p.get('workflow')}, evidence score {p.get('evidence_score')})", ""]
        L += ["### Supporting evidence"] + [f"- [{e['class']}] {e['source']} {e['ref']}: {e['text']}" for e in r.get("supporting_evidence", [])] + [""]
    if r.get("stakeholders"):
        L += ["## Stakeholders (simulated, inferred from repo)"] + [f"- **{s.get('role')}**: {s.get('goal')} — pain: {s.get('current_pain')}" for s in r["stakeholders"]] + [""]
    if r.get("branches"):
        L += ["## Solution branches", ", ".join(r["branches"]), f"raw candidates: {r.get('raw_candidates')}, dedup dropped: {r.get('dedup_dropped')}", ""]
    if r.get("opportunities"):
        L += ["## Worthwhile opportunities"] + [f"{i+1}. **{o['title']}** [{o.get('mechanism')}] cheap={o.get('cheap_score')} — {o.get('summary')}"
                                                 for i, o in enumerate(r["opportunities"])] + [""]
    if r.get("finalists"):
        L += ["## Finalists"]
        for f in r["finalists"]:
            a = f.get("adversarial", {})
            L += [f"- **{f['title']}** stakeholder={f.get('stakeholder_score')} verdict={a.get('verdict')} fatal={a.get('fatal')}"
                  f" simpler={a.get('simpler_alternative')} assumption={a.get('key_assumption')}"]
        L += [""]
    w = r.get("winner")
    if w:
        L += ["## Winner", f"**{w['title']}** (risk: {w.get('risk')}) — {w.get('summary')}", ""]
    if r.get("spec"):
        L += ["## Spec", r["spec"].get("spec", ""), "Acceptance: " + "; ".join(r["spec"].get("acceptance", [])), ""]
    if r.get("verification"):
        v = r["verification"]
        L += ["## Verification", f"ok={v.get('ok')} attempts={v.get('attempts')}"] + \
             [f"- {s['step']}: {'pass' if s['ok'] else 'FAIL'} ({s['seconds']}s) `{s['cmd']}`" for s in v.get("steps", [])] + [""]
    if r.get("review"):
        L += ["## Review", f"verdict={r['review'].get('verdict')} blocking={r['review'].get('blocking')} warnings={r['review'].get('warnings')}", ""]
    if r.get("gate"):
        L += ["## Delivery gate", json.dumps(r["gate"]), f"status: {r.get('status')} branch: {r.get('branch')} commit: {r.get('commit')} pr: {r.get('pr')}", ""]
    if r.get("claim"):
        L += [f"> Claim: {r['claim']}. This is NOT customer validation.", ""]
    if r.get("lesson"):
        l = r["lesson"]
        L += ["## Lesson", f"worked: {l.get('what_worked')} | failed: {l.get('what_failed')} | implication: {l.get('reusable_implication')}", ""]
    u = r.get("usage", {})
    L += ["## Usage", f"model calls {u.get('model_calls')} · in {u.get('input_tokens')} · out {u.get('output_tokens')} · wall {u.get('wall_seconds')}s · by role {u.get('by_role')}"]
    return "\n".join(L) + "\n"
