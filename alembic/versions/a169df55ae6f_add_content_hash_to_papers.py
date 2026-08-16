"""add content_hash to papers

Revision ID: a169df55ae6f
Revises: b2e6f1a9c3d0
Create Date: 2026-08-16 14:49:19.049787

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a169df55ae6f"
down_revision: Union[str, None] = "b2e6f1a9c3d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("content_hash", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_papers_content_hash", "papers", ["content_hash"])


def downgrade() -> None:
    op.drop_constraint("uq_papers_content_hash", "papers", type_="unique")
    op.drop_column("papers", "content_hash")
