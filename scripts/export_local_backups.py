"""Local Backup Exporter for LitGraph.

Exports Neo4j graph nodes and relationships to data_backups/neo4j_dump.json
Exports ChromaDB collections (vectors, documents, metadatas, ids) to data_backups/chroma_dump.json
"""

import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from neo4j import GraphDatabase
from src.config import settings


def dump_neo4j():
    print("--- Exporting Local Neo4j Data ---")
    driver = GraphDatabase.driver(
        "bolt://localhost:7687", auth=(settings.neo4j_user, settings.neo4j_password)
    )

    with driver.session() as session:
        # Get all nodes
        nodes_result = session.run(
            "MATCH (n) RETURN id(n) AS internal_id, labels(n) AS labels, properties(n) AS props"
        )
        nodes = []
        for record in nodes_result:
            nodes.append(
                {
                    "internal_id": record["internal_id"],
                    "labels": record["labels"],
                    "properties": record["props"],
                }
            )

        # Get all relationships
        rels_result = session.run(
            "MATCH (a)-[r]->(b) RETURN id(a) AS start_id, id(b) AS end_id, type(r) AS type, properties(r) AS props"
        )
        relationships = []
        for record in rels_result:
            relationships.append(
                {
                    "start_id": record["start_id"],
                    "end_id": record["end_id"],
                    "type": record["type"],
                    "properties": record["props"],
                }
            )

    driver.close()

    out_file = Path("data_backups/neo4j_dump.json")
    backup_data = {
        "node_count": len(nodes),
        "rel_count": len(relationships),
        "nodes": nodes,
        "relationships": relationships,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, default=str)

    print(
        f"Neo4j backup complete: {len(nodes)} nodes, {len(relationships)} relationships saved to {out_file}"
    )


def dump_chromadb():
    print("--- Exporting Local ChromaDB Data ---")
    host = "localhost" if settings.chroma_host == "chromadb" else settings.chroma_host
    port = 8001 if settings.chroma_port == 8000 else settings.chroma_port
    client = chromadb.HttpClient(host=host, port=port)

    collections_data = {}
    total_vectors = 0

    for coll_name in [settings.chroma_collection_chunks, settings.chroma_collection_entities]:
        try:
            coll = client.get_collection(coll_name)
            res = coll.get(include=["embeddings", "documents", "metadatas"])

            ids = res.get("ids", [])
            embeddings = res.get("embeddings", [])
            documents = res.get("documents", [])
            metadatas = res.get("metadatas", [])

            # If embeddings is numpy array or list
            if hasattr(embeddings, "tolist"):
                embeddings = embeddings.tolist()

            collections_data[coll_name] = {
                "count": len(ids),
                "ids": ids,
                "embeddings": embeddings,
                "documents": documents,
                "metadatas": metadatas,
            }
            total_vectors += len(ids)
            print(f"Collection '{coll_name}': {len(ids)} items exported.")
        except Exception as e:
            print(f"Collection '{coll_name}' export skipped/error: {e}")

    out_file = Path("data_backups/chroma_dump.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(collections_data, f, indent=2, default=str)

    print(f"ChromaDB backup complete: {total_vectors} total vectors saved to {out_file}")


if __name__ == "__main__":
    os.makedirs("data_backups", exist_ok=True)
    dump_neo4j()
    dump_chromadb()
