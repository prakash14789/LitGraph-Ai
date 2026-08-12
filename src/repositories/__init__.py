from src.models import Collection, ExtractionJob, Paper, QueryLog
from src.repositories.base import Repository

paper_repository = Repository(Paper)
collection_repository = Repository(Collection)
extraction_job_repository = Repository(ExtractionJob)
query_log_repository = Repository(QueryLog)

__all__ = [
    "Repository",
    "paper_repository",
    "collection_repository",
    "extraction_job_repository",
    "query_log_repository",
]
