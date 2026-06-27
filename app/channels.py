"""Channel registry — the seam that makes the bot multi-messenger.

Every messenger adapter (WhatsApp now; Telegram / Instagram later) registers a
`send_text(recipient, text)` callable here under a channel name. Shared code
(operator handoff, escalation push) can then deliver a message to any channel
without importing the adapter, e.g. `channels.send_to_session(session_id, text)`.

Session ids are prefixed per channel (`wa-<num>`, `tg-<chat>`, `ig-<id>`) so the
channel + recipient can be recovered from the id alone.
"""
import logging

log = logging.getLogger("alatoo.channels")

# channel name -> send_text(recipient, text)
_SENDERS = {}

# session-id prefix -> channel name
_PREFIX = {"wa-": "whatsapp", "tg-": "telegram", "ig-": "instagram"}


def register_sender(channel: str, fn) -> None:
    _SENDERS[channel] = fn


def channel_of(session_id: str) -> str:
    for p, c in _PREFIX.items():
        if (session_id or "").startswith(p):
            return c
    return "web"


def recipient_of(session_id: str) -> str:
    for p in _PREFIX:
        if (session_id or "").startswith(p):
            return session_id[len(p):]
    return session_id or ""


def send(channel: str, recipient: str, text: str) -> bool:
    fn = _SENDERS.get(channel)
    if not fn:
        log.warning("no sender registered for channel '%s'", channel)
        return False
    try:
        fn(recipient, text)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("send via '%s' failed: %s", channel, e)
        return False


def send_to_session(session_id: str, text: str) -> bool:
    """Deliver a message to whatever channel a session belongs to."""
    return send(channel_of(session_id), recipient_of(session_id), text)
