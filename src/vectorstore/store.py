"""Qdrant Cloud Vector Store Adapter — replaces ChromaDB.

Supports paper_chunks and entity_embeddings collections using Qdrant Cloud client.
Preserves Cosine metric, 384 vector dimensions, and full backward compatibility with ChromaDB's API.
"""

import uuid
from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient, models
from src.config import settings
from src.vectorstore.embedder import embed

EMBEDDING_DIMENSION = 384


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    """One shared QdrantClient per process."""
    if not settings.qdrant_url:
        # Fallback for local testing or unconfigured url
        return QdrantClient(location=":memory:")
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=60)


def _to_uuid(string_id: str) -> str:
    """Convert any string ID into a deterministic valid UUID v5 for Qdrant point ID."""
    try:
        # Check if already a valid UUID
        return str(uuid.UUID(string_id))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, string_id))


def _build_qdrant_filter(where: dict[str, Any] | None) -> models.Filter | None:
    if not where:
        return None
    must_conditions = []
    for k, v in where.items():
        must_conditions.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))
    return models.Filter(must=must_conditions)


class QdrantCollectionAdapter:
    """Adapter class wrapping a Qdrant collection to match ChromaDB's Collection interface."""

    def __init__(self, name: str):
        self.name = name
        self.client = get_client()
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        collections = [c.name for c in self.client.get_collections().collections]
        if self.name not in collections:
            self.client.create_collection(
                collection_name=self.name,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIMENSION, distance=models.Distance.COSINE
                ),
            )
        # Unlike ChromaDB (arbitrary metadata filtering, no index needed),
        # Qdrant Cloud 400s any query/scroll `where` filter on a field with
        # no payload index — confirmed live: "Index required but not found
        # for 'paper_id'". Every `where=` filter in this codebase keys on
        # paper_id or collection_id (see vector_retriever.py,
        # vanilla_rag/retriever.py, pipeline.py's cleanup path), so both are
        # indexed here, once, right after the collection itself is ensured.
        # create_payload_index is idempotent — re-running it on an
        # already-indexed field is a no-op, not an error.
        for field in ("paper_id", "collection_id"):
            self.client.create_payload_index(
                collection_name=self.name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str] | None = None,
        metadatas: list[dict] | None = None,
    ) -> None:
        points = []
        for i, doc_id in enumerate(ids):
            point_id = _to_uuid(doc_id)
            vector = embeddings[i]
            doc_text = documents[i] if documents else ""
            meta = dict(metadatas[i]) if metadatas and i < len(metadatas) else {}
            payload = {
                "_original_id": doc_id,
                "_document": doc_text,
                **meta,
            }
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        # Batch upsert points
        if points:
            self.client.upsert(collection_name=self.name, points=points)

    # ChromaDB's Collection.upsert() has the same signature as .add() and the
    # same add-or-replace semantics — graph_writer.py calls .upsert() (an
    # entity's embedding must overwrite, not duplicate, on re-resolution) and
    # qdrant_client.upsert() above is already add-or-replace by point id, so
    # this is a plain alias, not new behavior.
    upsert = add

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 5,
        where: dict | None = None,
    ) -> dict[str, list]:
        query_vector = query_embeddings[0]
        q_filter = _build_qdrant_filter(where)

        if hasattr(self.client, "query_points"):
            res = self.client.query_points(
                collection_name=self.name,
                query=query_vector,
                limit=n_results,
                query_filter=q_filter,
                with_payload=True,
            )
            scored_points = res.points
        else:
            scored_points = self.client.search(
                collection_name=self.name,
                query_vector=query_vector,
                limit=n_results,
                query_filter=q_filter,
                with_payload=True,
            )

        res_ids = []
        res_docs = []
        res_metas = []
        res_dists = []

        for p in scored_points:
            orig_id = p.payload.get("_original_id", str(p.id))
            doc = p.payload.get("_document", "")
            meta = {k: v for k, v in p.payload.items() if not k.startswith("_")}

            # Qdrant cosine score is similarity in [-1, 1], Chroma cosine distance is (1 - score)
            distance = 1.0 - p.score

            res_ids.append(orig_id)
            res_docs.append(doc)
            res_metas.append(meta)
            res_dists.append(distance)

        return {
            "ids": [res_ids],
            "documents": [res_docs],
            "metadatas": [res_metas],
            "distances": [res_dists],
        }

    def get(
        self,
        ids: list[str] | None = None,
        where: dict | None = None,
        limit: int | None = None,
    ) -> dict[str, list]:
        q_filter = _build_qdrant_filter(where)
        point_ids = [_to_uuid(i) for i in ids] if ids else None

        if point_ids:
            records = self.client.retrieve(
                collection_name=self.name,
                ids=point_ids,
                with_payload=True,
            )
        else:
            scroll_res, _ = self.client.scroll(
                collection_name=self.name,
                scroll_filter=q_filter,
                limit=limit or 10000,
                with_payload=True,
            )
            records = scroll_res

        res_ids = []
        res_docs = []
        res_metas = []

        for p in records:
            orig_id = p.payload.get("_original_id", str(p.id))
            doc = p.payload.get("_document", "")
            meta = {k: v for k, v in p.payload.items() if not k.startswith("_")}

            res_ids.append(orig_id)
            res_docs.append(doc)
            res_metas.append(meta)

        return {
            "ids": res_ids,
            "documents": res_docs,
            "metadatas": res_metas,
        }

    def delete(self, ids: list[str]) -> None:
        point_ids = [_to_uuid(i) for i in ids]
        if point_ids:
            self.client.delete(
                collection_name=self.name,
                points_selector=models.PointIdsList(points=point_ids),
            )

    def update(self, ids: list[str], metadatas: list[dict]) -> None:
        for doc_id, meta in zip(ids, metadatas, strict=True):
            point_id = _to_uuid(doc_id)
            # Retrieve existing payload to keep _original_id and _document
            records = self.client.retrieve(
                collection_name=self.name, ids=[point_id], with_payload=True
            )
            if records:
                existing_payload = records[0].payload
                new_payload = {
                    **existing_payload,
                    **meta,
                }
                self.client.set_payload(
                    collection_name=self.name,
                    payload=new_payload,
                    points=[point_id],
                )

    def count(self) -> int:
        return self.client.count(collection_name=self.name).count


@lru_cache(maxsize=8)
def get_collection(name: str) -> QdrantCollectionAdapter:
    # Cached (like get_client() above) — _ensure_exists() does 3 HTTP round
    # trips (list collections + 2 payload-index creates); every query_similar
    # call was paying that cost fresh before this, since nothing else in the
    # codebase holds onto the adapter instance.
    return QdrantCollectionAdapter(name)


def init_collections() -> None:
    """Ensure both Qdrant collections exist. Called at app startup."""
    get_collection(settings.qdrant_collection_chunks)
    get_collection(settings.qdrant_collection_entities)


def add_texts(
    collection_name: str, ids: list[str], texts: list[str], metadatas: list[dict] | None = None
) -> None:
    collection = get_collection(collection_name)
    collection.add(ids=ids, embeddings=embed(texts), documents=texts, metadatas=metadatas)


def query_similar(
    collection_name: str, query_text: str, top_k: int = 5, where: dict | None = None
) -> dict:
    collection = get_collection(collection_name)
    return collection.query(query_embeddings=embed([query_text]), n_results=top_k, where=where)
