"""LLM client with robust automatic provider failover (OpenAI-compatible + Azure).

Tries providers in order; falls through on quota / rate-limit / server errors.
Default order: Azure OpenAI -> primary (e.g. Groq) -> explicit fallback (e.g.
OpenAI) -> GitHub Models. Streaming is hardened so a provider failure never
breaks the SSE stream (which surfaced as client 'payload is not completed' /
TransferEncodingError): we only switch providers before any token is emitted,
and on total failure we emit a short message instead of raising mid-stream.
"""
import logging
from functools import lru_cache
from typing import Dict, Iterator, List, Tuple

from openai import OpenAI

from app.config import settings

log = logging.getLogger("alatoo.llm")

# (name, base_url, api_key, model, api_version)  api_version != "" => Azure
Provider = Tuple[str, str, str, str, str]

_FAIL_MSG = ("Извините, сервис ИИ временно недоступен. Пожалуйста, попробуйте чуть позже "
             "или обратитесь в приёмную комиссию.")


def _providers() -> List[Provider]:
    p: List[Provider] = []
    if settings.llm_azure_endpoint and settings.llm_azure_api_key and settings.llm_azure_deployment:
        p.append(("azure", settings.llm_azure_endpoint, settings.llm_azure_api_key,
                  settings.llm_azure_deployment, settings.llm_azure_api_version))
    if settings.llm_api_key and settings.llm_base_url:
        p.append(("primary", settings.llm_base_url, settings.llm_api_key, settings.llm_model, ""))
    if settings.llm_fallback_api_key and settings.llm_fallback_base_url:
        p.append(("fallback", settings.llm_fallback_base_url, settings.llm_fallback_api_key,
                  settings.llm_fallback_model or settings.llm_model, ""))
    if settings.github_token:
        p.append(("github-models", settings.github_models_base_url,
                  settings.github_token, settings.github_model, ""))
    if not p:
        p.append(("github-models", settings.github_models_base_url,
                  settings.github_token, settings.github_model, ""))
    return p


@lru_cache(maxsize=8)
def _client(base_url: str, api_key: str, api_version: str):
    if api_version:  # Azure OpenAI
        from openai import AzureOpenAI
        return AzureOpenAI(azure_endpoint=base_url, api_key=api_key,
                           api_version=api_version, timeout=60, max_retries=0)
    return OpenAI(base_url=base_url, api_key=api_key, timeout=60, max_retries=0)


def get_llm() -> OpenAI:  # back-compat (e.g. API embeddings); first provider's client
    _, base, key, _, ver = _providers()[0]
    return _client(base, key, ver)


def chat(messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
    last_err = None
    for name, base, key, model, ver in _providers():
        try:
            resp = _client(base, key, ver).chat.completions.create(
                model=model, messages=messages, temperature=temperature)
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 — fail over on any provider error
            last_err = e
            log.warning("LLM provider '%s' failed: %s — trying next", name, str(e)[:200])
    log.error("All LLM providers failed: %s", last_err)
    return _FAIL_MSG


def chat_stream(messages: List[Dict[str, str]], temperature: float = 0.2) -> Iterator[str]:
    last_err = None
    for name, base, key, model, ver in _providers():
        produced = False
        try:
            stream = _client(base, key, ver).chat.completions.create(
                model=model, messages=messages, temperature=temperature, stream=True)
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    produced = True
                    yield chunk.choices[0].delta.content
            return  # finished cleanly
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("LLM stream provider '%s' failed: %s", name, str(e)[:200])
            if produced:
                # Already streamed partial output — switching would garble it; stop cleanly.
                return
            continue  # nothing emitted yet — try the next provider
    log.error("All LLM stream providers failed: %s", last_err)
    yield _FAIL_MSG  # graceful message instead of breaking the SSE stream
