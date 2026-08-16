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

import re
from datetime import UTC, datetime

import structlog
from rapidfuzz import fuzz
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
    _cosine_similarity,
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
from src.vectorstore.embedder import embed
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

# FIX-B live finding: relation_extractor's own prompt tells the LLM
# EVALUATES_ON's target must always be a Dataset, but nothing downstream
# enforced that — name_index (below) resolves a name to *any* entity
# regardless of type, so a model slip ("BERT" as an EVALUATES_ON target)
# silently wrote a Method-typed edge where a Dataset was required. Checked
# only for relation types where the schema actually pins down one target
# type; anything not listed here (EXTENDS/OUTPERFORMS/INTRODUCES/...) is
# unconstrained, same as before.
_TARGET_TYPE_BY_REL = {
    "EVALUATES_ON": "Dataset",
    "TRAINED_ON": "Dataset",
    "USES_METHOD": "Method",
    "DISTILLED_FROM": "Method",
}

# EVAL-002 fix 1 live finding: HuggingFace-style shared-institution bylines
# ("{victor, lysandre, julien, thomas}@huggingface.co") sit in the preamble
# section right alongside the title/abstract — pdf_parser's own author-list
# parsing already filters this out of paper.authors, but the *raw preamble
# text* still went untouched into entity extraction, where the LLM read the
# bracketed names as separate entities. Stripped here, at the same place the
# title gets stripped, rather than added to pdf_parser — this is about what
# the extraction prompt sees, not what parse_pdf returns.
_EMAIL_BLOCK_RE = re.compile(r"\{[\w\s,]+\}@[\w.]+")
_EMAIL_RE = re.compile(r"[\w.]+@[\w.]+\.\w+")

# EVAL-002 fix 4 backstop: the CLAIMS prompt definition (prompts.py) is
# already strict, but a title paraphrased just enough to dodge FIX-8's
# exact/fuzzy grounding check, or a bare section-header-shaped fragment,
# still occasionally slips through as a "claim". ponytail: regex verb-hint,
# not real POS tagging — good enough to tell a header-shaped noun phrase
# from an actual assertion, not a general grammar check.
# EVAL-002 FIX C backstop: live finding — even with a tightened prompt,
# INTRODUCES occasionally names a target whose own stated evidence_text
# doesn't actually mention it at all (evidence about a different result, or
# about the paper's real contribution, attached to the wrong target name by
# the model). Same grounding idea as entity_extractor's FIX-7/8 — purely
# structural, no entity/paper name ever referenced in code: the relation's
# own evidence must actually contain the name it claims to support. 70, not
# entity_extractor's 40 — short acronym-style names (e.g. "BERTBASE") can
# clear a lower bar against unrelated text by coincidence: 50.0 against text
# that never mentions it at all, and 66.7 against text that merely shares a
# common substring ("BERT") with the target without the target's full name
# ("BERTBASE") appearing anywhere — both measured live. 70 clears both of
# those false-positive floors while still passing genuine grounding (a
# target actually named in its evidence scores 100).
_INTRODUCES_GROUNDING_THRESHOLD = 70.0

_MIN_CLAIM_WORDS = 5
_CLAIM_TITLE_MATCH_THRESHOLD = 85.0
_VERB_HINT_RE = re.compile(
    r"\b(is|are|was|were|has|have|had|can|could|will|would|"
    r"shows?|showed|achiev\w*|outperform\w*|propos\w*|introduc\w*|"
    r"demonstrat\w*|obtain\w*|report\w*|present\w*|train\w*|"
    r"improv\w*|reduc\w*|find|finds|found|enable\w*|allow\w*)\b",
    re.IGNORECASE,
)


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


def _strip_title_from_preamble(sections: dict[str, str], title: str | None) -> dict[str, str]:
    """The "preamble" section (pdf_parser._split_sections) deliberately keeps
    title/authors/abstract text together — but the raw title string sitting
    right there in the extraction input got itself extracted as a Claim.
    Removing the exact title substring is a cheap, targeted fix; doesn't
    touch anything else preamble carries (authors, abstract lead-in)."""
    if "preamble" not in sections:
        return sections
    sections = dict(sections)
    preamble = sections["preamble"]
    if title:
        preamble = preamble.replace(title, "", 1)
    preamble = _EMAIL_BLOCK_RE.sub("", preamble)
    preamble = _EMAIL_RE.sub("", preamble)
    sections["preamble"] = preamble.strip()
    return sections


def _dedupe_claims(extractions: dict[str, SectionExtraction]) -> None:
    """EVAL-002 fix 2: drop near-duplicate claims across a paper's sections
    before they're written to Neo4j — the same finding restated in both the
    Abstract and Conclusion was showing up as two separate Claim nodes.
    Mutates extractions in place. ponytail: O(n^2) pairwise cosine compare —
    fine for a paper's per-run claim count (dozens); revisit if that ever
    grows into the hundreds."""
    flat = [(name, i, c) for name, ext in extractions.items() for i, c in enumerate(ext.claims)]
    if len(flat) < 2:
        return

    vectors = embed([c.text for _, _, c in flat])
    dropped: set[tuple[str, int]] = set()
    for i in range(len(flat)):
        key_i = (flat[i][0], flat[i][1])
        if key_i in dropped:
            continue
        for j in range(i + 1, len(flat)):
            key_j = (flat[j][0], flat[j][1])
            if key_j in dropped or _cosine_similarity(vectors[i], vectors[j]) <= 0.90:
                continue
            # Keep the longer/more complete claim text.
            dropped.add(key_i if len(flat[i][2].text) < len(flat[j][2].text) else key_j)

    if not dropped:
        return
    for name, ext in extractions.items():
        ext.claims = [c for i, c in enumerate(ext.claims) if (name, i) not in dropped]
    logger.info("pipeline.claims_deduped", dropped_count=len(dropped))


