from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM providers with automatic failover ---
    # The client tries providers in order; on a quota/rate-limit/server error
    # it falls through to the next. Order: primary -> explicit fallback ->
    # GitHub Models (always available via github_token, used as last resort).

    # Primary provider (generic OpenAI-compatible). Set to switch, e.g. Gemini:
    #   LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
    #   LLM_API_KEY=...   LLM_MODEL=gemini-2.0-flash
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gemini-2.0-flash"

    # Explicit fallback provider (optional, e.g. Groq). If unset, GitHub Models
    # is used as the fallback.
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""

    # Azure OpenAI (gpt-4o-mini) — high quota via GitHub Education $100 credit.
    # If endpoint+key+deployment are set, Azure becomes the TOP primary, with
    # the generic provider (e.g. Gemini) and GitHub Models as auto-fallbacks.
    llm_azure_endpoint: str = ""       # https://<resource>.openai.azure.com
    llm_azure_api_key: str = ""
    llm_azure_deployment: str = ""     # your gpt-4o-mini deployment name
    llm_azure_api_version: str = "2024-10-21"

    # GitHub Models (OpenAI-compatible) — built-in last-resort fallback.
    github_token: str = ""
    github_models_base_url: str = "https://models.github.ai/inference"
    github_model: str = "openai/gpt-4o-mini"

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
