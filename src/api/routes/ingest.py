"""POST /ingest/upload, POST /ingest/arxiv, GET /ingest/status/{job_id}."""

import hashlib
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.rate_limit import limiter
from src.api.schemas.ingest import ArxivImportRequest, JobStatusResponse, UploadResult
from src.config import settings
from src.models.extraction_job import JobStatus
from src.models.paper import IngestionStatus, Paper
from src.repositories import extraction_job_repository, paper_repository
from src.tasks.ingest_task import process_paper

router = APIRouter()

_PDF_MAGIC = b"%PDF-"

# New-style ("1706.03762", optionally "v2") or old-style
# ("cs.CL/0112017")  arXiv ids — matched anywhere in the input so a bare id,
# an abs/pdf URL, or a URL with a trailing ".pdf" all resolve the same way.
_ARXIV_ID_RE = re.compile(
    r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7}(?:v\d+)?)", re.IGNORECASE
)
_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ARXIV_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _validate_pdf(filename: str, content: bytes) -> None:
    if not content.startswith(_PDF_MAGIC):
        raise ValueError(f"{filename}: not a valid PDF (missing %PDF- header)")
    max_bytes = settings.max_pdf_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        size_mb = len(content) / 1_048_576
        raise ValueError(
            f"{filename}: {size_mb:.1f}MB exceeds the {settings.max_pdf_size_mb}MB limit"
        )


def _parse_arxiv_id(identifier: str) -> str | None:
    """Accepts a bare id, an abs/pdf URL, with or without a version suffix
    or trailing ".pdf" — generic pattern match, not a lookup table."""
    stripped = re.sub(r"\.pdf$", "", identifier.strip(), flags=re.IGNORECASE)
    match = _ARXIV_ID_RE.search(stripped)
    return match.group(1) if match else None


async def _fetch_arxiv_metadata(client: httpx.AsyncClient, arxiv_id: str) -> dict | None:
    """arXiv's export API (Atom feed) — stdlib XML parsing, no extra
    dependency. Returns None if the id doesn't resolve to a real paper
    (arXiv answers those with a single synthetic "Error" entry rather than
    an HTTP error status)."""
    resp = await client.get(_ARXIV_API_URL, params={"id_list": arxiv_id}, timeout=30.0)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    entry = root.find(f"{_ARXIV_ATOM_NS}entry")
    if entry is None:
        return None
    entry_id = entry.find(f"{_ARXIV_ATOM_NS}id")
    if entry_id is not None and entry_id.text and "api/errors" in entry_id.text:
        return None
    title_el = entry.find(f"{_ARXIV_ATOM_NS}title")
    if title_el is None or not title_el.text:
        return None
    summary_el = entry.find(f"{_ARXIV_ATOM_NS}summary")
    published_el = entry.find(f"{_ARXIV_ATOM_NS}published")
    authors = [
        name_el.text.strip()
        for author_el in entry.findall(f"{_ARXIV_ATOM_NS}author")
        if (name_el := author_el.find(f"{_ARXIV_ATOM_NS}name")) is not None and name_el.text
    ]
    abstract = None
    if summary_el is not None and summary_el.text:
        abstract = re.sub(r"\s+", " ", summary_el.text).strip()
    year = None
    if published_el is not None and published_el.text:
        year = int(published_el.text[:4])
    return {
        "title": re.sub(r"\s+", " ", title_el.text).strip(),
        "authors": authors,
        "abstract": abstract,
        "year": year,
    }


