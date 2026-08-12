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


def retrieve(query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    result = query_similar(
        settings.chroma_collection_chunks, query, top_k=top_k or settings.vector_top_k
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
