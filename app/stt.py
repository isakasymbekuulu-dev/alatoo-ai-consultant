"""Speech-to-text for voice messages on social channels.

Uses OpenAI `gpt-4o-transcribe` (per Isa's choice) — strong multilingual model
that auto-detects language and handles code-switching (ru/ky/en mixed in one
voice note) when we DON'T pin a language. Falls back to `whisper-1` on error.

Best-effort: returns None if disabled, unconfigured, or all attempts fail, so a
failed transcription degrades to the polite "send text" reply, never a crash.
"""
import io
import logging

from openai import OpenAI

from app.config import settings

log = logging.getLogger("alatoo.stt")


def _key() -> str:
    return settings.stt_api_key or settings.llm_api_key or ""


def _client() -> OpenAI:
    return OpenAI(base_url=settings.stt_base_url, api_key=_key(), timeout=120, max_retries=0)


def available() -> bool:
    return bool(settings.stt_enabled and _key())


def transcribe(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe an audio blob to text. Returns '' on any failure."""
    if not available() or not audio_bytes:
        return ""
    if len(audio_bytes) > settings.stt_max_mb * 1024 * 1024:
        log.warning("audio too large: %d bytes", len(audio_bytes))
        return ""
    client = _client()
    for model in (settings.stt_model, settings.stt_fallback_model):
        if not model:
            continue
        try:
            f = io.BytesIO(audio_bytes)
            f.name = filename
            # No `language=` on purpose -> auto-detect / code-switching.
            resp = client.audio.transcriptions.create(model=model, file=f)
            text = (getattr(resp, "text", "") or "").strip()
            if text:
                return text
        except Exception as e:  # noqa: BLE001 — try fallback, then give up
            log.warning("STT model '%s' failed: %s", model, str(e)[:200])
    return ""
