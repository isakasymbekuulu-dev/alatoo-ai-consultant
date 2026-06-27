"""Lightweight conversation logging to SQLite (stdlib only)."""
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
            mcols = [r[1] for r in c.execute("PRAGMA table_info(messages)").fetchall()]
            if "problematic" not in mcols:
                c.execute("ALTER TABLE messages ADD COLUMN problematic INTEGER DEFAULT 0")
            if "flagged" not in mcols:
                c.execute("ALTER TABLE messages ADD COLUMN flagged INTEGER DEFAULT 0")
            if "problem_reason" not in mcols:
                c.execute("ALTER TABLE messages ADD COLUMN problem_reason TEXT")
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS riasec_results (
                    id         TEXT PRIMARY KEY,
                    ts         TEXT,
                    session_id TEXT,
                    lang       TEXT,
                    code       TEXT,
                    scores     TEXT,
                    recs       TEXT,
                    consent    INTEGER,
                    name       TEXT
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_riasec_session ON riasec_results(session_id)")
            # migration: add applicant name column if an older table lacks it
            cols = [r[1] for r in c.execute("PRAGMA table_info(riasec_results)").fetchall()]
            if "name" not in cols:
                c.execute("ALTER TABLE riasec_results ADD COLUMN name TEXT")
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS wa_test_tokens (
                    token      TEXT PRIMARY KEY,
                    session_id TEXT,
                    ts         INTEGER
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_traces (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT,
                    session_id TEXT,
                    intent     TEXT,
                    query      TEXT,
                    steps      TEXT,
                    n_chunks   INTEGER
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_trace_session ON graph_traces(session_id)")
    except Exception as e:
        print(f"[log] init failed: {e}")


_PROBLEM_MARKERS = ("приёмной комисси", "приемной комисси", "точной информации нет",
                    "нет точной информац", "временно недоступен", "не могу ответить",
                    "нет информации по", "обратитесь в приёмн", "обратитесь в приемн",
                    "контекст не найден", "сервис ии временно")


_COMPLAINT_MARKERS = ("не работает", "не помог", "бесполезн", "плохо отвеч", "плохой бот",
                      "ужасный бот", "тупой", "дурак", "идиот", "тварь", "неправильно",
                      "ты не прав", "это не то", "не отвечаешь", "жалоб", "отстой", "бред",
                      "ничего не понял", "ничего не понятно", "бесит", "раздражает",
                      "глупый", "ненавижу", "неверно ответил", "ты ошиб")


def _auto_problem(user_msg, assistant_msg, sources) -> int:
    """Problematic if (a) the answer could not really help (deflected to admissions,
    said it has no info, LLM-failure), or (b) the user complained / was rude."""
    a = (assistant_msg or "").lower()
    if any(m in a for m in _PROBLEM_MARKERS):
        return 1
    u = (user_msg or "").lower()
    return 1 if any(m in u for m in _COMPLAINT_MARKERS) else 0


def log_turn(session_id, source, user_msg, assistant_msg, sources, consent):
    """Insert one turn. Returns the new row id (or None on failure) so the caller
    can hand it to the async LLM problem-reviewer (app/feedback.py)."""
    try:
        with _lock, _connect() as c:
            cur = c.execute(
                "INSERT INTO messages (ts, session_id, source, user_msg, assistant_msg, sources, consent, problematic) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    session_id or "anon",
                    source or "unknown",
                    user_msg or "",
                    assistant_msg or "",
                    json.dumps(sources, ensure_ascii=False),
                    1 if consent else 0,
                    _auto_problem(user_msg, assistant_msg, sources),
                ),
            )
            return cur.lastrowid
    except Exception as e:
        print(f"[log] write failed: {e}")
        return None


def save_riasec(result_id, session_id, lang, code, scores, recs, consent, name=None) -> None:
    try:
        with _lock, _connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO riasec_results (id, ts, session_id, lang, code, scores, recs, consent, name) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    result_id,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    session_id or "anon",
                    lang or "ru",
                    code or "",
                    json.dumps(scores, ensure_ascii=False),
                    json.dumps(recs, ensure_ascii=False),
                    1 if consent else 0,
                    (name or "").strip() or None,
                ),
            )
    except Exception as e:
        print(f"[log] riasec write failed: {e}")


def _riasec_row_to_dict(row) -> dict:
    cols = ["id", "ts", "session_id", "lang", "code", "scores", "recs", "consent", "name"]
    d = dict(zip(cols, row))
    for k in ("scores", "recs"):
        try:
            d[k] = json.loads(d[k] or "null")
        except Exception:
            d[k] = None
    return d


