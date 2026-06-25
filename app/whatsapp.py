"""WhatsApp Cloud API (Meta) adapter — a thin bridge to the existing backend.

    GET  /webhooks/whatsapp  -> Meta webhook verification (echoes hub.challenge)
    POST /webhooks/whatsapp  -> incoming text -> run_graph -> chat() -> send reply

The same dialog brain powers every channel: we just turn an inbound WhatsApp
message into the backend's `history` format, get the answer, and POST it back
through the Graph API. The sender's WhatsApp number becomes the session_id so
conversation logging stays per-user.

Config (app.config.settings, from .env):
    whatsapp_verify_token     must match the "Verify token" set in the Meta webhook
    whatsapp_token            Cloud API access token (System User token recommended)
    whatsapp_phone_number_id  the sending number's Phone Number ID
    whatsapp_app_secret       optional; if set, X-Hub-Signature-256 is verified
    whatsapp_api_version      Graph API version (default v21.0)
"""
import hashlib
import hmac
import logging
import re
import secrets
from collections import deque

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse

from app.config import settings
from app import logging_store, riasec
from app.graph import run_graph
from app.llm import chat

log = logging.getLogger("alatoo.whatsapp")
router = APIRouter()

# Small in-memory guard against Meta's webhook retries (same message delivered
# more than once). Bounded; resets on restart — fine for at-least-once delivery.
_seen_ids: deque = deque(maxlen=512)
_seen_set: set = set()

_NON_TEXT_REPLY = ("Пока я понимаю только текстовые сообщения. "
                   "Напишите вопрос текстом — и я помогу.")

WA_DIRECTIVE = (
    "КАНАЛ: WhatsApp. Учитывай:\n"
    "- Ты общаешься в WhatsApp, а не на сайте. НЕ советуй «обновить страницу», "
    "«нажать Новый чат» или другие действия веб-интерфейса — их здесь нет.\n"
    "- Чтобы пройти тест профориентации заново или начать диалог заново, пользователь "
    "пишет «пройти тест заново» или «новый чат» — подскажи это, если он спрашивает, как начать сначала.\n"
    "- Пиши простым текстом, без markdown-заголовков и таблиц. Ссылки давай как обычный URL.\n"
    "Отвечай на языке пользователя."
)

_RESET_REPLY = (
    "Готово — начинаем с чистого листа, прежние результаты теста сброшены. "
    "Чем могу помочь? Если хотите пройти тест профориентации — напишите «пройти тест»."
)


def _is_retake(t: str) -> bool:
    again = ("заново", "заного", "снова", "сначала", "ещё раз", "еще раз",
             "ещёраз", "ещераз", "по новой", "по-новой", "again", "retake", "повтор")
    test = ("тест", "test", "профориент", "пройти")
    return any(a in t for a in again) and any(x in t for x in test)


def _is_reset(t: str) -> bool:
    keys = ("новый чат", "новый диалог", "новый разговор", "начать заново",
            "начни заново", "начать сначала", "сброс", "сбрось", "очистить истори",
            "очисти истори", "очистить контекст", "с чистого листа", "clear", "reset",
            "/new", "/reset")
    return any(k in t for k in keys)


def _test_invite(session_id: str) -> str:
    num = (settings.whatsapp_display_number or "").strip()
    q = "src=wa" + ("&wa=" + num if num else "")
    tok = secrets.token_urlsafe(9)
    logging_store.save_wa_token(tok, session_id)
    q += "&t=" + tok
    url = _SITE_BASE + "/test?" + q
    return ("Открываю тест профориентации заново (≈7 минут, 60 вопросов):\n" + url +
            "\n\nПосле прохождения результат придёт сюда, в WhatsApp.")



# WhatsApp text messages have no Markdown links: "[label](url)" renders literally
# and looks broken. We convert them to a WhatsApp-native form — *bold label* on
# one line, the raw (auto-clickable) URL on the next — and turn **bold** into
# WhatsApp's single-asterisk bold. The web chat keeps real Markdown (web only).
_SITE_BASE = "https://chat.alatoogpt.xyz"
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+|/[^\s)]+)\)")
_MD_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")


def _wa_format(text: str, session_id: str = None) -> str:
    def link(m):
        label = m.group(1).strip()
        url = m.group(2).strip()
        if url.startswith("/test"):
            # came from WhatsApp -> carry source + an opaque token that ties the
            # test result back to this wa session (no phone number in the URL),
            # and return the user to WhatsApp after the test.
            q = "src=wa"
            num = (settings.whatsapp_display_number or "").strip()
            if num:
                q += "&wa=" + num
            if session_id:
                tok = secrets.token_urlsafe(9)
                logging_store.save_wa_token(tok, session_id)
                q += "&t=" + tok
            url = _SITE_BASE + url + ("&" if "?" in url else "?") + q
        elif url.startswith("/"):
            url = _SITE_BASE + url
        return "*%s*\n%s" % (label, url)
    text = _MD_LINK.sub(link, text)
    text = _MD_BOLD.sub(r"*\1*", text)
    return text


def _graph_api() -> str:
    return "https://graph.facebook.com/" + settings.whatsapp_api_version


def _valid_signature(body: bytes, header: str) -> bool:
    """Verify X-Hub-Signature-256 if an app secret is configured."""
    secret = settings.whatsapp_app_secret
    if not secret:
        return True  # signature verification disabled
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def _send_text(to: str, text: str) -> None:
    token = settings.whatsapp_token
    pnid = settings.whatsapp_phone_number_id
    if not token or not pnid:
        log.error("WhatsApp send skipped: token or phone_number_id not configured")
        return
    url = "%s/%s/messages" % (_graph_api(), pnid)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": True, "body": text[:4096]},
    }
    try:
        r = httpx.post(url, json=payload,
                       headers={"Authorization": "Bearer " + token}, timeout=30)
        if r.status_code >= 400:
            log.error("WhatsApp send failed %s: %s", r.status_code, r.text[:300])
    except Exception as e:  # noqa: BLE001
        log.error("WhatsApp send error: %s", e)


