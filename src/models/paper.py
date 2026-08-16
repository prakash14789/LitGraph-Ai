import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class IngestionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list] = mapped_column(JSONB, nullable=False)  # ["Author A", "Author B"]
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    arxiv_id: Mapped[str | None] = mapped_column(Text, unique=True)
    doi: Mapped[str | None] = mapped_column(Text, unique=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str] = mapped_column(Text, nullable=False)
    # POLISH-001: sha256 of the raw PDF bytes at upload time. Nullable (rows
    # from before this column existed have none) but unique where set — the
    # real live problem this closes: the exact same PDF re-uploaded (a
    # second manual upload, a re-run seed script, two people uploading the
    # same paper) used to silently create a second Paper row with a fresh
    # UUID and re-run the entire extraction pipeline from scratch, doubling
    # the graph's node count for that paper. Checked explicitly in
    # ingest.py before insert (a clear "already ingested" response) with
    # this column's own unique constraint as a second line of defense
    # against a genuine race between two concurrent uploads of the same file.
    content_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    raw_text: Mapped[str | None] = mapped_column(Text)
    sections: Mapped[dict | None] = mapped_column(JSONB)  # {"introduction": "...", "method": "..."}
    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        Enum(
            IngestionStatus, name="ingestion_status", values_callable=lambda e: [m.value for m in e]
        ),
        default=IngestionStatus.PENDING,
        nullable=False,
        index=True,
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
