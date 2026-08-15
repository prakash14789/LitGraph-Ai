"""Integration tests for graph_retriever.py — real Neo4j, no mocks (same
rationale as test_graph_writer.py: this module's only job is the Cypher
traversal, so mocking the driver would test nothing real).

Test graph is built directly via Cypher, not graph_writer.py — this suite
is about traversal/filtering/capping logic, not about write-idempotency,
so hand-built nodes with exact confidence values are more direct than
routing through resolve_entity()/write_named_entity() for every fixture.
"""

import uuid

import pytest

from src.graph.connection import get_driver
from src.services.retrieval import graph_retriever
from src.services.retrieval.vector_retriever import EntitySeed, SeedResult

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("close_neo4j_driver_after_test")]


def _seed(node_id: str, paper_ids: list[str] | None = None) -> SeedResult:
    return SeedResult(
        entities=[
            EntitySeed(node_id=node_id, entity_type="Method", canonical_name="seed", score=1.0)
        ],
        chunks=[],
        paper_ids=paper_ids or [],
    )


async def _run(query: str, **params):
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(query, **params)
        return [record async for record in result]


async def _build_graph(tag: str) -> dict:
    """Paper -[AUTHORED_BY]-> Author
       Paper -[USES_METHOD conf=0.9]-> MethodA
       MethodA -[EXTENDS conf=0.8]-> MethodB
       MethodB -[OUTPERFORMS conf=0.7]-> MethodC
    Returns elementIds keyed by short name, plus the paper_id string."""
    paper_id = f"{tag}-paper"
    rows = await _run(
        """
        CREATE (p:Paper {paper_id: $paper_id, title: 'test'})
        CREATE (au:Author {name: $author})
        CREATE (a:Method {canonical_name: $a})
        CREATE (b:Method {canonical_name: $b})
        CREATE (c:Method {canonical_name: $c})
        CREATE (p)-[:AUTHORED_BY]->(au)
        CREATE (p)-[:USES_METHOD {confidence: 0.9}]->(a)
        CREATE (a)-[:EXTENDS {confidence: 0.8}]->(b)
        CREATE (b)-[:OUTPERFORMS {confidence: 0.7}]->(c)
        RETURN elementId(p) AS p, elementId(au) AS au, elementId(a) AS a,
               elementId(b) AS b, elementId(c) AS c
        """,
        paper_id=paper_id,
        author=f"{tag}-author",
        a=f"{tag}-A",
        b=f"{tag}-B",
        c=f"{tag}-C",
    )
    ids = dict(rows[0])
    ids["paper_id"] = paper_id
    return ids


async def _cleanup(tag: str) -> None:
    await _run(
        "MATCH (n) WHERE n.canonical_name STARTS WITH $tag OR n.paper_id = $paper_id "
        "OR n.name STARTS WITH $tag DETACH DELETE n",
        tag=tag,
        paper_id=f"{tag}-paper",
    )


async def test_two_hop_traversal_returns_meaningful_subgraph():
    tag = f"GR-TEST-{uuid.uuid4()}"
    try:
        ids = await _build_graph(tag)

        sub = await graph_retriever.retrieve_subgraph(_seed(ids["a"]), hops=2)

        node_ids = {n.node_id for n in sub.nodes}
        assert ids["p"] in node_ids  # 1 hop from A
        assert ids["b"] in node_ids  # 1 hop from A
        assert ids["c"] in node_ids  # 2 hops from A, via B
        rel_types = {e.rel_type for e in sub.edges}
        assert {"USES_METHOD", "EXTENDS", "OUTPERFORMS"} <= rel_types
        extends_edge = next(e for e in sub.edges if e.rel_type == "EXTENDS")
        assert extends_edge.properties["confidence"] == 0.8
        # embedding never on these fixtures, but confirms the strip doesn't blow up
        assert "embedding" not in next(n for n in sub.nodes if n.node_id == ids["a"]).properties
    finally:
        await _cleanup(tag)


async def test_paper_id_seed_resolves_to_paper_elementid():
    tag = f"GR-TEST-{uuid.uuid4()}"
    try:
        ids = await _build_graph(tag)

        sub = await graph_retriever.retrieve_subgraph(_seed_by_paper(ids["paper_id"]), hops=1)

        node_ids = {n.node_id for n in sub.nodes}
        assert ids["p"] in node_ids
        assert ids["a"] in node_ids  # Paper -[USES_METHOD]-> A, one hop
        assert ids["au"] in node_ids  # Paper -[AUTHORED_BY]-> Author, one hop
    finally:
        await _cleanup(tag)