def _riasec_summary(session_id: str):
    """If this wa-user took the profiling test (result saved under their wa session),
    return a short summary so the bot can discuss it back in WhatsApp."""
    try:
        stored = logging_store.riasec_for_session(session_id)
        if not stored:
            return None
        result = {
            "code": stored["code"],
            "scores": stored["scores"]["scores"],
            "percents": stored["scores"]["percents"],
            "ranked": stored["scores"]["ranked"],
            "recommendations": stored["recs"],
        }
        return riasec.summary_for_llm(result, name=stored.get("name"))
    except Exception:
        return None


_PUSH_L = {
    "ru": ("🎯 Ваш результат теста профориентации готов!",
           "Ваш код по методике Голланда",
           "Подходящие программы Ала-Тоо для вас",
           "Хотите обсудить результат или узнать подробнее о какой-то программе? Просто напишите — и я помогу."),
    "ky": ("🎯 Кесиптик багыт тестиңиздин жыйынтыгы даяр!",
           "Голланд методикасы боюнча кодуңуз",
           "Сизге ылайыктуу Ала-Тоо программалары",
           "Жыйынтыкты талкуулайбызбы же кайсы бир программа жөнүндө кеңири билгиңиз келеби? Жазыңыз — жардам берем."),
    "en": ("🎯 Your career test result is ready!",
           "Your Holland code",
           "Programs at Ala-Too that fit you",
           "Want to discuss your result or learn more about a program? Just message me — I'll help."),
}


def _format_riasec_push(result: dict, lang: str, name=None) -> str:
    L = _PUSH_L.get(lang, _PUSH_L["ru"])
    greet = ("%s, " % name) if name else ""
    lines = [greet + L[0], "", "%s: *%s*" % (L[1], result.get("code", "")), "", L[2] + ":"]
    for i, r in enumerate((result.get("recommendations") or [])[:5], 1):
        lines.append("%d. *%s* (%s) — %s%%" % (
            i, r.get("program", ""), r.get("faculty", ""), r.get("match", "")))
    lines += ["", L[3]]
    return "\n".join(lines)


def push_riasec_result(to: str, result: dict, lang: str = "ru", name=None) -> None:
    """Proactively message the WhatsApp user their test result right after submit,
    so when they return to WhatsApp the result is already waiting (no need to ask)."""
    try:
        _send_text(to, _format_riasec_push(result, lang, name))
    except Exception as e:  # noqa: BLE001 — never break the test submit
        log.warning("WhatsApp riasec push failed: %s", e)


def _answer_for(text: str, session_id: str) -> str:
    history = [{"role": "user", "content": text}]
    messages, chunks, intent, trace = run_graph(history, riasec_summary=_riasec_summary(session_id))
    messages.append({"role": "system", "content": WA_DIRECTIVE})   # WhatsApp-channel role
    answer = _wa_format(chat(messages), session_id)
    try:
        sources = [{"title": c.get("title", ""), "source": c.get("source", ""),
                    "source_url": c.get("source_url", ""),
                    "score": round(c.get("score", 0), 3)} for c in chunks]
        logging_store.log_turn(session_id, "whatsapp", text, answer, sources, False)
    except Exception as e:  # noqa: BLE001 — never let logging break a reply
        log.warning("WhatsApp log_turn failed: %s", e)
    return answer


def _process(value: dict) -> None:
    """Handle one webhook 'value' object: reply to any text messages in it."""
    for msg in value.get("messages", []) or []:
        mid = msg.get("id")
        if mid:
            if mid in _seen_set:
                continue
            _seen_set.add(mid)
            _seen_ids.append(mid)
            if len(_seen_ids) == _seen_ids.maxlen:
                # keep the set bounded alongside the deque
                while len(_seen_set) > _seen_ids.maxlen:
                    _seen_set.discard(_seen_ids[0])
        sender = msg.get("from")
        if not sender:
            continue
        session_id = "wa-" + sender
        if msg.get("type") == "text":
            text = (msg.get("text") or {}).get("body", "").strip()
            if not text:
                continue
            low = text.lower()
            if _is_retake(low):
                logging_store.clear_riasec(session_id)
                reply = _test_invite(session_id)
            elif _is_reset(low):
                logging_store.clear_riasec(session_id)
                reply = _RESET_REPLY
            else:
                reply = _answer_for(text, session_id)
        else:
            reply = _NON_TEXT_REPLY
        _send_text(sender, reply)


@router.get("/webhooks/whatsapp")
def verify(hub_mode: str = Query("", alias="hub.mode"),
           hub_challenge: str = Query("", alias="hub.challenge"),
           hub_verify_token: str = Query("", alias="hub.verify_token")):
    """Meta webhook verification handshake."""
    if (hub_mode == "subscribe" and settings.whatsapp_verify_token
            and hub_verify_token == settings.whatsapp_verify_token):
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/webhooks/whatsapp")
async def incoming(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not _valid_signature(body, request.headers.get("x-hub-signature-256", "")):
        return JSONResponse({"error": "bad signature"}, status_code=403)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": True})  # ack non-JSON pings
    # Acknowledge fast (Meta retries slow endpoints); do the LLM work in the
    # background so the webhook returns 200 immediately.
    for entry in data.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            if value.get("messages"):
                background.add_task(_process, value)
    return JSONResponse({"ok": True})
