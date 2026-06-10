from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (GitHub Models, OpenAI-compatible)
    github_token: str = ""
    github_models_base_url: str = "https://models.github.ai/inference"
    llm_model: str = "openai/gpt-4o-mini"

    # Embeddings. Local BGE-M3 by default (best ky/ru/en).
    # For an API backend instead, set EMBED_MODEL=openai/text-embedding-3-small, EMBED_DIM=1536
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "alatoo_kb"

    # Retrieval / generation
    top_k: int = 5
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
