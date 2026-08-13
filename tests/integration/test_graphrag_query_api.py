"""Integration test for POST /api/v1/query (RETRIEVAL-005) — real HTTP
request through the real FastAPI app, real Postgres/Neo4j/ChromaDB, mocked
LLM (mock_llm_client), same overall pattern test_query_api.py uses for
/query/vanilla. Proves the full retrieve_seeds -> retrieve_subgraph ->
score_subgraph -> build_context -> generate_answer chain actually connects
end to end against real infrastructure, not just that each stage's own
unit tests pass in isolation.

Setup/cleanup lives inline in the test function (try/finally), not a
shared autouse fixture — matches test_graph_writer.py/test_graph_retriever.py's
own pattern, deliberately: a separate fixture's yield-based teardown can run
its Neo4j cleanup *after* close_neo4j_driver_after_test has already closed
the driver (fixture teardown order between an autouse fixture and a
usefixtures-marked one isn't guaranteed), which is exactly what happened
when this test was first written that way — caught live via a
'driver already closed' DeprecationWarning on an otherwise-passing run.

Named test_graphrag_query_api.py, not test_query_api.py, to avoid
colliding with that file (both live in tests/integration/)."""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.graph.connection import get_driver
from src.models.paper import IngestionStatus, Paper
from src.vectorstore.embedder import embed
from src.vectorstore.store import add_texts, get_collection

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("close_neo4j_driver_after_test")]


async def test_graphrag_query_returns_answer_citations_and_subgraph(
    test_client, mock_llm_client, test_engine
):
    mock_llm_client.return_value = (
        "GQ-TEST-BERT is a bidirectional transformer. ['GQ-TEST BERT Paper']"
    )

    paper_id = str(uuid.uuid4())
    chunk_id = f"{paper_id}_0"
    method_node_id = None
    entities = get_collection(settings.chroma_collection_entities)

    try:
        async with AsyncSession(bind=test_engine) as session:
            session.add(
                Paper(
                    id=uuid.UUID(paper_id),
                    title="GQ-TEST BERT Paper",
                    authors=[],
                    year=2018,
                    pdf_path="/tmp/x.pdf",
                    ingestion_status=IngestionStatus.COMPLETED,
                )
            )
            await session.commit()

        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                """
                CREATE (p:Paper {paper_id: $paper_id, title: 'GQ-TEST BERT Paper', year: 2018})
                CREATE (m:Method {canonical_name: 'GQ-TEST-BERT', description: 'a bidirectional transformer'})
                CREATE (p)-[:USES_METHOD {confidence: 0.9, evidence_text: 'the paper uses BERT'}]->(m)
                RETURN elementId(m) AS method_id
                """,
                paper_id=paper_id,
            )
            method_node_id = (await result.single())["method_id"]

        entities.add(
            ids=[f"entity_{method_node_id}"],
            embeddings=embed(["GQ-TEST-BERT: a bidirectional transformer language model"]),
            documents=["GQ-TEST-BERT: a bidirectional transformer language model"],
            metadatas=[
                {
                    "entity_type": "Method",
                    "canonical_name": "GQ-TEST-BERT",
                    "source_papers": paper_id,
                }
            ],
        )

        add_texts(
            settings.chroma_collection_chunks,
            ids=[chunk_id],
            texts=["GQ-TEST-BERT is a bidirectional transformer for language understanding."],
            metadatas=[{"paper_id": paper_id, "section_name": "abstract", "chunk_index": 0}],
        )

        response = await test_client.post("/api/v1/query", json={"query": "What is GQ-TEST-BERT?"})

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == mock_llm_client.return_value
        mock_llm_client.assert_called_once()

        citation_ids = {c["paper_id"] for c in body["citations"]}
        assert paper_id in citation_ids
        citation = next(c for c in body["citations"] if c["paper_id"] == paper_id)
        assert citation["title"] == "GQ-TEST BERT Paper"

        node_names = {
            n["properties"].get("canonical_name") for n in body["retrieved_subgraph"]["nodes"]
        }
        assert "GQ-TEST-BERT" in node_names
        assert len(body["retrieved_subgraph"]["edges"]) >= 1

        stats = body["retrieval_stats"]
        assert stats["entity_seeds"] >= 1
        assert stats["graph_nodes"] >= 1
        assert stats["ranked_nodes"] >= 1
        assert stats["context_tokens"] > 0
        assert stats["latency_ms"] >= 0
    finally:
        driver = get_driver()
        async with driver.session() as session:
            await session.run(
                "MATCH (n) WHERE n.paper_id = $pid OR n.canonical_name = 'GQ-TEST-BERT' "
                "DETACH DELETE n",
                pid=paper_id,
            )
        if method_node_id is not None:
            entities.delete(ids=[f"entity_{method_node_id}"])
        get_collection(settings.chroma_collection_chunks).delete(ids=[chunk_id])
        async with AsyncSession(bind=test_engine) as session:
            await session.execute(delete(Paper).where(Paper.id == uuid.UUID(paper_id)))
            await session.commit()

    # empty-context "I don't know" skip path is covered directly in
    # test_graphrag_generator.py's unit test — not repeated here, since
    # Chroma always returns its nearest neighbors regardless of semantic
    # distance, so "no relevant content" isn't reliably reproducible
    # through a real vector search without a corpus-dependent, flaky test.