def _is_introduces_grounded(relation: ExtractedRelation) -> bool:
    return (
        fuzz.partial_ratio(relation.target, relation.evidence_text)
        >= _INTRODUCES_GROUNDING_THRESHOLD
    )


def _drop_conflicting_trained_on(
    entries: list[tuple[ExtractedRelation, str, str]],
) -> list[tuple[ExtractedRelation, str, str]]:
    """EVAL-002 FIX D backstop: live finding — even with a tightened
    prompt, TRAINED_ON still occasionally fires on genuine fine-tuning/
    downstream data when the paper's own wording says "trained on X"
    (literal keyword match winning over the prompt's semantic distinction).
    Purely structural — never inspects what the dataset is named: if the
    same (source, target) pair would get both TRAINED_ON and EVALUATES_ON
    from this run, EVALUATES_ON is the more literal/reliable reading (it
    always comes with a reported metric+value) and wins; TRAINED_ON for
    that pair is dropped. entries is (relation, source_id, target_id)."""
    evaluates_on_pairs = {
        (source_id, target_id)
        for r, source_id, target_id in entries
        if r.relation_type == "EVALUATES_ON"
    }
    kept = []
    for r, source_id, target_id in entries:
        if r.relation_type == "TRAINED_ON" and (source_id, target_id) in evaluates_on_pairs:
            logger.warning(
                "pipeline.trained_on_conflicts_with_evaluates_on",
                target=r.target,
                evidence_text=r.evidence_text[:200],
            )
            continue
        kept.append((r, source_id, target_id))
    return kept


def _drop_title_and_trivial_claims(
    extractions: dict[str, SectionExtraction], title: str | None
) -> None:
    """EVAL-002 fix 4 backstop — see module-level comment above _VERB_HINT_RE.
    Mutates extractions in place."""
    for name, ext in extractions.items():
        kept = []
        for c in ext.claims:
            if title and fuzz.ratio(c.text.lower(), title.lower()) > _CLAIM_TITLE_MATCH_THRESHOLD:
                logger.warning(
                    "entity_extractor.claim_matches_title", section=name, text=c.text[:200]
                )
                continue
            words = c.text.split()
            if len(words) < _MIN_CLAIM_WORDS and not _VERB_HINT_RE.search(c.text):
                logger.warning("entity_extractor.claim_too_short", section=name, text=c.text[:200])
                continue
            kept.append(c)
        ext.claims = kept


async def _write_graph(session: AsyncSession, job: ExtractionJob, paper: Paper) -> None:
    sections: dict[str, str] = _truncate_sections(paper.sections or {})
    sections = _strip_title_from_preamble(sections, paper.title)

    job.status = JobStatus.EXTRACTING_ENTITIES
    await session.commit()
    extractions: dict[str, SectionExtraction] = {
        name: extract_entities(name, text) for name, text in sections.items()
    }
    _drop_title_and_trivial_claims(extractions, paper.title)
    _dedupe_claims(extractions)
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
    # FIX-B: value is (node_id, entity_type) now, not just node_id — the
    # relation-linking loop below needs the type to enforce
    # _TARGET_TYPE_BY_REL.
    name_index: dict[str, tuple[str, str]] = {}
    for c in candidates:
        if c.id is not None:
            for n in {c.name, *c.aliases}:
                name_index[_norm(n)] = (c.id, c.entity_type)

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

    # Resolve every relation to (source_id, target_id) first, filter, THEN
    # write — FIX D's conflict check needs to see the whole batch's
    # EVALUATES_ON targets before deciding whether a given TRAINED_ON
    # survives, which isn't knowable while writing one relation at a time.
    linked: list[tuple[ExtractedRelation, str, str]] = []
    for section_relations in relations.values():
        for r in section_relations:
            if r.relation_type in _SKIPPED_RELATION_TYPES:
                continue
            if r.source == "paper":
                source_id = paper_node_id
            else:
                source_id, _ = name_index.get(_norm(r.source), (None, None))
            target_id, target_type = name_index.get(_norm(r.target), (None, None))
            if source_id is None or target_id is None:
                logger.warning(
                    "pipeline.relation_unlinked",
                    relation_type=r.relation_type,
                    source=r.source,
                    target=r.target,
                )
                continue

            expected_target_type = _TARGET_TYPE_BY_REL.get(r.relation_type)
            if expected_target_type and target_type != expected_target_type:
                logger.warning(
                    "pipeline.relation_type_mismatch",
                    relation_type=r.relation_type,
                    target=r.target,
                    expected_type=expected_target_type,
                    actual_type=target_type,
                )
                continue

            if r.relation_type == "INTRODUCES" and not _is_introduces_grounded(r):
                logger.warning(
                    "pipeline.introduces_not_grounded",
                    target=r.target,
                    evidence_text=r.evidence_text[:200],
                )
                continue

            linked.append((r, source_id, target_id))

    for r, source_id, target_id in _drop_conflicting_trained_on(linked):
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
    name_index: dict[str, tuple[str, str]],
    candidates: list[ResolvableEntity],
    resolution: ResolutionResult,
    node_id: str,
    original_name: str,
    entity_type: str,
) -> None:
    for n in {resolution.canonical_name, original_name, *resolution.aliases}:
        name_index[_norm(n)] = (node_id, entity_type)
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
