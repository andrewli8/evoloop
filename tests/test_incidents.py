import json
from pathlib import Path

import pytest

from evoloop import evidence as ev_mod
from evoloop.config import Config, Mode
from evoloop.cycle import run_cycle
from evoloop.incidents import exception_incident, incidents_path, load_incidents, record_incident
from evoloop.providers import Budgeted, MockProvider, Role
from evoloop.providers.base import Provider
from evoloop.state import State

KEYS = {"ts", "kind", "summary", "detail", "source", "exit_code"}


def test_write_read_round_trip(tmp_path):
    record_incident("provider_error", summary="a", detail="x" * 5000, source="claude-cli", exit_code=1, root=tmp_path)
    record_incident("exception", summary="b", source="cycle", root=tmp_path)
    p = incidents_path(tmp_path)
    assert p == tmp_path / ".evoloop" / "incidents.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(set(json.loads(l)) == KEYS for l in lines)
    recs = load_incidents(tmp_path)
    assert [r["summary"] for r in recs] == ["a", "b"]
    assert recs[0]["exit_code"] == 1 and len(recs[0]["detail"]) == 4000 and recs[1]["exit_code"] is None
    assert load_incidents(tmp_path, limit=1) == [recs[1]]


def test_absent_file_returns_empty_and_creates_nothing(tmp_path):
    assert load_incidents(tmp_path) == []
    assert list(tmp_path.iterdir()) == []


def test_malformed_line_skipped(tmp_path):
    record_incident("a", summary="first", root=tmp_path)
    with incidents_path(tmp_path).open("a") as f:
        f.write("not json\n[1,2]\n")
    record_incident("a", summary="last", root=tmp_path)
    assert [r["summary"] for r in load_incidents(tmp_path)] == ["first", "last"]


def test_unwritable_root_does_not_raise(tmp_path):
    f = tmp_path / "file"
    f.write_text("")
    assert record_incident("a", summary="s", root=f) is None  # parent path is a file: mkdir fails
    assert record_incident("a", summary="s", root=Path("/dev/null/nope")) is None


def test_capture_incidents_opt_out(tmp_path):
    Config(capture_incidents=False).save(tmp_path)
    record_incident("a", summary="s", root=tmp_path)
    assert not incidents_path(tmp_path).exists()


def test_exception_incident_has_class_and_traceback(tmp_path):
    try:
        raise ValueError("boom")
    except ValueError as e:
        exception_incident(e, source="cycle", root=tmp_path)
    (r,) = load_incidents(tmp_path)
    assert r["summary"].startswith("ValueError") and "Traceback" in r["detail"] and r["source"] == "cycle"


class Failing(Provider):
    name = "failing"

    def complete(self, role, system, prompt):
        raise RuntimeError("claude failed (3): stderr tail")


def test_provider_error_recorded_and_reraised(tmp_path):
    llm = Budgeted(Failing(), 10, 10_000, root=tmp_path)
    with pytest.raises(RuntimeError, match="failed \\(3\\)"):
        llm.text(Role.FAST, "s", "[phase:x] p")
    (r,) = load_incidents(tmp_path)
    assert r["kind"] == "provider_error" and r["exit_code"] == 3 and r["source"] == "failing" and "stderr tail" in r["detail"]
    assert llm.usage.calls == 0


def test_successful_provider_call_writes_nothing(tmp_path):
    llm = Budgeted(MockProvider(), 10, 10_000, root=tmp_path)
    llm.text(Role.FAST, "s", "[phase:x] p")
    assert not incidents_path(tmp_path).exists()


def test_successful_cycle_writes_nothing(repo):
    r = run_cycle(repo, Config.load(repo), MockProvider(), Mode.ANALYZE)
    assert r["status"] == "done" and not incidents_path(repo).exists()


def test_unhandled_cycle_exception_recorded_and_propagated(repo, monkeypatch):
    from evoloop import cycle
    monkeypatch.setattr(cycle.scan, "refresh", lambda *a: (_ for _ in ()).throw(KeyError("pack")))
    with pytest.raises(KeyError):
        run_cycle(repo, Config.load(repo), MockProvider(), Mode.ANALYZE)
    (r,) = load_incidents(repo)
    assert r["summary"].startswith("KeyError") and "Traceback" in r["detail"] and r["source"] == "cycle"


def test_evidence_includes_incidents(repo):
    state = State(repo)
    assert [e for e in ev_mod.collect(repo, state, ["todos"]) if e["source"] == "incidents"] == []
    record_incident("provider_error", summary="claude failed (1)", source="claude-cli", exit_code=1, root=repo)
    got = [e for e in ev_mod.collect(repo, state, ["todos"]) if e["source"] == "incidents"]
    assert len(got) == 1 and got[0]["kind"] == "incident" and got[0]["class"] == "observed"
    assert "provider_error in claude-cli: claude failed (1)" in got[0]["text"] and got[0]["id"]
