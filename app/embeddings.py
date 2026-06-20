"""Embeddings for hybrid retrieval, exposed as LangChain objects.

Dense (semantic): local BGE-M3 via sentence-transformers (default; best
multilingual ru/ky/en) or an API model (EMBED_MODEL=openai/...). Sparse
(lexical): BM25 via FastEmbed — cheap, great for exact tokens (room numbers
like "A315", phones, ОРТ scores). Same objects at index- and query-time.
"""
import os
from functools import lru_cache
from typing import List

from langchain_core.embeddings import Embeddings

from app.config import settings

_BATCH = 64
_API_VENDORS = {"openai", "azure", "cohere"}


def _is_api_model(name: str) -> bool:
    return "/" in name and name.split("/", 1)[0].lower() in _API_VENDORS


class _LocalDense(Embeddings):
    """BGE-M3 (sentence-transformers) as LangChain Embeddings."""

    @lru_cache(maxsize=1)
    def _model(self):
        try:
            import torch
            torch.set_num_threads(os.cpu_count() or 4)
        except Exception:
            pass
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(settings.embed_model)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vecs = self._model().encode(
            texts, normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False, batch_size=16,
        )
        return vecs.tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class _ApiDense(Embeddings):
    """API embeddings via the OpenAI-compatible client."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        from app.llm import get_llm
        client = get_llm()
        out: List[List[float]] = []
        for i in range(0, len(texts), _BATCH):
            batch = [t.replace("\n", " ") for t in texts[i:i + _BATCH]]
            resp = client.embeddings.create(model=settings.embed_model, input=batch)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return out

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


@lru_cache(maxsize=1)
def get_dense_embeddings() -> Embeddings:
    return _ApiDense() if _is_api_model(settings.embed_model) else _LocalDense()


@lru_cache(maxsize=1)
def get_sparse_embeddings():
    """BM25 sparse embeddings (FastEmbed). Lazily loaded/cached."""
    from langchain_qdrant import FastEmbedSparse
    return FastEmbedSparse(model_name=settings.sparse_model, threads=os.cpu_count() or 4)
