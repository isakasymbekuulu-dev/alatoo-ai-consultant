from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (GitHub Models, OpenAI-compatible)
    github_token: str = ""
    github_models_base_url: str = "https://models.github.ai/inference"
    llm_model: str = "openai/gpt-4o-mini"

    # Embeddings
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


settings = Settings()