@router.post("/ingest/upload", response_model=list[UploadResult])
@limiter.limit("10/hour")  # §5.1: ingestion is expensive (LLM calls per paper)
async def upload_papers(
    request: Request,  # unused directly — slowapi's decorator requires this exact param name
    files: list[UploadFile] = File(...),
    collection_id: uuid.UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> list[UploadResult]:
    if not files:
        raise HTTPException(400, "no files provided")
    if len(files) > settings.max_papers_per_upload:
        raise HTTPException(
            400, f"too many files: {len(files)} exceeds the {settings.max_papers_per_upload} limit"
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    results: list[UploadResult] = []
    for upload in files:
        filename = upload.filename or "unnamed"
        content = await upload.read()
        try:
            _validate_pdf(filename, content)
        except ValueError as exc:
            results.append(UploadResult(filename=filename, status="rejected", error=str(exc)))
            continue

        # POLISH-001: the exact same PDF re-uploaded (a second manual
        # upload, a re-run seed script, two people uploading the same
        # paper) used to silently create a second Paper row and re-run the
        # whole extraction pipeline from scratch. Checked before writing
        # anything to disk or DB — content_hash's own unique constraint
        # (see src/models/paper.py) still catches a genuine race between
        # two concurrent uploads of the same file that both pass this
        # check before either commits.
        content_hash = hashlib.sha256(content).hexdigest()
        existing = await db.execute(select(Paper).where(Paper.content_hash == content_hash))
        existing_paper = existing.scalar_one_or_none()
        if existing_paper is not None:
            results.append(
                UploadResult(filename=filename, status="duplicate", paper_id=existing_paper.id)
            )
            continue

        paper_id = uuid.uuid4()
        dest_path = upload_dir / f"{paper_id}.pdf"  # UUID name — never the user-provided filename
        dest_path.write_bytes(content)

        # Paper + ExtractionJob committed together right here, not left to
        # Depends(get_db)'s end-of-request commit — the task dispatched
        # right after must find a durable row; dispatching before commit
        # risks a worker racing ahead of the transaction. Still atomic: both
        # go through repository.create(), which only flushes, so if the
        # ExtractionJob insert fails the Paper row rolls back too (neither
        # is committed until both flushes succeed).
        try:
            paper = await paper_repository.create(
                db,
                id=paper_id,
                title=Path(filename).stem,
                authors=[],
                pdf_path=str(dest_path),
                content_hash=content_hash,
                collection_id=collection_id,
                ingestion_status=IngestionStatus.PENDING,
            )
            job = await extraction_job_repository.create(
                db, paper_id=paper.id, status=JobStatus.QUEUED
            )
            await db.commit()
        except IntegrityError:
            # The race the pre-check above can't fully close: two uploads
            # of the same file committing concurrently. Whichever loses the
            # DB-level unique constraint reports "duplicate" instead of a
            # raw 500 — the winner's row is the real one either way.
            await db.rollback()
            dest_path.unlink(missing_ok=True)
            existing = await db.execute(select(Paper).where(Paper.content_hash == content_hash))
            existing_paper = existing.scalar_one_or_none()
            results.append(
                UploadResult(
                    filename=filename,
                    status="duplicate",
                    paper_id=existing_paper.id if existing_paper else None,
                )
            )
            continue
        except Exception:
            await db.rollback()
            raise

        process_paper.delay(str(job.id))
        results.append(
            UploadResult(filename=filename, status="queued", paper_id=paper.id, job_id=job.id)
        )

    return results


@router.post("/ingest/arxiv", response_model=UploadResult)
@limiter.limit("10/hour")  # §5.1: same cost profile as /ingest/upload (LLM calls per paper)
async def import_arxiv(
    request: Request,  # unused directly — slowapi's decorator requires this exact param name
    body: ArxivImportRequest,
    db: AsyncSession = Depends(get_db),
) -> UploadResult:
    """POLISH-004. Resolves an arXiv URL/id, fetches title/authors/abstract/
    year from arXiv's own API (skips pdf_parser's title/author heuristics —
    arXiv's metadata is authoritative), downloads the PDF, then runs the
    exact same queued-job path as /ingest/upload."""
    arxiv_id = _parse_arxiv_id(body.identifier)
    if arxiv_id is None:
        return UploadResult(
            filename=body.identifier,
            status="rejected",
            error="not a recognizable arXiv URL or id",
        )

    # Cheap dedup check before any network call — arxiv_id is unique on Paper.
    existing = await db.execute(select(Paper).where(Paper.arxiv_id == arxiv_id))
    existing_paper = existing.scalar_one_or_none()
    if existing_paper is not None:
        return UploadResult(filename=arxiv_id, status="duplicate", paper_id=existing_paper.id)

    async with httpx.AsyncClient() as client:
        try:
            metadata = await _fetch_arxiv_metadata(client, arxiv_id)
        except httpx.HTTPError as exc:
            return UploadResult(
                filename=arxiv_id, status="rejected", error=f"arXiv metadata lookup failed: {exc}"
            )
        if metadata is None:
            return UploadResult(
                filename=arxiv_id, status="rejected", error=f"no arXiv paper found for '{arxiv_id}'"
            )
        try:
            resp = await client.get(
                f"https://arxiv.org/pdf/{arxiv_id}", timeout=60.0, follow_redirects=True
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return UploadResult(
                filename=arxiv_id, status="rejected", error=f"PDF download failed: {exc}"
            )
    content = resp.content
    try:
        _validate_pdf(arxiv_id, content)
    except ValueError as exc:
        return UploadResult(filename=arxiv_id, status="rejected", error=str(exc))

    # Same content-hash dedup as /ingest/upload — this can't be checked
    # before the download since the hash is over the PDF bytes themselves.
    content_hash = hashlib.sha256(content).hexdigest()
    existing = await db.execute(select(Paper).where(Paper.content_hash == content_hash))
    existing_paper = existing.scalar_one_or_none()
    if existing_paper is not None:
        return UploadResult(filename=arxiv_id, status="duplicate", paper_id=existing_paper.id)

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    paper_id = uuid.uuid4()
    dest_path = upload_dir / f"{paper_id}.pdf"
    dest_path.write_bytes(content)

    try:
        paper = await paper_repository.create(
            db,
            id=paper_id,
            title=metadata["title"],
            authors=metadata["authors"],
            abstract=metadata["abstract"],
            year=metadata["year"],
            arxiv_id=arxiv_id,
            pdf_path=str(dest_path),
            content_hash=content_hash,
            collection_id=body.collection_id,
            ingestion_status=IngestionStatus.PENDING,
        )
        job = await extraction_job_repository.create(db, paper_id=paper.id, status=JobStatus.QUEUED)
        await db.commit()
    except IntegrityError:
        # Same race as /ingest/upload: two imports of the same paper
        # committing concurrently (e.g. arxiv_id or content_hash losing the
        # DB-level unique constraint).
        await db.rollback()
        dest_path.unlink(missing_ok=True)
        existing = await db.execute(
            select(Paper).where((Paper.arxiv_id == arxiv_id) | (Paper.content_hash == content_hash))
        )
        existing_paper = existing.scalar_one_or_none()
        return UploadResult(
            filename=arxiv_id,
            status="duplicate",
            paper_id=existing_paper.id if existing_paper else None,
        )
    except Exception:
        await db.rollback()
        raise

    process_paper.delay(str(job.id))
    return UploadResult(filename=arxiv_id, status="queued", paper_id=paper.id, job_id=job.id)


@router.get("/ingest/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> JobStatusResponse:
    job = await extraction_job_repository.get_by_id(db, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return JobStatusResponse(
        job_id=job.id,
        paper_id=job.paper_id,
        status=job.status.value,
        entities_found=job.entities_found,
        relations_found=job.relations_found,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
