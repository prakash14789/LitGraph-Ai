"""Vector-only baseline retriever — embed query, search paper_chunks,
return top-K chunks with similarity scores. No graph traversal; this is
the system GraphRAG (Epic 3+) gets compared against."""

from dataclasses import dataclass

from src.config import settings
from src.vectorstore.store import query_similar


@dataclass
class RetrievedChunk:
    text: str
    paper_id: str
    section_name: str
    page_number: int | None
    score: float  # cosine similarity (1 - Chroma's cosine distance) — higher is better


def retrieve(
    query: str, top_k: int | None = None, collection_id: str | None = None
) -> list[RetrievedChunk]:
    """collection_id (POLISH-005b) — chunks carry it directly in Chroma
    metadata (embedding_storage.py), so this is a straight `where` filter,
    unlike vector_retriever.py's entity search which has no such filter
    (see that module's own docstring for why)."""
    where = {"collection_id": collection_id} if collection_id else None
    result = query_similar(
        settings.chroma_collection_chunks,
        query,
        top_k=top_k or settings.vector_top_k,
        where=where,
    )

    documents = result["documents"][0] if result.get("documents") else []
    metadatas = result["metadatas"][0] if result.get("metadatas") else []
    distances = result["distances"][0] if result.get("distances") else []

    return [
        RetrievedChunk(
            text=doc,
            paper_id=meta.get("paper_id", ""),
            section_name=meta.get("section_name", ""),
            page_number=meta.get("page_number"),
            score=1 - dist,
        )
        for doc, meta, dist in zip(documents, metadatas, distances)
    ]
