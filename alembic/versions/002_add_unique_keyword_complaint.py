"""Add unique constraint on complaint keyword

Revision ID: 002
Revises: 001
Create Date: 2026-03-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_complaints_keyword", table_name="complaints")
    op.create_unique_constraint("uq_complaint_keyword", "complaints", ["keyword"])


def downgrade() -> None:
    op.drop_constraint("uq_complaint_keyword", "complaints", type_="unique")
    op.create_index("ix_complaints_keyword", "complaints", ["keyword"])
