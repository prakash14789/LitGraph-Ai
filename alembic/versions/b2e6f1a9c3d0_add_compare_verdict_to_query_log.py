"""add compare_verdict to query_log

Revision ID: b2e6f1a9c3d0
Revises: 7a1e9c2b4d8f
Create Date: 2026-08-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e6f1a9c3d0"
down_revision: Union[str, None] = "7a1e9c2b4d8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    compare_verdict = sa.Enum("vanilla", "graphrag", "tie_good", "tie_bad", name="compare_verdict")
    compare_verdict.create(op.get_bind())
    op.add_column("query_log", sa.Column("compare_verdict", compare_verdict, nullable=True))


def downgrade() -> None:
    op.drop_column("query_log", "compare_verdict")
    sa.Enum(name="compare_verdict").drop(op.get_bind())
