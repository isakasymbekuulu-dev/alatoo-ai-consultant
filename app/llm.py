"""LLM client with automatic provider failover (OpenAI-compatible + Azure).

Tries providers in order and falls through on quota / rate-limit / server errors,
so the bot stays up when one provider is exhausted. Default order:
  Azure OpenAI (no hard limit)  ->  generic/primary (e.g. Gemini)  ->  GitHub Models
Each provider is enabled only when its credentials are configured.
"""
import logging
from functools import lru_cache
from typing import Dict, Iterator, List, Tuple

from openai import OpenAI

from app.config import settings

log = logging.getLogger("alatoo.llm")

# (name, base_url, api_key, model, api_version)  api_version != "" => Azure
Provider = Tuple[str, str, str, str, str]


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
    raise last_err


def chat_stream(messages: List[Dict[str, str]], temperature: float = 0.2) -> Iterator[str]:
    last_err = None
    for name, base, key, model, ver in _providers():
        try:
            stream = _client(base, key, ver).chat.completions.create(
                model=model, messages=messages, temperature=temperature, stream=True)
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        except Exception as e:  # noqa: BLE001 — quota/429 occur before any token
            last_err = e
            log.warning("LLM stream provider '%s' failed: %s — trying next", name, str(e)[:200])
            continue
    raise last_err
