"""Named Cypher query templates.

Labels are built into the string via .format() rather than passed as query
params — Cypher doesn't support parameterized labels — which is safe here
because labels only ever come from our own fixed entity-type set (Paper,
Method, Dataset, ...), never from user input.

Epic 2/3 add the real extraction/retrieval queries (entity resolution
lookups, N-hop traversal, etc.) as those tickets land. PAPER_SUBGRAPH and
DELETE_PAPER_CASCADE (INGEST-007) are ahead of that — written against the
§4.2 schema and tested with hand-created nodes, since EXTRACT-004 (graph
writer) hasn't landed yet to populate real ones.
"""

CREATE_NODE = "CREATE (n:{label} $props) RETURN n"
GET_NODE_BY_ID = "MATCH (n:{label} {{id: $id}}) RETURN n"
DELETE_NODE = "MATCH (n:{label} {{id: $id}}) DETACH DELETE n"

# Every non-Paper node connected to this paper, plus the relationship linking
# it in — one row per (entity, relationship) pair. Powers GET /papers/{id}'s
# entities+relationships lists.
PAPER_SUBGRAPH = """
MATCH (p:Paper {paper_id: $paper_id})-[r]-(n)
WHERE NOT n:Paper
RETURN DISTINCT elementId(n) AS id, labels(n) AS labels,
       coalesce(n.canonical_name, n.name, n.text) AS name,
       type(r) AS rel_type, properties(r) AS rel_props,
       startNode(r) = p AS from_paper
"""

# Deletes this paper's own node, then any neighbor that's left with zero
# remaining relationships (i.e. not shared with any other paper). Neighbors
# still connected to something else (another paper, or each other) survive —
# matches the ticket's own suggested Cypher shape exactly. Returns the
# elementIds of whatever got deleted, so the caller can also drop their
# matching `entity_{id}` records from Chroma's entity_embeddings collection.
DELETE_PAPER_CASCADE = """
MATCH (p:Paper {paper_id: $paper_id})
OPTIONAL MATCH (p)-[]-(neighbor)
WHERE NOT neighbor:Paper
WITH p, collect(DISTINCT neighbor) AS neighbors
DETACH DELETE p
WITH neighbors
UNWIND neighbors AS n
WITH n WHERE NOT (n)--()
WITH n, elementId(n) AS id
DETACH DELETE n
RETURN collect(id) AS orphaned_ids
"""

# Every existing Method/Dataset node, across all papers — the "real Neo4j
# lookup" entity_resolver.py's and relation_extractor.py's candidate-list
# interfaces were always designed around (see their own module docstrings).
# Built EXTRACT-005, which is the first ticket that actually has real graph
# data to look candidates up against, now that EXTRACT-004 exists to write
# it. Returns everything resolve_entity()/ResolvableEntity needs, so the
# pipeline doesn't need a second round-trip per entity.
EXISTING_NAMED_ENTITIES = """
MATCH (n)
WHERE n:Method OR n:Dataset
RETURN elementId(n) AS id, labels(n)[0] AS entity_type, n.canonical_name AS canonical_name,
       n.description AS description, n.aliases AS aliases, n.embedding AS embedding
"""
