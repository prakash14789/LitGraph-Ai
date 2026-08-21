"""Application settings, loaded from environment variables / .env.

Single source of config truth — every service (DB, graph, vector store, LLM,
retrieval tuning) reads from here rather than os.environ directly.
"""

from typing import Literal

from pydantic import Field
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
    postgres_password: str = "devpassword123"
    database_url_raw: str = Field(default="", alias="DATABASE_URL")

    @property
    def database_url(self) -> str:
        """SQLAlchemy async DSN (used from SETUP-004 onward)."""
        if self.database_url_raw:
            return self.database_url_raw
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn(self) -> str:
        """Raw asyncpg DSN (used for the /health ping — no ORM involved)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str  # required — no safe default, fail loudly at startup if missing

    # Qdrant Cloud
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection_chunks: str = "paper_chunks"
    qdrant_collection_entities: str = "entity_embeddings"

    # Legacy ChromaDB aliases for backwards compatibility
    chroma_host: str = "localhost"
    chroma_port: int = 8000

    @property
    def chroma_collection_chunks(self) -> str:
        return self.qdrant_collection_chunks

    @property
    def chroma_collection_entities(self) -> str:
        return self.qdrant_collection_entities

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    llm_provider: Literal[
        "gemini", "openai", "anthropic", "groq", "openrouter", "cerebras", "huggingface", "ollama"
    ] = "gemini"
    gemini_api_key: str = ""
    # Optional 2nd Gemini key — llm_client.py switches to it automatically
    # once gemini_api_key hits a 429 quota error. A free key's daily cap can
    # be as low as ~20 requests for a given model (measured live, EXTRACT-001)
    # — far stricter than the RPM limit below, and not something backoff
    # retries fix (waiting a minute doesn't refill a daily quota).
    gemini_api_key_fallback: str = ""
    # Free tier, no card, OpenAI-compatible endpoint — same shape as the
    # other three providers, no new SDK needed. Meaningfully higher daily cap
    # than Gemini's free tier (100K tokens/day on llama-3.3-70b-versatile vs
    # Gemini's measured ~20 requests/day) — the fallback for when both
    # Gemini keys are exhausted for the day. Flip LLM_PROVIDER=groq and set
    # EXTRACTION_MODEL/GENERATION_MODEL to a Groq model name to use it.
    groq_api_key: str = ""
    # Optional 2nd Groq key — same _KeyRing llm_client.py already built for
    # Gemini switches to it automatically on a 429, no new logic needed
    # (the ring is generic over any provider's key list, not Gemini-specific).
    groq_api_key_fallback: str = ""
    # Optional 3rd Groq key — added 2026-08-13 after both prior Groq keys
    # hit the real 100K tokens/day cap in one session (EXTRACT-005/006
    # live-testing). Same _KeyRing, no new code needed — just extends the
    # list in llm_client.py's _API_KEYS["groq"].
    groq_api_key_fallback_2: str = ""
    # Optional 4th Groq key — added 2026-08-15 (EVAL-002). Same _KeyRing.
    groq_api_key_fallback_3: str = ""
    # Optional 5th Groq key — added 2026-08-15 during the ingestion-pipeline
    # fixes' live verification, same day the ring hit key_index=3 mid-BERT-
    # reprocess. Same _KeyRing.
    groq_api_key_fallback_4: str = ""
    # Optional 6th Groq key — added 2026-08-15, same session (the 5th key
    # alone wasn't enough headroom to avoid falling to Gemini/OpenRouter
    # mid-BERT-reprocess). Same _KeyRing, same org-level-quota caveat.
    groq_api_key_fallback_5: str = ""
    # Optional 7th Groq key — added 2026-08-15, same session. Same
    # _KeyRing, same org-level-quota caveat as the 4th/5th/6th keys.
    groq_api_key_fallback_6: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # OpenRouter — single OpenAI-compatible endpoint proxying many vendors'
    # models, several with a free ":free" variant. Added 2026-08-13 as a 3rd
    # fallback once both Gemini and Groq were near/at their real free-tier
    # caps the same day. Own rate limits per free model (not yet
    # characterized live the way Gemini's/Groq's are — see
    # gemini-free-tier-daily-cap.md's hard-won methodology lesson before
    # assuming this one's headroom either).
    openrouter_api_key: str = ""
    # 2nd OpenRouter key — user-provided 2026-08-16 specifically to speed up
    # this session's RoBERTa/ELECTRA/ALBERT reprocess once Groq+Gemini were
    # both exhausted for the day, same multi-key pattern as Groq's ring.
    openrouter_api_key_fallback: str = ""
    # Cerebras — OpenAI-compatible endpoint, Llama models. Added 2026-08-16
    # (EVAL-002) as a single test key, scoped by the user to only this
    # session's RoBERTa/ELECTRA reprocess (not a general-purpose key like
    # the Groq ring) — still wired through the normal fallback chain since
    # that's the only thing running when it's used.
    cerebras_api_key: str = ""
    # Hugging Face Inference Providers router — OpenAI-compatible, added
    # 2026-08-16 (EVAL-002) once the Cerebras key above turned out to need
    # billing set up before any model on it would answer. Live-verified
    # working: meta-llama/Llama-3.3-70B-Instruct via this token.
    huggingface_api_key: str = ""
    # EVAL-001 — local Ollama, genuinely unlimited (runs on this machine's own
    # GPU/CPU, no daily cap of any kind), the real fix for "every free cloud
    # tier ran dry the same day". host.docker.internal is Docker Desktop's
    # special DNS name for reaching a service on the host machine from inside
    # a container — plain "localhost" here would resolve to the container
    # itself, not the host running `ollama serve`. Use "localhost" instead if
    # running the backend outside Docker. No API key needed/used — Ollama's
    # local server has no auth; llm_client.py sends a harmless placeholder
    # since the OpenAI SDK requires a non-empty string.
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
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
    # POLISH-006: below this, the self-audit warns the answer may not be
    # fully grounded (src/services/generation/faithfulness.py). 0.6 rather
    # than a stricter number — the judge is scoring free-form generated
    # prose against retrieved context, not exact-string grounding, so some
    # slack for reasonable paraphrase is expected, not itself a red flag.
    faithfulness_threshold: float = 0.6
    # 200 was sized for a direct JSON reply. Live finding 2026-08-20: with
    # gemini/groq quota-exhausted, the fallback chain lands on OpenRouter's
    # nvidia/nemotron-3-ultra (a reasoning model) - it burns the whole
    # budget on an unrequested chain-of-thought preamble before ever
    # reaching "{", so every single check silently came back unparseable
    # (fails open to "no warning", not a crash - but the audit was doing
    # nothing). Bumped to give a reasoning model room to think then answer.
    faithfulness_max_tokens: int = 600

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
    entity_resolution_fuzzy_threshold: float = 0.85  # name/alias string similarity — EXTRACT-003
    # The ticket specifies >0.90, but measured live with the real embedding
    # model (all-MiniLM-L6-v2) against the ticket's own example pairs
    # ("BERT" vs a differently-worded-but-same-entity description): genuine
    # matches scored 0.57-0.64, nowhere near 0.90 — that threshold would
    # make this channel never fire in practice. 0.55 is calibrated off
    # those two real measurements (with a little margin below both), not
    # the ticket's literal number. See entity_resolver.py's module
    # docstring for the measurements and the two name-pattern heuristics
    # (suffix/acronym variants) added alongside this to reduce reliance on
    # embedding similarity for the cases it's least reliable at.
    entity_resolution_embedding_threshold: float = 0.55

    # File storage
    upload_dir: str = "./data/uploads"
    processed_dir: str = "./data/processed"


settings = Settings()
