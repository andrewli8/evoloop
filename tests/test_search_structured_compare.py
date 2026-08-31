"""Structured (mechanism + surface) dedup and risk scoring in search.py."""
from evoloop.search import (
    _normalize_mechanism,
    _normalize_surface,
    classify_candidate_risk,
    dedup,
    ensure_structured,
)

TERMS = ["security", "billing", "password"]


def cand(title, summary="", mechanism=None, surface=None):
    c = {"title": title, "summary": summary}
    if mechanism is not None:
        c["mechanism"] = mechanism
    if surface is not None:
        c["surface"] = surface
    return c


def test_normalize_mechanism_converges_paraphrases():
    assert _normalize_mechanism("cache the parsed config") == _normalize_mechanism("caching config parse")


def test_normalize_surface_overlaps_across_prefixes_and_extensions():
    a = _normalize_surface(["src/evoloop/search.py"])
    b = _normalize_surface(["./evoloop/search"])
    assert a & b


def test_paraphrased_duplicates_same_mechanism_overlapping_surface_collapse():
    kept, dropped = dedup([
        cand("Cache the parsed configuration file", mechanism="cache the parsed config", surface=["src/evoloop/config.py"]),
        cand("Memoize configuration parsing step", mechanism="caching config parse", surface=["evoloop/config.py"]),
    ], [])
    assert len(kept) == 1 and dropped == 1
    assert kept[0]["title"] == "Cache the parsed configuration file"  # first survives (existing tie-break)


def test_same_mechanism_disjoint_surface_both_retained():
    kept, dropped = dedup([
        cand("Cache the parsed configuration file", mechanism="cache computed value", surface=["src/evoloop/config.py"]),
        cand("Memoize repository scan results deterministically", mechanism="cache computed value", surface=["src/evoloop/scan.py"]),
    ], [])
    assert len(kept) == 2 and dropped == 0


def test_risky_mechanism_elevates_risk_without_keywords():
    c = cand("Tidy up the workspace afterwards", "remove stale entries", mechanism="delete old records", surface=["evoloop/store.py"])
    assert classify_candidate_risk(c, TERMS) == "high"


def test_sensitive_surface_elevates_risk():
    c = cand("Speed up startup", "small tweak", mechanism="cache computed value", surface=["src/evoloop/config.py"])
    assert classify_candidate_risk(c, TERMS) == "high"


def test_risk_is_max_of_structured_and_keyword():
    c = cand("Harden password reset", "security fix", mechanism="cache computed value", surface=["evoloop/scan.py"])
    assert classify_candidate_risk(c, TERMS) == "high"  # keyword signal alone still elevates
    safe = cand("Speed up startup", "small tweak", mechanism="cache computed value", surface=["evoloop/scan.py"])
    assert classify_candidate_risk(safe, TERMS) == "low"


def test_missing_mechanism_and_surface_fall_back_without_raising():
    c = ensure_structured(cand("Cache parsing in src/evoloop/config.py"))
    assert c["mechanism"] and isinstance(c["surface"], list)
    assert set(c["structured_fallback"]) == {"mechanism", "surface"}
    kept, dropped = dedup([cand("Only a title here")], [])
    assert len(kept) == 1 and dropped == 0
    assert classify_candidate_risk(cand("Only a title here"), TERMS) == "low"


def test_title_jaccard_duplicates_still_caught():
    kept, dropped = dedup([
        cand("Simplify the onboarding form", "Fewer fields", mechanism="simplify", surface=["a.py"]),
        cand("Simplify onboarding form", "Fewer fields", mechanism="different mechanism entirely", surface=["b.py"]),
    ], [])
    assert len(kept) == 1 and dropped == 1


def test_prior_title_dedup_unchanged():
    kept, dropped = dedup([cand("Automate the nightly check")], ["Automate the nightly check"])
    assert kept == [] and dropped == 1
