"""LLM-based review of chat turns: decide if a turn is *problematic* and should
be surfaced to a human (complaint, negative feedback, or a failed/unhelpful answer).

The keyword pre-filter in `logging_store._auto_problem` catches the obvious cases
instantly at write time; this module adds context-aware judgement by the LLM itself,
which is what catches complaints/feedback that no keyword list anticipated.

It runs **after** the answer is already sent, in a daemon thread, so it never adds
user-facing latency and never breaks the chat if the LLM is unavailable. When the
user's message is a complaint about the PREVIOUS answer, that earlier turn is
flagged too (back-flagging), so the actual bad answer shows up in the panel.
"""
import json
import logging
import threading

from app import logging_store
from app.llm import chat

log = logging.getLogger("alatoo.feedback")

_SYS = """Ты — модератор качества чат-бота приёмной комиссии университета «Ала-Тоо».
Тебе дают одну реплику диалога: вопрос пользователя и ответ бота. Для контекста
также дан предыдущий ответ бота. Реши, ПРОБЛЕМНЫЙ ли это случай — такой, который
должен увидеть и проверить человек.

Считай ПРОБЛЕМНЫМ, если выполнено хотя бы одно:
- пользователь жалуется, недоволен, раздражён, ругается, говорит что бот неправ,
  ответ неверный / бесполезный / не по теме;
- пользователь даёт негативный фидбэк об ответе (в том числе о ПРЕДЫДУЩЕМ ответе);
- бот не смог реально помочь: отговорился «обратитесь в приёмную комиссию», сказал
  что нет информации, ответил не на заданный вопрос, выдал явно неверный или
  противоречивый факт, либо произошёл технический сбой.

НЕ проблемное: обычный вопрос с нормальным содержательным ответом по существу;
благодарность; уточняющий вопрос; приветствие.

Верни СТРОГО JSON одной строкой, без markdown и пояснений:
{"problematic": true|false, "target": "current"|"previous"|"both", "reason": "<кратко, по-русски>"}
Где target:
- "current"  — проблема в текущем ответе бота;
- "previous" — пользователь жалуется на ПРЕДЫДУЩИЙ ответ (текущая реплика — сама жалоба);
- "both"     — проблема и в текущем, и в предыдущем.
Если problematic=false — target и reason можно оставить пустыми."""


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if "\n" in raw:
            raw = raw.split("\n", 1)[1]
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        raw = raw[s:e + 1]
    return json.loads(raw)


def _classify(user_msg, assistant_msg, prev_assistant_msg) -> dict:
    user = (
        f"Предыдущий ответ бота (контекст):\n{prev_assistant_msg or '—'}\n\n"
        f"Вопрос / реплика пользователя:\n{user_msg or '—'}\n\n"
        f"Ответ бота сейчас:\n{assistant_msg or '—'}"
    )
    raw = chat(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
        temperature=0.0,
    )
    return _parse_json(raw)


def _review_turn(message_id, session_id, user_msg, assistant_msg) -> None:
    try:
        prev_id, prev_assistant = logging_store.prev_turn(session_id, message_id)
        verdict = _classify(user_msg, assistant_msg, prev_assistant)
        if not verdict.get("problematic"):
            return
        reason = (verdict.get("reason") or "").strip()[:300]
        target = (verdict.get("target") or "current").lower()
        if target in ("current", "both"):
            logging_store.mark_problematic(message_id, reason)
        if target in ("previous", "both") and prev_id:
            logging_store.mark_problematic(prev_id, reason or "Жалоба на этот ответ")
    except Exception as e:  # noqa: BLE001 — best-effort; must never affect the chat
        log.warning("feedback review failed: %s", str(e)[:200])


def review_turn_async(message_id, session_id, user_msg, assistant_msg) -> None:
    """Fire-and-forget LLM review of one freshly-logged turn."""
    if not message_id:
        return
    threading.Thread(
        target=_review_turn,
        args=(message_id, session_id, user_msg, assistant_msg),
        daemon=True,
    ).start()
