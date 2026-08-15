"""ChromaDB wrapper — two collections: paper_chunks (INGEST-003) and
entity_embeddings (EXTRACT-004). Kept as plain sync calls: Chroma's client is
sync, and the ingestion pipeline that will use this runs in Celery workers
(also sync), so there's nothing to gain from wrapping it as async."""

from functools import lru_cache

import chromadb

from src.config import settings
from src.vectorstore.embedder import embed


@lru_cache(maxsize=1)
def get_client() -> chromadb.ClientAPI:
    """One shared client per process — same caching pattern as the local
    embedding model, instead of paying a fresh HTTP client + handshake on
    every add_texts/query_similar call."""
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def get_collection(name: str):
    # cosine, not Chroma's l2 default — matches how sentence-transformer
    # embeddings are meant to be compared, and gives a bounded [0, 2]
    # distance the hybrid scorer (RETRIEVAL-003) can combine with graph
    # distance/confidence predictably. Only takes effect at creation time —
    # an existing collection keeps whatever space it was made with.
    return get_client().get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def init_collections() -> None:
    """Ensure both collections exist. Called once at app startup."""
    get_collection(settings.chroma_collection_chunks)
    get_collection(settings.chroma_collection_entities)


def add_texts(
    collection_name: str, ids: list[str], texts: list[str], metadatas: list[dict] | None = None
) -> None:
    collection = get_collection(collection_name)
    collection.add(ids=ids, embeddings=embed(texts), documents=texts, metadatas=metadatas)


def query_similar(
    collection_name: str, query_text: str, top_k: int = 5, where: dict | None = None
) -> dict:
    """where (POLISH-005b) — Chroma metadata filter, e.g. {"collection_id": "..."}.
    None (default) searches the full collection, unchanged from before."""
    collection = get_collection(collection_name)
    kwargs = {"query_embeddings": embed([query_text]), "n_results": top_k}
    if where:
        kwargs["where"] = where
    return collection.query(**kwargs)
