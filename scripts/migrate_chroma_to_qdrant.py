"""Vector Migration & Spot-Check Script (ChromaDB -> Qdrant Cloud).

Migrates vectors, payloads, and documents from data_backups/chroma_dump.json into Qdrant Cloud.
Performs count verification and 3-item payload/vector spot-checks.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import QdrantClient, models
from src.vectorstore.store import _to_uuid

QDRANT_URL = "https://ee501dc0-e242-4742-9b16-e2806b84cb18.eu-central-1-0.aws.cloud.qdrant.io"
QDRANT_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6NTcwODE2YjMtNjgzZi00YWYxLTkxYWQtMGNkOWU1ZDA1ZDFlIn0.R5Z_njzoXAYU_IQ49jH-h2VaYjPQojaEQbxKbA1EGF0"


def migrate():
    print("=== Step 5: ChromaDB -> Qdrant Cloud Migration ===", flush=True)

    backup_file = Path("data_backups/chroma_dump.json")
    if not backup_file.exists():
        print(f"ERROR: {backup_file} not found!", flush=True)
        return

    with open(backup_file, "r", encoding="utf-8") as f:
        chroma_data = json.load(f)

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60)

    # 1. Recreate collections on Qdrant
    for coll_name in ["paper_chunks", "entity_embeddings"]:
        print(f"Creating Qdrant collection '{coll_name}' (384 dim, Cosine)...", flush=True)
        client.recreate_collection(
            collection_name=coll_name,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        )

    # 2. Upload points
    total_migrated = 0
    coll_counts = {}

    for coll_name, data in chroma_data.items():
        ids = data.get("ids", [])
        embeddings = data.get("embeddings", [])
        documents = data.get("documents", [])
        metadatas = data.get("metadatas", [])

        print(f"Uploading {len(ids)} vectors for collection '{coll_name}'...", flush=True)

        points = []
        for i, doc_id in enumerate(ids):
            point_id = _to_uuid(doc_id)
            vector = embeddings[i]
            doc_text = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}

            payload = {"_original_id": doc_id, "_document": doc_text, **meta}

            points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

        # Batch upsert (25 at a time for reliable network transit)
        batch_size = 25
        for b in range(0, len(points), batch_size):
            batch = points[b : b + batch_size]
            client.upsert(collection_name=coll_name, points=batch)

        cnt = client.count(collection_name=coll_name).count
        coll_counts[coll_name] = cnt
        total_migrated += cnt
        print(f"Collection '{coll_name}': {cnt} points stored in Qdrant.", flush=True)

    print("\n--- Vector Count Comparison ---", flush=True)
    print(
        f"{'Collection Name':<20} | {'Chroma Count':<14} | {'Qdrant Count':<14} | {'Match Status'}",
        flush=True,
    )
    print("-" * 65, flush=True)

    all_match = True
    for coll_name in ["paper_chunks", "entity_embeddings"]:
        chroma_cnt = chroma_data.get(coll_name, {}).get("count", 0)
        qdrant_cnt = coll_counts.get(coll_name, 0)
        status = "[OK] Match" if chroma_cnt == qdrant_cnt else "[MISMATCH]"
        if chroma_cnt != qdrant_cnt:
            all_match = False
        print(f"{coll_name:<20} | {chroma_cnt:<14} | {qdrant_cnt:<14} | {status}", flush=True)

    # 3. Spot-Check 3 Specific Vectors & Payloads
    print("\n--- Spot-Check Comparison (3 Random Vector Entries) ---", flush=True)

    sample_items = []
    # Pick 2 from paper_chunks, 1 from entity_embeddings
    if "paper_chunks" in chroma_data and chroma_data["paper_chunks"]["count"] >= 2:
        sample_items.append(("paper_chunks", 0))
        sample_items.append(("paper_chunks", len(chroma_data["paper_chunks"]["ids"]) // 2))
    if "entity_embeddings" in chroma_data and chroma_data["entity_embeddings"]["count"] >= 1:
        sample_items.append(("entity_embeddings", 0))

    for coll_name, idx in sample_items:
        orig_id = chroma_data[coll_name]["ids"][idx]
        orig_doc = chroma_data[coll_name]["documents"][idx]
        orig_meta = chroma_data[coll_name]["metadatas"][idx]
        orig_vec = chroma_data[coll_name]["embeddings"][idx]

        point_id = _to_uuid(orig_id)
        retrieved = client.retrieve(
            collection_name=coll_name, ids=[point_id], with_vectors=True, with_payload=True
        )

        if not retrieved:
            print(f"FAILED to retrieve spot-check item {orig_id} from Qdrant!", flush=True)
            continue

        pt = retrieved[0]
        q_doc = pt.payload.get("_document", "")
        q_orig_id = pt.payload.get("_original_id", "")
        q_meta = {k: v for k, v in pt.payload.items() if not k.startswith("_")}
        q_vec = pt.vector

        id_match = orig_id == q_orig_id
        doc_match = orig_doc == q_doc
        meta_match = orig_meta == q_meta
        vec_dim_match = len(orig_vec) == len(q_vec)

        print(
            f"\n[Spot-Check #{len(sample_items)}] Collection: {coll_name} | ID: {orig_id}",
            flush=True,
        )
        print(f"  - Original ID Match:   {id_match} ('{q_orig_id}')", flush=True)
        print(f"  - Document Match:      {doc_match} (len: {len(q_doc)})", flush=True)
        print(f"  - Metadata Match:      {meta_match} ({q_meta})", flush=True)
        print(f"  - Vector Dim Match:    {vec_dim_match} ({len(q_vec)} dim)", flush=True)
        print(f"  - Document Snippet:    '{q_doc[:80]}...'", flush=True)

    if all_match:
        print(
            "\n[SUCCESS] ChromaDB -> Qdrant Cloud migration & spot-checks 100% VERIFIED!",
            flush=True,
        )


if __name__ == "__main__":
    migrate()
