"""Text -> embedding vectors. Provider chosen via EMBEDDING_PROVIDER (local | openai) —
same interface either way, so the rest of the pipeline never branches on provider."""

from functools import lru_cache

from src.config import settings


@lru_cache(maxsize=1)
def _local_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed — required for EMBEDDING_PROVIDER=local"
        ) from exc
    try:
        return SentenceTransformer(settings.embedding_model)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load local embedding model '{settings.embedding_model}': {exc}"
        ) from exc


def warm_up() -> None:
    """Pre-load the local embedding model at process startup — loading it
    (~10s: reads the model weights off disk, initializes torch) is a one-time
    cost per process, but without this it lands on whichever request happens
    to embed first. Measured live via /query/vanilla: cold retrieval took
    10.5s, warm retrieval took 0.02s — the entire ticket's "<10s latency"
    acceptance criterion was at risk purely from unlucky request ordering.
    No-op for EMBEDDING_PROVIDER=openai — nothing local to preload there."""
    if settings.embedding_provider == "local":
        _local_model()


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of strings. Returns one vector per input, same order."""
    if not texts:
        return []

    if settings.embedding_provider == "local":
        model = _local_model()
        return [vector.tolist() for vector in model.encode(texts)]

    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set")
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(model=settings.embedding_model, input=texts)
        return [item.embedding for item in response.data]

    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {settings.embedding_provider!r}")
