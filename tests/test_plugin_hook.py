import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "evoloop_hook.py"


def run(cmd, env, stdin=""):
    r = subprocess.run([sys.executable, str(HOOK), cmd], input=stdin, capture_output=True, text=True, env=env, timeout=10)
    assert r.returncode == 0
    return r.stdout


def env_for(tmp):
    return {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp / "claude"), "XDG_CONFIG_HOME": str(tmp / "xdg"), "HOME": str(tmp)}


def test_session_default_full_and_flag(tmp_path):
    env = env_for(tmp_path)
    out = run("session", env)
    assert out.startswith("EVOLOOP MODE ACTIVE — level: full")
    assert (tmp_path / "claude" / ".evoloop-mode").read_text() == "full"


def test_prompt_switch_and_off(tmp_path):
    env = env_for(tmp_path)
    run("session", env)
    out = json.loads(run("prompt", env, json.dumps({"prompt": "/evoloop ultra"})))
    assert "level: ultra" in out["hookSpecificOutput"]["additionalContext"]
    assert (tmp_path / "claude" / ".evoloop-mode").read_text() == "ultra"
    out = json.loads(run("prompt", env, json.dumps({"prompt": "stop evoloop."})))
    assert out["hookSpecificOutput"]["additionalContext"] == "EVOLOOP MODE OFF"
    assert not (tmp_path / "claude" / ".evoloop-mode").exists()
    assert run("prompt", env, json.dumps({"prompt": "add a normal stop evoloop button"})) == ""


def test_default_persists_and_off_default_emits_nothing(tmp_path):
    env = env_for(tmp_path)
    run("prompt", env, json.dumps({"prompt": "/evoloop default off"}))
    assert json.loads((tmp_path / "xdg" / "evoloop" / "config.json").read_text()) == {"defaultMode": "off"}
    assert run("session", env) == ""
    assert not (tmp_path / "claude" / ".evoloop-mode").exists()


def test_garbage_stdin_never_fails(tmp_path):
    assert run("prompt", env_for(tmp_path), "not json") == ""
