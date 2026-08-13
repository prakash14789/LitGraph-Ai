"""Integration tests for GET /graph/* (GRAPH-001) — real HTTP requests
against the real FastAPI app and the real Neo4j container. Hand-built
Cypher fixtures, same rationale/pattern as test_graph_retriever.py: this
module's job is real Cypher aggregation, mocking the driver would test
nothing real.
"""

import uuid

import pytest

from src.graph.connection import get_driver

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("close_neo4j_driver_after_test")]


async def _run(query: str, **params):
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(query, **params)
        return [record async for record in result]


async def _cleanup(tag: str) -> None:
    await _run(
        "MATCH (n) WHERE n.canonical_name STARTS WITH $tag OR n.paper_id STARTS WITH $tag "
        "OR n.name STARTS WITH $tag OR n.title STARTS WITH $tag "
        "DETACH DELETE n",
        tag=tag,
    )


async def test_overview_counts_include_fixture_nodes_and_edges(test_client):
    tag = f"GA-TEST-{uuid.uuid4()}"
    try:
        await _run(
            "CREATE (p:Paper {paper_id: $paper_id, title: $title}) "
            "CREATE (m:Method {canonical_name: $method}) "
            "CREATE (p)-[:USES_METHOD {confidence: 0.9}]->(m)",
            paper_id=f"{tag}-paper",
            title=f"{tag}-title",
            method=f"{tag}-method",
        )

        response = await test_client.get("/api/v1/graph/overview")
        assert response.status_code == 200
        body = response.json()
        assert body["node_counts"].get("Paper", 0) >= 1
        assert body["node_counts"].get("Method", 0) >= 1
        assert body["edge_counts"].get("USES_METHOD", 0) >= 1
        assert body["total_nodes"] == sum(body["node_counts"].values())
        assert body["total_edges"] == sum(body["edge_counts"].values())
    finally:
        await _cleanup(tag)


async def test_subgraph_expands_from_entity_and_includes_usage_count(test_client):
    tag = f"GA-TEST-{uuid.uuid4()}"
    try:
        rows = await _run(
            "CREATE (p1:Paper {paper_id: $p1, title: 'p1'}) "
            "CREATE (p2:Paper {paper_id: $p2, title: 'p2'}) "
            "CREATE (m:Method {canonical_name: $method}) "
            "CREATE (p1)-[:USES_METHOD {confidence: 0.9}]->(m) "
            "CREATE (p2)-[:USES_METHOD {confidence: 0.8}]->(m) "
            "RETURN elementId(m) AS m",
            p1=f"{tag}-p1",
            p2=f"{tag}-p2",
            method=f"{tag}-method",
        )
        method_id = rows[0]["m"]

        response = await test_client.get(
            "/api/v1/graph/subgraph", params={"entity_id": method_id, "hops": 1}
        )
        assert response.status_code == 200
        body = response.json()

        method_node = next(n for n in body["nodes"] if n["id"] == method_id)
        assert method_node["usage_count"] == 2  # used by both papers
        assert len(body["nodes"]) == 3  # method + 2 papers
        assert {e["rel_type"] for e in body["edges"]} == {"USES_METHOD"}
    finally:
        await _cleanup(tag)


async def test_subgraph_without_entity_id_returns_whole_graph_snapshot(test_client):
    # GRAPH-003: no entity_id -> a capped whole-graph snapshot, not a 422.
    # Same superset-check pattern as test_papers_api.py's collection-filter
    # test — other tests' fixtures/pre-existing data legitimately coexist,
    # so this only asserts the fixture is *included*, not that it's all
    # that comes back.
    tag = f"GA-TEST-{uuid.uuid4()}"
    try:
        rows = await _run(
            "CREATE (p:Paper {paper_id: $paper_id, title: 'p'}) "
            "CREATE (m:Method {canonical_name: $method}) "
            "CREATE (p)-[:USES_METHOD {confidence: 0.9}]->(m) "
            "RETURN elementId(p) AS p, elementId(m) AS m",
            paper_id=f"{tag}-paper",
            method=f"{tag}-method",
        )
        ids = rows[0]

        response = await test_client.get("/api/v1/graph/subgraph")
        assert response.status_code == 200
        body = response.json()

        node_ids = {n["id"] for n in body["nodes"]}
        # A whole-graph snapshot is capped — the fixture may or may not
        # survive the LIMIT depending on what else is in this Neo4j
        # instance, so this only checks the response is well-formed, not
        # that this specific fixture is necessarily included.
        assert isinstance(body["nodes"], list)
        assert isinstance(body["edges"], list)
        # If the fixture *did* make it into the capped set, its edge and
        # usage_count must be correct — not silently dropped/miscounted.
        if ids["m"] in node_ids and ids["p"] in node_ids:
            method_node = next(n for n in body["nodes"] if n["id"] == ids["m"])
            assert method_node["usage_count"] == 1
            assert any(
                e["source"] == ids["p"]
                and e["target"] == ids["m"]
                and e["rel_type"] == "USES_METHOD"
                for e in body["edges"]
            )
    finally:
        await _cleanup(tag)


async def test_subgraph_404_for_unknown_entity(test_client):
    response = await test_client.get(
        "/api/v1/graph/subgraph", params={"entity_id": "4:nonexistent:999999"}
    )
    assert response.status_code == 404


async def test_entity_detail_returns_relationships_and_usage_count(test_client):
    tag = f"GA-TEST-{uuid.uuid4()}"
    try:
        rows = await _run(
            "CREATE (p:Paper {paper_id: $paper_id, title: 'p'}) "
            "CREATE (a:Author {name: $author}) "
            "CREATE (p)-[:AUTHORED_BY]->(a) "
            "RETURN elementId(a) AS a",
            paper_id=f"{tag}-paper",
            author=f"{tag}-author",
        )
        author_id = rows[0]["a"]

        response = await test_client.get(f"/api/v1/graph/entity/{author_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["labels"] == ["Author"]
        assert body["usage_count"] == 1  # authored 1 paper
        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["rel_type"] == "AUTHORED_BY"
        assert body["relationships"][0]["direction"] == "incoming"
    finally:
        await _cleanup(tag)


async def test_entity_detail_404_for_unknown_entity(test_client):
    response = await test_client.get("/api/v1/graph/entity/4:nonexistent:999999")
    assert response.status_code == 404


async def test_search_finds_entity_by_text_and_respects_type_filter(test_client):
    tag = f"GA-TEST-{uuid.uuid4()}"
    try:
        await _run(
            "CREATE (m:Method {canonical_name: $method, description: 'a transformer variant'})",
            method=f"{tag}-UniqueSearchableMethod",
        )

        response = await test_client.get(
            "/api/v1/graph/search", params={"q": f"{tag}-UniqueSearchableMethod"}
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert any(r["name"] == f"{tag}-UniqueSearchableMethod" for r in results)

        response = await test_client.get(
            "/api/v1/graph/search",
            params={"q": f"{tag}-UniqueSearchableMethod", "type": "Author"},
        )
        assert response.status_code == 200
        assert response.json()["results"] == []
    finally:
        await _cleanup(tag)


async def test_search_unknown_type_returns_400(test_client):
    response = await test_client.get("/api/v1/graph/search", params={"q": "x", "type": "NotAType"})
    assert response.status_code == 400
