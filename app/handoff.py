"""Human handoff + escalation state for social-channel conversations.

One row per conversation in a `conversations` table (same SQLite DB as the chat
logs). Tracks who is replying (`mode`: bot vs human operator) and whether the
conversation needs a human (`escalation`/`priority`/`handled`, raised either
automatically by the LLM reviewer or manually by staff).

Channel-agnostic: keyed by session_id and the channel/recipient stored on the
row, so the same operator console drives WhatsApp now and Telegram/Instagram
later without changes here.
"""
import os
import sqlite3
import threading
import time
from typing import List, Optional

from app.config import settings

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings.log_db), exist_ok=True)
    return sqlite3.connect(settings.log_db, timeout=10)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init() -> None:
    try:
        with _lock, _connect() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id  TEXT PRIMARY KEY,
                    channel     TEXT,
                    recipient   TEXT,
                    title       TEXT,
                    mode        TEXT DEFAULT 'bot',     -- 'bot' | 'human'
                    escalation  INTEGER DEFAULT 0,      -- needs a human
                    priority    INTEGER DEFAULT 0,      -- 0 normal, 1 high, 2 urgent
                    handled     INTEGER DEFAULT 0,      -- staff marked done
                    auto        INTEGER DEFAULT 0,      -- 1 auto-raised, 0 manual
                    reason      TEXT,
                    operator    TEXT,
                    created_ts  TEXT,
                    updated_ts  TEXT
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_conv_queue ON conversations(escalation, mode)")
    except Exception as e:
        print(f"[handoff] init failed: {e}")


_COLS = ["session_id", "channel", "recipient", "title", "mode", "escalation",
         "priority", "handled", "auto", "reason", "operator", "created_ts", "updated_ts"]


def _row(r) -> dict:
    return dict(zip(_COLS, r)) if r else None


def get(session_id: str) -> Optional[dict]:
    try:
        with _lock, _connect() as c:
            r = c.execute(
                "SELECT %s FROM conversations WHERE session_id=?" % ", ".join(_COLS),
                (session_id,),
            ).fetchone()
        return _row(r)
    except Exception:
        return None


def ensure(session_id: str, channel: str = None, recipient: str = None, title: str = None) -> None:
    """Make sure a row exists; fill channel/recipient/title if not set; bump time."""
    try:
        with _lock, _connect() as c:
            r = c.execute("SELECT title, channel, recipient FROM conversations WHERE session_id=?",
                          (session_id,)).fetchone()
            if r is None:
                c.execute(
                    "INSERT INTO conversations(session_id, channel, recipient, title, mode, created_ts, updated_ts) "
                    "VALUES (?,?,?,?, 'bot', ?, ?)",
                    (session_id, channel or "", recipient or "", (title or "")[:200], _now(), _now()),
                )
            else:
                new_title = r[0] or (title or "")[:200]
                c.execute(
                    "UPDATE conversations SET channel=COALESCE(NULLIF(?,''),channel), "
                    "recipient=COALESCE(NULLIF(?,''),recipient), title=?, updated_ts=? WHERE session_id=?",
                    (channel or "", recipient or "", new_title, _now(), session_id),
                )
    except Exception as e:
        print(f"[handoff] ensure failed: {e}")


def is_bot_active(session_id: str) -> bool:
    """True unless a human operator has taken the conversation over."""
    row = get(session_id)
    return not (row and row.get("mode") == "human")


def take_over(session_id: str, operator: str = "") -> None:
    try:
        with _lock, _connect() as c:
            c.execute("UPDATE conversations SET mode='human', operator=?, handled=0, updated_ts=? "
                      "WHERE session_id=?", (operator or "", _now(), session_id))
    except Exception:
        pass


def release_to_bot(session_id: str) -> None:
    """Operator hands the conversation back to the bot (also clears escalation)."""
    try:
        with _lock, _connect() as c:
            c.execute("UPDATE conversations SET mode='bot', escalation=0, handled=1, updated_ts=? "
                      "WHERE session_id=?", (_now(), session_id))
    except Exception:
        pass


def flag(session_id: str, reason: str = "", priority: int = 0, auto: bool = True,
         channel: str = None, recipient: str = None, title: str = None) -> bool:
    """Raise (or escalate) the need for a human. Returns True only if this is a
    NEW escalation (was not already pending) so callers can notify staff once."""
    ensure(session_id, channel, recipient, title)
    try:
        with _lock, _connect() as c:
            r = c.execute("SELECT escalation, handled FROM conversations WHERE session_id=?",
                          (session_id,)).fetchone()
            already = bool(r and r[0] == 1 and r[1] == 0)
            c.execute(
                "UPDATE conversations SET escalation=1, handled=0, "
                "priority=MAX(priority, ?), auto=?, "
                "reason=COALESCE(NULLIF(?,''), reason), updated_ts=? WHERE session_id=?",
                (int(priority), 1 if auto else 0, (reason or "").strip(), _now(), session_id),
            )
            return not already
    except Exception:
        return False


def mark_handled(session_id: str, handled: bool = True) -> None:
    try:
        with _lock, _connect() as c:
            c.execute("UPDATE conversations SET handled=?, updated_ts=? WHERE session_id=?",
                      (1 if handled else 0, _now(), session_id))
    except Exception:
        pass


def set_priority(session_id: str, priority: int) -> None:
    try:
        with _lock, _connect() as c:
            c.execute("UPDATE conversations SET priority=?, updated_ts=? WHERE session_id=?",
                      (int(priority), _now(), session_id))
    except Exception:
        pass


def bump(session_id: str, unhandle: bool = False) -> None:
    """Touch updated_ts on a new inbound; optionally re-open (a new message after
    it was marked handled should pull it back into the queue)."""
    try:
        with _lock, _connect() as c:
            if unhandle:
                c.execute("UPDATE conversations SET handled=0, updated_ts=? WHERE session_id=?",
                          (_now(), session_id))
            else:
                c.execute("UPDATE conversations SET updated_ts=? WHERE session_id=?",
                          (_now(), session_id))
    except Exception:
        pass


def queue(limit: int = 200) -> List[dict]:
    """Conversations that need operator attention: escalated OR human-controlled.
    Ordered: unhandled first, then by priority (urgent first), then most recent."""
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                "SELECT %s FROM conversations WHERE escalation=1 OR mode='human' "
                "ORDER BY handled ASC, priority DESC, updated_ts DESC LIMIT ?" % ", ".join(_COLS),
                (int(limit),),
            ).fetchall()
        return [_row(r) for r in rows]
    except Exception as e:
        print(f"[handoff] queue failed: {e}")
        return []


def counts() -> dict:
    try:
        with _lock, _connect() as c:
            pending = c.execute(
                "SELECT COUNT(*) FROM conversations WHERE (escalation=1 OR mode='human') AND handled=0"
            ).fetchone()[0]
            human = c.execute("SELECT COUNT(*) FROM conversations WHERE mode='human'").fetchone()[0]
        return {"pending": pending, "human": human}
    except Exception:
        return {"pending": 0, "human": 0}
