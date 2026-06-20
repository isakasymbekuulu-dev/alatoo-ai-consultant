from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (GitHub Models, OpenAI-compatible)
    github_token: str = ""
    github_models_base_url: str = "https://models.github.ai/inference"
    llm_model: str = "openai/gpt-4o-mini"

    # Generic OpenAI-compatible LLM override — set to switch provider
    # (Gemini/Groq/Azure/OpenAI). If empty, falls back to GitHub Models above.
    # e.g. LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
    #      LLM_API_KEY=...   LLM_MODEL=gemini-2.0-flash
    llm_base_url: str = ""
    llm_api_key: str = ""

    # Embeddings. Local BGE-M3 by default (best ky/ru/en).
    # For an API backend: EMBED_MODEL=openai/text-embedding-3-small, EMBED_DIM=1536
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024

    # Sparse embeddings for hybrid (lexical) retrieval — great for exact tokens
    # (room numbers like "A315", phones, ОРТ scores). BM25 is tiny/CPU-cheap.
    sparse_model: str = "Qdrant/bm25"

    # Cross-encoder reranking (FastEmbed, ONNX). Re-scores the top candidates for
    # precision. Light multilingual model to stay fast on 1 vCPU.
    rerank_enabled: bool = False  # off by default: cross-encoder is too slow on CPU for live chat (set RERANK_ENABLED=true to re-enable)
    rerank_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    rerank_fetch_k: int = 10   # candidates from hybrid before reranking

    # Qdrant (hybrid collection uses named vectors: "dense" + "sparse")
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "alatoo_kb"

    # Retrieval / generation. NOTE: hybrid fused score is RRF (~0.01-0.03),
    # NOT cosine — so score_threshold is not applied to hybrid results.
    top_k: int = 6
    score_threshold: float = 0.3
    max_context_chars: int = 8000

    # Backend
    backend_api_key: str = ""
    served_model_name: str = "alatoo-rag"

    # Conversation logging
    log_db: str = "/app/logs/chat.db"
    admin_token: str = ""   # protects /admin/logs; if empty, viewer is disabled

    # Rate limiting for the public chat (per client IP, per minute)
    rate_limit_per_min: int = 20


settings = Settings()