async def test_collection_filter_drops_other_collections_paper_and_its_private_node_but_keeps_shared_entity():
    # POLISH-005b, real Cypher end-to-end: tag's own Paper -> A -> B -> C
    # chain gets collection_id "coll-a"; a second, unrelated paper in
    # "coll-b" also uses shared Method C plus its own private Author.
    tag = f"GR-TEST-{uuid.uuid4()}"
    try:
        ids = await _build_graph(tag)
        await _run(
            "MATCH (p:Paper {paper_id: $paper_id}) SET p.collection_id = 'coll-a'",
            paper_id=ids["paper_id"],
        )
        other_paper_id = f"{tag}-other-paper"
        rows = await _run(
            """
            MATCH (c:Method) WHERE elementId(c) = $c_id
            CREATE (p2:Paper {paper_id: $other_paper_id, title: 'other', collection_id: 'coll-b'})
            CREATE (au2:Author {name: $other_author})
            CREATE (p2)-[:AUTHORED_BY]->(au2)
            CREATE (p2)-[:USES_METHOD {confidence: 0.5}]->(c)
            RETURN elementId(p2) AS p2, elementId(au2) AS au2
            """,
            c_id=ids["c"],
            other_paper_id=other_paper_id,
            other_author=f"{tag}-other-author",
        )
        other_ids = dict(rows[0])

        sub = await graph_retriever.retrieve_subgraph(
            _seed(ids["a"]), hops=3, collection_id="coll-a"
        )

        node_ids = {n.node_id for n in sub.nodes}
        assert ids["p"] in node_ids  # in-collection paper survives
        assert ids["c"] in node_ids  # shared entity survives (still tied to p1)
        assert other_ids["p2"] not in node_ids  # other collection's paper dropped
        assert other_ids["au2"] not in node_ids  # its private entity orphaned+dropped
    finally:
        await _cleanup(tag)
        await _run(
            "MATCH (n) WHERE n.paper_id = $other_paper_id OR n.name STARTS WITH $tag "
            "DETACH DELETE n",
            other_paper_id=other_paper_id,
            tag=tag,
        )


async def test_relationship_type_filter_only_returns_matching_edges():
    tag = f"GR-TEST-{uuid.uuid4()}"
    try:
        ids = await _build_graph(tag)

        sub = await graph_retriever.retrieve_subgraph(
            _seed(ids["a"]), hops=2, relationship_types=["EXTENDS"]
        )

        assert {e.rel_type for e in sub.edges} == {"EXTENDS"}
        node_ids = {n.node_id for n in sub.nodes}
        assert node_ids == {ids["a"], ids["b"]}
        assert ids["p"] not in node_ids  # USES_METHOD filtered out
        assert ids["c"] not in node_ids  # OUTPERFORMS filtered out
    finally:
        await _cleanup(tag)


async def test_unknown_relationship_type_returns_empty_without_matching_everything():
    tag = f"GR-TEST-{uuid.uuid4()}"
    try:
        ids = await _build_graph(tag)

        sub = await graph_retriever.retrieve_subgraph(
            _seed(ids["a"]), hops=2, relationship_types=["NOT_A_REAL_TYPE"]
        )

        assert sub.nodes == []
        assert sub.edges == []
    finally:
        await _cleanup(tag)


async def test_max_nodes_cap_keeps_highest_confidence_edges_first():
    tag = f"GR-TEST-{uuid.uuid4()}"
    try:
        rows = await _run(
            """
            CREATE (seed:Method {canonical_name: $seed})
            CREATE (hi:Method {canonical_name: $hi})
            CREATE (mid:Method {canonical_name: $mid})
            CREATE (lo:Method {canonical_name: $lo})
            CREATE (seed)-[:EXTENDS {confidence: 0.9}]->(hi)
            CREATE (seed)-[:EXTENDS {confidence: 0.5}]->(mid)
            CREATE (seed)-[:EXTENDS {confidence: 0.1}]->(lo)
            RETURN elementId(seed) AS seed, elementId(hi) AS hi
            """,
            seed=f"{tag}-seed",
            hi=f"{tag}-hi",
            mid=f"{tag}-mid",
            lo=f"{tag}-lo",
        )
        ids = dict(rows[0])

        sub = await graph_retriever.retrieve_subgraph(_seed(ids["seed"]), hops=1, max_nodes=2)

        node_ids = {n.node_id for n in sub.nodes}
        assert node_ids == {ids["seed"], ids["hi"]}
        assert len(sub.edges) == 1
        assert sub.edges[0].properties["confidence"] == 0.9
    finally:
        await _cleanup(tag)


async def test_no_seeds_returns_empty_subgraph():
    sub = await graph_retriever.retrieve_subgraph(SeedResult(entities=[], chunks=[], paper_ids=[]))
    assert sub.nodes == []
    assert sub.edges == []


def _seed_by_paper(paper_id: str) -> SeedResult:
    return SeedResult(entities=[], chunks=[], paper_ids=[paper_id])
