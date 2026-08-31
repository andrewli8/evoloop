"""SQLite-backed local state: knowledge graph nodes/edges, cycles, lock, usage."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from .config import EVO_DIR

KINDS = {"Actor", "Goal", "Workflow", "WorkflowStep", "PainPoint", "Constraint", "Capability",
         "Intervention", "Evidence", "Metric", "Experiment", "Result", "Lesson", "Problem"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, kind TEXT, data TEXT, cycle TEXT, created REAL);
CREATE TABLE IF NOT EXISTS edges(src TEXT, rel TEXT, dst TEXT, PRIMARY KEY(src, rel, dst));
CREATE TABLE IF NOT EXISTS cycles(id TEXT PRIMARY KEY, status TEXT, started REAL, finished REAL, result TEXT);
CREATE TABLE IF NOT EXISTS lock(id INTEGER PRIMARY KEY CHECK(id=1), pid INTEGER, started REAL);
CREATE TABLE IF NOT EXISTS contracts(cycle TEXT PRIMARY KEY, sha TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(kind);
"""


class LockedError(RuntimeError):
    pass


class State:
    def __init__(self, repo: Path):
        self.path = repo / EVO_DIR / "state.sqlite"
        self.path.parent.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.executescript(SCHEMA)

    # --- knowledge graph -------------------------------------------------
    def add(self, kind: str, data: dict, cycle: str | None = None, id: str | None = None) -> str:
        assert kind in KINDS, kind
        nid = id or f"{kind[:3].lower()}_{uuid.uuid4().hex[:10]}"
        self.db.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?,?)",
                        (nid, kind, json.dumps(data), cycle, time.time()))
        return nid

    def link(self, src: str, rel: str, dst: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?)", (src, rel, dst))

    def nodes(self, kind: str, limit: int = 50) -> list[dict]:
        rows = self.db.execute("SELECT id,data,cycle FROM nodes WHERE kind=? ORDER BY created DESC LIMIT ?",
                               (kind, limit)).fetchall()
        return [{"id": r[0], "cycle": r[2], **json.loads(r[1])} for r in rows]

    def related(self, src: str, rel: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT n.id,n.kind,n.data FROM edges e JOIN nodes n ON n.id=e.dst WHERE e.src=? AND e.rel=?",
            (src, rel)).fetchall()
        return [{"id": r[0], "kind": r[1], **json.loads(r[2])} for r in rows]

    # --- cycles -------------------------------------------------------------
    def start_cycle(self) -> str:
        cid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.db.execute("INSERT INTO cycles VALUES(?,?,?,?,?)", (cid, "running", time.time(), None, None))
        return cid

    def finish_cycle(self, cid: str, status: str, result: dict) -> None:
        self.db.execute("UPDATE cycles SET status=?, finished=?, result=? WHERE id=?",
                        (status, time.time(), json.dumps(result), cid))

    def cycles(self, limit: int = 10) -> list[dict]:
        rows = self.db.execute("SELECT id,status,started,finished,result FROM cycles ORDER BY started DESC LIMIT ?",
                               (limit,)).fetchall()
        return [{"id": r[0], "status": r[1], "started": r[2], "finished": r[3],
                 "result": json.loads(r[4]) if r[4] else None} for r in rows]

    def awaiting(self) -> list[dict]:
        return [c for c in self.cycles(50) if c["status"] == "awaiting_human"]

    # --- lock ---------------------------------------------------------------
    def acquire(self) -> None:
        row = self.db.execute("SELECT pid, started FROM lock WHERE id=1").fetchone()
        if row and _alive(row[0]):
            raise LockedError(f"cycle already running (pid {row[0]})")
        self.db.execute("INSERT OR REPLACE INTO lock VALUES(1,?,?)", (os.getpid(), time.time()))

    def release(self) -> None:
        self.db.execute("DELETE FROM lock WHERE id=1")

    # --- evaluation contracts -------------------------------------------------
    def freeze_contract(self, cycle: str, sha: str, body: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO contracts VALUES(?,?,?)", (cycle, sha, body))

    def contract_sha(self, cycle: str) -> str | None:
        row = self.db.execute("SELECT sha FROM contracts WHERE cycle=?", (cycle,)).fetchone()
        return row[0] if row else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False
