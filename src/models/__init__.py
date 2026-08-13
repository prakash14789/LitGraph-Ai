"""Import every model here so Base.metadata (and Alembic autogenerate) sees the full schema."""

from src.models.base import Base
from src.models.collection import Collection
from src.models.extraction_job import ExtractionJob, JobStatus
from src.models.paper import IngestionStatus, Paper
from src.models.query_log import CompareVerdict, QueryLog, UserFeedback

__all__ = [
    "Base",
    "Collection",
    "Paper",
    "IngestionStatus",
    "ExtractionJob",
    "JobStatus",
    "QueryLog",
    "UserFeedback",
    "CompareVerdict",
]
