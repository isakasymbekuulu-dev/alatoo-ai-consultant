"""Thin Qdrant helper: collection management + search."""
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import settings


def get_client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=60,
    )


def ensure_collection(client: QdrantClient, recreate: bool = False) -> None:
    name = settings.qdrant_collection
    exists = client.collection_exists(name)
    if exists and recreate:
        client.delete_collection(name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(
                size=settings.embed_dim,
                distance=qm.Distance.COSINE,
            ),
        )
        # Payload indexes for fast metadata filtering.
        for field in ("lang", "doc_type", "faculty", "program", "source"):
            try:
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=qm.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass


def search(
    client: QdrantClient,
    query_vector: List[float],
    top_k: int,
    score_threshold: Optional[float] = None,
    lang: Optional[str] = None,
) -> List[qm.ScoredPoint]:
    flt = None
    if lang:
        flt = qm.Filter(
            must=[qm.FieldCondition(key="lang", match=qm.MatchValue(value=lang))]
        )
    return client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=flt,
        with_payload=True,
    ).points
