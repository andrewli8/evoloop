"""Prompt templates. Each prompt starts with a [phase:x] tag and ends with an INPUT: JSON block.
Generator and critic use separate system prompts so authoring output does not judge itself."""
from __future__ import annotations

import json

GENERATOR = ("You are a product engineer helping improve an existing software product. Ground everything in the "
             "provided evidence; never invent facts. Keep every string field under 30 words. Output JSON only, no prose.")
CRITIC = ("You are an independent, skeptical reviewer. You did not write the proposals you are reviewing. Look for "
          "symptoms mistaken for causes, simpler alternatives, hidden losers and new failure modes. Under 30 words per field. JSON only.")
ENGINEER = "You are a careful senior engineer. Smallest coherent change; no unrelated refactoring. JSON only."


def p(phase: str, body: str, inp: dict) -> str:
    return f"[phase:{phase}]\n{body}\nINPUT: {json.dumps(inp)}"


def problem_search(n: int) -> str:
    return (f"From the project context, evidence and past lessons, list up to {n} distinct valuable PROBLEMS users of this "
            "product appear to have NOW (not features). Each must cite evidence ids; drop any problem with no evidence. "
            "A git_log fix commit shows a problem was addressed: cite it only when other evidence shows the problem persists. "
            'Schema: {"problems":[{"title","description","workflow","evidence_ids":[],"confidence":0-1}]}')


def stakeholders(n: int) -> str:
    return (f"Infer the 2-{n} stakeholder roles MATERIALLY affected by this problem. Ordinary, realistic roles grounded in the "
            "product; no generic personas. Schema: "
            '{"roles":[{"role","goal","workflow","current_pain","constraints","likely_behavior","success_condition","possible_downside","confidence":"observed|inferred"}]}')


def branches(n: int, per: int) -> str:
    return (f"Propose up to {n} solution NEIGHBORHOODS for this problem that differ in MECHANISM (e.g. remove the problem, "
            "simplify, automate, guide, validate, predict, communicate, change workflow, change incentives/policy, integrate, "
            "remove an existing feature). Exactly one branch must answer: can this be solved without adding software? "
            f"Give at most {per} candidates per branch. Do not repeat the 'already explored' list. Schema: "
            '{"branches":[{"mechanism","candidates":[{"title","summary","mechanism","software_required":bool}]}]}')


CHEAP_SCORES = ('Score each candidate 1-5 on impact (on the evidenced problem), effort (1=trivial), risk (1=none). '
                'Schema: {"scores":[{"id","impact","effort","risk"}]}')

STAKEHOLDER_EVAL = ('You are the stakeholder described in `role`. Evaluate each finalist from that role only. 1-5 scales, '
                    'adoption_friction and new_work are 1=none 5=severe. Schema: {"evaluations":[{"id","pain_fit","utility",'
                    '"behavior_change","adoption_friction","new_work","failure_cases","unintended","score"}]} where score is your overall 1-5.')

ADVERSARIAL = ('For each finalist answer: are we solving a symptom? is there a substantially simpler intervention (incl. process/config)? '
               'what assumption carries most expected value? which stakeholder loses? what new failure mode appears? will behavior '
               'actually change? how is success distinguished from noise? what would make us regret shipping? Schema: '
               '{"reviews":[{"id","symptom_only":bool,"simpler_alternative":str|null,"key_assumption","loser","new_failure_mode",'
               '"fatal":bool,"verdict":"proceed|revise|reject","confidence":0-1}]}')

SPEC = ('Write a concise implementation spec for the winner in THIS repository: what to change, which files (paths), acceptance '
        'criteria as checkable statements, rollback. Smallest change that tests the hypothesis. Schema: '
        '{"spec","files":[],"acceptance":[],"rollback"}')

REVIEW = ('Review this diff against the spec for correctness, missing states, security/auth, data consistency, error handling, '
          'race conditions, regressions, test gaps, unnecessary complexity. Schema: {"blocking":[str],"warnings":[str],"verdict":"approve|block"}')

RECHECK = ('Given the implemented change (diff summary), does it still plausibly solve the evidenced problem for these stakeholders '
           'without unacceptable tradeoffs? Schema: {"still_solves_problem":bool,"tradeoffs","score":1-5}')

LESSON = ('Summarize this cycle as a reusable lesson in <=60 words per field. Schema: '
          '{"what_worked","what_failed","reusable_implication","confidence":0-1}')


def implement_instructions(spec: dict, contract_text: str, failure: str | None = None) -> str:
    base = (f"Implement the following spec in this repository. Make the smallest coherent change. Do not refactor unrelated code. "
            f"Do not touch the .evoloop directory or any file named contract.json. Add or update tests for the change.\n\n"
            f"SPEC:\n{json.dumps(spec, indent=1)}\n\nEVALUATION CONTRACT (read-only; you must satisfy it, never edit it):\n{contract_text}\n")
    if failure:
        base += f"\nThe previous attempt failed verification. Fix ONLY what is needed:\n{failure}\n"
    return base
