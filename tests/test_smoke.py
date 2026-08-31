"""Smoke evidence source: tiny shell commands via fake configs; no network, no real builds."""
from evoloop import evidence as ev_mod
from evoloop.config import Config
from evoloop.smoke import collect_smoke_evidence


def _cfg(**kw) -> Config:
    smoke = {"enabled": True, **kw.pop("smoke", {})}
    return Config(smoke=smoke, **kw)


def test_failing_command_yields_one_item_with_exit_code_and_stderr():
    cfg = _cfg(commands={"test": "echo boom >&2; exit 3"})
    items = collect_smoke_evidence(cfg)
    assert len(items) == 1
    e = items[0]
    assert e["source"] == "smoke"
    assert e["class"] == "observed"
    assert e["ref"] == "echo boom >&2; exit 3"
    assert "exit code 3" in e["text"]
    assert "boom" in e["text"]


def test_passing_fast_command_yields_nothing():
    cfg = _cfg(commands={"test": "true"})
    assert collect_smoke_evidence(cfg) == []


def test_missing_command_yields_not_configured_item():
    cfg = _cfg(smoke={"commands": ["lint"]})  # lint not set in commands
    items = collect_smoke_evidence(cfg)
    assert len(items) == 1
    assert "no `lint` command configured" in items[0]["text"]
    assert items[0]["ref"] == "lint"


def test_timeout_yields_timeout_item_without_raising():
    cfg = _cfg(commands={"test": "sleep 2"}, smoke={"timeout_s": 0.1})
    items = collect_smoke_evidence(cfg)
    assert len(items) == 1
    assert "timed out" in items[0]["text"]


def test_slow_passing_command_yields_slow_item():
    cfg = _cfg(commands={"test": "true"}, smoke={"slow_threshold_s": 0})
    items = collect_smoke_evidence(cfg)
    assert len(items) == 1
    assert "slow" in items[0]["text"]


def test_smoke_item_shape_matches_existing_evidence():
    existing = ev_mod._ev("todos", "observed", "x", "f:1")
    item = collect_smoke_evidence(_cfg(commands={"test": "exit 1"}))[0]
    assert set(item) == set(existing)


def test_disabled_by_default_collect_has_no_smoke_evidence(tmp_path):
    cfg = Config(commands={"test": "exit 1"})
    assert cfg.smoke.enabled is False
    ev = ev_mod.collect(tmp_path, None, [], cfg=cfg)
    assert [e for e in ev if e["source"] == "smoke"] == []


def test_enabled_collect_includes_smoke_evidence(tmp_path):
    cfg = _cfg(commands={"test": "exit 1"})
    ev = ev_mod.collect(tmp_path, None, [], cfg=cfg)
    smoke = [e for e in ev if e["source"] == "smoke"]
    assert len(smoke) == 1
    assert smoke[0]["id"]  # collect assigns ids like every other source


def test_unknown_smoke_key_is_surfaced():
    cfg = _cfg(commands={"test": "true"}, smoke={"commands": ["tests"]})  # typo for "test"
    ev = collect_smoke_evidence(cfg)
    assert len(ev) == 1 and "unknown key `tests`" in ev[0]["text"]
