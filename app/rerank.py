"""Cross-encoder reranking via FastEmbed (ONNX, CPU-friendly).

Hybrid retrieval (dense+sparse) gives high recall; a cross-encoder re-scores the
top candidates jointly against the query for higher precision. Model:
jina-reranker-v2-base-multilingual (~278M, ru/en + many langs) — light enough for
the 1-vCPU droplet when applied to a small candidate set. Lazily loaded/cached.
"""
from functools import lru_cache
from typing import List

from app.config import settings


@lru_cache(maxsize=1)
def get_reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder(model_name=settings.rerank_model)


def rerank(query: str, chunks: List[dict], top_n: int) -> List[dict]:
    """Re-score chunks (list of dicts with 'text') and return the top_n, ordered."""
    if not chunks:
        return chunks
    ce = get_reranker()
    scores = list(ce.rerank(query, [c.get("text", "") for c in chunks]))
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    out = []
    for i in order[:top_n]:
        c = dict(chunks[i])
        c["rerank_score"] = float(scores[i])
        out.append(c)
    return out
