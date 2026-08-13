import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class UserFeedback(str, enum.Enum):
    GOOD = "good"
    BAD = "bad"
    NONE = "none"


class CompareVerdict(str, enum.Enum):
    """COMPARE-002 — distinct from UserFeedback (binary good/bad on a single
    answer): this is a 4-way verdict on which of the two *compared* answers
    was better, so it needs its own value set."""

    VANILLA = "vanilla"
    GRAPHRAG = "graphrag"
    TIE_GOOD = "tie_good"
    TIE_BAD = "tie_bad"


class QueryLog(Base):
    __tablename__ = "query_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    graphrag_answer: Mapped[str | None] = mapped_column(Text)
    vanilla_answer: Mapped[str | None] = mapped_column(Text)
    retrieved_nodes: Mapped[dict | list | None] = mapped_column(JSONB)  # node IDs used in answer
    user_feedback: Mapped[UserFeedback] = mapped_column(
        Enum(UserFeedback, name="user_feedback", values_callable=lambda e: [m.value for m in e]),
        default=UserFeedback.NONE,
        nullable=False,
    )
    compare_verdict: Mapped[CompareVerdict | None] = mapped_column(
        Enum(CompareVerdict, name="compare_verdict", values_callable=lambda e: [m.value for m in e])
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
