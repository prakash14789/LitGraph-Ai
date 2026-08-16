"""Integration tests for graph_writer.py — real Neo4j and real ChromaDB
containers, no mocks. This is the module the ticket's own acceptance
criteria explicitly wants proven live ("verify with a direct Chroma query
after ingesting a test paper, not just a Neo4j check"), so mocking either
side would test the wrong thing.

Every test cleans up its own nodes/Chroma ids — a prefixed test marker
("GW-TEST-...") keeps this test run from colliding with anything real.
"""

import uuid

import pytest

from src.config import settings
from src.graph.connection import get_driver
from src.services.ingestion import graph_writer
from src.services.ingestion.entity_resolver import ResolutionResult
from src.vectorstore.store import get_collection

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("close_neo4j_driver_after_test")]


def _resolution(name: str, description: str = "", aliases=None) -> ResolutionResult:
    return ResolutionResult(
        decision="create",
        matched_id=None,
        canonical_name=name,
        aliases=aliases or [],
        description=description,
        method="none",
        rationale="test",
    )


async def _node_count(match_clause: str, **params) -> int:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(f"MATCH {match_clause} RETURN count(*) AS c", **params)
        return (await result.single())["c"]


async def _cleanup(*names: str) -> None:
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (n) WHERE n.canonical_name IN $names OR n.name IN $names "
            "OR n.paper_id IN $names OR n.claim_id IN $names DETACH DELETE n",
            names=list(names),
        )


async def test_write_paper_is_idempotent():
    # merges, not duplicates, on reprocess
    paper_id = f"GW-TEST-PAPER-{uuid.uuid4()}"
    try:
        node_id_1 = await graph_writer.write_paper(
            paper_id, "GW Test Paper", ["A. Author"], 2024, "TestConf", "an abstract"
        )
        node_id_2 = await graph_writer.write_paper(
            paper_id,
            "GW Test Paper (updated title)",
            ["A. Author"],
            2024,
            "TestConf",
            "an abstract",
        )

        assert node_id_1 == node_id_2
        assert await _node_count("(p:Paper {paper_id: $id})", id=paper_id) == 1

        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (p:Paper {paper_id: $id}) RETURN p.title AS title, size(p.embedding) AS dim",
                id=paper_id,
            )
            record = await result.single()
        assert record["title"] == "GW Test Paper (updated title)"  # SET n += overwrote it
        assert record["dim"] == settings.embedding_dimension
    finally:
        await _cleanup(paper_id)


async def test_write_paper_stamps_collection_id_when_given():
    # POLISH-005b prep — plain property tagging, never on Method/Dataset/
    # Author/Metric (see write_paper's own docstring for why).
    paper_id = f"GW-TEST-PAPER-{uuid.uuid4()}"
    try:
        await graph_writer.write_paper(
            paper_id, "GW Collection Test", [], None, None, None, collection_id="COLL-TEST-ID"
        )

        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (p:Paper {paper_id: $id}) RETURN p.collection_id AS collection_id",
                id=paper_id,
            )
            record = await result.single()
        assert record["collection_id"] == "COLL-TEST-ID"
    finally:
        await _cleanup(paper_id)


async def test_write_named_entity_merges_on_reprocess_and_upserts_chroma():
    name = f"GW-TEST-METHOD-{uuid.uuid4()}"
    node_id_1 = None
    try:
        node_id_1 = await graph_writer.write_named_entity(
            "Method",
            _resolution(name, "a test method"),
            paper_id="paper-1",
            extra_properties={"category": "test"},
        )
        node_id_2 = await graph_writer.write_named_entity(
            "Method", _resolution(name, "a test method, re-extracted"), paper_id="paper-2"
        )

        assert node_id_1 == node_id_2
        assert await _node_count("(m:Method {canonical_name: $name})", name=name) == 1

        entities = get_collection(settings.chroma_collection_entities)
        record = entities.get(ids=[f"entity_{node_id_1}"], include=["metadatas", "embeddings"])
        assert record["ids"] == [f"entity_{node_id_1}"]
        assert record["metadatas"][0]["canonical_name"] == name
        # both source papers tracked, not overwritten by the 2nd write
        assert set(record["metadatas"][0]["source_papers"].split(",")) == {"paper-1", "paper-2"}
        assert len(record["embeddings"][0]) == settings.embedding_dimension
    finally:
        await _cleanup(name)
        if node_id_1 is not None:
            get_collection(settings.chroma_collection_entities).delete(ids=[f"entity_{node_id_1}"])


async def test_author_and_metric_get_no_embedding_or_chroma_row():
    name = f"GW-TEST-AUTHOR-{uuid.uuid4()}"
    try:
        node_id = await graph_writer.write_named_entity(
            "Author", _resolution(name), paper_id="paper-1"
        )

        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (a:Author {name: $name}) RETURN a.embedding AS embedding", name=name
            )
            record = await result.single()
        assert record["embedding"] is None

        entities = get_collection(settings.chroma_collection_entities)
        assert entities.get(ids=[f"entity_{node_id}"])["ids"] == []
    finally:
        await _cleanup(name)


