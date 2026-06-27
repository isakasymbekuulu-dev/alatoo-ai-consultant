"""Active staff notification for escalations (the "push" half of queue+push).

Best-effort, fire-and-forget. Sends to a staff Telegram group (if a bot token +
chat id are configured) and/or a generic webhook. If nothing is configured it is
a no-op — the operator-console queue still shows the escalation either way.
"""
import logging
import threading

import httpx

from app.config import settings

log = logging.getLogger("alatoo.notify")


def _send_telegram(text: str) -> None:
    token = settings.staff_telegram_bot_token
    chat = settings.staff_telegram_chat_id
    if not token or not chat:
        return
    try:
        httpx.post(
            "https://api.telegram.org/bot%s/sendMessage" % token,
            json={"chat_id": chat, "text": text, "disable_web_page_preview": False},
            timeout=15,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("telegram notify failed: %s", str(e)[:200])


def _send_webhook(text: str) -> None:
    url = settings.staff_notify_webhook
    if not url:
        return
    try:
        httpx.post(url, json={"text": text}, timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("webhook notify failed: %s", str(e)[:200])


def _deliver(text: str) -> None:
    _send_telegram(text)
    _send_webhook(text)


def notify_staff(text: str) -> None:
    """Fire-and-forget staff ping."""
    if not (settings.staff_telegram_bot_token or settings.staff_notify_webhook):
        return
    threading.Thread(target=_deliver, args=(text,), daemon=True).start()


def escalation_message(session_id: str, channel: str, reason: str, priority: int) -> str:
    pr = {2: "🔴 СРОЧНО", 1: "🟠 Важно", 0: "🟡 Обычный"}.get(int(priority or 0), "🟡")
    link = settings.operator_base_url.rstrip("/") + "/admin/operator"
    return (
        "⚑ Нужен оператор (%s)\n"
        "Канал: %s\n"
        "Причина: %s\n"
        "Диалог: %s\n"
        "Открыть консоль: %s"
    ) % (pr, channel or "—", (reason or "—")[:300], session_id, link)
