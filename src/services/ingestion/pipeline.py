"""Orchestrates the full per-paper ingestion pipeline: parse -> chunk ->
embed -> extract entities -> extract relations -> resolve -> write graph
(EXTRACT-005). Dispatched by the Celery task in src/tasks/ingest_task.py —
kept as a plain async function here, not tied to Celery, so it's directly
testable.

Two separate try/except blocks, deliberately not one: the first covers
parse/chunk/embed (unchanged since INGEST-006) and on failure cleans up
partial chunks + marks the paper FAILED, same as before. The second covers
extraction/resolution/graph-write and is wrapped independently — by the
time it runs, chunks are already durably in Chroma and
paper.ingestion_status is already COMPLETED, so a crash here must not roll
any of that back. That's the ticket's own acceptance criterion: a paper is
still queryable via vanilla RAG even if graph extraction fails. On that
failure only the ExtractionJob is marked FAILED; the Paper row stays
COMPLETED.

The extraction phase is idempotent on retry, not transactional: every
entity/claim/paper write goes through graph_writer.py's MERGE-keyed
functions, so re-running it after a partial failure converges instead of
duplicating — no explicit rollback/cleanup needed the way
_cleanup_partial_chunks exists for the chunk-embedding phase.
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import AsyncSessionLocal
from src.models.extraction_job import ExtractionJob, JobStatus
from src.models.paper import IngestionStatus, Paper
from src.services.ingestion.chunker import chunk_paper
from src.services.ingestion.embedding_storage import store_chunks
from src.services.ingestion.entity_extractor import SectionExtraction, extract_entities
from src.services.ingestion.entity_resolver import (
    ResolutionResult,
    ResolvableEntity,
    resolve_entity,
)
from src.services.ingestion.graph_writer import (
    fetch_candidate_entities,
    write_authors,
    write_claim,
    write_named_entity,
    write_paper,
    write_relationship,
)
from src.services.ingestion.pdf_parser import parse_pdf
from src.services.ingestion.relation_extractor import (
    ExtractedRelation,
    extract_cross_paper_relations,
    extract_intra_paper_relations,
)
from src.vectorstore.store import get_collection

logger = structlog.get_logger()

# Handled directly from entity_extractor's own claims (see _write_graph),
# not from relation_extractor's independently-worded REPORTS_RESULT target —
# fuzzy-matching two separate LLM outputs' claim text against each other to
# find "the same" claim node is fragile; writing the claim once and its
# REPORTS_RESULT edge in the same step from the same text isn't.
# CONTRADICTS/CITES need claim-to-claim and paper-to-paper resolution this
# ticket doesn't build (no lookup-by-text infrastructure for either exists
# yet) — skipped, not silently dropped: revisit if eval surfaces a real
# need for them.
_SKIPPED_RELATION_TYPES = {"REPORTS_RESULT", "CONTRADICTS", "CITES"}


async def run_pipeline(job_id: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(ExtractionJob, job_id)
        if job is None:
            logger.error("pipeline.job_not_found", job_id=job_id)
            return

        paper = await session.get(Paper, job.paper_id)
        if paper is None:
            job.status = JobStatus.FAILED
            job.error_message = "paper record not found"
            await session.commit()
            return
        # Captured once, up front, as a plain string: a failed flush expires
        # every ORM object in the session, and *reading* an attribute off an
        # expired object (even an immutable one like an id) tries an
        # implicit refresh that needs real async I/O — which fails with
        # MissingGreenlet when attempted from inside a plain (non-awaited)
        # attribute access, exactly where the except block below needs
        # paper.id after an error-recovery rollback() has already expired
        # it. A plain str has no such lifecycle to worry about.
        paper_id_str = str(paper.id)

        try:
            job.status = JobStatus.PARSING
            job.started_at = datetime.now(UTC)
            await session.commit()

            parsed = parse_pdf(paper.pdf_path)
            if not parsed.ok:
                raise RuntimeError(f"PDF parse failed: {parsed.error}")

            paper.title = parsed.title or paper.title
            paper.authors = parsed.authors or paper.authors
            paper.raw_text = parsed.full_text
            paper.sections = parsed.sections
            paper.abstract = parsed.sections.get("abstract") or paper.abstract
            await session.commit()

            job.status = JobStatus.CHUNKING
            await session.commit()
            chunks = chunk_paper(parsed, paper_id=paper_id_str)

            job.status = JobStatus.EMBEDDING
            await session.commit()
            collection_id_str = str(paper.collection_id) if paper.collection_id else None
            store_chunks(paper_id_str, chunks, collection_id=collection_id_str)

            # Chunks are durable and queryable via vanilla RAG from here —
            # independent of whether graph extraction below succeeds.
            paper.ingestion_status = IngestionStatus.COMPLETED
            await session.commit()
        except Exception as exc:
            logger.error("pipeline.failed", job_id=job_id, error=str(exc))
            # EVAL-001 live finding: if the exception that landed here came
            # from a failed flush/commit (e.g. ELECTRA's real PDF hit a
            # Postgres UTF8 NUL-byte rejection on the paper.sections
            # UPDATE), a failed flush expires every object in the session,
            # and rollback() (needed before the session is usable again at
            # all) doesn't undo that expiry. Setting a *new* value on an
            # expired attribute (job.status = ...) is fine — no read
            # needed — but *reading* one (paper.id, if it weren't already
            # captured as paper_id_str above) tries an implicit refresh
            # that needs real async I/O, which fails with MissingGreenlet
            # from a plain attribute access outside an awaited context.
            await session.rollback()
            _cleanup_partial_chunks(paper_id_str)
            job.status = JobStatus.FAILED
            job.error_message = str(exc)[:2000]
            paper.ingestion_status = IngestionStatus.FAILED
            await session.commit()
            return

        try:
            await _write_graph(session, job, paper)
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            await session.commit()
        except Exception as exc:
            logger.error("pipeline.extraction_failed", job_id=job_id, error=str(exc))
            await session.rollback()  # same reasoning as above
            job.status = JobStatus.FAILED
            job.error_message = str(exc)[:2000]
            await session.commit()


_MAX_SECTION_CHARS = 10_000  # ~2500 tokens at ~4 chars/token — EVAL-001 live
# finding: raw section text was passed into entity/relation-extraction
# prompts completely untruncated. GPT-2's ingestion hit a real provider
# 413 ("Request too large", Groq's 12000 TPM cap) from ONE oversized
# section — measured live: the candidate-entity list itself was cheap
# (79 candidates = ~700 tokens), so the section text alone accounted for
# the bulk of the ~15240 requested tokens. A section this large is more
# likely mis-parsed (heading detection swallowing following sections)
# than genuinely one coherent section, so truncating is a safe tradeoff,
# not just an ugly workaround.


def _truncate_sections(sections: dict[str, str]) -> dict[str, str]:
    return {
        name: (
            text if len(text) <= _MAX_SECTION_CHARS else text[:_MAX_SECTION_CHARS] + "\n[truncated]"
        )
        for name, text in sections.items()
    }


async def _write_graph(session: AsyncSession, job: ExtractionJob, paper: Paper) -> None:
    sections: dict[str, str] = _truncate_sections(paper.sections or {})

    job.status = JobStatus.EXTRACTING_ENTITIES
    await session.commit()
    extractions: dict[str, SectionExtraction] = {
        name: extract_entities(name, text) for name, text in sections.items()
    }
    entities_found = sum(
        len(e.methods) + len(e.datasets) + len(e.metrics) + len(e.claims)
        for e in extractions.values()
    )

    job.status = JobStatus.EXTRACTING_RELATIONS
    await session.commit()
    candidates = await fetch_candidate_entities()
    candidate_tuples = [(c.name, c.entity_type) for c in candidates]
    relations: dict[str, list[ExtractedRelation]] = {}
    for name, text in sections.items():
        own_names = [m.name for m in extractions[name].methods] + [
            d.name for d in extractions[name].datasets
        ]
        intra = extract_intra_paper_relations(name, text, own_names)
        cross = extract_cross_paper_relations(name, text, own_names, candidate_tuples)
        relations[name] = intra + cross

    job.status = JobStatus.RESOLVING_ENTITIES
    await session.commit()
    paper_node_id = await write_paper(
        str(paper.id),
        paper.title,
        paper.authors,
        paper.year,
        paper.venue,
        paper.abstract,
        collection_id=str(paper.collection_id) if paper.collection_id else None,
    )
    await write_authors(paper_node_id, paper.authors or [])

    # candidates grows as each entity resolves+writes, so a later section's
    # mention of the same/variant entity within THIS paper correctly merges
    # into the node a prior section just created, not just entities from
    # other papers fetched above.
    #
    # name_index is seeded from the pre-existing candidates FIRST — found
    # live: a cross-paper EXTENDS/OUTPERFORMS relation can correctly target
    # a candidate that already existed before this run (that's the whole
    # point of the cross-paper pass), and without this seed step its id was
    # never indexed, so a genuinely correct relation silently dropped as
    # "unlinked" below purely because it pointed at something this run
    # didn't itself just write.
    name_index: dict[str, str] = {}
    for c in candidates:
        if c.id is not None:
            for n in {c.name, *c.aliases}:
                name_index[_norm(n)] = c.id

    for extraction in extractions.values():
        for m in extraction.methods:
            resolution = resolve_entity(
                ResolvableEntity(name=m.name, entity_type="Method", description=m.description),
                candidates,
            )
            node_id = await write_named_entity(
                "Method",
                resolution,
                paper_id=str(paper.id),
                extra_properties={"category": m.category},
            )
            _index_entity(name_index, candidates, resolution, node_id, m.name, "Method")
        for d in extraction.datasets:
            resolution = resolve_entity(
                ResolvableEntity(name=d.name, entity_type="Dataset", description=""), candidates
            )
            node_id = await write_named_entity(
                "Dataset", resolution, paper_id=str(paper.id), extra_properties={"domain": d.domain}
            )
            _index_entity(name_index, candidates, resolution, node_id, d.name, "Dataset")

    job.status = JobStatus.WRITING_GRAPH
    await session.commit()
    relations_written = 0
    for extraction in extractions.values():
        for c in extraction.claims:
            claim_id = await write_claim(str(paper.id), c.text, c.claim_type, c.confidence)
            await write_relationship(
                "REPORTS_RESULT",
                paper_node_id,
                claim_id,
                {"confidence": c.confidence, "evidence_text": c.text},
            )
            relations_written += 1

    for section_relations in relations.values():
        for r in section_relations:
            if r.relation_type in _SKIPPED_RELATION_TYPES:
                continue
            source_id = paper_node_id if r.source == "paper" else name_index.get(_norm(r.source))
            target_id = name_index.get(_norm(r.target))
            if source_id is None or target_id is None:
                logger.warning(
                    "pipeline.relation_unlinked",
                    relation_type=r.relation_type,
                    source=r.source,
                    target=r.target,
                )
                continue
            await write_relationship(
                r.relation_type,
                source_id,
                target_id,
                {"confidence": r.confidence, "evidence_text": r.evidence_text, **r.properties},
            )
            relations_written += 1

    job.entities_found = entities_found
    job.relations_found = relations_written


def _index_entity(
    name_index: dict[str, str],
    candidates: list[ResolvableEntity],
    resolution: ResolutionResult,
    node_id: str,
    original_name: str,
    entity_type: str,
) -> None:
    for n in {resolution.canonical_name, original_name, *resolution.aliases}:
        name_index[_norm(n)] = node_id
    candidates.append(
        ResolvableEntity(
            name=resolution.canonical_name,
            entity_type=entity_type,
            description=resolution.description,
            aliases=resolution.aliases,
            id=node_id,
        )
    )


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _cleanup_partial_chunks(paper_id: str) -> None:
    collection = get_collection(settings.chroma_collection_chunks)
    existing = collection.get(where={"paper_id": paper_id})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
        logger.info(
            "pipeline.cleanup_partial_chunks", paper_id=paper_id, count=len(existing["ids"])
        )
