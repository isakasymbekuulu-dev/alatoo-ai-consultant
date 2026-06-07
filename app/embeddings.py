"""Embeddings — pluggable backend.

- If EMBED_MODEL looks like an API model (e.g. "openai/text-embedding-3-small"),
  embeddings are computed via GitHub Models (no local model, low RAM).
- Otherwise EMBED_MODEL is loaded locally with sentence-transformers
  (default: BAAI/bge-m3, dim 1024 — best multilingual ru/ky/en).

The same model is used at index-time and query-time. Switch backends by
changing EMBED_MODEL / EMBED_DIM in .env — no code change needed.
"""
from functools import lru_cache
from typing import List

from app.config import settings

_BATCH = 64
_API_VENDORS = {"openai", "azure", "cohere"}


def _is_api_model(name: str) -> bool:
    return "/" in name and name.split("/", 1)[0].lower() in _API_VENDORS


@lru_cache(maxsize=1)
def _local_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embed_model)


def embed_texts(texts: List[str]) -> List[List[float]]:
    if _is_api_model(settings.embed_model):
        from app.llm import get_llm
        client = get_llm()
        out: List[List[float]] = []
        for i in range(0, len(texts), _BATCH):
            batch = [t.replace("\n", " ") for t in texts[i:i + _BATCH]]
            resp = client.embeddings.create(model=settings.embed_model, input=batch)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return out

    model = _local_model()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
        batch_size=16,
    )
    return vectors.tolist()


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
