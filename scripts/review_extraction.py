"""Developer CLI (EXTRACT-006) — given a paper_id already in Postgres
(parsed, i.e. paper.sections is populated), re-runs entity extraction ->
relation extraction -> entity resolution and prints a human-readable,
color-coded review: every extracted entity/relation with confidence, every
resolution decision with its rationale. Never writes to Neo4j/Chroma — a
dry run, so it's safe to re-run repeatedly while iterating on prompt
wording in src/services/generation/prompts.py.

Not the ingestion pipeline (src/services/ingestion/pipeline.py) reused
wholesale: that one commits real graph writes and job-status transitions,
neither of which belongs in a read-only review tool. Reuses the same
extract_entities/extract_intra_paper_relations/extract_cross_paper_relations/
resolve_entity/fetch_candidate_entities functions instead, so "what this
script shows" and "what a real ingest would decide" never drift apart.

Usage: python -m scripts.review_extraction <paper_id>
"""

import asyncio
import sys

from src.db import AsyncSessionLocal
from src.models.paper import Paper
from src.services.ingestion.entity_extractor import SectionExtraction, extract_entities
from src.services.ingestion.entity_resolver import ResolvableEntity, resolve_entity
from src.services.ingestion.graph_writer import fetch_candidate_entities
from src.services.ingestion.relation_extractor import (
    extract_cross_paper_relations,
    extract_intra_paper_relations,
)

_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _confidence(score: float) -> str:
    color = _GREEN if score >= 0.8 else _YELLOW if score >= 0.5 else _RED
    return f"{color}{score:.2f}{_RESET}"


async def review(paper_id: str) -> None:
    async with AsyncSessionLocal() as session:
        paper = await session.get(Paper, paper_id)
    if paper is None:
        print(f"No paper found with id {paper_id}")
        return
    if not paper.sections:
        print(f"Paper {paper_id!r} ({paper.title!r}) has no parsed sections — ingest it first.")
        return

    print(f"{_BOLD}=== {paper.title} ({paper_id}) ==={_RESET}")

    extractions: dict[str, SectionExtraction] = {
        name: extract_entities(name, text) for name, text in paper.sections.items()
    }
    candidates = await fetch_candidate_entities()
    candidate_tuples = [(c.name, c.entity_type) for c in candidates]

    for name, extraction in extractions.items():
        print(f"\n{_BOLD}--- Section: {name} ---{_RESET}")
        _print_items("Methods", [(m.name, m.confidence) for m in extraction.methods])
        _print_items("Datasets", [(d.name, d.confidence) for d in extraction.datasets])
        _print_items(
            "Metrics", [(f"{m.name} = {m.value}", m.confidence) for m in extraction.metrics]
        )
        _print_items(
            "Claims", [(f"[{c.claim_type}] {c.text[:80]}", c.confidence) for c in extraction.claims]
        )

        own_names = [m.name for m in extraction.methods] + [d.name for d in extraction.datasets]
        text = paper.sections[name]
        relations = extract_intra_paper_relations(
            name, text, own_names
        ) + extract_cross_paper_relations(name, text, own_names, candidate_tuples)
        if relations:
            print("  Relations:")
            for r in relations:
                print(
                    f"    - {r.source} --{r.relation_type}--> {r.target} "
                    f"[{_confidence(r.confidence)}]  {r.evidence_text[:80]!r}"
                )

    print(f"\n{_BOLD}--- Entity Resolution Decisions ---{_RESET}")
    resolution_pool = list(candidates)  # grows as we go, same as pipeline.py's name_index build
    for extraction in extractions.values():
        for m in extraction.methods:
            _print_resolution(m.name, "Method", m.description, resolution_pool)
        for d in extraction.datasets:
            _print_resolution(d.name, "Dataset", "", resolution_pool)


def _print_items(label: str, items: list[tuple[str, float]]) -> None:
    if not items:
        return
    print(f"  {label}:")
    for name, confidence in items:
        print(f"    - {name} [{_confidence(confidence)}]")


def _print_resolution(
    name: str, entity_type: str, description: str, resolution_pool: list[ResolvableEntity]
) -> None:
    resolution = resolve_entity(
        ResolvableEntity(name=name, entity_type=entity_type, description=description),
        resolution_pool,
    )
    if resolution.decision == "merge":
        print(
            f"  {name} -> MERGED into '{resolution.canonical_name}' ({resolution.method}): {resolution.rationale}"
        )
    else:
        print(f"  {name} -> CREATED new node '{resolution.canonical_name}'")
    resolution_pool.append(
        ResolvableEntity(
            name=resolution.canonical_name,
            entity_type=entity_type,
            description=resolution.description,
            aliases=resolution.aliases,
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.review_extraction <paper_id>")
        sys.exit(1)
    asyncio.run(review(sys.argv[1]))
