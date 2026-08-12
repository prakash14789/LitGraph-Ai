"""ChromaDB wrapper — two collections: paper_chunks (INGEST-003) and
entity_embeddings (EXTRACT-004). Kept as plain sync calls: Chroma's client is
sync, and the ingestion pipeline that will use this runs in Celery workers
(also sync), so there's nothing to gain from wrapping it as async."""

import chromadb

from src.config import settings
from src.vectorstore.embedder import embed


def get_client() -> chromadb.ClientAPI:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def get_collection(name: str):
    return get_client().get_or_create_collection(name=name)


def init_collections() -> None:
    """Ensure both collections exist. Called once at app startup."""
    get_collection(settings.chroma_collection_chunks)
    get_collection(settings.chroma_collection_entities)


def add_texts(
    collection_name: str, ids: list[str], texts: list[str], metadatas: list[dict] | None = None
) -> None:
    collection = get_collection(collection_name)
    collection.add(ids=ids, embeddings=embed(texts), documents=texts, metadatas=metadatas)


def query_similar(collection_name: str, query_text: str, top_k: int = 5) -> dict:
    collection = get_collection(collection_name)
    return collection.query(query_embeddings=embed([query_text]), n_results=top_k)
