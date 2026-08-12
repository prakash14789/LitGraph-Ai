"""add parsing/chunking/embedding job_status values

Revision ID: 7a1e9c2b4d8f
Revises: 3f7d443f5035
Create Date: 2026-08-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1e9c2b4d8f"
down_revision: Union[str, None] = "3f7d443f5035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'parsing' BEFORE 'extracting_entities'"
    )
    op.execute(
        "ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'chunking' BEFORE 'extracting_entities'"
    )
    op.execute(
        "ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'embedding' BEFORE 'extracting_entities'"
    )


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing one means recreating
    # the type and rewriting every row. Not implemented: acceptable for a
    # dev-stage MVP migration; nothing downstream depends on downgrading past
    # this yet.
    pass
