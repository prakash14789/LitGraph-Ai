"""Fast Batched Neo4j Data Migration Script (Local -> Neo4j AuraDB).

Reads all nodes and relationships from local Neo4j container and writes them
to Neo4j AuraDB in batches via UNWIND.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j import GraphDatabase
from src.config import settings

# Local connection
LOCAL_URI = "bolt://localhost:7687"
LOCAL_USER = settings.neo4j_user
LOCAL_PASS = settings.neo4j_password

# AuraDB connection
AURA_URI = "neo4j+s://272a5db2.databases.neo4j.io"
AURA_USER = "272a5db2"
AURA_PASS = "XU55uz4XXqTb-ldItKIEINF6nM95zB6IZyLacMd6gTE"


def migrate():
    print("=== Step 3: Neo4j AuraDB Migration ===", flush=True)

    local_driver = GraphDatabase.driver(LOCAL_URI, auth=(LOCAL_USER, LOCAL_PASS))
    aura_driver = GraphDatabase.driver(AURA_URI, auth=(AURA_USER, AURA_PASS))

    # 1. Fetch local counts & data
    with local_driver.session() as session:
        local_node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        local_rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

        print(
            f"Local Neo4j baseline: {local_node_count} nodes, {local_rel_count} relationships.",
            flush=True,
        )

        # Read nodes
        node_records = session.run(
            "MATCH (n) RETURN elementId(n) AS elem_id, labels(n) AS labels, properties(n) AS props"
        ).data()

        # Read relationships
        rel_records = session.run(
            "MATCH (a)-[r]->(b) RETURN elementId(a) AS start_elem, elementId(b) AS end_elem, type(r) AS rel_type, properties(r) AS props"
        ).data()

    local_driver.close()

    # 2. Setup AuraDB schema & clear existing data if any
    with aura_driver.session() as session:
        print("Checking AuraDB initial state...", flush=True)
        # Clear existing nodes if any
        session.run("MATCH (n) DETACH DELETE n")

        # Initialize constraints and indexes
        from src.graph.schema import CONSTRAINTS, INDEXES, FULLTEXT_INDEXES

        for stmt in [*CONSTRAINTS, *INDEXES, *FULLTEXT_INDEXES]:
            try:
                session.run(stmt)
            except Exception:
                pass

    # 3. Import nodes into AuraDB batched by label set
    nodes_by_labels = {}
    for r in node_records:
        lbl_key = tuple(sorted(r["labels"]))
        if lbl_key not in nodes_by_labels:
            nodes_by_labels[lbl_key] = []
        nodes_by_labels[lbl_key].append({"elem_id": r["elem_id"], "props": r["props"]})

    id_map = {}  # local elementId -> aura elementId
    print(f"Importing {len(node_records)} nodes into AuraDB in batches...", flush=True)

    with aura_driver.session() as session:
        for lbl_tuple, batch in nodes_by_labels.items():
            labels_str = "".join([f":`{lbl}`" for lbl in lbl_tuple])
            cypher = f"""
            UNWIND $batch AS row
            CREATE (n{labels_str})
            SET n = row.props
            RETURN row.elem_id AS local_id, elementId(n) AS aura_id
            """
            results = session.run(cypher, batch=batch).data()
            for res in results:
                id_map[res["local_id"]] = res["aura_id"]

    print(f"Imported {len(id_map)} nodes into AuraDB.", flush=True)

    # 4. Import relationships into AuraDB batched by type
    print(f"Importing {len(rel_records)} relationships into AuraDB in batches...", flush=True)
    with aura_driver.session() as session:
        rel_by_type = {}
        for r in rel_records:
            t = r["rel_type"]
            if t not in rel_by_type:
                rel_by_type[t] = []
            rel_by_type[t].append(
                {
                    "start_elem": id_map[r["start_elem"]],
                    "end_elem": id_map[r["end_elem"]],
                    "props": r["props"],
                }
            )

        rel_imported = 0
        for rel_type, batch in rel_by_type.items():
            cypher = f"""
            UNWIND $batch AS row
            MATCH (a), (b)
            WHERE elementId(a) = row.start_elem AND elementId(b) = row.end_elem
            CREATE (a)-[r:`{rel_type}`]->(b)
            SET r = row.props
            """
            session.run(cypher, batch=batch)
            rel_imported += len(batch)

    print(f"Imported {rel_imported} relationships into AuraDB.", flush=True)

    # 5. Verification
    with aura_driver.session() as session:
        aura_node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        aura_rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

        # Per-label counts
        aura_labels = {}
        for lbl in ["Paper", "Method", "Dataset", "Author", "Claim"]:
            cnt = session.run(f"MATCH (n:`{lbl}`) RETURN count(n) AS c").single()["c"]
            aura_labels[lbl] = cnt

    aura_driver.close()

    print("\n--- Neo4j Migration Verification Summary ---", flush=True)
    print(
        f"Local Nodes:         {local_node_count}  | AuraDB Nodes:         {aura_node_count}",
        flush=True,
    )
    print(
        f"Local Relationships: {local_rel_count}  | AuraDB Relationships: {aura_rel_count}",
        flush=True,
    )
    print(f"AuraDB Node Breakdown by Label: {aura_labels}", flush=True)

    if local_node_count == aura_node_count and local_rel_count == aura_rel_count:
        print("[SUCCESS] Neo4j node and relationship counts match 100%!", flush=True)
    else:
        print("⚠️ WARNING: Count mismatch detected!", flush=True)


if __name__ == "__main__":
    migrate()
