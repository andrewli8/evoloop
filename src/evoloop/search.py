"""Deterministic helpers for the search phases: dedup, scoring, diversity, memory retrieval."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

STOP = {"the", "a", "an", "of", "to", "for", "and", "in", "on", "with", "via", "by", "option", "add"}


def tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP}


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


# --- structured compare: mechanism + surface (declared fields, free-text fallback) ---

_MECH_STOP = {"a", "an", "the", "to", "for", "of", "on", "in", "with", "by"}
_RISKY_MECH_STEMS = ("delet", "migrat", "schema", "concurren", "auth", "retr", "timeout", "drop")
# Domains that are dangerous anywhere, not repo-structure words: "cli"/"config" are ordinary module
# names in most repos (including this one) and blanket-fired on every candidate (observed cycle 2ae3).
_SENSITIVE_SURFACES = ("auth", "billing", "payment", "secret", "credential", "migration", "checkout", "session")


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "s"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            w = w[: -len(suf)]
            break
    return w.removesuffix("e")  # cache/caching -> cach, parse/parsed -> pars


def _normalize_mechanism(s: str) -> str:
    toks = [_stem(w) for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _MECH_STOP]
    return " ".join(sorted(toks))


def _normalize_surface(paths: list[str]) -> frozenset[str]:
    out = set()
    for p in paths or []:
        p = str(p).lower().replace("\\", "/").strip()
        p = p.removeprefix("./").removeprefix("src/")
        p = re.sub(r"\.(py|pyi|ts|tsx|js|jsx|mjs|cjs|go|rs|rb|java|kt|php|css|scss|html|md|yaml|yml|toml|json|sql)$", "", p)  # only real file extensions; 'evoloop.search' is a module, not 'evoloop'

        if p:
            out.add(p)
    return frozenset(out)


def ensure_structured(c: dict) -> dict:
    """Return candidate with required mechanism/surface, deriving from free text when absent (fallback recorded)."""
    fallback = []
    mech = c.get("mechanism")
    if not mech:
        mech = c.get("title", "")
        fallback.append("mechanism")
    surface = c.get("surface")
    if isinstance(surface, str):  # a bare string would explode into characters under list()
        surface = [surface]
    if not surface:
        surface = re.findall(r"[\w.-]+/[\w./-]+|[\w-]+\.[a-z]{1,4}\b", c.get("title", "") + " " + c.get("summary", ""))
        fallback.append("surface")
    out = {**c, "mechanism": mech, "surface": list(surface)}
    if fallback:
        out["structured_fallback"] = fallback
    return out


def _structured_dup(a: dict, b: dict) -> bool:
    # fallback surfaces are guessed from prose; only dedup on surfaces the generator declared
    if any("surface" in x.get("structured_fallback", []) for x in (a, b)):
        return False
    ma, mb = _normalize_mechanism(a["mechanism"]), _normalize_mechanism(b["mechanism"])
    return bool(ma) and ma == mb and bool(_normalize_surface(a["surface"]) & _normalize_surface(b["surface"]))


def risk_signal(c: dict, terms: list[str]) -> str | None:
    """Name of the first rule that escalates this candidate (mechanism:<stem>, surface:<domain>, keyword:<term>), or None."""
    c = ensure_structured(c)
    mech_toks = _normalize_mechanism(c["mechanism"]).split()
    for s in _RISKY_MECH_STEMS:
        if any(t.startswith(s) for t in mech_toks):
            return f"mechanism:{s}"
    for s in _SENSITIVE_SURFACES:
        if any(seg.startswith(s) for p in _normalize_surface(c["surface"]) for seg in p.split("/")):
            return f"surface:{s}"
    from .contract import classify_risk
    text = c.get("title", "") + " " + c.get("summary", "")
    for t in terms:
        if classify_risk(text, [t]) != "low":
            return f"keyword:{t}"
    return None


def classify_candidate_risk(c: dict, terms: list[str]) -> str:
    """max(structured risk, keyword risk): the structured signal only ever raises risk."""
    from .contract import classify_risk
    c = ensure_structured(c)
    mech_toks = _normalize_mechanism(c["mechanism"]).split()
    structured = any(t.startswith(s) for t in mech_toks for s in _RISKY_MECH_STEMS) or \
        any(seg.startswith(s) for p in _normalize_surface(c["surface"]) for seg in p.split("/") for s in _SENSITIVE_SURFACES)
    keyword = classify_risk(c.get("title", "") + " " + c.get("summary", ""), terms)
    return "high" if structured else keyword  # structured signal only raises to the top level; keyword otherwise preserved


@dataclass(frozen=True)
class ScreenDecision:
    verdict: str  # "keep" | "drop"
    matched_id: str | None = None  # id (or title, before ids are assigned) of the prior/duplicate candidate it matched
    similarity: float | None = None  # score that produced matched_id, 0.0-1.0
    risk_signal: str | None = None  # name of the rule that escalated it
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _match(c: dict, kept: list[dict], prior_titles: list[str], threshold: float) -> ScreenDecision | None:
    key = c["title"] + " " + c.get("summary", "")
    for k in kept:
        kid = k.get("id") or k["title"]
        if _structured_dup(c, k):
            return ScreenDecision("drop", kid, 1.0, reason="same mechanism and surface")
        sim = jaccard(key, k["title"] + " " + k.get("summary", ""))
        if sim >= threshold:
            return ScreenDecision("drop", kid, round(sim, 3), reason="near-duplicate of another candidate")
    for t in prior_titles:
        sim = jaccard(c["title"], t)
        if sim >= 0.8:
            return ScreenDecision("drop", t, round(sim, 3), reason="already explored in a prior cycle")
    return None


def screen(cands: list[dict], prior_titles: list[str], threshold: float = 0.6, terms: list[str] = ()) -> list[dict]:
    """Every candidate, in order, with one ScreenDecision attached under `screen` (as a dict, so it serializes)."""
    out: list[dict] = []
    kept: list[dict] = []
    for c in map(ensure_structured, cands):
        d = _match(c, kept, prior_titles, threshold) or ScreenDecision("keep", risk_signal=risk_signal(c, terms))
        c = {**c, "screen": d.to_dict()}
        out.append(c)
        if d.verdict == "keep":
            kept.append(c)
    return out


def dedup(cands: list[dict], prior_titles: list[str], threshold: float = 0.6) -> tuple[list[dict], int]:
    screened = screen(cands, prior_titles, threshold)
    kept = [c for c in screened if c["screen"]["verdict"] == "keep"]
    return kept, len(screened) - len(kept)


def cheap_rank(cands: list[dict], scores: list[dict]) -> list[dict]:
    by_id = {s["id"]: s for s in scores if "id" in s}
    out = []
    for c in cands:
        s = by_id.get(c["id"], {})
        val = 2 * _n(s.get("impact"), 3) - _n(s.get("effort"), 3) - _n(s.get("risk"), 2)
        out.append({**c, "cheap": {k: s.get(k) for k in ("impact", "effort", "risk")}, "cheap_score": val})
    return sorted(out, key=lambda c: -c["cheap_score"])


def _n(v, default: int) -> int:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return default


def mechanisms(cands: list[dict]) -> set[str]:
    return {c.get("mechanism", "").strip().lower() for c in cands if c.get("mechanism")}


def select_problem(problems: list[dict], evidence: list[dict]) -> list[dict]:
    """Rank problems by evidence quality (observed > inferred > ...) then stated confidence."""
    rank = {"observed": 3, "inferred": 2, "hypothetical": 1, "simulated": 1}
    ev = {e["id"]: e for e in evidence}
    scored = []
    for p in problems:
        ids = [i for i in p.get("evidence_ids", []) if i in ev]
        if not ids:
            continue
        if all(ev[i]["source"] == "git_log" for i in ids):
            continue  # fix commits alone show a problem was addressed, not that it persists
        score = sum(rank[ev[i]["class"]] for i in ids) + float(p.get("confidence", 0.5) or 0)
        scored.append({**p, "evidence_ids": ids, "evidence_score": round(score, 2)})
    return sorted(scored, key=lambda p: -p["evidence_score"])


def relevant(items: list[dict], query: str, fields: tuple[str, ...], k: int = 3) -> list[dict]:
    q = tokens(query)
    scored = [(len(q & tokens(" ".join(str(i.get(f, "")) for f in fields))), i) for i in items]
    return [i for s, i in sorted(scored, key=lambda x: -x[0]) if s > 0][:k]
