"""One-time cleanup — collapses relationship duplicates written before
graph_writer.write_relationship() switched from CREATE to MERGE (see its
module docstring). For every (source, target, rel_type) with more than one
edge, keeps whichever copy has the highest occurrence_count (defaulting to
1 for pre-fix edges that never had the property), folds the others' count
into it, and deletes the rest.

Global MATCH (a)-[r]->(b) — every relationship type in the graph, not just
the fixed ones graph_writer.py writes, since any type could have
accumulated duplicates the same way. Idempotent: re-running finds nothing
left to collapse (every group already has size 1).

Usage: python -m scripts.cleanup_duplicate_relationships
"""

import asyncio

from src.graph.connection import close_driver, get_driver

_PREVIEW = """
MATCH (a)-[r]->(b)
WITH a, b, type(r) AS relType, count(r) AS c
WHERE c > 1
RETURN relType, count(*) AS duplicate_groups, sum(c - 1) AS extra_edges
ORDER BY extra_edges DESC
"""

_CLEANUP = """
MATCH (a)-[r]->(b)
WITH a, b, type(r) AS relType, collect(r) AS rels
WHERE size(rels) > 1
WITH rels,
     reduce(best = rels[0], r IN rels |
       CASE WHEN coalesce(r.occurrence_count, 1) > coalesce(best.occurrence_count, 1)
            THEN r ELSE best END) AS keepRel
UNWIND rels AS r
WITH keepRel, r
WHERE elementId(r) <> elementId(keepRel)
WITH keepRel, count(r) AS extras, collect(elementId(r)) AS deleteIds
SET keepRel.occurrence_count = coalesce(keepRel.occurrence_count, 1) + extras
RETURN count(keepRel) AS groups_collapsed, sum(extras) AS edges_deleted, collect(deleteIds) AS deleteIdLists
"""

_DELETE = """
UNWIND $ids AS id
MATCH ()-[r]->() WHERE elementId(r) = id
DELETE r
"""


async def cleanup() -> None:
    driver = get_driver()
    async with driver.session() as session:
        before = [r async for r in await session.run(_PREVIEW)]
        if not before:
            print("No duplicate relationships found — nothing to do.")
            return
        print("Before cleanup:")
        for r in before:
            print(
                f"  {r['relType']}: {r['duplicate_groups']} groups, {r['extra_edges']} extra edges"
            )

        record = await (await session.run(_CLEANUP)).single()
        # deleteIdLists is a list of per-group id lists — flatten before the delete pass.
        all_ids = [id_ for group in record["deleteIdLists"] for id_ in group]
        if all_ids:
            await session.run(_DELETE, ids=all_ids)

        print(
            f"\nCollapsed {record['groups_collapsed']} duplicate groups, "
            f"deleted {record['edges_deleted']} extra edges."
        )

        after = [r async for r in await session.run(_PREVIEW)]
        print("After cleanup:", after or "no duplicates remain")


async def main() -> None:
    try:
        await cleanup()
    finally:
        await close_driver()


if __name__ == "__main__":
    asyncio.run(main())
