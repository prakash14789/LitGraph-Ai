"""Application settings, loaded from environment variables / .env.

Single source of config truth — every service (DB, graph, vector store, LLM,
retrieval tuning) reads from here rather than os.environ directly.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "litgraph"
    app_env: Literal["development", "staging", "production"] = "development"
    app_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "litgraph"
    postgres_user: str = "litgraph_user"
    postgres_password: str  # required — no safe default, fail loudly at startup if missing

    @property
    def database_url(self) -> str:
        """SQLAlchemy async DSN (used from SETUP-004 onward)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn(self) -> str:
        """Raw asyncpg DSN (used for the /health ping — no ORM involved)."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str  # required — no safe default, fail loudly at startup if missing

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection_chunks: str = "paper_chunks"
    chroma_collection_entities: str = "entity_embeddings"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    llm_provider: Literal["gemini", "openai", "anthropic"] = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # "-latest" aliases, not dated snapshots — Google deprecates dated Gemini
    # models for new API keys faster than this project's timeline (verified
    # live: gemini-2.5-flash-lite and gemini-2.5-flash both 404'd as "no
    # longer available to new users" while gemini-flash-latest worked fine).
    extraction_model: str = "gemini-flash-latest"
    extraction_max_tokens: int = 4096
    extraction_temperature: float = 0.1
    generation_model: str = "gemini-flash-latest"
    generation_max_tokens: int = 2048
    generation_temperature: float = 0.3
    llm_rate_limit_rpm: int = 15  # Gemini free tier default (Flash: 15 RPM)

    # Embedding
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Retrieval
    vector_top_k: int = 10
    entity_top_k: int = 5
    graph_traversal_hops: int = 2
    hybrid_alpha: float = 0.4
    hybrid_beta: float = 0.4
    hybrid_gamma: float = 0.2
    context_max_nodes: int = 20

    # Ingestion
    max_papers_per_upload: int = 50
    max_pdf_size_mb: int = 50
    chunk_size_tokens: int = 1000
    chunk_overlap_tokens: int = 200
    entity_confidence_threshold: float = 0.5
    relation_confidence_threshold: float = 0.5

    # File storage
    upload_dir: str = "./data/uploads"
    processed_dir: str = "./data/processed"


settings = Settings()