async def test_write_claim_dedupes_same_paper_same_text():
    paper_id = f"GW-TEST-PAPER-{uuid.uuid4()}"
    text = "this is a test claim about a result"
    try:
        node_id_1 = await graph_writer.write_claim(paper_id, text, "RESULT", 0.9)
        node_id_2 = await graph_writer.write_claim(paper_id, text, "RESULT", 0.95)

        assert node_id_1 == node_id_2
        assert await _node_count("(c:Claim {source_paper_id: $id})", id=paper_id) == 1

        entities = get_collection(settings.chroma_collection_entities)
        assert entities.get(ids=[f"entity_{node_id_1}"])["ids"] == [f"entity_{node_id_1}"]
    finally:
        driver = get_driver()
        async with driver.session() as session:
            await session.run("MATCH (c:Claim {source_paper_id: $id}) DETACH DELETE c", id=paper_id)
        get_collection(settings.chroma_collection_entities).delete(ids=[f"entity_{node_id_1}"])


async def test_write_authors_creates_author_nodes_and_authored_by_edges():
    paper_id = f"GW-TEST-PAPER-{uuid.uuid4()}"
    author_name = f"GW-TEST-AUTHOR-{uuid.uuid4()}"
    try:
        paper_node_id = await graph_writer.write_paper(
            paper_id, "title", [author_name], None, None, None
        )
        author_ids = await graph_writer.write_authors(paper_node_id, [author_name])

        assert len(author_ids) == 1
        assert await _node_count("(a:Author {name: $name})", name=author_name) == 1
        assert (
            await _node_count(
                "(:Paper {paper_id: $pid})-[:AUTHORED_BY]->(:Author {name: $name})",
                pid=paper_id,
                name=author_name,
            )
            == 1
        )
    finally:
        await _cleanup(paper_id, author_name)


async def test_write_relationship_carries_confidence_and_evidence_properties():
    paper_id = f"GW-TEST-PAPER-{uuid.uuid4()}"
    method_name = f"GW-TEST-METHOD-{uuid.uuid4()}"
    method_node_id = None
    try:
        paper_node_id = await graph_writer.write_paper(paper_id, "t", [], None, None, None)
        method_node_id = await graph_writer.write_named_entity(
            "Method", _resolution(method_name, "d"), paper_id=paper_id
        )
        await graph_writer.write_relationship(
            "USES_METHOD",
            paper_node_id,
            method_node_id,
            {"confidence": 0.87, "evidence_text": "we use X for Y"},
        )

        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (:Paper {paper_id: $pid})-[r:USES_METHOD]->(:Method {canonical_name: $name}) "
                "RETURN r.confidence AS confidence, r.evidence_text AS evidence_text",
                pid=paper_id,
                name=method_name,
            )
            record = await result.single()
        assert record["confidence"] == 0.87
        assert record["evidence_text"] == "we use X for Y"
    finally:
        await _cleanup(paper_id, method_name)
        if method_node_id is not None:
            get_collection(settings.chroma_collection_entities).delete(
                ids=[f"entity_{method_node_id}"]
            )


async def test_write_relationship_is_idempotent_on_reprocess():
    # FIX-1: reprocessing a paper used to CREATE a second, duplicate edge.
    # write_relationship now MERGEs — same edge, occurrence_count increments.
    paper_id = f"GW-TEST-PAPER-{uuid.uuid4()}"
    method_name = f"GW-TEST-METHOD-{uuid.uuid4()}"
    method_node_id = None
    try:
        paper_node_id = await graph_writer.write_paper(paper_id, "t", [], None, None, None)
        method_node_id = await graph_writer.write_named_entity(
            "Method", _resolution(method_name, "d"), paper_id=paper_id
        )
        await graph_writer.write_relationship(
            "USES_METHOD", paper_node_id, method_node_id, {"confidence": 0.8}
        )
        await graph_writer.write_relationship(
            "USES_METHOD", paper_node_id, method_node_id, {"confidence": 0.9}
        )

        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (:Paper {paper_id: $pid})-[r:USES_METHOD]->(:Method {canonical_name: $name}) "
                "RETURN count(r) AS edge_count, r.occurrence_count AS occurrence_count",
                pid=paper_id,
                name=method_name,
            )
            record = await result.single()
        assert record["edge_count"] == 1  # not duplicated
        assert record["occurrence_count"] == 2
    finally:
        await _cleanup(paper_id, method_name)
        if method_node_id is not None:
            get_collection(settings.chroma_collection_entities).delete(
                ids=[f"entity_{method_node_id}"]
            )
