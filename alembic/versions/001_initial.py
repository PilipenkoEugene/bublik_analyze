"""Initial migration - reviews and complaints tables

Revision ID: 001
Revises:
Create Date: 2026-03-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "platform",
            sa.Enum("GOOGLE", "YANDEX", "TWOGIS", name="platform"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_platform_external_id"),
    )
    op.create_index("ix_reviews_platform", "reviews", ["platform"])
    op.create_index("ix_reviews_published_at", "reviews", ["published_at"])

    op.create_table(
        "complaints",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("category", sa.String(255), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_texts", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_complaints_keyword", "complaints", ["keyword"])
    op.create_index("ix_complaints_category", "complaints", ["category"])


def downgrade() -> None:
    op.drop_table("complaints")
    op.drop_table("reviews")
    op.execute("DROP TYPE IF EXISTS platform")
