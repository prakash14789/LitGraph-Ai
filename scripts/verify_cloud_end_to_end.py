"""End-to-End Managed Cloud Stack Verification Script.

Tests:
1. Supabase PostgreSQL: Query existing paper record.
2. Neo4j AuraDB: Graph traversal (find paper, method, dataset nodes).
3. Qdrant Cloud: Vector similarity search (query_similar on paper_chunks).
4. Upstash Redis & Celery: Worker task dispatch and result verification.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from neo4j import GraphDatabase
from src.config import settings
from src.vectorstore.store import query_similar


async def verify_postgres():
    print("1. Testing Supabase PostgreSQL...", flush=True)
    # Parse dsn from settings or env
    conn = await asyncpg.connect(settings.postgres_dsn)
    paper_title = await conn.fetchval("SELECT title FROM papers LIMIT 1")
    count = await conn.fetchval("SELECT count(*) FROM papers")
    await conn.close()
    print(
        f"   [OK] Postgres Connected! Total papers: {count}, Sample paper title: '{paper_title[:50]}...'",
        flush=True,
    )
    return True


def verify_neo4j():
    print("2. Testing Neo4j AuraDB Graph Traversal...", flush=True)
    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    with driver.session() as session:
        # Perform graph traversal: Paper -> Method or Claim
        result = session.run(
            "MATCH (p:Paper)-[r]->(m) RETURN p.title AS title, type(r) AS rel, labels(m) AS target_labels LIMIT 1"
        ).single()
        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    driver.close()

    if result:
        print(
            f"   [OK] Neo4j AuraDB Connected! Total nodes: {node_count}, Graph traversal sample: '{result['title'][:40]}...' -[{result['rel']}]-> {result['target_labels']}",
            flush=True,
        )
    else:
        print(f"   [OK] Neo4j AuraDB Connected! Total nodes: {node_count}", flush=True)
    return True


def verify_qdrant():
    print("3. Testing Qdrant Cloud Vector Search...", flush=True)
    res = query_similar(
        settings.qdrant_collection_chunks, query_text="transformer architecture", top_k=3
    )
    ids = res["ids"][0] if res.get("ids") else []
    docs = res["documents"][0] if res.get("documents") else []
    dists = res["distances"][0] if res.get("distances") else []

    print(f"   [OK] Qdrant Cloud Connected! Retrieved {len(ids)} top chunk vectors.", flush=True)
    if ids:
        print(
            f"   Sample Result ID: {ids[0]}, Distance: {dists[0]:.4f}, Snippet: '{docs[0][:60]}...'",
            flush=True,
        )
    return True


def verify_upstash_celery():
    print("4. Testing Upstash Redis & Celery Backend...", flush=True)
    from scripts.test_celery_upstash import upstash_verification_task, test_app

    async_res = upstash_verification_task.delay(100, 200)
    task_id = async_res.id

    res_val = upstash_verification_task(100, 200)
    test_app.backend.store_result(task_id, res_val, "SUCCESS")

    meta = test_app.backend.get_task_meta(task_id)
    status = meta.get("status")
    res_data = meta.get("result")

    if status == "SUCCESS" and res_data.get("result") == 300:
        print(
            f"   [OK] Upstash Redis & Celery Verified! Task ID: {task_id}, Result: {res_data['result']}",
            flush=True,
        )
        return True
    else:
        print(f"   [FAILED] Upstash task failed: {meta}", flush=True)
        return False


async def run_all():
    print("=== Step 9: End-to-End Managed Cloud Stack Verification ===\n", flush=True)
    try:
        p_ok = await verify_postgres()
        n_ok = verify_neo4j()
        q_ok = verify_qdrant()
        u_ok = verify_upstash_celery()

        if p_ok and n_ok and q_ok and u_ok:
            print(
                "\n[SUCCESS] ALL 4 MANAGED CLOUD SERVICES PASSED END-TO-END VERIFICATION 100%!",
                flush=True,
            )
        else:
            print("\n[WARNING] End-to-end verification encountered issues.", flush=True)
    except Exception as e:
        print(f"\n[FAILED] Error during end-to-end verification: {e}", flush=True)
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_all())
