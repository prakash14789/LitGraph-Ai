"""Wires chunker output into ChromaDB — embeds and stores each chunk with
its metadata in the paper_chunks collection. Batches embedding calls
(default 100/batch) and skips papers already ingested."""

import structlog

from src.config import settings
from src.services.ingestion.chunker import Chunk
from src.vectorstore import store

logger = structlog.get_logger()

_BATCH_SIZE = 100


def store_chunks(paper_id: str, chunks: list[Chunk], collection_id: str | None = None) -> int:
    """Embeds and stores chunks in the paper_chunks collection. Returns the
    number of chunks stored (0 if empty or the paper's already ingested).

    collection_id (POLISH-005b prep) is stamped into chunk metadata only —
    plain tagging, not read by any query yet (vector_retriever.py's search
    stays global until POLISH-005b wires a `where` filter into it)."""
    if not chunks:
        return 0

    if _already_ingested(paper_id):
        logger.info("embedding_storage.skip_duplicate", paper_id=paper_id)
        return 0

    for batch in _batched(chunks, _BATCH_SIZE):
        store.add_texts(
            collection_name=settings.chroma_collection_chunks,
            ids=[_chunk_id(c) for c in batch],
            texts=[c.text for c in batch],
            metadatas=[_metadata(c, collection_id) for c in batch],
        )

    logger.info("embedding_storage.stored", paper_id=paper_id, chunk_count=len(chunks))
    return len(chunks)


def _already_ingested(paper_id: str) -> bool:
    collection = store.get_collection(settings.chroma_collection_chunks)
    existing = collection.get(where={"paper_id": paper_id}, limit=1)
    return len(existing["ids"]) > 0


def _chunk_id(chunk: Chunk) -> str:
    return f"{chunk.paper_id}_{chunk.chunk_index}"


def _metadata(chunk: Chunk, collection_id: str | None = None) -> dict:
    # Chroma metadata values must be str/int/float/bool — no None.
    metadata = {
        "paper_id": chunk.paper_id,
        "section_name": chunk.section_name,
        "chunk_index": chunk.chunk_index,
    }
    if chunk.page_number is not None:
        metadata["page_number"] = chunk.page_number
    if collection_id is not None:
        metadata["collection_id"] = collection_id
    return metadata


def _batched(items: list[Chunk], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
