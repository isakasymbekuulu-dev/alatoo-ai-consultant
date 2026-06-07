"""Shared embedding model (BGE-M3 by default).

Loaded once per process and reused by both the API and the ingestion script,
so query-time and index-time vectors come from exactly the same model.
"""
from functools import lru_cache
from typing import List

from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    # Lazy singleton; first call downloads the model into the HF cache volume.
    return SentenceTransformer(settings.embed_model)


def embed_texts(texts: List[str]) -> List[List[float]]:
    model = get_model()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,   # cosine-ready unit vectors
        convert_to_numpy=True,
        show_progress_bar=False,
        batch_size=16,
    )
    return vectors.tolist()


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
