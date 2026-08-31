"""Runtime evidence: smoke-run the repo's own configured commands and record failures/slowness."""
from __future__ import annotations

import subprocess
import time

SMOKE_DEFAULT_TIMEOUT_S = 300
SMOKE_KEY_ORDER = ("test", "build", "lint", "typecheck")
TAIL_LINES = 40
TEXT_CAP = 2000


def _ev(text: str, ref: str) -> dict:
    # same keys as evidence._ev; wider text cap so command output tails survive
    return {"source": "smoke", "class": "observed", "text": text.strip()[:TEXT_CAP], "ref": ref}


def _tail(stderr: str, stdout: str) -> str:
    lines = (stderr or "").splitlines()[-TAIL_LINES:] + (stdout or "").splitlines()[-TAIL_LINES:]
    return "\n".join(lines)


def collect_smoke_evidence(config, cwd: str = ".") -> list[dict]:
    """Run the configured command keys named in `smoke.commands`; emit evidence for
    failures, timeouts, slow passes, and missing commands. Never raises."""
    smoke = config.smoke
    out: list[dict] = []
    for key in smoke.commands:
        if key not in SMOKE_KEY_ORDER:
            out.append(_ev(f"smoke.commands names unknown key `{key}` (valid: {', '.join(SMOKE_KEY_ORDER)})", key))
            continue
        cmd = getattr(config.commands, key, None)
        if not cmd:
            out.append(_ev(f"no `{key}` command configured", key))
            continue
        start = time.monotonic()
        try:
            r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                               timeout=smoke.timeout_s)
            dur = time.monotonic() - start
            if r.returncode != 0:
                out.append(_ev(f"`{cmd}` failed (exit code {r.returncode}, {dur:.1f}s):\n"
                               f"{_tail(r.stderr, r.stdout)}", cmd))
            elif dur > smoke.slow_threshold_s:
                out.append(_ev(f"`{cmd}` passed but took {dur:.1f}s "
                               f"(slow threshold {smoke.slow_threshold_s}s)", cmd))
        except subprocess.TimeoutExpired:
            out.append(_ev(f"`{cmd}` timed out after {smoke.timeout_s}s", cmd))
        except Exception as e:  # OSError etc. — a broken command is evidence, not a crash
            out.append(_ev(f"`{cmd}` could not run: {e}", cmd))
    return out
