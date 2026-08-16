"""EVAL-003: demo seed script.

Downloads the demo paper set ("Transformer architectures for NLP" — the
same papers tests/eval/eval_dataset.json's 27 questions reference) and runs
each through the real ingestion pipeline via Celery, exactly like a real
POST /ingest/upload call would (see src/api/routes/ingest.py — this script
mirrors that endpoint's Paper+ExtractionJob creation instead of re-using it
directly, since there's no running HTTP server to call from inside this
one-off script).

Run after `docker compose up`:

    docker compose exec backend python scripts/seed_sample_papers.py

Idempotent: skips any paper whose title already exists in Postgres, so a
re-run only fills in whatever's missing (a partial prior run, a paper added
to the list later) instead of re-uploading everything.
"""

import asyncio
import time
import uuid
from pathlib import Path

import httpx
import structlog
from sqlalchemy import select

from src.config import settings
from src.db import AsyncSessionLocal
from src.models.extraction_job import JobStatus
from src.models.paper import IngestionStatus, Paper
from src.repositories import extraction_job_repository, paper_repository
from src.tasks.ingest_task import process_paper

logger = structlog.get_logger()

# (name, source_id, url). source_id is a stable dedup key stored as
# papers.arxiv_id (unique) — NOT paper.title, because pipeline.py
# overwrites paper.title with the PDF's own parsed title once a job
# actually runs ("BERT" becomes "BERT: Pre-training of Deep..."), which
# would silently break a title-based re-run check the second time this
# script is run. GPT-2's paper was never published on arXiv (OpenAI hosted
# the PDF directly) — everything else follows arXiv's /pdf/<id> convention
# and source_id is that same arXiv id.
_DEMO_PAPERS = [
    ("Attention Is All You Need", "1706.03762", "https://arxiv.org/pdf/1706.03762"),
    ("BERT", "1810.04805", "https://arxiv.org/pdf/1810.04805"),
    (
        "GPT-2",
        "gpt2-openai",
        "https://cdn.openai.com/better-language-models/"
        "language_models_are_unsupervised_multitask_learners.pdf",
    ),
    ("GPT-3", "2005.14165", "https://arxiv.org/pdf/2005.14165"),
    ("RoBERTa", "1907.11692", "https://arxiv.org/pdf/1907.11692"),
    ("ELECTRA", "2003.10555", "https://arxiv.org/pdf/2003.10555"),
    ("XLNet", "1906.08237", "https://arxiv.org/pdf/1906.08237"),
    ("DistilBERT", "1910.01108", "https://arxiv.org/pdf/1910.01108"),
    ("ALBERT", "1909.11942", "https://arxiv.org/pdf/1909.11942"),
    ("T5", "1910.10683", "https://arxiv.org/pdf/1910.10683"),
]

_DOWNLOAD_TIMEOUT = 60.0
_POLL_INTERVAL = 15.0
# Generous ceiling, not a target — a local-Ollama fallback day (no cloud
# quota left) has run a single paper past 80 minutes live this session.
# This script is meant to be started and left running, not timed.
_POLL_TIMEOUT = 3 * 60 * 60


async def _already_ingested(session, source_id: str) -> bool:
    result = await session.execute(select(Paper).where(Paper.arxiv_id == source_id))
    return result.scalar_one_or_none() is not None


async def _download(client: httpx.AsyncClient, name: str, url: str) -> bytes | None:
    try:
        resp = await client.get(url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("seed.download_failed", name=name, url=url, error=str(exc))
        return None
    if not resp.content.startswith(b"%PDF-"):
        logger.error("seed.not_a_pdf", name=name, url=url)
        return None
    return resp.content


async def _enqueue(session, name: str, source_id: str, content: bytes) -> uuid.UUID:
    paper_id = uuid.uuid4()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"{paper_id}.pdf"
    dest_path.write_bytes(content)

    paper = await paper_repository.create(
        session,
        id=paper_id,
        title=name,
        authors=[],
        pdf_path=str(dest_path),
        arxiv_id=source_id,
        ingestion_status=IngestionStatus.PENDING,
    )
    job = await extraction_job_repository.create(
        session, paper_id=paper.id, status=JobStatus.QUEUED
    )
    await session.commit()
    process_paper.delay(str(job.id))
    return job.id


async def main() -> None:
    job_ids: list[uuid.UUID] = []
    async with httpx.AsyncClient() as client, AsyncSessionLocal() as session:
        for name, source_id, url in _DEMO_PAPERS:
            if await _already_ingested(session, source_id):
                print(f"skip (already ingested): {name}")
                continue
            print(f"downloading: {name} ...")
            content = await _download(client, name, url)
            if content is None:
                print(f"  FAILED to download {name}, skipping")
                continue
            job_id = await _enqueue(session, name, source_id, content)
            print(f"  queued: {name} (job {job_id})")
            job_ids.append(job_id)

    if not job_ids:
        print("\nNothing new to process.")
        return

    print(f"\nWaiting for {len(job_ids)} job(s) to finish (up to {_POLL_TIMEOUT // 60} min)...")
    deadline = time.monotonic() + _POLL_TIMEOUT
    pending = set(job_ids)
    async with AsyncSessionLocal() as session:
        while pending and time.monotonic() < deadline:
            await asyncio.sleep(_POLL_INTERVAL)
            done = set()
            for job_id in pending:
                job = await extraction_job_repository.get_by_id(session, job_id)
                if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    note = f" ({job.error_message})" if job.error_message else ""
                    print(f"  {job.status.value}: job {job_id}{note}")
                    done.add(job_id)
            pending -= done

    if pending:
        print(
            f"\n{len(pending)} job(s) still running after the timeout — "
            "check GET /ingest/status/<job_id>."
        )
    else:
        print("\nAll done.")


if __name__ == "__main__":
    asyncio.run(main())