def get_riasec(result_id: str):
    try:
        with _lock, _connect() as c:
            row = c.execute(
                "SELECT id, ts, session_id, lang, code, scores, recs, consent, name "
                "FROM riasec_results WHERE id = ?",
                (result_id,),
            ).fetchone()
        return _riasec_row_to_dict(row) if row else None
    except Exception as e:
        print(f"[log] riasec read failed: {e}")
        return None


def riasec_for_session(session_id: str):
    """Latest test result attached to a chat session (if any)."""
    try:
        with _lock, _connect() as c:
            row = c.execute(
                "SELECT id, ts, session_id, lang, code, scores, recs, consent, name "
                "FROM riasec_results WHERE session_id = ? ORDER BY ts DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return _riasec_row_to_dict(row) if row else None
    except Exception as e:
        print(f"[log] riasec read failed: {e}")
        return None


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
                "SELECT id, ts, source, user_msg, assistant_msg, sources, consent, problematic, flagged, problem_reason "
                "FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
    except Exception as e:
        print(f"[log] session_messages failed: {e}")
        return []
    cols = ["id", "ts", "source", "user_msg", "assistant_msg", "sources", "consent", "problematic", "flagged", "problem_reason"]
    return [dict(zip(cols, r)) for r in rows]


def session_problems(session_id: str) -> List[dict]:
    """Only the problematic / flagged messages of one conversation (problems view)."""
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                "SELECT id, ts, source, user_msg, assistant_msg, sources, consent, problematic, flagged, problem_reason "
                "FROM messages WHERE session_id = ? AND (problematic=1 OR flagged=1) ORDER BY id ASC",
                (session_id,),
            ).fetchall()
    except Exception as e:
        print(f"[log] session_problems failed: {e}")
        return []
    cols = ["id", "ts", "source", "user_msg", "assistant_msg", "sources", "consent", "problematic", "flagged", "problem_reason"]
    return [dict(zip(cols, r)) for r in rows]


