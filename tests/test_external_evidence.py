import io
import json
import sys

import pytest

from evoloop import evidence as ev_mod
from evoloop.config import Config, Mode
from evoloop.cycle import run_cycle
from evoloop.evidence.external import load_external_evidence
from evoloop.providers import MockProvider

ITEMS = [{"id": "T-1", "text": "Export times out for large accounts", "url": "https://x/1", "weight": 3},
         "Admins cannot find the billing page", {"text": "inferred pain", "class": "inferred"}]


def test_array_and_items_object_equivalent(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(ITEMS))
    b.write_text(json.dumps({"items": ITEMS}))
    ea, eb = load_external_evidence(str(a)), load_external_evidence(str(b))
    assert len(ea) == len(eb) == 3
    assert [{k: v for k, v in e.items() if k != "source"} for e in ea] == [{k: v for k, v in e.items() if k != "source"} for e in eb]
    assert all(e["kind"] == "external" and e["source"] == str(a) for e in ea)
    assert ea[0]["ref"] == "T-1" and ea[0]["url"] == "https://x/1" and ea[0]["weight"] == 3
    assert ea[1]["text"] == "Admins cannot find the billing page" and ea[1]["class"] == "observed"
    assert ea[2]["class"] == "inferred"


def test_stdin_and_command_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(["from stdin"])))
    e = load_external_evidence("-")
    assert [x["text"] for x in e] == ["from stdin"] and e[0]["source"] == "-"
    cmd = "echo '[\"from command\"]'"
    e = load_external_evidence(cmd)
    assert [x["text"] for x in e] == ["from command"] and e[0]["source"] == cmd


@pytest.mark.parametrize("source", ["{not json", "/nonexistent/file.json", "exit 1", "echo '{\"nope\": 1}'"])
def test_failures_warn_and_yield_nothing(source, tmp_path, caplog):
    if source == "{not json":
        (tmp_path / "bad.json").write_text(source)
        source = str(tmp_path / "bad.json")
    with caplog.at_level("WARNING"):
        assert load_external_evidence(source) == []
    assert "external evidence" in caplog.text


def test_limit_and_max_chars(tmp_path):
    p = tmp_path / "many.json"
    p.write_text(json.dumps(["x" * 500] * 80))
    e = load_external_evidence(str(p), limit=10, max_chars=20)
    assert len(e) == 10 and all(len(x["text"]) == 20 for x in e)
    assert len(load_external_evidence(str(p))) == 50


def test_collect_unchanged_without_external(repo):
    from evoloop.state import State
    before = ev_mod.collect(repo, State(repo), ["todos", "docs"])
    after = ev_mod.collect(repo, State(repo), ["todos", "docs"], [])
    assert before == after and not any(e.get("kind") for e in before)


def test_cli_flag_and_config_feed_cycle(repo, monkeypatch):
    from typer.testing import CliRunner
    from evoloop.cli import app
    f1, f2 = repo / "f1.json", repo / "f2.json"
    f1.write_text(json.dumps(["Search is slow on mobile"]))
    f2.write_text(json.dumps({"items": [{"text": "Invoices email never arrives"}]}))
    monkeypatch.chdir(repo)
    out = CliRunner().invoke(app, ["analyze", "--evidence-json", str(f1), "--evidence-json", str(f2)])
    assert out.exit_code == 0, out.output
    result = json.loads(next((repo / ".evoloop" / "runs").iterdir()).joinpath("result.json").read_text())
    assert result["evidence_count"]["observed"] >= 4  # todo + fix commit + 2 external


def test_external_source_survives_into_proposal(repo):
    f = repo / "ext.json"
    f.write_text(json.dumps([{"id": "Z-9", "text": "Checkout fails for EU cards"}]))
    cfg = Config.model_validate({**Config.load(repo).model_dump(), "evidence_sources": [], "evidence": {"external": [str(f)]}})
    r = run_cycle(repo, cfg, MockProvider(), Mode.ANALYZE)
    assert r["decision"] == "RECOMMEND"
    cited = r["supporting_evidence"]
    assert cited and all(e["source"] == str(f) and e["kind"] == "external" for e in cited)
    assert str(f) in (repo / ".evoloop" / "runs" / r["cycle"] / "report.md").read_text()
