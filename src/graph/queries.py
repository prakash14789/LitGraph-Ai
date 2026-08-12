"""Named Cypher query templates.

Labels are built into the string via .format() rather than passed as query
params — Cypher doesn't support parameterized labels — which is safe here
because labels only ever come from our own fixed entity-type set (Paper,
Method, Dataset, ...), never from user input.

Only the basic CRUD smoke-test queries exist so far; Epic 2/3 add the real
extraction/retrieval queries (entity resolution lookups, N-hop traversal, etc.)
as those tickets land.
"""

CREATE_NODE = "CREATE (n:{label} $props) RETURN n"
GET_NODE_BY_ID = "MATCH (n:{label} {{id: $id}}) RETURN n"
DELETE_NODE = "MATCH (n:{label} {{id: $id}}) DETACH DELETE n"