def problem_sessions(limit: int = 300) -> List[dict]:
    """One row per conversation that has at least one problematic / flagged message,
    with the count of such messages. Powers the sidebar of the «Проблемные» tab."""
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                """
                SELECT m.session_id, m.source,
                  SUM(CASE WHEN m.problematic=1 OR m.flagged=1 THEN 1 ELSE 0 END) AS n_problems,
                  COUNT(*) AS n,
                  MAX(m.ts) AS last_ts,
                  (SELECT user_msg FROM messages m2 WHERE m2.session_id = m.session_id
                     ORDER BY m2.id ASC LIMIT 1) AS title
                FROM messages m
                GROUP BY m.session_id
                HAVING n_problems > 0
                ORDER BY MAX(m.id) DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
    except Exception as e:
        print(f"[log] problem_sessions failed: {e}")
        return []
    cols = ["session_id", "source", "n_problems", "n", "last_ts", "title"]
    return [dict(zip(cols, r)) for r in rows]


def stats() -> dict:
    try:
        with _lock, _connect() as c:
            total = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            sessions = c.execute("SELECT COUNT(DISTINCT session_id) FROM messages").fetchone()[0]
        return {"messages": total, "sessions": sessions}
    except Exception:
        return {"messages": 0, "sessions": 0}


def save_trace(session_id, intent, query, steps, n_chunks) -> None:
    try:
        with _lock, _connect() as c:
            c.execute(
                "INSERT INTO graph_traces (ts, session_id, intent, query, steps, n_chunks) "
                "VALUES (?,?,?,?,?,?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    session_id or "anon",
                    intent or "",
                    (query or "")[:500],
                    json.dumps(steps or [], ensure_ascii=False),
                    int(n_chunks or 0),
                ),
            )
    except Exception as e:
        print(f"[log] trace write failed: {e}")


def _trace_rows(rows) -> List[dict]:
    cols = ["id", "ts", "session_id", "intent", "query", "steps", "n_chunks"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["steps"] = json.loads(d["steps"] or "[]")
        except Exception:
            d["steps"] = []
        out.append(d)
    return out


def traces_for_session(session_id: str) -> List[dict]:
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                "SELECT id, ts, session_id, intent, query, steps, n_chunks "
                "FROM graph_traces WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return _trace_rows(rows)
    except Exception as e:
        print(f"[log] traces read failed: {e}")
        return []


def recent_traces(limit: int = 100) -> List[dict]:
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                "SELECT id, ts, session_id, intent, query, steps, n_chunks "
                "FROM graph_traces ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return _trace_rows(rows)
    except Exception as e:
        print(f"[log] traces read failed: {e}")
        return []


def analytics() -> dict:
    """Aggregate stats for the admin dashboard."""
    out = {"messages": 0, "sessions": 0, "tests": 0,
           "intents": [], "codes": [], "conversion": 0.0}
    try:
        with _lock, _connect() as c:
            out["messages"] = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            out["sessions"] = c.execute("SELECT COUNT(DISTINCT session_id) FROM messages").fetchone()[0]
            out["tests"] = c.execute("SELECT COUNT(*) FROM riasec_results").fetchone()[0]
            out["intents"] = [
                {"intent": i or "—", "n": n}
                for i, n in c.execute(
                    "SELECT intent, COUNT(*) FROM graph_traces GROUP BY intent ORDER BY COUNT(*) DESC"
                ).fetchall()
            ]
            out["codes"] = [
                {"code": code or "—", "n": n}
                for code, n in c.execute(
                    "SELECT code, COUNT(*) FROM riasec_results GROUP BY code ORDER BY COUNT(*) DESC LIMIT 10"
                ).fetchall()
            ]
            # conversion: tests whose session later had a chat turn
            conv = c.execute(
                "SELECT COUNT(*) FROM riasec_results r "
                "WHERE EXISTS (SELECT 1 FROM messages m "
                "WHERE m.session_id = r.session_id AND m.source != 'riasec-test')"
            ).fetchone()[0]
            out["conversion"] = round(100.0 * conv / out["tests"], 1) if out["tests"] else 0.0
    except Exception as e:
        print(f"[log] analytics failed: {e}")
    return out


# --- WhatsApp ↔ profiling-test token map -------------------------------------
# When the bot sends the RIASEC test link over WhatsApp, we attach an opaque
# token (NOT the phone number) that maps to the user's wa-<number> session, so
# the test result is saved under that session and the bot can discuss it back
# in WhatsApp.
def save_wa_token(token: str, session_id: str) -> None:
    if not token or not session_id:
        return
    try:
        with _lock, _connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO wa_test_tokens(token, session_id, ts) VALUES (?,?,?)",
                (token, session_id, int(time.time())),
            )
    except Exception:
        pass


def resolve_wa_token(token: str):
    if not token:
        return None
    try:
        with _lock, _connect() as c:
            row = c.execute(
                "SELECT session_id, ts FROM wa_test_tokens WHERE token=?", (token,)
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    sid, ts = row
    if int(time.time()) - int(ts or 0) > 86400:   # tokens valid 24h
        return None
    return sid


def clear_riasec(session_id: str) -> None:
    """Drop a session's profiling-test result (used by the WhatsApp «новый чат» /
    «пройти тест заново» commands so the bot starts fresh)."""
    if not session_id:
        return
    try:
        with _lock, _connect() as c:
            c.execute("DELETE FROM riasec_results WHERE session_id=?", (session_id,))
    except Exception:
        pass


def set_flag(message_id, flagged) -> None:
    """Manual flag toggle from the admin panel."""
    try:
        with _lock, _connect() as c:
            c.execute("UPDATE messages SET flagged=? WHERE id=?",
                      (1 if flagged else 0, int(message_id)))
    except Exception:
        pass


def mark_problematic(message_id, reason: str = "") -> None:
    """Mark a turn problematic (used by the async LLM reviewer in app/feedback.py).
    Keeps any existing reason if a new one is not supplied."""
    try:
        with _lock, _connect() as c:
            c.execute(
                "UPDATE messages SET problematic=1, "
                "problem_reason=COALESCE(NULLIF(?, ''), problem_reason) WHERE id=?",
                ((reason or "").strip(), int(message_id)),
            )
    except Exception:
        pass


def prev_turn(session_id: str, before_id):
    """(id, assistant_msg) of the turn just before `before_id` in the same session.
    Used to back-flag the answer a user is complaining about."""
    try:
        with _lock, _connect() as c:
            row = c.execute(
                "SELECT id, assistant_msg FROM messages "
                "WHERE session_id=? AND id<? ORDER BY id DESC LIMIT 1",
                (session_id, int(before_id)),
            ).fetchone()
        return (row[0], row[1]) if row else (None, None)
    except Exception:
        return (None, None)


def problems(limit: int = 300) -> List[dict]:
    """All problematic OR manually-flagged messages across every chat (any channel)."""
    try:
        with _lock, _connect() as c:
            rows = c.execute(
                "SELECT id, ts, session_id, source, user_msg, assistant_msg, sources, problematic, flagged, problem_reason "
                "FROM messages WHERE problematic=1 OR flagged=1 ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
    except Exception as e:
        print(f"[log] problems failed: {e}")
        return []
    cols = ["id", "ts", "session_id", "source", "user_msg", "assistant_msg",
            "sources", "problematic", "flagged", "problem_reason"]
    return [dict(zip(cols, r)) for r in rows]
