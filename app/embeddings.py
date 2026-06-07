"""Embeddings via GitHub Models (OpenAI-compatible), text-embedding-3-small.

Runs through the API (no local model / no torch), so it fits a small droplet.
The same GitHub token (Models: read) is used for both the LLM and embeddings.
The exact same model is used at index-time and query-time.
"""
from typing import List

from app.config import settings
from app.llm import get_llm

# GitHub Models / OpenAI cap the array size per request; keep batches modest.
_BATCH = 64


def embed_texts(texts: List[str]) -> List[List[float]]:
    client = get_llm()
    out: List[List[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = [t.replace("\n", " ") for t in texts[i:i + _BATCH]]
        resp = client.embeddings.create(model=settings.embed_model, input=batch)
        # Preserve input order.
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
