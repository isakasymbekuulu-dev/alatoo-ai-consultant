"""Lightweight conversation logging to SQLite (stdlib only).

Stores one row per assistant turn so conversations can be reviewed and analysed
later. The DB lives on a persistent Docker volume (see docker-compose).
"""
import json
import os
import sqlite3
import threading
import time
from typing import List

from app.config import settings

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings.log_db), exist_ok=True)
    return sqlite3.connect(settings.log_db, timeout=10)


def init() -> None:
    try:
        with _lock, _connect() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts            TEXT,
                    session_id    TEXT,
                    source        TEXT,
                    user_msg      TEXT,
                    assistant_msg TEXT,
                    sources       TEXT,
                    consent       INTEGER
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id)")
    except Exception as e:  # never let logging break the app
        print(f"[log] init failed: {e}")


def log_turn(session_id, source, user_msg, assistant_msg, sources, consent) -> None:
    try:
        with _lock, _connect() as c:
            c.execute(
                "INSERT INTO messages (ts, session_id, source, user_msg, assistant_msg, sources, consent) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    session_id or "anon",
                    source or "unknown",
                    user_msg or "",
                    assistant_msg or "",
                    json.dumps(sources, ensure_ascii=False),
                    1 if consent else 0,
                ),
            )
    except Exception as e:
        print(f"[log] write failed: {e}")


def recent(limit: int = 300) -> List[dict]:
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                "SELECT id, ts, session_id, source, user_msg, assistant_msg, sources, consent "
                "FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception as e:
        print(f"[log] read failed: {e}")
        return []
    cols = ["id", "ts", "session_id", "source", "user_msg", "assistant_msg", "sources", "consent"]
    return [dict(zip(cols, r)) for r in rows]


def sessions(limit: int = 200) -> List[dict]:
    """One row per conversation: id, title (first question), channel, counts, last time."""
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                """
                SELECT m.session_id, m.source, COUNT(*) AS n, MAX(m.ts) AS last_ts,
                  (SELECT user_msg FROM messages m2 WHERE m2.session_id = m.session_id
                     ORDER BY m2.id ASC LIMIT 1) AS title
                FROM messages m
                GROUP BY m.session_id
                ORDER BY MAX(m.id) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except Exception as e:
        print(f"[log] sessions failed: {e}")
        return []
    cols = ["session_id", "source", "n", "last_ts", "title"]
    return [dict(zip(cols, r)) for r in rows]


def session_messages(session_id: str) -> List[dict]:
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                "SELECT id, ts, source, user_msg, assistant_msg, sources, consent "
                "FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
    except Exception as e:
        print(f"[log] session_messages failed: {e}")
        return []
    cols = ["id", "ts", "source", "user_msg", "assistant_msg", "sources", "consent"]
    return [dict(zip(cols, r)) for r in rows]


def stats() -> dict:
    try:
        with _lock, _connect() as c:
            total = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            sessions = c.execute("SELECT COUNT(DISTINCT session_id) FROM messages").fetchone()[0]
        return {"messages": total, "sessions": sessions}
    except Exception:
        return {"messages": 0, "sessions": 0}
