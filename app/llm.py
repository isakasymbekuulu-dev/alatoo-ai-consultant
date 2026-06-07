"""LLM client backed by GitHub Models (OpenAI-compatible)."""
from functools import lru_cache
from typing import Iterator, List, Dict

from openai import OpenAI

from app.config import settings


@lru_cache(maxsize=1)
def get_llm() -> OpenAI:
    return OpenAI(
        base_url=settings.github_models_base_url,
        api_key=settings.github_token,
    )


def chat(messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
    resp = get_llm().chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def chat_stream(messages: List[Dict[str, str]], temperature: float = 0.2) -> Iterator[str]:
    stream = get_llm().chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=temperature,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
