"""Neo4j constraints + indexes — matches architecture doc §4.2 exactly.
All statements are `IF NOT EXISTS`, so running this on every app startup is safe."""

from src.graph.connection import get_driver

CONSTRAINTS = [
    "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE",
    "CREATE CONSTRAINT method_canonical IF NOT EXISTS FOR (m:Method) REQUIRE m.canonical_name IS UNIQUE",
    "CREATE CONSTRAINT dataset_canonical IF NOT EXISTS FOR (d:Dataset) REQUIRE d.canonical_name IS UNIQUE",
    "CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX paper_title IF NOT EXISTS FOR (p:Paper) ON (p.title)",
    "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
    "CREATE INDEX method_category IF NOT EXISTS FOR (m:Method) ON (m.category)",
    "CREATE INDEX dataset_domain IF NOT EXISTS FOR (d:Dataset) ON (d.domain)",
]

FULLTEXT_INDEXES = [
    "CREATE FULLTEXT INDEX paper_search IF NOT EXISTS FOR (p:Paper) ON EACH [p.title, p.abstract]",
    "CREATE FULLTEXT INDEX method_search IF NOT EXISTS FOR (m:Method) ON EACH [m.canonical_name, m.description]",
]


async def init_schema() -> None:
    driver = get_driver()
    async with driver.session() as session:
        for statement in [*CONSTRAINTS, *INDEXES, *FULLTEXT_INDEXES]:
            await session.run(statement)
