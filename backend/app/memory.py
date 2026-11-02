"""SQLite store: conversation, long-term facts, pending actions, audit log."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class Memory:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, ts REAL, role TEXT, content TEXT);
            CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, ts REAL, text TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY, ts REAL, tool TEXT, args TEXT, summary TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL, tool TEXT, args TEXT, status TEXT, detail TEXT);
            """
        )
        self.db.commit()

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self.db.execute(sql, params)
            self.db.commit()
            return cur

    # conversation
    def add_message(self, role: str, content: str):
        self._exec("INSERT INTO messages(ts, role, content) VALUES(?,?,?)", (time.time(), role, content))

    def recent_messages(self, limit: int = 20) -> list[dict]:
        rows = self._exec("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        while msgs and msgs[0]["role"] != "user":  # the API needs the first turn to be the user's
            msgs.pop(0)
        merged: list[dict] = []  # merge same-role neighbours (e.g. after a failed reply)
        for m in msgs:
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"] += "\n" + m["content"]
            else:
                merged.append(dict(m))
        return merged

    # long-term facts
    def remember(self, text: str):
        self._exec("INSERT OR IGNORE INTO facts(ts, text) VALUES(?,?)", (time.time(), text.strip()[:300]))

    def forget(self, needle: str) -> int:
        if needle.strip() in ("", "*"):
            return self._exec("DELETE FROM facts").rowcount
        return self._exec("DELETE FROM facts WHERE text LIKE ?", (f"%{needle.strip()}%",)).rowcount

    def facts(self) -> list[str]:
        return [r["text"] for r in self._exec("SELECT text FROM facts ORDER BY id").fetchall()]

    # pending actions awaiting the user's yes/no
    def add_pending(self, tool: str, args: dict, summary: str) -> str:
        pid = uuid.uuid4().hex[:12]
        self._exec("INSERT INTO pending VALUES(?,?,?,?,?,?)",
                   (pid, time.time(), tool, json.dumps(args, ensure_ascii=False), summary, "waiting"))
        return pid

    def take_pending(self, pid: str, max_age: float = 600) -> dict | None:
        row = self._exec("SELECT * FROM pending WHERE id=? AND status='waiting'", (pid,)).fetchone()
        if not row or time.time() - row["ts"] > max_age:
            return None
        self._exec("UPDATE pending SET status='taken' WHERE id=?", (pid,))
        return {"id": row["id"], "tool": row["tool"], "args": json.loads(row["args"]), "summary": row["summary"]}

    def reject_pending(self, pid: str) -> bool:
        return self._exec("UPDATE pending SET status='rejected' WHERE id=? AND status='waiting'", (pid,)).rowcount > 0

    # audit log
    def audit(self, tool: str, args: dict, status: str, detail: str = ""):
        self._exec("INSERT INTO audit(ts, tool, args, status, detail) VALUES(?,?,?,?,?)",
                   (time.time(), tool, json.dumps(args, ensure_ascii=False), status, detail[:500]))

    def audit_log(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def count_audit_since(self, tool: str, status: str, since: float) -> int:
        return self._exec("SELECT COUNT(*) c FROM audit WHERE tool=? AND status=? AND ts>?",
                          (tool, status, since)).fetchone()["c"]
