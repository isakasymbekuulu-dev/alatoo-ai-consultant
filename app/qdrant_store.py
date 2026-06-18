"""Qdrant access via LangChain's QdrantVectorStore in HYBRID mode.

Two named vectors: "dense" (BGE-M3, cosine) + "sparse" (BM25, exact tokens).
Results fused with Reciprocal Rank Fusion by langchain-qdrant.
"""
from functools import lru_cache
from typing import List

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import settings
from app.embeddings import get_dense_embeddings, get_sparse_embeddings

DENSE_NAME = "dense"
SPARSE_NAME = "sparse"

_FILTER_FIELDS = ("lang", "doc_type", "source", "faculty", "program", "section")


def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=60)


@lru_cache(maxsize=1)
def get_vector_store() -> QdrantVectorStore:
    """Vector store bound to the existing collection — for querying."""
    return QdrantVectorStore.from_existing_collection(
        collection_name=settings.qdrant_collection,
        embedding=get_dense_embeddings(),
        sparse_embedding=get_sparse_embeddings(),
        retrieval_mode=RetrievalMode.HYBRID,
        vector_name=DENSE_NAME,
        sparse_vector_name=SPARSE_NAME,
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )


def _create_filter_indexes(client: QdrantClient) -> None:
    for field in _FILTER_FIELDS:
        try:
            client.create_payload_index(
                collection_name=settings.qdrant_collection,
                field_name="metadata." + field,
                field_schema=qm.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass


def build_collection(documents: List[Document]) -> QdrantVectorStore:
    """(Re)create the hybrid collection and upsert documents — for ingestion."""
    vs = QdrantVectorStore.from_documents(
        documents,
        embedding=get_dense_embeddings(),
        sparse_embedding=get_sparse_embeddings(),
        retrieval_mode=RetrievalMode.HYBRID,
        vector_name=DENSE_NAME,
        sparse_vector_name=SPARSE_NAME,
        collection_name=settings.qdrant_collection,
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        force_recreate=True,
        batch_size=64,
    )
    _create_filter_indexes(get_client())
    return vs
