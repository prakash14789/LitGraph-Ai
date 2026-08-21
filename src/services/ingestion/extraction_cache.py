"""Per-section checkpoint cache for entity/relation extraction — the
LLM-heavy, 20-40+ min part of the pipeline. Live finding: any failure after
even 90% of a paper's sections finished meant redoing every single LLM call
on retry, since nothing survived a restart/redispatch. Caches each section's
raw extraction result to a plain JSON file on disk, keyed by paper_id — a
retry checks the cache before ever calling the LLM again, so it only redoes
the sections that genuinely never finished last time.

Filesystem, not Postgres/Redis: no schema/migration needed, and this is
disposable working state (same spirit as _cleanup_partial_chunks's own
cleanup), not data anything else queries. Cleared on a successful run (see
pipeline.py) so a genuine future reprocess doesn't silently skip fresh
extraction using stale cached results.
"""

import json
import shutil
from pathlib import Path
from typing import Any

_CACHE_ROOT = Path("data/extraction_cache")


def _paper_dir(paper_id: str) -> Path:
    return _CACHE_ROOT / paper_id


def load(paper_id: str, section_name: str, kind: str) -> Any | None:
    path = _paper_dir(paper_id) / f"{section_name}__{kind}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # corrupt/partial write from an interrupted save - treat as a miss


def save(paper_id: str, section_name: str, kind: str, data: Any) -> None:
    d = _paper_dir(paper_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{section_name}__{kind}.json").write_text(json.dumps(data), encoding="utf-8")


def clear(paper_id: str) -> None:
    shutil.rmtree(_paper_dir(paper_id), ignore_errors=True)
